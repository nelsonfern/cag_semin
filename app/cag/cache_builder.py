"""Construcción de la caché KV del prefijo documental (Fase B del CAG).

Atención y caché KV, en corto:
- En cada capa, cada token produce un vector Query, uno Key y uno Value.
- Un token "mira" a los anteriores comparando su Query con sus Keys y mezcla sus Values.
- En un modelo causal, las Keys y Values de un token dependen solo de él y de los tokens
  anteriores. Por eso, las K/V del prefijo documental son siempre las mismas, sin importar
  qué pregunta venga después.

CAG aprovecha esto: procesa el prefijo una vez, guarda sus K/V de todas las capas
(``DynamicCache``) y, en cada consulta, solo calcula las K/V de los tokens nuevos (pregunta y
respuesta), que atienden sobre las del prefijo.

Estructura en Transformers 5.x: ``cache.layers[i].keys`` y ``.values`` con forma
``[batch, cabezas_kv, tokens, dim_cabeza]``. Qwen2.5 usa GQA (pocas cabezas K/V compartidas
por varias de Query), lo que achica la caché.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

import torch

from app.cag.model_loader import rss_mb

DEFAULT_CHUNK_SIZE = 2048


@dataclass
class KVCacheState:
    cache: object                  # transformers.DynamicCache con las K/V del prefijo
    prefix_ids: list[int]
    prefix_len: int
    fingerprint: str               # hash de todas las K/V del prefijo (detecta contaminación)
    build_seconds: float
    chunk_size: int
    rss_before_mb: float
    rss_after_mb: float
    structure: dict = field(default_factory=dict)


def cache_structure(cache, prefix_len: int) -> dict:
    layers = cache.layers
    k0 = layers[0].keys
    total_bytes = sum(l.keys.numel() * l.keys.element_size() + l.values.numel() * l.values.element_size() for l in layers)
    return {
        "cache_class": type(cache).__name__,
        "num_layers": len(layers),
        "key_shape_per_layer": list(k0.shape),  # [batch, cabezas_kv, tokens, dim_cabeza]
        "value_shape_per_layer": list(layers[0].values.shape),
        "dtype": str(k0.dtype).replace("torch.", ""),
        "device": str(k0.device),
        "seq_length": cache.get_seq_length(),
        "prefix_len": prefix_len,
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / 2**20, 2),
        "bytes_per_token": total_bytes // max(prefix_len, 1),
    }


def fingerprint(cache, length: int) -> str:
    """SHA-256 de las K/V de las primeras ``length`` posiciones de todas las capas."""
    h = hashlib.sha256()
    for layer in cache.layers:
        for tensor in (layer.keys, layer.values):
            part = tensor[..., :length, :].contiguous()
            h.update(part.view(torch.uint8).cpu().numpy().tobytes())
    return h.hexdigest()[:32]


@torch.inference_mode()
def prefill(model, ids: list[int], cache, start: int = 0, chunk_size: int = DEFAULT_CHUNK_SIZE):
    """Procesa ``ids`` agregándolos a ``cache`` a partir de la posición ``start``.

    Se procesa por bloques: cada bloque atiende a lo ya cacheado más a sí mismo (máscara
    causal), así que el resultado equivale a procesar todo junto pero con menos memoria pico.
    ``cache_position`` indica la posición absoluta de cada token: la posición determina el
    RoPE y por eso tiene que continuar exactamente donde terminó lo anterior.
    Devuelve los logits del último token (lo único necesario para generar el siguiente).
    """
    device = model.device
    logits = None
    for offset in range(0, len(ids), chunk_size):
        chunk = ids[offset:offset + chunk_size]
        pos = start + offset
        out = model(
            input_ids=torch.tensor([chunk], device=device),
            cache_position=torch.arange(pos, pos + len(chunk), device=device),
            past_key_values=cache,
            use_cache=True,
            # Solo el último token necesita logits: evita una matriz [bloque x vocabulario].
            logits_to_keep=1,
        )
        logits = out.logits[0, -1]
    return logits


def build_kv_cache(model, prefix_ids: list[int], chunk_size: int = DEFAULT_CHUNK_SIZE) -> KVCacheState:
    from transformers import DynamicCache

    if not prefix_ids:
        raise ValueError("El prefijo está vacío")
    max_pos = getattr(model.config, "max_position_embeddings", None)
    if max_pos and len(prefix_ids) >= max_pos:
        raise ValueError(f"El prefijo ({len(prefix_ids)} tokens) no entra en el contexto del modelo ({max_pos})")

    rss_before = rss_mb()
    start = time.perf_counter()
    cache = DynamicCache(config=model.config)
    prefill(model, prefix_ids, cache, start=0, chunk_size=chunk_size)
    build_seconds = time.perf_counter() - start

    prefix_len = len(prefix_ids)
    if cache.get_seq_length() != prefix_len:
        raise RuntimeError(f"La caché tiene {cache.get_seq_length()} posiciones y el prefijo {prefix_len}")
    return KVCacheState(
        cache=cache,
        prefix_ids=list(prefix_ids),
        prefix_len=prefix_len,
        fingerprint=fingerprint(cache, prefix_len),
        build_seconds=build_seconds,
        chunk_size=chunk_size,
        rss_before_mb=rss_before,
        rss_after_mb=rss_mb(),
        structure=cache_structure(cache, prefix_len),
    )
