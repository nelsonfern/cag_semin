"""Demostración mínima reproducible de CAG (Fase 3).

Con el corpus real y un modelo real:
1. Construye UNA vez la caché KV del prefijo (instrucciones + corpus).
2. Responde dos preguntas independientes reutilizándola.
3. Las compara con el baseline (prefijo + pregunta procesados desde cero en cada consulta).
4. Comprueba que, después de cada consulta, la caché vuelve a ser exactamente la del prefijo,
   sin tokens de la respuesta anterior.
5. Control negativo: repite sin restaurar la caché para mostrar la contaminación.

Uso:
    python -X utf8 -m app.cag.demo_kv [--model Qwen/Qwen2.5-1.5B-Instruct] [--dtype float32]
Resultados: data/results/phase3_kv_demo_<fecha>.json
"""

from __future__ import annotations

import argparse
import gc
import json
import platform
import sys
import time
from datetime import datetime, timezone

import psutil
import torch
import transformers

from app.cag.cache_builder import DEFAULT_CHUNK_SIZE, build_kv_cache
from app.cag.engine import answer_with_cache, answer_without_cache, reset_to_prefix, verify_base_state
from app.cag.model_loader import load_model, rss_mb
from app.cag.prompt import build_prefix, build_question, check_boundary
from app.config import DATA_DIR
from app.ingestion.corpus_builder import CORPUS_DIR

QUESTIONS = [
    "¿Cómo solicito una partida de nacimiento en La Rioja?",
    "¿Qué requisitos necesito para tramitar el pasaporte de un menor de edad?",
]


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def summarize(result) -> dict:
    return {
        "question_tokens": result.question_tokens,
        "output_tokens": len(result.output_ids),
        "stopped_by": result.stopped_by,
        "cache_len_before": result.cache_len_before,
        "cache_len_after_generation": result.cache_len_after_generation,
        "prefill_seconds": round(result.prefill_seconds, 3),
        "ttft_seconds": round(result.ttft_seconds, 3),
        "total_seconds": round(result.total_seconds, 3),
        "text": result.text,
    }


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None)
    parser.add_argument("--device", default=None, help="cpu | cuda (por defecto, DEVICE del .env o cpu)")
    parser.add_argument("--dtype", default=None)
    parser.add_argument("--max-new-tokens", type=int, default=96)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    args = parser.parse_args(argv)

    latest = json.loads((CORPUS_DIR / "latest.json").read_text(encoding="utf-8"))
    corpus_text = (CORPUS_DIR / latest["text"]).read_text(encoding="utf-8")
    results: dict = {
        "phase": 3,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu_threads_torch": torch.get_num_threads(),
            "ram_total_gb": round(psutil.virtual_memory().total / 2**30, 2),
            "ram_available_gb_at_start": round(psutil.virtual_memory().available / 2**30, 2),
            "python": platform.python_version(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "cuda_available": torch.cuda.is_available(),
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "gpu_memory_gb": round(torch.cuda.get_device_properties(0).total_memory / 2**30, 2) if torch.cuda.is_available() else None,
        },
        "corpus_build_id": latest["build_id"],
    }

    log("Cargando modelo...")
    lm = load_model(args.model, device=args.device, dtype=args.dtype)
    model, tok = lm.model, lm.tokenizer
    results["model"] = {
        "model_id": lm.model_id, "revision": lm.revision, "device": lm.device, "dtype": lm.dtype,
        "num_parameters": lm.num_parameters, "load_seconds": round(lm.load_seconds, 2),
        "rss_before_mb": round(lm.rss_before_mb), "rss_after_mb": round(lm.rss_after_mb),
    }
    log(f"Modelo {lm.model_id} ({lm.dtype}) cargado en {lm.load_seconds:.1f} s")

    prefix = build_prefix(tok, corpus_text)
    questions = [build_question(tok, corpus_text, q) for q in QUESTIONS]
    results["prompt"] = {
        "prefix_tokens": len(prefix.ids),
        "question_tokens": [len(q.ids) for q in questions],
        "boundary_ok": [check_boundary(tok, prefix, q) for q in questions],
        "chunk_size": args.chunk_size,
        "max_new_tokens": args.max_new_tokens,
    }
    log(f"Prefijo: {len(prefix.ids)} tokens; preguntas: {results['prompt']['question_tokens']}; "
        f"unión de tokenización correcta: {results['prompt']['boundary_ok']}")
    if not all(results["prompt"]["boundary_ok"]):
        raise SystemExit("La tokenización por partes no coincide con la del texto completo")

    # --- Fase B: construir la caché una vez -----------------------------------
    log("Construyendo la caché KV del prefijo...")
    state = build_kv_cache(model, prefix.ids, chunk_size=args.chunk_size)
    results["cache"] = {
        "build_seconds": round(state.build_seconds, 2),
        "rss_before_mb": round(state.rss_before_mb), "rss_after_mb": round(state.rss_after_mb),
        "fingerprint": state.fingerprint, **state.structure,
    }
    log(f"Caché construida en {state.build_seconds:.1f} s: {state.structure['total_mb']} MB, "
        f"capas={state.structure['num_layers']}, forma K por capa={state.structure['key_shape_per_layer']}")

    # --- Fase C: dos consultas independientes reutilizando la caché -------------
    cag = []
    for i, q in enumerate(questions, 1):
        log(f"CAG pregunta {i}...")
        r = answer_with_cache(model, tok, state, q.ids, max_new_tokens=args.max_new_tokens)
        verify_base_state(state)  # lanza excepción si quedó algo de esta consulta
        cag.append(r)
        log(f"  {r.total_seconds:.1f} s (pregunta procesada en {r.prefill_seconds:.2f} s): {r.text[:120]!r}")

    # --- Baseline: sin caché reutilizable ---------------------------------------
    base = []
    for i, q in enumerate(questions, 1):
        log(f"Baseline pregunta {i} (procesa prefijo + pregunta desde cero)...")
        r = answer_without_cache(model, tok, prefix.ids, q.ids, max_new_tokens=args.max_new_tokens,
                                 chunk_size=args.chunk_size)
        base.append(r)
        gc.collect()
        log(f"  {r.total_seconds:.1f} s (prefill {r.prefill_seconds:.1f} s)")

    # --- Control negativo: sin restaurar la caché ---------------------------------
    log("Control negativo: pregunta 1 y 2 sin restaurar la caché...")
    answer_with_cache(model, tok, state, questions[0].ids, max_new_tokens=args.max_new_tokens, reset=False)
    contaminated = answer_with_cache(model, tok, state, questions[1].ids, max_new_tokens=args.max_new_tokens, reset=False)
    removed = reset_to_prefix(state)
    verify_base_state(state)

    checks = {
        "q1_cag_equals_baseline_tokens": cag[0].output_ids == base[0].output_ids,
        "q2_cag_equals_baseline_tokens": cag[1].output_ids == base[1].output_ids,
        "q2_first_logits_max_abs_diff_vs_baseline": float((cag[1].first_token_logits - base[1].first_token_logits).abs().max()),
        "cache_len_before_each_cag_query": [r.cache_len_before for r in cag],
        "prefix_len": state.prefix_len,
        "cache_restored_after_each_query": True,  # verify_base_state no lanzó excepción
        "negative_control": {
            "cache_len_before_q2_without_reset": contaminated.cache_len_before,
            "extra_positions_from_previous_query": contaminated.cache_len_before - state.prefix_len,
            "q2_tokens_differ_from_clean_answer": contaminated.output_ids != base[1].output_ids,
            "first_logits_max_abs_diff_vs_clean": float((contaminated.first_token_logits - base[1].first_token_logits).abs().max()),
            "text": contaminated.text,
            "positions_removed_by_reset": removed,
            "base_state_recovered": True,
        },
    }
    results["queries"] = [
        {"question": QUESTIONS[i], "cag": summarize(cag[i]), "baseline": summarize(base[i])} for i in range(2)
    ]
    results["checks"] = checks
    results["rss_peak_like_mb_at_end"] = round(rss_mb())
    if torch.cuda.is_available():
        results["vram_max_allocated_mb"] = round(torch.cuda.max_memory_allocated() / 2**20)
    results["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    out_dir = DATA_DIR / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"phase3_kv_demo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    log("RESULTADO")
    for k in ("q1_cag_equals_baseline_tokens", "q2_cag_equals_baseline_tokens", "q2_first_logits_max_abs_diff_vs_baseline"):
        log(f"  {k}: {checks[k]}")
    log(f"  control negativo: {json.dumps(checks['negative_control'], ensure_ascii=False)[:300]}")
    for i, q in enumerate(results["queries"], 1):
        log(f"  P{i} CAG {q['cag']['total_seconds']} s vs baseline {q['baseline']['total_seconds']} s")
    log(f"Guardado en {out}")


if __name__ == "__main__":
    main()
