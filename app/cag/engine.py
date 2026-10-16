"""Consulta sobre la caché KV (Fase C del CAG) y modo baseline sin caché reutilizable.

Por cada pregunta, el modo CAG:
1. Restaura la caché al estado base: recorta todo lo que esté después del prefijo, para que
   ni la pregunta ni la respuesta anteriores contaminen la nueva consulta.
2. Procesa solo los tokens de la pregunta, en las posiciones que siguen al prefijo.
3. Genera token por token (greedy). Cada paso procesa UN token nuevo, que atiende sobre las
   K/V del prefijo, de la pregunta y de lo ya generado.
4. Vuelve a restaurar la caché al terminar.

El modo baseline hace lo mismo pero partiendo de una caché vacía: procesa prefijo y pregunta
completos en cada consulta. Es la referencia para medir la ventaja de reutilizar la caché.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import torch

from app.cag.cache_builder import DEFAULT_CHUNK_SIZE, KVCacheState, fingerprint, prefill


class CacheContaminationError(RuntimeError):
    """La caché no volvió al estado base del prefijo."""


@dataclass
class GenerationResult:
    question_tokens: int
    output_ids: list[int]
    text: str
    first_token_logits: torch.Tensor | None = field(repr=False, default=None)
    prefill_seconds: float = 0.0       # procesar lo que no estaba cacheado (pregunta, o todo en baseline)
    ttft_seconds: float = 0.0          # tiempo hasta el primer token generado
    total_seconds: float = 0.0
    cache_len_before: int = 0          # largo de la caché al empezar la consulta
    cache_len_after_generation: int = 0
    stopped_by: str = "max_new_tokens"


def reset_to_prefix(state: KVCacheState) -> int:
    """Recorta la caché a las posiciones del prefijo. Devuelve cuántas posiciones quitó.

    En Transformers 5.x, ``crop`` recibe la cantidad de tokens a QUITAR como número negativo
    (``crop(-n)``); un valor positivo lanza un error. En versiones anteriores recibía la
    longitud final.
    """
    extra = state.cache.get_seq_length() - state.prefix_len
    if extra < 0:
        raise CacheContaminationError(f"La caché perdió posiciones del prefijo ({extra})")
    if extra > 0:
        state.cache.crop(-extra)
    return extra


def verify_base_state(state: KVCacheState) -> None:
    """Falla si la caché no es exactamente la del prefijo (largo y contenido)."""
    length = state.cache.get_seq_length()
    if length != state.prefix_len:
        raise CacheContaminationError(f"Largo de caché {length} != prefijo {state.prefix_len}")
    if fingerprint(state.cache, state.prefix_len) != state.fingerprint:
        raise CacheContaminationError("Las K/V del prefijo cambiaron respecto de la caché original")


def _eos_ids(model, tokenizer) -> set[int]:
    ids = set()
    for source in (getattr(model.generation_config, "eos_token_id", None), tokenizer.eos_token_id):
        if isinstance(source, int):
            ids.add(source)
        elif source:
            ids.update(source)
    return ids


@torch.inference_mode()
def _decode(model, tokenizer, cache, first_logits, next_pos: int, max_new_tokens: int, start: float, result: GenerationResult):
    eos = _eos_ids(model, tokenizer)
    device = model.device
    token = int(torch.argmax(first_logits))
    result.ttft_seconds = time.perf_counter() - start
    output = [token]
    for _ in range(max_new_tokens - 1):
        if token in eos:
            result.stopped_by = "eos"
            break
        out = model(
            input_ids=torch.tensor([[token]], device=device),
            cache_position=torch.tensor([next_pos], device=device),
            past_key_values=cache,
            use_cache=True,
        )
        next_pos += 1
        token = int(torch.argmax(out.logits[0, -1]))
        output.append(token)
    else:
        if token in eos:
            result.stopped_by = "eos"
    result.output_ids = output
    result.text = tokenizer.decode([t for t in output if t not in eos], skip_special_tokens=True).strip()
    result.cache_len_after_generation = cache.get_seq_length()


def answer_with_cache(
    model, tokenizer, state: KVCacheState, question_ids: list[int],
    max_new_tokens: int = 128, reset: bool = True, verify: bool = True,
) -> GenerationResult:
    """Responde reutilizando la caché del prefijo.

    ``reset=False`` existe solo como control negativo en la demo: muestra qué pasa si no se
    restaura el estado base (la pregunta se agrega después de la consulta anterior).
    """
    if reset:
        reset_to_prefix(state)
        if verify:
            verify_base_state(state)
    result = GenerationResult(question_tokens=len(question_ids), output_ids=[], text="")
    result.cache_len_before = state.cache.get_seq_length()

    start = time.perf_counter()
    logits = prefill(model, question_ids, state.cache, start=result.cache_len_before)
    result.prefill_seconds = time.perf_counter() - start
    result.first_token_logits = logits.float().cpu()
    _decode(model, tokenizer, state.cache, logits, result.cache_len_before + len(question_ids),
            max_new_tokens, start, result)
    result.total_seconds = time.perf_counter() - start

    if reset:
        reset_to_prefix(state)
    return result


def answer_without_cache(
    model, tokenizer, prefix_ids: list[int], question_ids: list[int],
    max_new_tokens: int = 128, chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> GenerationResult:
    """Baseline: caché nueva por consulta; procesa prefijo + pregunta completos cada vez."""
    from transformers import DynamicCache

    cache = DynamicCache(config=model.config)
    ids = list(prefix_ids) + list(question_ids)
    result = GenerationResult(question_tokens=len(question_ids), output_ids=[], text="")

    start = time.perf_counter()
    # Mismos bloques que al construir la caché, y la pregunta como bloque aparte: así la
    # comparación con CAG aísla el efecto de reutilizar la caché.
    prefill(model, prefix_ids, cache, start=0, chunk_size=chunk_size)
    logits = prefill(model, question_ids, cache, start=len(prefix_ids), chunk_size=chunk_size)
    result.prefill_seconds = time.perf_counter() - start
    result.first_token_logits = logits.float().cpu()
    _decode(model, tokenizer, cache, logits, len(ids), max_new_tokens, start, result)
    result.total_seconds = time.perf_counter() - start
    return result
