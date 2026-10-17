"""Carga del modelo causal y su tokenizer (Hugging Face Transformers).

El tiempo y la memoria de carga se registran por separado del costo de procesar el corpus y
del de generar respuestas, porque son costos distintos (§7 de la especificación).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import psutil
import torch

DEFAULT_MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"

_DTYPES = {"float32": torch.float32, "bfloat16": torch.bfloat16, "float16": torch.float16}


@dataclass
class LoadedModel:
    """Modelo y tokenizer cargados, con los datos que identifican los pesos y el costo de carga."""

    model: object
    tokenizer: object
    model_id: str
    revision: str | None
    device: str
    dtype: str
    num_parameters: int
    load_seconds: float
    rss_before_mb: float
    rss_after_mb: float


def rss_mb() -> float:
    """Memoria residente del proceso (RAM física usada), en MB."""
    return psutil.Process().memory_info().rss / 2**20


def resolve_revision(model_id: str, config=None) -> str | None:
    """Commit del modelo en el Hub, para saber exactamente qué pesos generaron una caché.

    ``config._commit_hash`` puede venir vacío al cargar desde la caché local; en ese caso se
    toma del nombre de la carpeta ``snapshots/<commit>`` de Hugging Face. Para un modelo en una
    carpeta propia (sin Hub) devuelve ``None``.
    """
    revision = getattr(config, "_commit_hash", None) if config is not None else None
    if revision:
        return revision
    if Path(model_id).exists():
        return None
    from huggingface_hub import try_to_load_from_cache

    cached = try_to_load_from_cache(model_id, "config.json")
    if isinstance(cached, str):
        parent = Path(cached).parent
        if parent.parent.name == "snapshots":
            return parent.name
    return None


def load_model(model_id: str | None = None, device: str | None = None, dtype: str | None = None) -> LoadedModel:
    """Carga modelo y tokenizer. Sin argumentos, usa ``MODEL_ID``, ``DEVICE`` y ``DTYPE`` del .env.

    Mide el tiempo y la RAM de la carga por separado: es un costo fijo por proceso, distinto
    del de construir la caché y del de responder. Registra la revisión de los pesos para
    poder validar después las cachés guardadas.
    """
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model_id = model_id or os.environ.get("MODEL_ID") or DEFAULT_MODEL_ID
    device = device or os.environ.get("DEVICE") or "cpu"
    dtype = dtype or os.environ.get("DTYPE") or "float32"
    if dtype not in _DTYPES:
        raise ValueError(f"DTYPE no soportado: {dtype!r}. Opciones: {sorted(_DTYPES)}")

    rss_before = rss_mb()
    start = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        dtype=_DTYPES[dtype],
        # SDPA usa kernels de atención eficientes en memoria cuando están disponibles.
        attn_implementation="sdpa",
    ).to(device)
    model.eval()
    load_seconds = time.perf_counter() - start

    return LoadedModel(
        model=model,
        tokenizer=tokenizer,
        model_id=model_id,
        revision=resolve_revision(model_id, model.config),
        device=device,
        dtype=dtype,
        num_parameters=sum(p.numel() for p in model.parameters()),
        load_seconds=load_seconds,
        rss_before_mb=rss_before,
        rss_after_mb=rss_mb(),
    )
