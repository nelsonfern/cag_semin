"""Benchmark de la Fase 6: CAG frente al baseline sin caché, con el motor de la app (llama.cpp).

Mide por separado cada costo (§7 de la especificación):

1. Preparación documental: descarga de las fuentes automáticas (sin tocar el manifiesto) y
   construcción del corpus en memoria (sin escribir archivos).
2. Carga del modelo: 3 cargas en procesos separados (la primera puede encontrar el archivo fuera
   de la caché del sistema operativo) y la del motor.
3. Carga de la caché KV desde disco: 5 veces.
4. Primera consulta sin calentamiento y consultas CAG: 6 preguntas × N repeticiones.
5. Construcción de la caché KV.
6. Baseline sin caché: prefijo + pregunta desde cero, 2 preguntas × M repeticiones.

Para comparar tiempos, cada respuesta genera exactamente ``--tokens`` tokens (``ignore_eos``):
así el largo de cada respuesta no influye. Se registra la memoria en cada etapa. El JSON se
guarda al terminar cada etapa (si el proceso se corta, lo medido no se pierde).

Uso:
    python -X utf8 -m app.evaluation.benchmark [--reps 5] [--baseline-reps 3] [--tokens 128] [--quick]
Resultados: data/results/phase6_benchmark_<fecha>.json
"""

from __future__ import annotations

import app.config  # noqa: F401  (carga el .env)

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone

import numpy as np
import psutil

from app.cag.model_loader import rss_mb
from app.config import DATA_DIR

QUESTIONS = {
    "q01": "¿Cómo solicito una partida de nacimiento en La Rioja?",
    "q02": "¿Qué requisitos piden para inscribir una defunción?",
    "q04": "¿Qué necesito para tramitar el DNI de un recién nacido?",
    "q06": "¿Cuáles son los requisitos para registrar una unión convivencial?",
    "q07": "¿Cómo hago para rectificar un error en una partida?",
    "q13": "¿Qué requisitos publica el Registro Civil para el pasaporte de un menor?",
}
BASELINE_QUESTIONS = ["q02", "q13"]


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def memoria() -> dict:
    vm = psutil.virtual_memory()
    peak = getattr(psutil.Process().memory_info(), "peak_wset", None)
    return {"rss_mb": round(rss_mb()), "peak_working_set_mb": round(peak / 2**20) if peak else None,
            "ram_available_gb": round(vm.available / 2**30, 2)}


def resumen(valores: list[float]) -> dict:
    """Mediana, p10, p90, mínimo, máximo y cantidad (con interpolación lineal)."""
    if not valores:
        return {}
    a = np.array(valores, dtype=float)
    return {"n": len(valores), "median": round(float(np.median(a)), 3), "p10": round(float(np.percentile(a, 10)), 3),
            "p90": round(float(np.percentile(a, 90)), 3), "min": round(float(a.min()), 3), "max": round(float(a.max()), 3)}


def cpu_name() -> str:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"],
                             capture_output=True, text=True, timeout=20)
        return out.stdout.strip() or platform.processor()
    except (OSError, subprocess.TimeoutExpired):
        return platform.processor()


def medir_descarga() -> dict:
    """Descarga las fuentes automáticas (robots.txt y pausas incluidos) sin registrar nada."""
    from app.ingestion.downloader import PoliteDownloader
    from app.ingestion.source_registry import load_sources

    d = PoliteDownloader()
    filas, inicio = [], time.perf_counter()
    for spec in load_sources():
        if spec.acquisition != "auto":
            continue
        t = time.perf_counter()
        try:
            r = d.fetch(spec.source_url)
            filas.append({"document_id": spec.document_id, "seconds": round(time.perf_counter() - t, 2),
                          "bytes": len(r.content), "status": r.status_code})
        except Exception as exc:  # se informa: una fuente caída no invalida el resto
            filas.append({"document_id": spec.document_id, "error": f"{type(exc).__name__}: {exc}"})
    return {"total_seconds": round(time.perf_counter() - inicio, 2), "delay_between_requests_s": d.min_delay
            if hasattr(d, "min_delay") else None, "documents": filas,
            "note": "Incluye las pausas de cortesía entre pedidos y la lectura de robots.txt; no modifica el manifiesto."}


def medir_corpus() -> dict:
    """Construye el corpus en memoria (mismo build_id que el actual si nada cambió)."""
    from app.ingestion.corpus_builder import HFTokenizer, build_corpus, load_config, load_latest
    from app.ingestion.source_registry import Manifest

    config = load_config()
    t = time.perf_counter()
    tok = HFTokenizer(config["tokenizer_id"])
    t_tok = time.perf_counter() - t
    t = time.perf_counter()
    build = build_corpus(Manifest(), config, tok)
    t_build = time.perf_counter() - t
    _, report = load_latest()
    return {"tokenizer_load_seconds": round(t_tok, 2), "build_seconds": round(t_build, 2),
            "build_id": build.build_id, "same_as_current": build.build_id == report["build_id"],
            "tokens": build.report["totals"]["tokens"]}


def medir_carga_modelo(model_path: str, n_ctx: int, threads: int, flash_attn: bool, veces: int) -> list[float]:
    """Carga el modelo en procesos separados (cada uno libera la memoria al terminar)."""
    codigo = (
        "import time, sys\n"
        "from llama_cpp import Llama\n"
        "t = time.perf_counter()\n"
        f"Llama(model_path=sys.argv[1], n_ctx={n_ctx}, n_batch=512, n_ubatch=512, n_threads={threads}, "
        f"n_threads_batch={threads}, flash_attn={flash_attn}, logits_all=False, verbose=False)\n"
        "print(time.perf_counter() - t)\n"
    )
    tiempos = []
    for _ in range(veces):
        out = subprocess.run([sys.executable, "-c", codigo, model_path], capture_output=True, text=True, check=True)
        tiempos.append(round(float(out.stdout.strip().splitlines()[-1]), 2))
    return tiempos


def generar_fijo(engine, n: int) -> tuple[list[int], float, float]:
    """Greedy de exactamente ``n`` tokens desde el estado actual (para el baseline)."""
    start = time.perf_counter()
    out, ttft = [], 0.0
    for i in range(n):
        token = int(np.argmax(engine._last_logits()))
        if i == 0:
            ttft = time.perf_counter() - start
        out.append(token)
        engine.llm.eval([token])
    return out, ttft, time.perf_counter() - start


def main(argv: list[str] | None = None) -> None:
    """Corre las etapas del benchmark y guarda el JSON después de cada una."""
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--reps", type=int, default=5, help="repeticiones de cada pregunta CAG")
    parser.add_argument("--baseline-reps", type=int, default=3)
    parser.add_argument("--tokens", type=int, default=128, help="tokens generados por respuesta (fijo)")
    parser.add_argument("--quick", action="store_true", help="prueba rápida: 1 rep, 2 preguntas, sin baseline ni descarga")
    args = parser.parse_args(argv)

    import llama_cpp

    from app.cag.factory import create_engine

    out_path = DATA_DIR / "results" / f"phase6_benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}{'_quick' if args.quick else ''}.json"
    res: dict = {
        "phase": 6, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {"reps": args.reps, "baseline_reps": args.baseline_reps, "tokens_per_answer": args.tokens,
                   "quick": args.quick, "ignore_eos": True},
        "environment": {
            "cpu": cpu_name(), "logical_cpus": psutil.cpu_count(), "physical_cpus": psutil.cpu_count(logical=False),
            "ram_total_gb": round(psutil.virtual_memory().total / 2**30, 2), "os": platform.platform(),
            "python": platform.python_version(), "llama_cpp_python": llama_cpp.__version__, "gpu_used": False,
            "gpu_note": "Radeon RX 6400 (4 GB): sin CUDA y fuera de ROCm en Windows; llama-cpp-python instalado para CPU.",
        },
        "stages": {},
    }

    def guardar():
        out_path.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    preguntas = dict(list(QUESTIONS.items())[:2]) if args.quick else QUESTIONS
    reps = 1 if args.quick else args.reps

    if not args.quick:
        log("Etapa 1: descarga de fuentes (sin registrar)...")
        res["stages"]["download"] = medir_descarga()
        log(f"  {res['stages']['download']['total_seconds']} s")
        guardar()
    log("Etapa 1b: construcción del corpus en memoria...")
    res["stages"]["corpus_build"] = medir_corpus()
    log(f"  {res['stages']['corpus_build']}")
    guardar()

    log("Etapa 2: motor (carga del modelo)...")
    m0 = memoria()
    engine, info, _ = create_engine("llamacpp", max_new_tokens=args.tokens)
    res["engine"] = {**info, "cache_id": engine.identity.cache_id, "prefix_tokens": engine.prefix_len,
                     "model_bytes": engine.gguf.path.stat().st_size}
    res["stages"]["model_load"] = {"engine_load_seconds": round(engine.load_seconds, 2),
                                   "memory_before": m0, "memory_after": memoria()}
    if not args.quick:
        log("  cargas extra en procesos separados...")
        res["stages"]["model_load"]["subprocess_load_seconds"] = medir_carga_modelo(
            str(engine.gguf.path), engine.n_ctx, engine.threads, engine.flash_attn, 3)
    log(f"  {res['stages']['model_load']}")
    guardar()

    log("Etapa 3: carga de la caché desde disco...")
    cargas = []
    for i in range(1 if args.quick else 5):
        rep = engine.prepare(allow_build=False)
        cargas.append(round(rep["seconds"], 3))
    res["stages"]["cache_load"] = {"seconds": cargas, "summary": resumen(cargas),
                                   "kv_mb": engine.state.structure["total_mb"], "memory": memoria()}
    log(f"  {cargas}")
    guardar()

    log("Etapa 4: primera consulta sin calentamiento + consultas CAG...")
    filas, ids_cag = [], {}
    for rep in range(reps):
        for qid, q in preguntas.items():
            r = engine.answer(q, max_new_tokens=args.tokens, ignore_eos=True)
            filas.append({"rep": rep, "id": qid, "first_in_process": not filas, "question_tokens": r.question_tokens,
                          "output_tokens": len(r.output_ids), "prefill_seconds": round(r.prefill_seconds, 3),
                          "ttft_seconds": round(r.ttft_seconds, 3), "total_seconds": round(r.total_seconds, 3),
                          "seconds_per_token": round((r.total_seconds - r.ttft_seconds) / max(len(r.output_ids) - 1, 1), 4),
                          "cache_len_before": r.cache_len_before})
            ids_cag.setdefault(qid, r.output_ids)
            log(f"  rep {rep} {qid}: TTFT {r.ttft_seconds:.2f} s · total {r.total_seconds:.1f} s")
            res["stages"]["cag"] = {"rows": filas}
            guardar()
    calientes = [f for f in filas if not f["first_in_process"]]
    res["stages"]["cag"].update({
        "first_query": filas[0],
        "ttft": resumen([f["ttft_seconds"] for f in calientes]),
        "prefill": resumen([f["prefill_seconds"] for f in calientes]),
        "total": resumen([f["total_seconds"] for f in calientes]),
        "seconds_per_token": resumen([f["seconds_per_token"] for f in calientes]),
        "memory": memoria(), "recoveries": engine.recoveries,
    })
    guardar()

    if not args.quick:
        log("Etapa 5: construcción de la caché KV...")
        m = memoria()
        rep = engine.prepare(force_rebuild=True)
        res["stages"]["cache_build"] = {"seconds": round(rep["seconds"], 2), "save_seconds": rep.get("save_seconds"),
                                        "state_bytes": rep.get("file_bytes"), "memory_before": m, "memory_after": memoria(),
                                        "fingerprint_unchanged": engine.state.fingerprint == engine.fingerprint()[0]}
        log(f"  {res['stages']['cache_build']['seconds']} s")
        guardar()

        log("Etapa 6: baseline sin caché (prefijo + pregunta desde cero)...")
        base = []
        for qid in BASELINE_QUESTIONS:
            for rep_i in range(args.baseline_reps):
                engine.llm.reset()
                t = time.perf_counter()
                engine.llm.eval(list(engine.identity.prefix_ids))
                t_prefix = time.perf_counter() - t
                q_ids = engine.encode_question(QUESTIONS[qid])
                t2 = time.perf_counter()
                engine.llm.eval(q_ids)
                t_q = time.perf_counter() - t2
                ids, ttft_gen, gen = generar_fijo(engine, args.tokens)
                fila = {"rep": rep_i, "id": qid, "prefix_seconds": round(t_prefix, 2), "question_seconds": round(t_q, 3),
                        "ttft_seconds": round(t_prefix + t_q + ttft_gen, 2), "total_seconds": round(t_prefix + t_q + gen, 2),
                        "seconds_per_token": round((gen - ttft_gen) / max(args.tokens - 1, 1), 4),
                        "same_tokens_as_cag": ids == ids_cag.get(qid), "memory": memoria()}
                base.append(fila)
                log(f"  {qid} rep {rep_i}: prefijo {t_prefix:.1f} s · total {fila['total_seconds']:.1f} s · "
                    f"igual a CAG: {fila['same_tokens_as_cag']}")
                res["stages"]["baseline"] = {"rows": base}
                guardar()
        res["stages"]["baseline"].update({
            "prefix": resumen([b["prefix_seconds"] for b in base]),
            "ttft": resumen([b["ttft_seconds"] for b in base]),
            "total": resumen([b["total_seconds"] for b in base]),
            "seconds_per_token": resumen([b["seconds_per_token"] for b in base]),
            "all_same_tokens_as_cag": all(b["same_tokens_as_cag"] for b in base),
        })
        engine.prepare(allow_build=False)  # deja la caché del prefijo como estaba
        guardar()

    res["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    res["peak_working_set_mb"] = memoria()["peak_working_set_mb"]
    guardar()
    log(f"Guardado en {out_path}")


if __name__ == "__main__":
    main()
