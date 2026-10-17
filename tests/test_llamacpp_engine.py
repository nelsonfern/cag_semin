"""Motor CAG con llama.cpp: reutilización, caché en disco, aislamiento, errores y límites.

Usa un modelo GGUF real (Qwen2.5-3B-Instruct Q4_K_M) si está en la caché de Hugging Face, con un
corpus chico para que la caché se construya en segundos. Si el archivo no está, se saltean: no
se descarga nada durante los tests.
"""

import json

import numpy as np
import pytest

pytest.importorskip("llama_cpp")

from app.cag.cache_store import CacheValidationError, cache_dir  # noqa: E402
from app.cag.engine import ContextLimitError, QuestionError  # noqa: E402
from app.cag.llamacpp_engine import STATE_FILE, META_FILE, GGUFModel, LlamaCppEngine  # noqa: E402
from tests.test_citations import CORPUS  # noqa: E402

REPO, FILE, REV = ("bartowski/Qwen2.5-3B-Instruct-GGUF", "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
                   "f302c64a2269a69fb27b2f9473b362f5bb8e78d8")
MAX_NEW = 8
Q1, Q2 = "¿Qué requisitos hay para pedir una partida?", "¿Cuándo entregan el DNI exprés?"


def _model_path():
    import app.config  # noqa: F401  (HF_HOME del .env)
    from huggingface_hub import try_to_load_from_cache

    path = try_to_load_from_cache(REPO, FILE, revision=REV)
    return path if isinstance(path, str) else None


MODEL_PATH = _model_path()
pytestmark = pytest.mark.skipif(MODEL_PATH is None, reason=f"{FILE} no está descargado")


@pytest.fixture(scope="module")
def caches(tmp_path_factory):
    return tmp_path_factory.mktemp("caches")


@pytest.fixture(scope="module")
def engine(caches):
    from pathlib import Path

    model = GGUFModel(path=Path(MODEL_PATH), model_id=f"{REPO}/{FILE}", revision=REV, quant="Q4_K_M")
    e = LlamaCppEngine(model, CORPUS, corpus_build_id="b1", corpus_version="v1", caches_root=caches,
                       threads=6, max_new_tokens=MAX_NEW, max_question_tokens=64)
    report = e.prepare()
    assert report["source"] == "built"
    return e


def baseline(e: LlamaCppEngine, question: str) -> list[int]:
    """Respuesta recalculando todo (prefijo + pregunta) desde una caché vacía."""
    e.llm.reset()
    e.llm.eval(list(e.identity.prefix_ids))
    e.llm.eval(e.encode_question(question))
    out = []
    for _ in range(MAX_NEW):
        token = int(np.argmax(e._last_logits()))
        out.append(token)
        if token in e.stop:
            break
        e.llm.eval([token])
    e._reset_to_prefix()
    return out


def test_cache_is_saved_with_metadata(engine, caches):
    directory = cache_dir(engine.identity, caches)
    meta = json.loads((directory / META_FILE).read_text(encoding="utf-8"))
    assert meta["fingerprint"] == engine.state.fingerprint and meta["prefix_len"] == engine.prefix_len
    assert meta["n_ctx"] == engine.n_ctx and meta["flash_attn"] is True and meta["revision"] == REV
    assert (directory / STATE_FILE).stat().st_size == meta["state_bytes"]


def test_cag_equals_baseline_and_questions_are_isolated(engine):
    alone = engine.answer(Q2).output_ids
    engine.answer(Q1)
    after_q1 = engine.answer(Q2)
    assert after_q1.output_ids == alone                 # Q1 no contaminó a Q2
    assert after_q1.cache_len_before == engine.prefix_len
    assert after_q1.output_ids == baseline(engine, Q2)  # reutilizar la caché = recalcular todo
    engine._verify_base_state()


def test_load_from_disk_reproduces_the_answer(engine):
    expected = engine.answer(Q1).output_ids
    report = engine.prepare(allow_build=False)
    assert report["source"] == "disk" and engine.state.source == "disk"
    assert engine.answer(Q1).output_ids == expected


def test_failure_mid_generation_restores_the_prefix(engine):
    def explode(token, seen=[]):
        seen.append(token)
        if len(seen) == 2:
            raise RuntimeError("falla simulada")

    with pytest.raises(RuntimeError, match="falla simulada"):
        engine.answer(Q1, on_token=explode)
    assert engine.llm.n_tokens == engine.prefix_len
    engine._verify_base_state()


def test_altered_state_is_recovered_from_disk(engine):
    expected = engine.answer(Q2).output_ids
    real = engine.state.fingerprint
    engine.state.fingerprint = "0" * 32  # simula una caché que no coincide con la original
    assert engine.answer(Q2).output_ids == expected
    assert engine.recoveries and engine.state.fingerprint == real


def test_streamed_tokens_and_text(engine):
    seen = []
    r = engine.answer(Q1, on_token=seen.append)
    assert seen == [t for t in r.output_ids if t not in engine.stop]
    assert r.text == engine.tokenizer.decode(r.output_ids).strip()


def test_tampered_state_file_is_rejected(engine, caches):
    state = cache_dir(engine.identity, caches) / STATE_FILE
    original = state.read_bytes()
    data = bytearray(original)
    data[len(data) // 2] ^= 0xFF
    state.write_bytes(bytes(data))
    try:
        with pytest.raises(CacheValidationError):
            engine.prepare(allow_build=False)
    finally:
        state.write_bytes(original)
        engine.prepare(allow_build=False)


def test_metadata_mismatch_is_rejected(engine, caches):
    meta_path = cache_dir(engine.identity, caches) / META_FILE
    original = meta_path.read_text(encoding="utf-8")
    meta = json.loads(original)
    meta["n_ctx"] += 1024
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    try:
        with pytest.raises(CacheValidationError, match="n_ctx"):
            engine.prepare(allow_build=False)
    finally:
        meta_path.write_text(original, encoding="utf-8")
        engine.prepare(allow_build=False)


def test_question_and_context_limits(engine):
    with pytest.raises(QuestionError, match="vacía"):
        engine.answer("  ")
    with pytest.raises(QuestionError, match="tokens"):
        engine.validate_question("palabra " * 100)  # 800 caracteres, más de 64 tokens
    limit = engine.context_limit
    try:
        engine.context_limit = engine.prefix_len + 20
        with pytest.raises(ContextLimitError):
            engine.validate_question(Q1, max_new_tokens=MAX_NEW)
    finally:
        engine.context_limit = limit


def test_warmup_leaves_the_prefix_intact(engine):
    assert engine.warmup() > 0
    assert engine.llm.n_tokens == engine.prefix_len
    engine._verify_base_state()
