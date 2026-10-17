"""Medición de la Fase 4: guardar la caché KV en disco, cargarla y verificar que responde igual.

1. Carga el modelo (separado del resto de los costos).
2. Construye la caché del prefijo y la guarda (``data/caches/<cache_id>/``).
3. Descarta la caché de memoria y la vuelve a cargar desde disco con otro motor, validando
   modelo, revisión, dtype, prefijo, corpus y huella.
4. Responde las preguntas de la Fase 3 con la caché cargada y compara el texto con el JSON de
   esa demo (mismo modelo, dtype, prefijo y ``max_new_tokens``; decodificación greedy).

Uso:
    python -X utf8 -m app.cag.demo_store --phase3 data/results/phase3_kv_demo_<fecha>.json
Resultados: data/results/phase4_cache_store_<fecha>.json
"""

from __future__ import annotations

import app.config  # noqa: F401  (carga el .env, incluido HF_HOME, antes de importar transformers)

import argparse
import gc
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import psutil
import torch
import transformers

from app.cag.cache_store import cache_dir
from app.cag.engine import CAGEngine
from app.cag.model_loader import load_model, rss_mb
from app.config import DATA_DIR


def log(msg: str) -> None:
    """Imprime con hora (el log queda en data/results/phase4_demo.log)."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def main(argv: list[str] | None = None) -> None:
    """Ejecuta los pasos 1 a 4 de la cabecera y guarda el JSON de resultados."""
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase3", type=Path, required=True, help="JSON de la demo de la Fase 3 para comparar")
    parser.add_argument("--device", default=None)
    args = parser.parse_args(argv)

    phase3 = json.loads(args.phase3.read_text(encoding="utf-8"))
    model_id, dtype = phase3["model"]["model_id"], phase3["model"]["dtype"]
    max_new = phase3["prompt"]["max_new_tokens"]
    results: dict = {
        "phase": 4,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": {
            "platform": platform.platform(),
            "cpu_threads_torch": torch.get_num_threads(),
            "ram_total_gb": round(psutil.virtual_memory().total / 2**30, 2),
            "ram_available_gb_at_start": round(psutil.virtual_memory().available / 2**30, 2),
            "python": platform.python_version(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
        },
        "compared_with": args.phase3.name,
    }

    log(f"Cargando modelo {model_id} ({dtype})...")
    lm = load_model(model_id, device=args.device, dtype=dtype)
    results["model"] = {"model_id": lm.model_id, "revision": lm.revision, "dtype": lm.dtype,
                        "load_seconds": round(lm.load_seconds, 2), "rss_after_mb": round(lm.rss_after_mb)}
    log(f"Modelo cargado en {lm.load_seconds:.1f} s · revisión {lm.revision}")

    # --- Construir y guardar --------------------------------------------------------------
    builder = CAGEngine.from_latest_corpus(lm, max_new_tokens=max_new)
    if builder.prefix_len != phase3["prompt"]["prefix_tokens"]:
        raise SystemExit(f"El prefijo cambió desde la Fase 3: {builder.prefix_len} != {phase3['prompt']['prefix_tokens']}")
    log(f"Construyendo y guardando la caché {builder.identity.cache_id}...")
    built = builder.prepare(force_rebuild=True)
    fingerprint_built = builder.state.fingerprint
    results["build"] = {
        "cache_id": built["cache_id"], "build_seconds": round(built["seconds"], 2),
        "save_seconds": built["save_seconds"], "file_bytes": built["file_bytes"],
        "file_mb": round(built["file_bytes"] / 2**20, 2), "fingerprint": fingerprint_built,
        "fingerprint_equals_phase3": fingerprint_built == phase3["cache"]["fingerprint"],
        "path": str(cache_dir(builder.identity).relative_to(DATA_DIR.parent)),
    }
    log(f"Construida en {built['seconds']:.1f} s · guardada en {built['save_seconds']:.2f} s · "
        f"{results['build']['file_mb']} MB · huella igual a la de la Fase 3: {results['build']['fingerprint_equals_phase3']}")

    # --- Descartar y cargar desde disco -----------------------------------------------------
    del builder
    gc.collect()
    rss_before_load = rss_mb()
    engine = CAGEngine.from_latest_corpus(lm, max_new_tokens=max_new)
    loaded = engine.prepare(allow_build=False)
    results["load"] = {
        "source": loaded["source"], "load_seconds": round(loaded["seconds"], 3),
        "rss_before_mb": round(rss_before_load), "rss_after_mb": round(rss_mb()),
        "fingerprint_equals_built": engine.state.fingerprint == fingerprint_built,
    }
    log(f"Cargada desde disco en {loaded['seconds']:.2f} s (validada) · huella igual: "
        f"{results['load']['fingerprint_equals_built']}")

    # --- Responder con la caché cargada ------------------------------------------------------
    results["queries"] = []
    for i, ref in enumerate(phase3["queries"], 1):
        log(f"Pregunta {i} con la caché cargada...")
        r = engine.answer(ref["question"])
        same = r.text == ref["cag"]["text"]
        results["queries"].append({
            "question": ref["question"], "question_tokens": r.question_tokens, "output_tokens": len(r.output_ids),
            "prefill_seconds": round(r.prefill_seconds, 3), "ttft_seconds": round(r.ttft_seconds, 3),
            "total_seconds": round(r.total_seconds, 3), "text_equals_phase3": same, "text": r.text,
        })
        log(f"  {r.total_seconds:.1f} s (pregunta en {r.prefill_seconds:.2f} s) · igual a la Fase 3: {same}")

    results["checks"] = {
        "all_answers_equal_phase3": all(q["text_equals_phase3"] for q in results["queries"]),
        "cache_restored": engine.state.cache.get_seq_length() == engine.prefix_len,
        "recoveries": engine.recoveries,
    }
    results["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = DATA_DIR / "results" / f"phase4_cache_store_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"RESULTADO {json.dumps(results['checks'], ensure_ascii=False)}")
    log(f"Guardado en {out}")


if __name__ == "__main__":
    main()
