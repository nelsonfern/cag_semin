"""Motor CAG sobre llama.cpp (llama-cpp-python) para modelos cuantizados GGUF.

Es la alternativa al motor de Transformers (``engine.CAGEngine``) para esta PC: con un modelo
cuantizado a 4 bits, llama.cpp entra en memoria con modelos más grandes (Qwen2.5-7B ocupa
~4,4 GB) y genera más rápido en CPU. Mantiene la misma interfaz (``prepare``, ``answer``,
``validate_question``, ``tokenizer``, ``identity``...) para que la API, la CLI y la evaluación
lo usen sin cambios.

Cómo se maneja la caché KV (verificado en el código de llama-cpp-python 0.3.x, Fase 5):
- ``Llama.eval(tokens)`` primero borra de la caché todo lo que está después de ``n_tokens`` y
  después procesa los tokens nuevos. **Restaurar el prefijo es volver ``n_tokens`` a su largo**
  (el equivalente de ``DynamicCache.crop``).
- La huella es el SHA-256 de la caché KV de la secuencia 0 (``llama_state_seq_get_data``): solo
  las K/V, sin logits ni estado del generador.
- ``save_state`` / ``load_state`` copian el estado del contexto para guardarlo en disco.
- Con ``logits_all=False`` los logits del último token se leen directamente del contexto.

La caché guardada (``data/caches/<cache_id>/state.bin`` + ``meta.json``) solo sirve con el mismo
archivo de modelo, el mismo prefijo y los mismos parámetros del contexto (``n_ctx``,
``flash_attn``: cambia cómo se guardan las V). Todo eso se valida al cargarla.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.cag.cache_builder import KVCacheState
from app.cag.cache_store import CACHES_DIR, CacheIdentity, CacheValidationError, cache_dir
from app.cag.engine import (
    DEFAULT_MAX_NEW_TOKENS, MAX_QUESTION_TOKENS, CacheContaminationError, CacheNotReadyError, CAGEngine,
    ContextLimitError, GenerationResult,
)
from app.cag.model_loader import rss_mb
from app.cag.prompt import CHAT_TEMPLATES, template_prefix, template_question

FORMAT = "tramitaia-llamacpp-state"
FORMAT_VERSION = 1
STATE_FILE = "state.bin"
META_FILE = "meta.json"


@dataclass
class GGUFModel:
    """Archivo GGUF y lo que lo identifica (para validar las cachés guardadas)."""

    path: Path
    model_id: str              # repo/archivo, o la ruta si es un archivo propio
    revision: str | None       # commit del Hub (carpeta snapshots/<commit>)
    quant: str                 # por ejemplo Q4_K_M (sale del nombre del archivo)


def resolve_gguf(repo: str | None = None, filename: str | None = None, revision: str | None = None,
                 path: str | None = None) -> GGUFModel:
    """Ubica el modelo: una ruta local o un archivo de un repo del Hub (lo descarga si falta).

    Sin argumentos usa ``LLAMACPP_MODEL_PATH`` o ``LLAMACPP_REPO`` + ``LLAMACPP_FILE`` (+
    ``LLAMACPP_REVISION``) del .env.
    """
    path = path or os.environ.get("LLAMACPP_MODEL_PATH")
    repo = repo or os.environ.get("LLAMACPP_REPO")
    filename = filename or os.environ.get("LLAMACPP_FILE")
    revision = revision or os.environ.get("LLAMACPP_REVISION") or None
    if path:
        p = Path(path)
        snapshot = p.parent.name if p.parent.parent.name == "snapshots" else None
        return GGUFModel(path=p, model_id=p.name, revision=snapshot, quant=_quant(p.name))
    if not (repo and filename):
        raise ValueError("Definí LLAMACPP_MODEL_PATH o LLAMACPP_REPO + LLAMACPP_FILE en el .env")
    from huggingface_hub import hf_hub_download

    p = Path(hf_hub_download(repo, filename, revision=revision))
    snapshot = p.parent.name if p.parent.parent.name == "snapshots" else revision
    return GGUFModel(path=p, model_id=f"{repo}/{filename}", revision=snapshot, quant=_quant(filename))


def _quant(filename: str) -> str:
    stem = Path(filename).stem
    return stem.rsplit("-", 1)[-1] if "-" in stem else "gguf"


class _Detokenizer:
    """Adaptador con la interfaz mínima de un tokenizer de Hugging Face que usan la API y la CLI."""

    def __init__(self, llm, stop: set[int]):
        self._llm = llm
        self._stop = stop
        self.eos_token_id = llm.token_eos()

    def decode(self, ids, skip_special_tokens: bool = True) -> str:
        ids = [i for i in ids if not (skip_special_tokens and i in self._stop)]
        # «replace» deja un � al final si un carácter quedó partido entre tokens: el
        # streaming de la API espera al token siguiente en ese caso.
        return self._llm.detokenize(ids).decode("utf-8", errors="replace")


class LlamaCppEngine:
    """Motor CAG con llama.cpp: una caché KV del prefijo, reutilizada por todas las consultas.

    Misma interfaz y mismas garantías que ``CAGEngine``: ``prepare()`` carga la caché desde disco
    si es válida (o la construye y la guarda), ``answer()`` valida la pregunta, verifica que la
    caché esté en el estado base (si no, la recupera), responde y la restaura aunque falle. Las
    consultas se atienden de a una.
    """

    def __init__(self, model: GGUFModel, corpus_text: str, *, template: str = "chatml",
                 corpus_build_id: str | None = None, corpus_version: str | None = None,
                 caches_root: Path | None = None, threads: int | None = None, flash_attn: bool = True,
                 n_batch: int = 512, max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS,
                 max_question_tokens: int = MAX_QUESTION_TOKENS, max_context_tokens: int | None = None,
                 verify_each_query: bool = True, manifest=None):
        """Carga el modelo (sin construir la caché: eso lo hace ``prepare``).

        ``n_ctx`` se calcula para que entren el prefijo, la pregunta más larga permitida y la
        respuesta máxima. ``verify_each_query`` recalcula la huella de la caché antes de cada
        consulta (unos segundos con el 7B): garantiza que nada quedó de la consulta anterior.
        """
        import llama_cpp
        from llama_cpp import Llama

        if template not in CHAT_TEMPLATES:
            raise ValueError(f"Plantilla desconocida: {template!r}. Opciones: {sorted(CHAT_TEMPLATES)}")
        self.gguf = model
        self.template = template
        self.corpus_text = corpus_text
        self.caches_root = caches_root or CACHES_DIR
        self.max_new_tokens = max_new_tokens
        self.max_question_tokens = max_question_tokens
        self.verify_each_query = verify_each_query
        self.manifest = manifest
        self.flash_attn = flash_attn
        self.n_batch = n_batch
        self.llama_cpp_version = llama_cpp.__version__

        prefix_text = template_prefix(template, corpus_text)
        vocab = Llama(model_path=str(model.path), vocab_only=True, verbose=False)
        prefix_ids = self._tokenize(vocab, prefix_text)
        # Contexto con el que se entrenó el modelo, de los metadatos del GGUF (con vocab_only,
        # n_ctx_train() devuelve 0).
        n_ctx_train = next((int(v) for k, v in vocab.metadata.items() if k.endswith(".context_length")), None)
        del vocab
        needed = len(prefix_ids) + max_question_tokens + max_new_tokens
        self.n_ctx = ((needed + 1023) // 1024) * 1024
        limits = [self.n_ctx] + [x for x in (n_ctx_train, max_context_tokens) if x]
        self.context_limit = min(limits)
        self.prefix_len = len(prefix_ids)
        if self.prefix_len >= self.context_limit:
            raise ContextLimitError(
                f"El prefijo ({self.prefix_len} tokens) no entra en el contexto permitido ({self.context_limit})"
            )

        threads = threads or int(os.environ.get("LLAMACPP_THREADS") or os.cpu_count() // 2 or 1)
        self.threads = threads
        rss_before, start = rss_mb(), time.perf_counter()
        self.llm = Llama(model_path=str(model.path), n_ctx=self.n_ctx, n_batch=n_batch, n_ubatch=n_batch,
                         n_threads=threads, n_threads_batch=threads, flash_attn=flash_attn,
                         logits_all=False, verbose=False)
        self.load_seconds = time.perf_counter() - start
        self.rss_before_mb, self.rss_after_mb = rss_before, rss_mb()

        end_of_turn = CHAT_TEMPLATES[template][2]
        self.stop = {self.llm.token_eos(), *self._tokenize(self.llm, end_of_turn)}
        self.tokenizer = _Detokenizer(self.llm, self.stop)
        self.identity = CacheIdentity(
            model_id=model.model_id, revision=model.revision,
            # Lo que cambia la forma de la caché además del modelo: cuantización y flash_attn.
            dtype=f"gguf-{model.quant}-fa{int(flash_attn)}",
            prefix_ids=tuple(prefix_ids), corpus_build_id=corpus_build_id, corpus_version=corpus_version,
        )
        self.state: KVCacheState | None = None
        self._saved_state = None
        self.recoveries: list[str] = []
        self._lock = threading.Lock()

    @classmethod
    def from_latest_corpus(cls, model: GGUFModel | None = None, manifest=None, **kwargs) -> "LlamaCppEngine":
        """Motor para el último corpus construido (rechaza un corpus desactualizado, como CAGEngine)."""
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
        kwargs.setdefault("template", os.environ.get("LLAMACPP_TEMPLATE") or "chatml")
        kwargs.setdefault("flash_attn", (os.environ.get("LLAMACPP_FLASH_ATTN") or "1") not in ("0", "false", "no"))
        return cls(model or resolve_gguf(), corpus_text, corpus_build_id=report["build_id"],
                   corpus_version=manifest.corpus_version, manifest=manifest, **kwargs)

    # -- Utilidades ------------------------------------------------------------------------------

    @staticmethod
    def _tokenize(llm, text: str) -> list[int]:
        """Tokens del texto reconociendo los tokens especiales, sin agregar BOS (va en la plantilla)."""
        return llm.tokenize(text.encode("utf-8"), add_bos=False, special=True)

    def encode_question(self, question: str) -> list[int]:
        """IDs del sufijo de una pregunta (lo que se procesa después del prefijo cacheado)."""
        return self._tokenize(self.llm, template_question(self.template, question))

    def _last_logits(self) -> np.ndarray:
        return np.ctypeslib.as_array(self.llm._ctx.get_logits(), shape=(self.llm.n_vocab(),))

    def fingerprint(self) -> tuple[str, int]:
        """SHA-256 de la caché KV de la secuencia 0 (solo K/V) y su tamaño en bytes."""
        import llama_cpp

        ctx = self.llm._ctx.ctx
        size = llama_cpp.llama_state_seq_get_size(ctx, 0)
        buf = (ctypes.c_uint8 * int(size))()
        n = llama_cpp.llama_state_seq_get_data(ctx, buf, size, 0)
        return hashlib.sha256(memoryview(buf)[: int(n)]).hexdigest()[:32], int(n)

    def _reset_to_prefix(self) -> int:
        """Recorta la caché al prefijo. Devuelve cuántas posiciones quitó."""
        extra = self.llm.n_tokens - self.prefix_len
        if extra < 0:
            raise CacheContaminationError(f"La caché perdió posiciones del prefijo ({extra})")
        self.llm.n_tokens = self.prefix_len
        self.llm.eval([])  # eval borra de la caché todo lo posterior a n_tokens
        return extra

    def _verify_base_state(self) -> None:
        if self.llm.n_tokens != self.prefix_len:
            raise CacheContaminationError(f"Largo de caché {self.llm.n_tokens} != prefijo {self.prefix_len}")
        if self.fingerprint()[0] != self.state.fingerprint:
            raise CacheContaminationError("Las K/V del prefijo cambiaron respecto de la caché original")

    def _structure(self, kv_bytes: int) -> dict:
        import llama_cpp

        n_layer = int(llama_cpp.llama_model_n_layer(self.llm.model))
        return {
            "cache_class": "llama.cpp", "num_layers": n_layer, "key_shape_per_layer": None,
            "dtype": "f16", "device": "cpu", "seq_length": self.prefix_len, "prefix_len": self.prefix_len,
            "total_bytes": kv_bytes, "total_mb": round(kv_bytes / 2**20, 2),
            "bytes_per_token": kv_bytes // max(self.prefix_len, 1), "n_ctx": self.n_ctx, "flash_attn": self.flash_attn,
        }

    # -- Caché en disco ------------------------------------------------------------------------

    def _meta(self, fp: str, kv_bytes: int, state_bytes: int, build_seconds: float, save_seconds: float) -> dict:
        return {
            "format": FORMAT, "format_version": FORMAT_VERSION, "cache_id": self.identity.cache_id,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model_id": self.identity.model_id, "revision": self.identity.revision, "dtype": self.identity.dtype,
            "model_file": self.gguf.path.name, "model_bytes": self.gguf.path.stat().st_size,
            "template": self.template, "n_ctx": self.n_ctx, "n_batch": self.n_batch, "flash_attn": self.flash_attn,
            "prefix_len": self.prefix_len, "prefix_hash": self.identity.prefix_hash,
            "corpus_build_id": self.identity.corpus_build_id, "corpus_version": self.identity.corpus_version,
            "fingerprint": fp, "kv_seq_bytes": kv_bytes, "state_bytes": state_bytes,
            "build_seconds": round(build_seconds, 2), "save_seconds": round(save_seconds, 2),
            "llama_cpp_python": self.llama_cpp_version,
        }

    def _save(self, build_seconds: float) -> dict:
        """Guarda el estado (carpeta temporal + renombrado, como cache_store) y devuelve los metadatos."""
        fp, kv_bytes = self.fingerprint()
        final = cache_dir(self.identity, self.caches_root)
        tmp = final.with_name(final.name + ".tmp")
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        start = time.perf_counter()
        state = self.llm.save_state()
        (tmp / STATE_FILE).write_bytes(state.llama_state)
        save_seconds = time.perf_counter() - start
        meta = self._meta(fp, kv_bytes, state.llama_state_size, build_seconds, save_seconds)
        (tmp / META_FILE).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if final.exists():
            shutil.rmtree(final)
        tmp.rename(final)
        return meta

    def _load(self) -> KVCacheState:
        """Carga la caché guardada validando metadatos y huella. Lanza ``CacheValidationError``."""
        from llama_cpp.llama import LlamaState

        directory = cache_dir(self.identity, self.caches_root)
        meta_path = directory / META_FILE
        if not meta_path.exists():
            raise CacheValidationError(f"No existe {meta_path}")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CacheValidationError(f"{meta_path} no es JSON válido: {exc}") from exc
        if meta.get("format") != FORMAT or meta.get("format_version") != FORMAT_VERSION:
            raise CacheValidationError(f"Formato de caché no soportado: {meta.get('format')}")
        expected = {"model_id": self.identity.model_id, "revision": self.identity.revision,
                    "dtype": self.identity.dtype, "prefix_len": self.prefix_len,
                    "prefix_hash": self.identity.prefix_hash, "n_ctx": self.n_ctx,
                    "model_bytes": self.gguf.path.stat().st_size}
        for key, value in expected.items():
            if meta.get(key) != value:
                raise CacheValidationError(f"{key} de la caché ({meta.get(key)!r}) != esperado ({value!r})")
        if self.identity.corpus_version is not None and meta.get("corpus_version") != self.identity.corpus_version:
            raise CacheValidationError(
                f"Caché desactualizada: corpus {meta.get('corpus_version')!r}, actual {self.identity.corpus_version!r}"
            )
        rss_before, start = rss_mb(), time.perf_counter()
        data = (directory / STATE_FILE).read_bytes()
        ids = np.zeros(self.n_ctx, dtype=np.intc)
        ids[: self.prefix_len] = self.identity.prefix_ids
        state = LlamaState(scores=np.zeros((min(self.prefix_len, self.n_batch), self.llm.n_vocab()), dtype=np.single),
                           input_ids=ids, n_tokens=self.prefix_len, llama_state=data,
                           llama_state_size=len(data), seed=self.llm._seed)
        try:
            self.llm.load_state(state)
        except RuntimeError as exc:
            raise CacheValidationError(f"llama.cpp rechazó el estado guardado: {exc}") from exc
        fp, kv_bytes = self.fingerprint()
        if fp != meta["fingerprint"]:
            raise CacheValidationError("La huella de la caché cargada no coincide con la guardada (archivo alterado o corrupto)")
        return KVCacheState(cache=self.llm, prefix_ids=list(self.identity.prefix_ids), prefix_len=self.prefix_len,
                            fingerprint=fp, build_seconds=meta.get("build_seconds", 0.0), chunk_size=self.n_batch,
                            rss_before_mb=rss_before, rss_after_mb=rss_mb(), structure=self._structure(kv_bytes),
                            source="disk", load_seconds=time.perf_counter() - start)

    # -- Preparación de la caché -------------------------------------------------------------

    def prepare(self, allow_build: bool = True, force_rebuild: bool = False) -> dict:
        """Deja la caché lista: desde disco si es válida o construyéndola. Mismo informe que CAGEngine."""
        with self._lock:
            return self._prepare_locked(allow_build, force_rebuild)

    def _prepare_locked(self, allow_build: bool, force_rebuild: bool) -> dict:
        self.state = None
        report = {"cache_id": self.identity.cache_id, "rejected": None}
        if not force_rebuild:
            try:
                self.state = self._load()
                report.update(source="disk", seconds=self.state.load_seconds)
                return report
            except CacheValidationError as exc:
                report["rejected"] = str(exc)
                if not allow_build:
                    raise
        rss_before, start = rss_mb(), time.perf_counter()
        self.llm.reset()
        self.llm.eval(list(self.identity.prefix_ids))
        build_seconds = time.perf_counter() - start
        meta = self._save(build_seconds)
        self.state = KVCacheState(cache=self.llm, prefix_ids=list(self.identity.prefix_ids), prefix_len=self.prefix_len,
                                  fingerprint=meta["fingerprint"], build_seconds=build_seconds, chunk_size=self.n_batch,
                                  rss_before_mb=rss_before, rss_after_mb=rss_mb(),
                                  structure=self._structure(meta["kv_seq_bytes"]))
        self._register(meta)
        report.update(source="built", seconds=build_seconds, save_seconds=meta["save_seconds"],
                      file_bytes=meta["state_bytes"])
        return report

    def _register(self, meta: dict) -> None:
        """Asienta la caché en el manifiesto documental (igual que CAGEngine)."""
        if self.manifest is None:
            return
        self.manifest.mark_stale_caches()
        self.manifest.caches = [c for c in self.manifest.caches if c.get("cache_id") != meta["cache_id"]]
        self.manifest.register_cache(meta["cache_id"], {
            "engine": "llama.cpp", "model_id": meta["model_id"], "revision": meta["revision"],
            "dtype": meta["dtype"], "corpus_build_id": meta["corpus_build_id"],
            "prefix_len": meta["prefix_len"], "fingerprint": meta["fingerprint"],
        })
        self.manifest.save()

    def warmup(self) -> float:
        """Consulta interna de un token para que la primera pregunta real no pague el arranque.

        Medido con Qwen2.5-7B: la primera consulta después de cargar la caché tardó 33 s hasta el
        primer token y las siguientes, ~8 s. Devuelve los segundos que tomó.
        """
        start = time.perf_counter()
        self.answer("Hola", max_new_tokens=1)
        return time.perf_counter() - start

    # -- Consultas ------------------------------------------------------------------------------

    def validate_question(self, question: str, max_new_tokens: int | None = None) -> list[int]:
        """Mismas reglas que ``CAGEngine.validate_question`` (pregunta vacía o larga, contexto)."""
        return CAGEngine.validate_question(self, question, max_new_tokens)

    def answer(self, question: str, max_new_tokens: int | None = None, on_token=None,
               ignore_eos: bool = False) -> GenerationResult:
        """Responde reutilizando la caché del prefijo (mismos pasos que ``CAGEngine.answer``).

        Valida la pregunta, toma el lock, restaura el prefijo y verifica la huella (si no
        coincide, recupera la caché desde disco), procesa solo la pregunta, genera token por
        token (greedy) y vuelve a restaurar el prefijo aunque la generación falle.

        ``ignore_eos`` genera exactamente ``max_new_tokens`` (no corta en el fin de turno): lo usa
        el benchmark para comparar tiempos sin que influya el largo de cada respuesta.
        """
        ids = self.validate_question(question, max_new_tokens)
        new_tokens = max_new_tokens or self.max_new_tokens
        with self._lock:
            if self.state is None:
                raise CacheNotReadyError("La caché no está preparada: llamá a prepare() antes de consultar")
            try:
                self._reset_to_prefix()
                if self.verify_each_query:
                    self._verify_base_state()
            except CacheContaminationError as exc:
                self.recoveries.append(str(exc))
                self._prepare_locked(allow_build=True, force_rebuild=False)
            result = GenerationResult(question_tokens=len(ids), output_ids=[], text="")
            result.cache_len_before = self.llm.n_tokens
            try:
                start = time.perf_counter()
                self.llm.eval(ids)
                result.prefill_seconds = time.perf_counter() - start
                output = []
                for i in range(new_tokens):
                    token = int(np.argmax(self._last_logits()))
                    if i == 0:
                        result.ttft_seconds = time.perf_counter() - start
                    output.append(token)
                    if token in self.stop and not ignore_eos:
                        result.stopped_by = "eos"
                        break
                    if on_token:
                        on_token(token)
                    self.llm.eval([token])
                result.output_ids = output
                result.text = self.tokenizer.decode(output).strip()
                result.cache_len_after_generation = self.llm.n_tokens
                result.total_seconds = time.perf_counter() - start
            finally:
                self._reset_to_prefix()
            return result
