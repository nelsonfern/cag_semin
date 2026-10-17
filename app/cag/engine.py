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

import os
import threading
import time
from dataclasses import dataclass, field

import torch

from app.cag.cache_builder import DEFAULT_CHUNK_SIZE, KVCacheState, build_kv_cache, fingerprint, prefill


class CacheContaminationError(RuntimeError):
    """La caché no volvió al estado base del prefijo."""


@dataclass
class GenerationResult:
    """Resultado de una consulta (CAG o baseline): respuesta, tiempos y estado de la caché.

    Los campos de la caché permiten comprobar el aislamiento: con CAG, ``cache_len_before``
    debe ser siempre el largo del prefijo; si es mayor, quedaron tokens de otra consulta.
    """

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
    """Tokens que terminan la respuesta (Qwen tiene más de uno: ``<|im_end|>`` y ``<|endoftext|>``)."""
    ids = set()
    for source in (getattr(model.generation_config, "eos_token_id", None), tokenizer.eos_token_id):
        if isinstance(source, int):
            ids.add(source)
        elif source:
            ids.update(source)
    return ids


@torch.inference_mode()
def _decode(model, tokenizer, cache, first_logits, next_pos: int, max_new_tokens: int, start: float,
            result: GenerationResult, on_token=None):
    """Genera la respuesta token por token (greedy) sobre una caché que ya contiene el contexto.

    ``first_logits`` son los logits del último token de la pregunta: de ahí sale el primer
    token. Después, cada paso le pasa al modelo UN solo token nuevo, en la posición
    ``next_pos`` (absoluta, para el RoPE). El modelo calcula sus K/V, las agrega a la caché y
    atiende sobre todas las anteriores (prefijo + pregunta + lo ya generado). Nada del
    prefijo se recalcula: ese es el ahorro de CAG.

    Para al llegar a un token de fin o a ``max_new_tokens``. Completa ``result`` con los
    tokens, el texto, el tiempo hasta el primer token y el largo final de la caché.
    Es greedy (siempre el token más probable) para que CAG y baseline sean comparables token
    por token.
    """
    eos = _eos_ids(model, tokenizer)
    device = model.device
    token = int(torch.argmax(first_logits))
    result.ttft_seconds = time.perf_counter() - start
    output = [token]
    if on_token and token not in eos:
        on_token(token)
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
        if on_token and token not in eos:
            on_token(token)
    else:
        if token in eos:
            result.stopped_by = "eos"
    result.output_ids = output
    result.text = tokenizer.decode([t for t in output if t not in eos], skip_special_tokens=True).strip()
    result.cache_len_after_generation = cache.get_seq_length()


def answer_with_cache(
    model, tokenizer, state: KVCacheState, question_ids: list[int],
    max_new_tokens: int = 128, reset: bool = True, verify: bool = True, on_token=None,
) -> GenerationResult:
    """Responde reutilizando la caché del prefijo.

    ``reset=False`` existe solo como control negativo en la demo: muestra qué pasa si no se
    restaura el estado base (la pregunta se agrega después de la consulta anterior).
    ``on_token`` recibe cada token generado apenas se calcula (para mostrar la respuesta en vivo).
    """
    if reset:
        reset_to_prefix(state)
        if verify:
            verify_base_state(state)
    result = GenerationResult(question_tokens=len(question_ids), output_ids=[], text="")
    result.cache_len_before = state.cache.get_seq_length()

    try:
        start = time.perf_counter()
        logits = prefill(model, question_ids, state.cache, start=result.cache_len_before)
        result.prefill_seconds = time.perf_counter() - start
        result.first_token_logits = logits.float().cpu()
        _decode(model, tokenizer, state.cache, logits, result.cache_len_before + len(question_ids),
                max_new_tokens, start, result, on_token)
        result.total_seconds = time.perf_counter() - start
    finally:
        # También si la generación falla a la mitad: la caché nunca queda con tokens de
        # una consulta para la siguiente.
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


# --- Motor con estado -----------------------------------------------------------------------

DEFAULT_MAX_NEW_TOKENS = 256
MAX_QUESTION_CHARS = 1000
MAX_QUESTION_TOKENS = 256


class QuestionError(ValueError):
    """La pregunta no es válida (vacía o demasiado larga)."""


class ContextLimitError(ValueError):
    """Prefijo + pregunta + respuesta no entran en el contexto permitido."""


class CacheNotReadyError(RuntimeError):
    """Se consultó el motor antes de preparar la caché."""


def _context_limit(model, max_context_tokens: int | None) -> int:
    """Contexto permitido: el menor entre el del modelo y ``MAX_CONTEXT_TOKENS`` (si se definió)."""
    limits = [getattr(model.config, "max_position_embeddings", None), max_context_tokens]
    limits = [int(x) for x in limits if x]
    if not limits:
        raise ValueError("No se conoce el contexto máximo del modelo; definí MAX_CONTEXT_TOKENS")
    return min(limits)


class CAGEngine:
    """Motor CAG: una caché KV del prefijo, reutilizada por todas las consultas.

    - ``prepare()`` carga la caché desde disco si es válida para este modelo, pesos, dtype,
      prefijo y corpus; si no, la construye y la guarda.
    - ``answer()`` valida la pregunta y los límites de contexto, comprueba que la caché esté
      en su estado base (si no, la recupera) y responde. La caché es una sola y cada consulta
      la extiende temporalmente, así que las consultas se atienden de a una (``_lock``).
    """

    def __init__(
        self, model, tokenizer, identity, encode_question, *,
        caches_root=None, chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS, max_context_tokens: int | None = None,
        max_question_tokens: int = MAX_QUESTION_TOKENS, manifest=None,
    ):
        """Configura el motor sin cargar ni construir nada todavía (eso lo hace ``prepare``).

        - ``identity``: ``CacheIdentity`` con modelo, revisión, dtype y los IDs del prefijo.
        - ``encode_question``: convierte una pregunta en los IDs del sufijo (``build_question``).
        - ``caches_root``: carpeta de las cachés guardadas (por defecto, ``data/caches``).
        - ``manifest``: si se pasa, cada caché construida se registra en el manifiesto.

        Falla con ``ContextLimitError`` si el prefijo solo ya no entra en el contexto.
        """
        from app.cag.cache_store import CACHES_DIR

        self.model = model
        self.tokenizer = tokenizer
        self.identity = identity
        self.encode_question = encode_question
        self.caches_root = caches_root or CACHES_DIR
        self.chunk_size = chunk_size
        self.max_new_tokens = max_new_tokens
        self.max_question_tokens = max_question_tokens
        self.manifest = manifest
        self.context_limit = _context_limit(model, max_context_tokens)
        self.prefix_len = len(identity.prefix_ids)
        if self.prefix_len >= self.context_limit:
            raise ContextLimitError(
                f"El prefijo ({self.prefix_len} tokens) no entra en el contexto permitido ({self.context_limit})"
            )
        self.state: KVCacheState | None = None
        self.recoveries: list[str] = []
        self._lock = threading.Lock()

    @classmethod
    def from_latest_corpus(cls, loaded, manifest=None, **kwargs) -> "CAGEngine":
        """Motor para el modelo cargado y el último corpus construido.

        Falla si el corpus se construyó con otra versión del manifiesto: una caché sobre un
        corpus desactualizado no debe presentarse como vigente.
        """
        from app.cag.cache_store import CacheIdentity
        from app.cag.prompt import build_prefix, build_question
        from app.ingestion.corpus_builder import load_latest
        from app.ingestion.source_registry import Manifest

        manifest = manifest or Manifest()
        corpus_text, report = load_latest()
        if report["manifest_corpus_version"] != manifest.corpus_version:
            raise RuntimeError(
                f"El corpus {report['build_id']} se construyó con la versión {report['manifest_corpus_version']} "
                f"del manifiesto y la actual es {manifest.corpus_version}: reconstruí el corpus"
            )
        env_limit = os.environ.get("MAX_CONTEXT_TOKENS")
        if env_limit:
            kwargs.setdefault("max_context_tokens", int(env_limit))
        tok = loaded.tokenizer
        identity = CacheIdentity(
            model_id=loaded.model_id, revision=loaded.revision, dtype=loaded.dtype,
            prefix_ids=tuple(build_prefix(tok, corpus_text).ids),
            corpus_build_id=report["build_id"], corpus_version=manifest.corpus_version,
        )
        return cls(loaded.model, tok, identity, lambda q: build_question(tok, corpus_text, q).ids,
                   manifest=manifest, **kwargs)

    # -- Preparación de la caché -------------------------------------------------------------

    def prepare(self, allow_build: bool = True, force_rebuild: bool = False) -> dict:
        """Deja la caché lista. Devuelve de dónde salió, cuánto tardó y por qué se descartó otra."""
        with self._lock:
            return self._prepare_locked(allow_build, force_rebuild)

    def _prepare_locked(self, allow_build: bool, force_rebuild: bool) -> dict:
        """Trabajo de ``prepare``; quien la llama ya tiene el lock (también ``_recover``).

        Orden: intentar cargar desde disco (salvo ``force_rebuild``); si la caché no existe o
        no pasa la validación, construirla (si ``allow_build``), guardarla y registrarla.
        """
        from app.cag.cache_store import CacheValidationError, load_kv_cache, save_kv_cache

        self.state = None
        report = {"cache_id": self.identity.cache_id, "rejected": None}
        if not force_rebuild:
            try:
                self.state = load_kv_cache(self.model, self.identity, self.caches_root)
                report.update(source="disk", seconds=self.state.load_seconds)
                return report
            except CacheValidationError as exc:
                report["rejected"] = str(exc)
                if not allow_build:
                    raise
        self.state = build_kv_cache(self.model, list(self.identity.prefix_ids), chunk_size=self.chunk_size)
        meta = save_kv_cache(self.state, self.identity, self.caches_root)
        self._register(meta)
        report.update(source="built", seconds=self.state.build_seconds, save_seconds=meta["save_seconds"],
                      file_bytes=meta["file_bytes"])
        return report

    def _register(self, meta: dict) -> None:
        """Asienta la caché en el manifiesto documental, asociada a la versión del corpus."""
        if self.manifest is None:
            return
        self.manifest.mark_stale_caches()
        self.manifest.caches = [c for c in self.manifest.caches if c.get("cache_id") != meta["cache_id"]]
        self.manifest.register_cache(meta["cache_id"], {
            "model_id": meta["model_id"], "revision": meta["revision"], "dtype": meta["dtype"],
            "corpus_build_id": meta["corpus_build_id"], "prefix_len": meta["prefix_len"],
            "fingerprint": meta["fingerprint"],
        })
        self.manifest.save()

    def _recover(self, reason: str) -> None:
        """La caché no está en su estado base: se descarta y se vuelve a cargar (o construir)."""
        self.recoveries.append(reason)
        self._prepare_locked(allow_build=True, force_rebuild=False)

    # -- Consultas ------------------------------------------------------------------------------

    def validate_question(self, question: str, max_new_tokens: int | None = None) -> list[int]:
        """Valida la pregunta y devuelve sus IDs, antes de tocar la caché.

        Rechaza (``QuestionError``) preguntas vacías o de más de ``MAX_QUESTION_CHARS``
        caracteres o ``max_question_tokens`` tokens. Rechaza (``ContextLimitError``) si
        prefijo + pregunta + respuesta máxima superan el contexto permitido: la respuesta
        cuenta porque cada token generado también ocupa una posición en la caché.
        """
        if not isinstance(question, str) or not question.strip():
            raise QuestionError("La pregunta está vacía")
        question = question.strip()
        if len(question) > MAX_QUESTION_CHARS:
            raise QuestionError(f"La pregunta supera los {MAX_QUESTION_CHARS} caracteres")
        ids = self.encode_question(question)
        if len(ids) > self.max_question_tokens:
            raise QuestionError(f"La pregunta tiene {len(ids)} tokens (máximo {self.max_question_tokens})")
        new_tokens = max_new_tokens or self.max_new_tokens
        needed = self.prefix_len + len(ids) + new_tokens
        if needed > self.context_limit:
            raise ContextLimitError(
                f"Prefijo ({self.prefix_len}) + pregunta ({len(ids)}) + respuesta ({new_tokens}) = {needed} "
                f"tokens, más que el contexto permitido ({self.context_limit})"
            )
        return ids

    def answer(self, question: str, max_new_tokens: int | None = None, on_token=None) -> GenerationResult:
        """Responde una pregunta reutilizando la caché del prefijo.

        1. Valida la pregunta (sin el lock, para no hacer esperar a otras consultas).
        2. Toma el lock: una consulta por vez sobre la única caché.
        3. Restaura la caché al prefijo y verifica largo y huella; si no coinciden, la
           recupera desde disco (o la reconstruye) y lo anota en ``recoveries``.
        4. Procesa solo los tokens de la pregunta, genera la respuesta y vuelve a restaurar la
           caché, aunque la generación falle.

        ``on_token`` recibe cada token apenas se genera. Lanza ``CacheNotReadyError`` si no se
        llamó a ``prepare``.
        """
        ids = self.validate_question(question, max_new_tokens)
        with self._lock:
            if self.state is None:
                raise CacheNotReadyError("La caché no está preparada: llamá a prepare() antes de consultar")
            try:
                reset_to_prefix(self.state)
                verify_base_state(self.state)
            except CacheContaminationError as exc:
                self._recover(str(exc))
            return answer_with_cache(
                self.model, self.tokenizer, self.state, ids,
                max_new_tokens=max_new_tokens or self.max_new_tokens, reset=True, verify=False,
                on_token=on_token,
            )
