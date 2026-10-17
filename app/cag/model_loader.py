"""Carga del modelo causal y su tokenizer (Hugging Face Transformers).

El tiempo y la memoria de carga se registran por separado del costo de procesar el corpus y
del de generar respuestas, porque son costos distintos (§7 de la especificación).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import psutil
import torch

DEFAULT_MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"

_DTYPES = {"float32": torch.float32, "bfloat16": torch.bfloat16, "float16": torch.float16}


@dataclass
class LoadedModel:
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


def load_model(model_id: str | None = None, device: str | None = None, dtype: str | None = None) -> LoadedModel:
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
        revision=getattr(model.config, "_commit_hash", None),
        device=device,
        dtype=dtype,
        num_parameters=sum(p.numel() for p in model.parameters()),
        load_seconds=load_seconds,
        rss_before_mb=rss_before,
        rss_after_mb=rss_mb(),
    )
