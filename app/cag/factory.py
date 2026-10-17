"""Creación del motor CAG según la configuración (``ENGINE`` en el .env).

- ``ENGINE=llamacpp``: modelo GGUF cuantizado con llama.cpp (``LlamaCppEngine``). Es el que usa
  TramitaIA desde la Fase 5 (Qwen2.5-7B-Instruct Q4_K_M).
- ``ENGINE=transformers``: modelo de Hugging Face con PyTorch (``CAGEngine``), el de las Fases 3 y 4.

La API, la CLI y la evaluación crean el motor por acá, así que cambiar de motor es cambiar el .env.
"""

from __future__ import annotations

import os

ENGINES = ("llamacpp", "transformers")


def engine_kind(kind: str | None = None) -> str:
    kind = (kind or os.environ.get("ENGINE") or "transformers").strip().lower()
    if kind not in ENGINES:
        raise ValueError(f"ENGINE desconocido: {kind!r}. Opciones: {ENGINES}")
    return kind


def create_engine(kind: str | None = None, transformers_model=None, **kwargs):
    """Crea el motor para el último corpus (sin preparar la caché) y un resumen de su configuración.

    ``transformers_model`` permite reutilizar un modelo de PyTorch ya cargado (al reconstruir la
    caché desde la API). Devuelve ``(motor, info, modelo_reutilizable)``.
    """
    kind = engine_kind(kind)
    if kind == "llamacpp":
        from app.cag.llamacpp_engine import LlamaCppEngine

        engine = LlamaCppEngine.from_latest_corpus(**kwargs)
        info = {
            "engine": "llama.cpp", "model_id": engine.identity.model_id, "revision": engine.identity.revision,
            "dtype": engine.identity.dtype, "device": "cpu", "model_load_seconds": round(engine.load_seconds, 2),
            "threads": engine.threads, "n_ctx": engine.n_ctx, "flash_attn": engine.flash_attn,
        }
        return engine, info, None

    from app.cag.engine import CAGEngine
    from app.cag.model_loader import load_model

    lm = transformers_model or load_model()
    engine = CAGEngine.from_latest_corpus(lm, **kwargs)
    info = {
        "engine": "transformers", "model_id": lm.model_id, "revision": lm.revision, "dtype": lm.dtype,
        "device": lm.device, "model_load_seconds": round(lm.load_seconds, 2) if transformers_model is None else None,
    }
    return engine, info, lm
