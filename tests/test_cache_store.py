"""Guardar y cargar la caché KV: equivalencia exacta y rechazo de cachés que no corresponden."""

import json

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("safetensors")

from app.cag.cache_builder import build_kv_cache  # noqa: E402
from app.cag.cache_store import (  # noqa: E402
    KV_FILE, META_FILE, CacheIdentity, CacheValidationError, cache_dir, list_caches, load_kv_cache, save_kv_cache,
)
from app.cag.engine import answer_with_cache, reset_to_prefix, verify_base_state  # noqa: E402

from tests.tiny_model import FakeTokenizer, make_tiny_model, random_ids  # noqa: E402

PREFIX = random_ids(300, 1)
Q1, Q2 = random_ids(12, 2), random_ids(9, 3)


@pytest.fixture(scope="module")
def model():
    return make_tiny_model()


def identity(**overrides):
    base = dict(model_id="tiny-qwen2", revision="abc123", dtype="float32", prefix_ids=tuple(PREFIX),
                corpus_build_id="build-1", corpus_version="v1")
    base.update(overrides)
    return CacheIdentity(**base)


@pytest.fixture()
def saved(model, tmp_path):
    state = build_kv_cache(model, PREFIX, chunk_size=64)
    meta = save_kv_cache(state, identity(), tmp_path)
    return state, meta, tmp_path


def test_roundtrip_is_exact(model, saved):
    state, meta, root = saved
    loaded = load_kv_cache(model, identity(), root)
    assert loaded.source == "disk" and loaded.load_seconds is not None
    assert loaded.fingerprint == state.fingerprint == meta["fingerprint"]
    assert loaded.structure == state.structure
    for a, b in zip(state.cache.layers, loaded.cache.layers):
        assert torch.equal(a.keys, b.keys) and torch.equal(a.values, b.values)

    tok = FakeTokenizer()
    for q in (Q1, Q2):
        fresh = answer_with_cache(model, tok, state, q, max_new_tokens=12)
        from_disk = answer_with_cache(model, tok, loaded, q, max_new_tokens=12)
        assert fresh.output_ids == from_disk.output_ids
        assert torch.equal(fresh.first_token_logits, from_disk.first_token_logits)
    verify_base_state(loaded)


def test_meta_records_what_determines_the_cache(saved):
    _, meta, root = saved
    ident = identity()
    assert meta["cache_id"] == ident.cache_id
    assert meta["prefix_hash"] == ident.prefix_hash and meta["prefix_len"] == len(PREFIX)
    assert (meta["model_id"], meta["revision"], meta["dtype"]) == ("tiny-qwen2", "abc123", "float32")
    assert meta["corpus_build_id"] == "build-1" and meta["corpus_version"] == "v1"
    assert meta["file_bytes"] == (cache_dir(ident, root) / KV_FILE).stat().st_size
    assert [m["cache_id"] for m in list_caches(root)] == [ident.cache_id]


def test_cache_id_changes_with_model_weights_dtype_or_prefix():
    ids = {identity().cache_id, identity(model_id="otro").cache_id, identity(revision="def456").cache_id,
           identity(dtype="bfloat16").cache_id, identity(prefix_ids=tuple(PREFIX[:-1])).cache_id}
    assert len(ids) == 5
    # La versión del corpus no entra en el id: se valida aparte para avisar que está desactualizada.
    assert identity(corpus_version="v2").cache_id == identity().cache_id


@pytest.mark.parametrize("field, value, message", [
    ("model_id", "otro-modelo", "model_id"),
    ("revision", "def456", "revision"),
    ("dtype", "bfloat16", "dtype"),
    ("prefix_ids", tuple(PREFIX[:-1] + [PREFIX[-1] % 400 + 3]), "prefix_hash"),
])
def test_mismatched_identity_is_rejected(model, saved, field, value, message):
    _, meta, root = saved
    other = identity(**{field: value})
    # Se fuerza a leer la carpeta guardada aunque el id esperado sea otro.
    target = cache_dir(other, root)
    if target != cache_dir(identity(), root):
        cache_dir(identity(), root).rename(target)
    with pytest.raises(CacheValidationError, match=message):
        load_kv_cache(model, other, root)


def test_stale_corpus_is_rejected(model, saved):
    _, _, root = saved
    with pytest.raises(CacheValidationError, match="desactualizada"):
        load_kv_cache(model, identity(corpus_version="v2"), root)


def test_tampered_file_is_detected(model, saved):
    _, _, root = saved
    path = cache_dir(identity(), root) / KV_FILE
    data = bytearray(path.read_bytes())
    data[-3] ^= 0xFF  # un byte de la última V de la última capa
    path.write_bytes(bytes(data))
    with pytest.raises(CacheValidationError, match="huella"):
        load_kv_cache(model, identity(), root)


def test_truncated_file_is_rejected(model, saved):
    _, _, root = saved
    path = cache_dir(identity(), root) / KV_FILE
    path.write_bytes(path.read_bytes()[:1000])
    with pytest.raises(CacheValidationError):
        load_kv_cache(model, identity(), root)


def test_missing_or_invalid_meta_is_rejected(model, saved):
    _, _, root = saved
    meta_path = cache_dir(identity(), root) / META_FILE
    meta_path.write_text("{no es json", encoding="utf-8")
    with pytest.raises(CacheValidationError, match="JSON"):
        load_kv_cache(model, identity(), root)
    meta_path.write_text(json.dumps({"format": "otro"}), encoding="utf-8")
    with pytest.raises(CacheValidationError, match="Formato"):
        load_kv_cache(model, identity(), root)
    meta_path.unlink()
    with pytest.raises(CacheValidationError, match="No existe"):
        load_kv_cache(model, identity(), root)


def test_missing_cache_is_rejected(model, tmp_path):
    with pytest.raises(CacheValidationError, match="No existe"):
        load_kv_cache(model, identity(), tmp_path)


def test_only_the_base_state_can_be_saved(model, tmp_path):
    state = build_kv_cache(model, PREFIX, chunk_size=64)
    answer_with_cache(model, FakeTokenizer(), state, Q1, max_new_tokens=5, reset=False)
    with pytest.raises(ValueError, match="estado base"):
        save_kv_cache(state, identity(), tmp_path)
    reset_to_prefix(state)
    with pytest.raises(ValueError, match="prefijo"):
        save_kv_cache(state, identity(prefix_ids=tuple(PREFIX[:-1])), tmp_path)
