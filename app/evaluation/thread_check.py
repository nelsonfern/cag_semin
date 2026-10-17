"""Compara la velocidad de una consulta CAG con distinta cantidad de hilos de torch en CPU.

Carga el modelo y la caché guardada una sola vez y, para cada cantidad de hilos, responde la
misma pregunta varias veces (decodificación greedy: el texto debe ser idéntico en todas).
Mide el procesamiento de la pregunta y los segundos por token generado.

Uso:
    python -X utf8 -m app.evaluation.thread_check --threads 6 12 --repeats 3 --max-new-tokens 48
Resultados: data/results/phase5_threads_<fecha>.json
"""

from __future__ import annotations

import app.config  # noqa: F401  (carga el .env, incluido HF_HOME, antes de importar transformers)

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone

import torch

from app.cag.engine import CAGEngine
from app.cag.model_loader import load_model
from app.config import DATA_DIR

QUESTION = "¿Cómo solicito una partida de nacimiento en La Rioja?"


def main(argv: list[str] | None = None) -> None:
    """Mide cada configuración de hilos y guarda medianas y valores individuales."""
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, nargs="+", default=[6, 12])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--max-new-tokens", type=int, default=48)
    args = parser.parse_args(argv)

    default_threads = torch.get_num_threads()
    lm = load_model()
    engine = CAGEngine.from_latest_corpus(lm, max_new_tokens=args.max_new_tokens)
    engine.prepare(allow_build=False)
    print(f"Modelo {lm.model_id} ({lm.dtype}) · caché {engine.identity.cache_id} desde disco", flush=True)

    engine.answer(QUESTION)  # calentamiento: la primera consulta paga inicializaciones de torch
    runs, texts = {}, set()
    for n in args.threads:
        torch.set_num_threads(n)
        rows = []
        for _ in range(args.repeats):
            r = engine.answer(QUESTION)
            decode_tokens = len(r.output_ids) - 1
            rows.append({
                "prefill_seconds": round(r.prefill_seconds, 3),
                "total_seconds": round(r.total_seconds, 3),
                "seconds_per_token": round((r.total_seconds - r.ttft_seconds) / max(decode_tokens, 1), 4),
                "output_tokens": len(r.output_ids),
            })
            texts.add(r.text)
        runs[n] = {
            "runs": rows,
            "median_prefill_seconds": statistics.median(x["prefill_seconds"] for x in rows),
            "median_seconds_per_token": statistics.median(x["seconds_per_token"] for x in rows),
            "median_total_seconds": statistics.median(x["total_seconds"] for x in rows),
        }
        print(f"{n} hilos: {runs[n]['median_seconds_per_token']:.3f} s/token · pregunta "
              f"{runs[n]['median_prefill_seconds']:.2f} s · total {runs[n]['median_total_seconds']:.1f} s", flush=True)

    result = {
        "phase": 5,
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_id": lm.model_id, "dtype": lm.dtype, "revision": lm.revision,
        "cache_id": engine.identity.cache_id, "question": QUESTION,
        "max_new_tokens": args.max_new_tokens, "repeats": args.repeats,
        "torch_default_threads": default_threads,
        "same_text_in_all_runs": len(texts) == 1,
        "by_threads": runs,
    }
    out = DATA_DIR / "results" / f"phase5_threads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Guardado en {out}", flush=True)


if __name__ == "__main__":
    main()
