"""Guardar y cargar la caché KV del prefijo en disco.

Construir la caché cuesta minutos en CPU; cargarla desde disco, segundos. Para que una caché
cargada siga siendo CAG correcto (las mismas K/V que se obtendrían recalculando), se guarda
junto con todo lo que la determina y se valida al cargarla:

- ``kv.safetensors``: K y V de cada capa, en su dtype exacto. safetensors no ejecuta código
  al cargar (a diferencia de ``torch.load`` con pickle).
- ``meta.json``: modelo, revisión (commit del Hub), dtype, hash de los IDs del prefijo,
  versión del corpus, huella SHA-256 de las K/V, formas y versiones de torch/transformers.

Se rechaza la caché si cambia el modelo, la revisión, el dtype o el prefijo (corpus o
instrucciones), si quedó desactualizada respecto del corpus, o si la huella recalculada no
coincide con la guardada (archivo corrupto o alterado).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import torch

from app.cag.cache_builder import KVCacheState, cache_structure, fingerprint
from app.cag.model_loader import rss_mb
from app.config import DATA_DIR

CACHES_DIR = DATA_DIR / "caches"
FORMAT = "tramitaia-kv"
FORMAT_VERSION = 1
KV_FILE = "kv.safetensors"
META_FILE = "meta.json"


class CacheValidationError(RuntimeError):
    """La caché guardada no corresponde al modelo, al prefijo o al corpus actuales."""


@dataclass(frozen=True)
class CacheIdentity:
    """Lo que determina las K/V del prefijo. Si algo cambia, la caché ya no sirve."""

    model_id: str
    revision: str | None
    dtype: str
    prefix_ids: tuple[int, ...]
    corpus_build_id: str | None = None
    corpus_version: str | None = None

    @property
    def prefix_hash(self) -> str:
        return prefix_hash(self.prefix_ids)

    @property
    def cache_id(self) -> str:
        """Identificador estable: mismo modelo, pesos, dtype y prefijo -> mismo ``cache_id``."""
        key = json.dumps([self.model_id, self.revision, self.dtype, self.prefix_hash])
        return hashlib.sha256(key.encode()).hexdigest()[:16]


def prefix_hash(ids) -> str:
    """SHA-256 de los IDs del prefijo: identifica corpus + instrucciones + plantilla."""
    return hashlib.sha256(json.dumps(list(ids)).encode()).hexdigest()


def cache_dir(identity: CacheIdentity, root: Path = CACHES_DIR) -> Path:
    """Carpeta de una caché: ``<root>/<cache_id>``."""
    return root / identity.cache_id


def read_meta(directory: Path) -> dict:
    """Lee ``meta.json`` y comprueba el formato. No valida contra el modelo (eso es ``check_meta``)."""
    path = directory / META_FILE
    if not path.exists():
        raise CacheValidationError(f"No existe {path}")
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CacheValidationError(f"{path} no es JSON válido: {exc}") from exc
    if meta.get("format") != FORMAT or meta.get("format_version") != FORMAT_VERSION:
        raise CacheValidationError(f"Formato de caché no soportado: {meta.get('format')} v{meta.get('format_version')}")
    return meta


def save_kv_cache(state: KVCacheState, identity: CacheIdentity, root: Path = CACHES_DIR) -> dict:
    """Guarda las K/V del prefijo y sus metadatos. Devuelve los metadatos (con tiempos y tamaño).

    Se escribe en una carpeta temporal y se renombra al final: una escritura interrumpida
    nunca deja una caché a medias con el nombre válido.
    """
    from safetensors.torch import save_file

    if list(state.prefix_ids) != list(identity.prefix_ids):
        raise ValueError("La caché no corresponde al prefijo de la identidad")
    if state.cache.get_seq_length() != state.prefix_len:
        raise ValueError("Solo se guarda la caché en su estado base (sin pregunta ni respuesta)")

    final = cache_dir(identity, root)
    tmp = final.with_name(final.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    start = time.perf_counter()
    tensors = {}
    for i, layer in enumerate(state.cache.layers):
        tensors[f"layer.{i}.keys"] = layer.keys[..., :state.prefix_len, :].contiguous()
        tensors[f"layer.{i}.values"] = layer.values[..., :state.prefix_len, :].contiguous()
    save_file(tensors, str(tmp / KV_FILE), metadata={"format": FORMAT, "cache_id": identity.cache_id})
    save_seconds = time.perf_counter() - start

    import transformers

    meta = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "cache_id": identity.cache_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_id": identity.model_id,
        "revision": identity.revision,
        "dtype": identity.dtype,
        "prefix_len": state.prefix_len,
        "prefix_hash": identity.prefix_hash,
        "corpus_build_id": identity.corpus_build_id,
        "corpus_version": identity.corpus_version,
        "fingerprint": state.fingerprint,
        "chunk_size": state.chunk_size,
        "build_seconds": round(state.build_seconds, 3),
        "save_seconds": round(save_seconds, 3),
        "file_bytes": (tmp / KV_FILE).stat().st_size,
        "structure": state.structure,
        "torch": torch.__version__,
        "transformers": transformers.__version__,
    }
    (tmp / META_FILE).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    if final.exists():
        shutil.rmtree(final)
    tmp.rename(final)
    return meta


def check_meta(meta: dict, identity: CacheIdentity) -> None:
    """Falla si los metadatos no corresponden a la identidad esperada."""
    checks = [
        ("model_id", identity.model_id),
        ("revision", identity.revision),
        ("dtype", identity.dtype),
        ("prefix_len", len(identity.prefix_ids)),
        ("prefix_hash", identity.prefix_hash),
    ]
    for key, expected in checks:
        if meta.get(key) != expected:
            raise CacheValidationError(f"{key} de la caché ({meta.get(key)!r}) != esperado ({expected!r})")
    if identity.corpus_version is not None and meta.get("corpus_version") != identity.corpus_version:
        raise CacheValidationError(
            f"Caché desactualizada: corpus {meta.get('corpus_version')!r}, actual {identity.corpus_version!r}"
        )


def load_kv_cache(model, identity: CacheIdentity, root: Path = CACHES_DIR) -> KVCacheState:
    """Carga la caché de ``identity`` validándola por completo. Lanza ``CacheValidationError``."""
    from safetensors import SafetensorError
    from safetensors.torch import load_file
    from transformers import DynamicCache

    directory = cache_dir(identity, root)
    meta = read_meta(directory)
    check_meta(meta, identity)

    rss_before = rss_mb()
    start = time.perf_counter()
    try:
        tensors = load_file(str(directory / KV_FILE), device=str(model.device))
    except (SafetensorError, OSError) as exc:
        raise CacheValidationError(f"No se pudo leer {directory / KV_FILE}: {exc}") from exc

    num_layers = model.config.num_hidden_layers
    expected_shape = meta["structure"]["key_shape_per_layer"]
    cache = DynamicCache(config=model.config)
    for i in range(num_layers):
        keys, values = tensors.get(f"layer.{i}.keys"), tensors.get(f"layer.{i}.values")
        if keys is None or values is None:
            raise CacheValidationError(f"Faltan las K/V de la capa {i}")
        if list(keys.shape) != expected_shape or list(values.shape) != expected_shape:
            raise CacheValidationError(f"Forma inesperada en la capa {i}: {list(keys.shape)}")
        if str(keys.dtype).replace("torch.", "") != identity.dtype:
            raise CacheValidationError(f"dtype de la capa {i} ({keys.dtype}) != {identity.dtype}")
        cache.update(keys, values, i)
    if len(tensors) != 2 * num_layers:
        raise CacheValidationError(f"El archivo tiene {len(tensors)} tensores; el modelo espera {2 * num_layers}")

    prefix_len = len(identity.prefix_ids)
    if cache.get_seq_length() != prefix_len:
        raise CacheValidationError(f"La caché cargada tiene {cache.get_seq_length()} posiciones; el prefijo {prefix_len}")
    actual = fingerprint(cache, prefix_len)
    if actual != meta["fingerprint"]:
        raise CacheValidationError("La huella de las K/V cargadas no coincide con la guardada (archivo alterado o corrupto)")
    load_seconds = time.perf_counter() - start

    return KVCacheState(
        cache=cache,
        prefix_ids=list(identity.prefix_ids),
        prefix_len=prefix_len,
        fingerprint=actual,
        build_seconds=meta.get("build_seconds", 0.0),
        chunk_size=meta.get("chunk_size", 0),
        rss_before_mb=rss_before,
        rss_after_mb=rss_mb(),
        structure=cache_structure(cache, prefix_len),
        source="disk",
        load_seconds=load_seconds,
    )


def list_caches(root: Path = CACHES_DIR) -> list[dict]:
    """Metadatos de las cachés guardadas (las ilegibles se informan con su error)."""
    if not root.exists():
        return []
    found = []
    for directory in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.endswith(".tmp")):
        try:
            found.append(read_meta(directory))
        except CacheValidationError as exc:
            found.append({"cache_id": directory.name, "error": str(exc)})
    return found
