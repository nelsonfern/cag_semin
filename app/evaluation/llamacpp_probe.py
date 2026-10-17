"""Prueba de factibilidad: CAG con llama.cpp (llama-cpp-python) y un modelo GGUF cuantizado.

Pregunta a responder: ¿se puede hacer CAG verificable con llama.cpp, que es mucho más rápido en
CPU que PyTorch? Ollama y LM Studio usan llama.cpp pero no exponen la caché KV (ver Fase 3);
la librería llama-cpp-python sí permite guardarla y restaurarla.

Cómo funciona la caché en llama-cpp-python 0.3.x (verificado en su código):
- ``Llama.eval(tokens)`` primero borra de la caché KV todo lo que está después de ``n_tokens``
  (``kv_cache_seq_rm``) y después procesa los tokens nuevos. Por eso **restaurar el prefijo es
  volver ``n_tokens`` al largo del prefijo**: el equivalente de ``DynamicCache.crop``.
- ``save_state()`` / ``load_state()`` copian el estado del contexto (incluida la caché KV) para
  guardarlo en disco y volver a cargarlo.
- Con ``logits_all=False`` esta versión no guarda logits en ``eval``: se leen del contexto.

Verificaciones (las mismas que la Fase 3): CAG = baseline token por token, huella de la caché
del prefijo igual antes y después de cada consulta, control negativo sin restaurar, y que el
estado guardado reproduce la misma respuesta. Después responde preguntas de la evaluación y
aplica las mismas reglas de citas que la app.

Uso:
    python -X utf8 -m app.evaluation.llamacpp_probe --model-path <archivo.gguf> --only q01 q11 q13 q14
Resultados: data/results/phase5_llamacpp_<fecha>.json
"""

from __future__ import annotations

import app.config  # noqa: F401  (carga el .env)

import argparse
import ctypes
import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import psutil

from app.cag.model_loader import rss_mb
from app.cag.prompt import CHAT_TEMPLATES, SYSTEM_CLOSING, SYSTEM_INSTRUCTIONS
from app.config import DATA_DIR
from app.evaluation.evaluate import QUESTIONS_FILE, classify
from app.ingestion.corpus_builder import load_latest
from app.services.answer_service import _is_abstention, decide
from app.services.citations import CitationIndex

# Plantillas de chat compartidas con el motor de la app (app/cag/prompt.py).
TEMPLATES = CHAT_TEMPLATES


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def tokenize(llm, text: str) -> list[int]:
    """Tokens del texto, reconociendo los tokens especiales y sin agregar BOS (ya está en el texto)."""
    return llm.tokenize(text.encode("utf-8"), add_bos=False, special=True)


def last_logits(llm) -> np.ndarray:
    """Logits del último token procesado, leídos del contexto de llama.cpp (copia)."""
    return np.ctypeslib.as_array(llm._ctx.get_logits(), shape=(llm.n_vocab(),)).copy()


def kv_fingerprint(llm) -> tuple[str, int]:
    """SHA-256 de la caché KV de la secuencia 0 (solo K/V, sin logits ni RNG) y su tamaño en bytes."""
    import llama_cpp

    ctx = llm._ctx.ctx
    size = llama_cpp.llama_state_seq_get_size(ctx, 0)
    buf = (ctypes.c_uint8 * int(size))()
    n = llama_cpp.llama_state_seq_get_data(ctx, buf, size, 0)
    return hashlib.sha256(bytes(buf)[: int(n)]).hexdigest()[:32], int(n)


def generate(llm, max_new_tokens: int, stop: set[int]) -> tuple[list[int], np.ndarray, float, float]:
    """Decodificación greedy desde el estado actual. Devuelve tokens, primeros logits, TTFT y total."""
    start = time.perf_counter()
    out, first_logits, ttft = [], None, 0.0
    for i in range(max_new_tokens):
        logits = last_logits(llm)
        token = int(np.argmax(logits))
        if i == 0:
            first_logits, ttft = logits, time.perf_counter() - start
        out.append(token)
        if token in stop:
            break
        llm.eval([token])
    return out, first_logits, ttft, time.perf_counter() - start


def answer_cag(llm, prefix_len: int, q_ids: list[int], max_new: int, stop: set[int]) -> dict:
    """Restaura el prefijo (n_tokens = largo del prefijo), procesa la pregunta y genera."""
    llm.n_tokens = prefix_len
    start = time.perf_counter()
    llm.eval(q_ids)
    prefill = time.perf_counter() - start
    out, first, ttft, total = generate(llm, max_new, stop)
    return {"ids": out, "first_logits": first, "prefill_seconds": prefill,
            "ttft_seconds": prefill + ttft, "total_seconds": prefill + total, "cache_len_after": llm.n_tokens}


def main(argv: list[str] | None = None) -> None:
    """Corre las verificaciones de CAG con llama.cpp y las preguntas pedidas; guarda el JSON."""
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--only", nargs="*", default=["q01", "q11", "q13", "q14"])
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--n-batch", type=int, default=512)
    parser.add_argument("--skip-baseline", action="store_true", help="no recalcular el prefijo (ahorra tiempo)")
    parser.add_argument("--load-state", type=Path, default=None,
                        help="cargar una caché guardada (llamacpp_<huella>.state) en vez de construirla")
    parser.add_argument("--flash-attn", action="store_true", help="atención optimizada de llama.cpp")
    parser.add_argument("--template", choices=sorted(TEMPLATES), default="llama3")
    args = parser.parse_args(argv)

    import llama_cpp
    from llama_cpp import Llama

    PREFIX_TEMPLATE, QUESTION_TEMPLATE, END_OF_TURN = TEMPLATES[args.template]

    corpus_text, report = load_latest()
    system = SYSTEM_INSTRUCTIONS + corpus_text + SYSTEM_CLOSING
    results: dict = {
        "phase": 5, "experiment": "llama.cpp feasibility",
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": {"platform": platform.platform(), "python": platform.python_version(),
                        "llama_cpp_python": llama_cpp.__version__, "threads": args.threads, "n_batch": args.n_batch,
                        "ram_available_gb_at_start": round(psutil.virtual_memory().available / 2**30, 2)},
        "model_path": str(args.model_path), "template": args.template, "model_file_gb": round(args.model_path.stat().st_size / 2**30, 3),
        "corpus_build_id": report["build_id"],
    }

    # --- Carga --------------------------------------------------------------------------------
    log("Cargando el modelo...")
    vocab = Llama(model_path=str(args.model_path), vocab_only=True, verbose=False)
    prefix_text = PREFIX_TEMPLATE.format(system=system)
    prefix_ids = tokenize(vocab, prefix_text)
    n_ctx = ((len(prefix_ids) + 512 + args.max_new_tokens) // 1024 + 1) * 1024
    del vocab
    rss0, t0 = rss_mb(), time.perf_counter()
    llm = Llama(model_path=str(args.model_path), n_ctx=n_ctx, n_batch=args.n_batch, n_ubatch=args.n_batch,
                n_threads=args.threads, n_threads_batch=args.threads, logits_all=False, verbose=False,
                flash_attn=args.flash_attn)
    load_seconds = time.perf_counter() - t0
    stop = {llm.token_eos(), *tokenize(llm, END_OF_TURN)}
    results["model"] = {"load_seconds": round(load_seconds, 2), "rss_before_mb": round(rss0),
                        "rss_after_mb": round(rss_mb()), "n_ctx": n_ctx, "n_vocab": llm.n_vocab(),
                        "stop_tokens": sorted(stop)}
    log(f"Modelo cargado en {load_seconds:.1f} s · n_ctx {n_ctx} · RSS {rss_mb():.0f} MB")

    questions = {q["id"]: q for q in json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))["questions"]}
    q_ids = {qid: tokenize(llm, QUESTION_TEMPLATE.format(question=questions[qid]["question"])) for qid in args.only}
    boundary = {qid: tokenize(llm, prefix_text + QUESTION_TEMPLATE.format(question=questions[qid]["question"]))
                == prefix_ids + ids for qid, ids in q_ids.items()}
    results["prompt"] = {"prefix_tokens": len(prefix_ids), "question_tokens": {k: len(v) for k, v in q_ids.items()},
                         "boundary_ok": boundary, "max_new_tokens": args.max_new_tokens}
    log(f"Prefijo: {len(prefix_ids)} tokens (tokenizer del modelo) · unión de tokenización correcta: {boundary}")

    from llama_cpp.llama import LlamaState

    def state_from_file(path: Path) -> LlamaState:
        """Estado guardado -> LlamaState (los logits no hacen falta: se procesa la pregunta antes de generar)."""
        data = path.read_bytes()
        ids = np.zeros(n_ctx, dtype=np.intc)
        ids[: len(prefix_ids)] = prefix_ids
        return LlamaState(scores=np.zeros((min(len(prefix_ids), args.n_batch), llm.n_vocab()), dtype=np.single),
                          input_ids=ids, n_tokens=len(prefix_ids), llama_state=data,
                          llama_state_size=len(data), seed=llm._seed)

    rss1 = rss_mb()
    if args.load_state:
        # --- Cargar la caché guardada y verificar su huella --------------------------------------
        log(f"Cargando la caché guardada {args.load_state.name}...")
        t1 = time.perf_counter()
        state = state_from_file(args.load_state)
        llm.load_state(state)
        load_seconds_state = time.perf_counter() - t1
        fp0, kv_bytes = kv_fingerprint(llm)
        expected = args.load_state.stem.removeprefix("llamacpp_")
        if not fp0.startswith(expected):
            raise SystemExit(f"La huella de la caché cargada ({fp0[:16]}) no coincide con la del archivo ({expected})")
        state_path = args.load_state
        results["cache"] = {"loaded_from": args.load_state.name, "load_seconds": round(load_seconds_state, 2),
                            "kv_seq_bytes": kv_bytes, "kv_seq_mb": round(kv_bytes / 2**20, 1),
                            "kv_bytes_per_token": kv_bytes // len(prefix_ids), "fingerprint": fp0,
                            "rss_before_mb": round(rss1), "rss_after_mb": round(rss_mb())}
        log(f"Caché cargada y verificada en {load_seconds_state:.1f} s · KV {kv_bytes / 2**20:.0f} MB")
    else:
        # --- Construir la caché del prefijo y guardarla --------------------------------------------
        log("Construyendo la caché KV del prefijo...")
        t1 = time.perf_counter()
        llm.eval(prefix_ids)
        build_seconds = time.perf_counter() - t1
        fp0, kv_bytes = kv_fingerprint(llm)
        t2 = time.perf_counter()
        state = llm.save_state()
        save_state_seconds = time.perf_counter() - t2
        state_path = DATA_DIR / "caches" / f"llamacpp_{fp0[:16]}.state"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        t3 = time.perf_counter()
        state_path.write_bytes(state.llama_state)
        write_seconds = time.perf_counter() - t3
        results["cache"] = {"build_seconds": round(build_seconds, 2), "kv_seq_bytes": kv_bytes,
                            "kv_seq_mb": round(kv_bytes / 2**20, 1), "kv_bytes_per_token": kv_bytes // len(prefix_ids),
                            "state_bytes": state.llama_state_size, "save_state_seconds": round(save_state_seconds, 3),
                            "write_to_disk_seconds": round(write_seconds, 3), "fingerprint": fp0,
                            "state_file": state_path.name, "rss_before_mb": round(rss1), "rss_after_mb": round(rss_mb())}
        log(f"Caché construida en {build_seconds:.1f} s · KV {kv_bytes / 2**20:.0f} MB · estado guardado en disco "
            f"en {save_state_seconds + write_seconds:.2f} s ({state_path.name})")

    # --- Verificaciones de CAG -----------------------------------------------------------------
    first = args.only[0]
    second = args.only[1] if len(args.only) > 1 else args.only[0]
    checks: dict = {}
    log(f"CAG {first}...")
    cag1 = answer_cag(llm, len(prefix_ids), q_ids[first], args.max_new_tokens, stop)
    log(f"  {len(cag1['ids'])} tokens · primer token a los {cag1['ttft_seconds']:.2f} s · total {cag1['total_seconds']:.1f} s")
    llm.n_tokens = len(prefix_ids)
    llm.eval([])  # aplica el recorte de la caché sin procesar tokens
    checks["fingerprint_restored_after_query"] = kv_fingerprint(llm)[0] == fp0

    log(f"CAG {second} (después de {first})...")
    cag2 = answer_cag(llm, len(prefix_ids), q_ids[second], args.max_new_tokens, stop)

    if not args.skip_baseline:
        log(f"Baseline {second}: prefijo + pregunta desde cero...")
        llm.reset()
        t = time.perf_counter()
        llm.eval(prefix_ids)
        llm.eval(q_ids[second])
        base_prefill = time.perf_counter() - t
        base_ids, base_first, _, base_gen = generate(llm, args.max_new_tokens, stop)
        checks.update({
            "baseline_prefill_seconds": round(base_prefill, 2), "baseline_total_seconds": round(base_prefill + base_gen, 2),
            "cag_equals_baseline_tokens": cag2["ids"] == base_ids,
            "first_logits_max_abs_diff_vs_baseline": float(np.max(np.abs(cag2["first_logits"] - base_first))),
        })
        log(f"  CAG = baseline: {checks['cag_equals_baseline_tokens']} (baseline {base_prefill + base_gen:.1f} s)")
        llm.n_tokens = len(prefix_ids)
        llm.eval([])
        checks["fingerprint_after_baseline_recompute"] = kv_fingerprint(llm)[0] == fp0

    log("Control negativo: segunda pregunta sin restaurar...")
    answer_cag(llm, len(prefix_ids), q_ids[first], 8, stop)
    contaminated_len = llm.n_tokens
    llm.eval(q_ids[second])
    contaminated = last_logits(llm)
    checks["negative_control"] = {
        "cache_len_before_second_without_reset": contaminated_len,
        "first_logits_max_abs_diff_vs_clean": float(np.max(np.abs(contaminated - cag2["first_logits"]))),
    }

    log("Cargar el estado guardado en disco y repetir la segunda pregunta...")
    t = time.perf_counter()
    llm.load_state(state_from_file(state_path))
    load_state_seconds = time.perf_counter() - t
    checks["load_state_seconds"] = round(load_state_seconds, 3)
    checks["fingerprint_after_load_state"] = kv_fingerprint(llm)[0] == fp0
    again = answer_cag(llm, len(prefix_ids), q_ids[second], args.max_new_tokens, stop)
    checks["load_state_reproduces_answer"] = again["ids"] == cag2["ids"]
    results["checks"] = checks
    log(f"Verificaciones: {json.dumps(checks, ensure_ascii=False)}")

    # --- Preguntas con las reglas de citas de la app ---------------------------------------------
    index = CitationIndex.from_corpus(corpus_text, report)
    done = {first: cag1, second: cag2}
    rows = []
    for qid in args.only:
        r = done.get(qid) or answer_cag(llm, len(prefix_ids), q_ids[qid], args.max_new_tokens, stop)
        llm.n_tokens = len(prefix_ids)
        llm.eval([])  # restaurar el prefijo
        restored_ok = kv_fingerprint(llm)[0] == fp0
        q = questions[qid]
        text = llm.detokenize([t for t in r["ids"] if t not in stop]).decode("utf-8", errors="replace").strip()
        citations = index.review(text, q["question"])
        decision, _ = decide(q["question"], text, citations)
        outcome = classify(q, decision, [d.document_id for d in citations.documents])
        n = len(r["ids"])
        rows.append({
            "id": qid, "question": q["question"], "answerable": q["answerable"], "outcome": outcome,
            "decision": decision, "coverage": citations.coverage,
            "cited_sections": [c.section_id for c in citations.citations], "invalid_ids": citations.invalid_ids,
            "off_topic_ids": citations.off_topic_ids, "rejected_citations": citations.rejected_citations,
            "output_tokens": n, "stopped_by": "eos" if r["ids"] and r["ids"][-1] in stop else "max_new_tokens",
            "prefill_seconds": round(r["prefill_seconds"], 3), "ttft_seconds": round(r["ttft_seconds"], 3),
            "total_seconds": round(r["total_seconds"], 2),
            "seconds_per_token": round((r["total_seconds"] - r["ttft_seconds"]) / max(n - 1, 1), 4),
            "fingerprint_restored": restored_ok, "raw_text": text,
        })
        log(f"{qid} {outcome:20} {decision:11} cobertura={citations.coverage} citas={rows[-1]['cited_sections']} "
            f"{n} tokens en {r['total_seconds']:.1f} s ({rows[-1]['seconds_per_token']} s/token)")

    results["rows"] = rows
    results["peak_working_set_mb"] = round(getattr(psutil.Process().memory_info(), "peak_wset", 0) / 2**20) or None
    results["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = DATA_DIR / "results" / f"phase5_llamacpp_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"Guardado en {out}")


if __name__ == "__main__":
    main()
