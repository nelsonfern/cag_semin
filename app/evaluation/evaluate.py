"""Evaluación de respuestas reales: ¿responde con fuentes cuando puede y se abstiene cuando no?

Usa el mismo servicio que la API (motor CAG + citas), sin HTTP, sobre ``questions.json``. Por
cada pregunta registra la decisión, las citas válidas e inválidas, si citó un documento donde
está la respuesta, las advertencias, los tiempos y el texto generado (también cuando no se
muestra). La fidelidad del contenido se revisa a mano con ese texto: el script no la juzga.

Uso:
    python -X utf8 -m app.evaluation.evaluate [--only q01 q09] [--max-new-tokens 256]
    python -X utf8 -m app.evaluation.evaluate --rescore data/results/phase5_eval_<fecha>.json
Resultados: data/results/phase5_eval_<fecha>.json

``--rescore`` vuelve a aplicar las reglas de citas a los textos ya generados, sin el modelo. Es
equivalente a correrlo de nuevo porque la decodificación es greedy (determinista): con el mismo
prefijo (mismo ``cache_id``) el modelo produce exactamente el mismo texto. Por eso antes de
re-evaluar se comprueba que el ``cache_id`` actual coincida con el de la corrida original.
"""

from __future__ import annotations

import app.config  # noqa: F401  (carga el .env, incluido HF_HOME, antes de importar transformers)

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psutil
import torch

from app.api.runtime import default_factory
from app.cag.model_loader import rss_mb
from app.config import DATA_DIR
from app.services.answer_service import ABSTAINED, ANSWERED, OUT_OF_SCOPE, UNSUPPORTED

QUESTIONS_FILE = Path(__file__).with_name("questions.json")


def classify(q: dict, decision: str, cited_docs: list[str]) -> str:
    """Resultado de la pregunta según lo esperado.

    - ``correct_answer``: respondible, respondió y citó un documento esperado.
    - ``wrong_source``: respondible, respondió pero citando solo documentos no esperados.
    - ``missed``: respondible, pero se abstuvo o quedó sin respaldo.
    - ``correct_abstention``: no respondible y no se mostró respuesta.
    - ``hallucination_shown``: no respondible y se mostró una respuesta con citas.
    """
    if q["answerable"]:
        if decision != ANSWERED:
            return "missed"
        return "correct_answer" if set(cited_docs) & set(q["expected_documents"]) else "wrong_source"
    return "correct_abstention" if decision in (ABSTAINED, UNSUPPORTED, OUT_OF_SCOPE) else "hallucination_shown"


def summarize(rows: list[dict]) -> dict[str, int]:
    """Cantidad de preguntas por resultado."""
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    return counts


def rescore(path: Path) -> None:
    """Re-evalúa una corrida guardada con las reglas de citas actuales (ver la cabecera)."""
    from transformers import AutoTokenizer

    from app.cag.cache_store import CacheIdentity
    from app.cag.prompt import build_prefix
    from app.ingestion.corpus_builder import load_latest
    from app.services.answer_service import _is_abstention, decide
    from app.services.citations import CitationIndex

    original = json.loads(path.read_text(encoding="utf-8"))
    eng = original["engine"]
    corpus_text, report = load_latest()
    tok = AutoTokenizer.from_pretrained(eng["model_id"], revision=eng["revision"])
    identity = CacheIdentity(model_id=eng["model_id"], revision=eng["revision"], dtype=eng["dtype"],
                             prefix_ids=tuple(build_prefix(tok, corpus_text).ids))
    if identity.cache_id != eng["cache_id"]:
        raise SystemExit(f"El prefijo cambió (cache_id {identity.cache_id} != {eng['cache_id']}): "
                         "hay que volver a correr el modelo, no alcanza con re-evaluar")
    index = CitationIndex.from_corpus(corpus_text, report)
    questions = {q["id"]: q for q in json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))["questions"]}
    rows = []
    for old in original["rows"]:
        q, raw = questions[old["id"]], old["raw_text"]
        citations = index.review(raw, q["question"])
        decision, _ = decide(q["question"], raw, citations)
        cited_docs = [d.document_id for d in citations.documents]
        rows.append({**old, "outcome": classify(q, decision, cited_docs), "decision": decision,
                     "cited_sections": [c.section_id for c in citations.citations], "cited_documents": cited_docs,
                     "invalid_ids": citations.invalid_ids, "off_topic_ids": citations.off_topic_ids,
                     "rejected_citations": citations.rejected_citations, "coverage": citations.coverage,
                     "warnings": citations.warnings})
        print(f"{old['id']} {rows[-1]['outcome']:20} {decision:11} cobertura={citations.coverage} "
              f"citas={rows[-1]['cited_sections']}", flush=True)
    result = {**original, "phase": 5, "rescored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "rescored_from": path.name, "summary": summarize(rows), "rows": rows}
    out = DATA_DIR / "results" / f"{path.stem}_rescored_{datetime.now().strftime('%H%M%S')}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Resumen: {result['summary']}\nGuardado en {out}", flush=True)


def main(argv: list[str] | None = None) -> None:
    """Corre las preguntas, imprime un resumen por pregunta y guarda el JSON completo."""
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", default=None, help="ids de preguntas a correr")
    parser.add_argument("--max-new-tokens", type=int, default=None)
    parser.add_argument("--threads", type=int, default=None, help="hilos de torch (por defecto, los de torch)")
    parser.add_argument("--rescore", type=Path, default=None, help="re-evaluar una corrida guardada, sin el modelo")
    parser.add_argument("--engine", default=None, choices=["llamacpp", "transformers"], help="por defecto, ENGINE del .env")
    parser.add_argument("--model", default=None, help="motor transformers: por defecto, MODEL_ID del .env")
    parser.add_argument("--dtype", default=None, help="por defecto, DTYPE del .env")
    parser.add_argument("--tag", default="", help="sufijo para el nombre del archivo de resultados")
    args = parser.parse_args(argv)
    if args.rescore:
        rescore(args.rescore)
        return
    if args.threads:
        torch.set_num_threads(args.threads)

    questions = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))["questions"]
    if args.only:
        questions = [q for q in questions if q["id"] in args.only]

    # El modelo y el dtype se eligen por variables de entorno, como en la API (load_model las lee).
    if args.engine:
        os.environ["ENGINE"] = args.engine
    if args.model:
        os.environ["MODEL_ID"] = args.model
    if args.dtype:
        os.environ["DTYPE"] = args.dtype
    ram_before = psutil.virtual_memory()
    service, info, _ = default_factory()
    structure = service.engine.state.structure
    memory = {
        "rss_after_model_and_cache_mb": round(rss_mb()),
        "kv_cache_mb": structure["total_mb"], "kv_bytes_per_token": structure["bytes_per_token"],
        "kv_shape_per_layer": structure["key_shape_per_layer"], "num_layers": structure["num_layers"],
        "ram_total_gb": round(ram_before.total / 2**30, 2),
        "ram_available_gb_before": round(ram_before.available / 2**30, 2),
        "ram_available_gb_after_load": round(psutil.virtual_memory().available / 2**30, 2),
    }
    print(f"Motor listo: {info['model_id']} ({info['dtype']}) · caché {info['cache_id']} ({info['cache_source']}, "
          f"{info['cache_seconds']} s) · KV {structure['total_mb']} MB · RSS {memory['rss_after_model_and_cache_mb']} MB "
          f"· {torch.get_num_threads()} hilos", flush=True)

    rows = []
    for q in questions:
        a = service.answer(q["question"], max_new_tokens=args.max_new_tokens)
        cited_docs = [d.document_id for d in a.citations.documents]
        outcome = classify(q, a.decision, cited_docs)
        rows.append({
            "id": q["id"], "question": q["question"], "answerable": q["answerable"],
            "expected_documents": q.get("expected_documents", []), "outcome": outcome,
            "decision": a.decision, "cited_sections": [c.section_id for c in a.citations.citations],
            "cited_documents": cited_docs, "invalid_ids": a.citations.invalid_ids,
            "off_topic_ids": a.citations.off_topic_ids, "rejected_citations": a.citations.rejected_citations,
            "coverage": a.citations.coverage,
            "weak_citations": [c.section_id for c in a.citations.citations if c.weak_support],
            "warnings": a.citations.warnings, "stopped_by": a.stopped_by,
            "tokens": a.tokens, "timings": a.timings, "raw_text": a.raw_text,
            "seconds_per_token": round((a.timings["generation_seconds"] - a.timings["first_token_seconds"])
                                       / max(a.tokens["output"] - 1, 1), 4),
        })
        print(f"{q['id']} {outcome:20} {a.decision:11} citas={rows[-1]['cited_sections']} "
              f"inválidas={a.citations.invalid_ids} {a.tokens['output']} tokens en "
              f"{a.timings['generation_seconds']:.0f} s ({rows[-1]['seconds_per_token']} s/token)", flush=True)

    counts = summarize(rows)
    result = {
        "phase": 5,
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": info, "memory": memory, "peak_working_set_mb": round(getattr(psutil.Process().memory_info(), "peak_wset", 0) / 2**20) or None, "torch_threads": torch.get_num_threads(),
        "questions_file": QUESTIONS_FILE.name, "summary": counts, "rows": rows,
    }
    tag = f"_{args.tag}" if args.tag else ""
    out = DATA_DIR / "results" / f"phase5_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}{tag}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Resumen: {counts}\nGuardado en {out}", flush=True)


if __name__ == "__main__":
    main()
