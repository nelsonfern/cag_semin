"""Motor CAG con estado: reutilización, errores, límites de contexto y aislamiento entre consultas."""

import threading

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("safetensors")

from app.cag.cache_store import CacheIdentity, CacheValidationError  # noqa: E402
from app.cag.engine import (  # noqa: E402
    CacheNotReadyError, CAGEngine, ContextLimitError, QuestionError, answer_without_cache,
)
from app.ingestion.source_registry import Manifest  # noqa: E402

from tests.tiny_model import FakeTokenizer, encode_text, make_tiny_model, random_ids  # noqa: E402

PREFIX = random_ids(300, 1)
QUESTIONS = ["partida de nacimiento", "pasaporte de un menor", "DNI exprés", "costo del trámite", "horarios"]
MAX_NEW = 12


@pytest.fixture(scope="module")
def model():
    return make_tiny_model()


def make_engine(model, root, prefix=PREFIX, **kwargs):
    identity = CacheIdentity(model_id="tiny-qwen2", revision="abc123", dtype="float32",
                             prefix_ids=tuple(prefix), corpus_build_id="build-1", corpus_version="v1")
    kwargs.setdefault("max_new_tokens", MAX_NEW)
    kwargs.setdefault("chunk_size", 64)
    return CAGEngine(model, FakeTokenizer(), identity, encode_text, caches_root=root, **kwargs)


@pytest.fixture(scope="module")
def baseline(model):
    """Respuesta de referencia de cada pregunta, recalculando todo desde cero."""
    tok = FakeTokenizer()
    return {q: answer_without_cache(model, tok, PREFIX, encode_text(q), max_new_tokens=MAX_NEW, chunk_size=64).output_ids
            for q in QUESTIONS}


@pytest.fixture()
def engine(model, tmp_path):
    e = make_engine(model, tmp_path)
    e.prepare()
    return e


# --- Reutilización ------------------------------------------------------------------------

def test_first_prepare_builds_and_saves_then_loads_from_disk(model, tmp_path, baseline):
    first = make_engine(model, tmp_path)
    report = first.prepare()
    assert report["source"] == "built" and report["rejected"] and report["file_bytes"] > 0

    second = make_engine(model, tmp_path)
    report = second.prepare(allow_build=False)
    assert report["source"] == "disk" and report["rejected"] is None
    assert second.state.fingerprint == first.state.fingerprint
    for q in QUESTIONS[:2]:
        assert second.answer(q).output_ids == baseline[q]


def test_force_rebuild_ignores_a_valid_cache(model, engine):
    report = engine.prepare(force_rebuild=True)
    assert report["source"] == "built"


def test_prepare_without_build_fails_if_there_is_no_cache(model, tmp_path):
    with pytest.raises(CacheValidationError):
        make_engine(model, tmp_path).prepare(allow_build=False)


def test_answer_before_prepare_fails(model, tmp_path):
    with pytest.raises(CacheNotReadyError):
        make_engine(model, tmp_path).answer("hola")


def test_build_is_registered_in_the_manifest(model, tmp_path):
    manifest = Manifest(tmp_path / "manifest.json")
    e = make_engine(model, tmp_path, manifest=manifest)
    e.prepare()
    e.prepare(force_rebuild=True)  # reconstruir no duplica el registro
    saved = Manifest(tmp_path / "manifest.json")
    assert [c["cache_id"] for c in saved.caches] == [e.identity.cache_id]
    entry = saved.caches[0]
    assert entry["corpus_version"] == manifest.corpus_version and entry["stale"] is False
    assert entry["fingerprint"] == e.state.fingerprint and entry["model_id"] == "tiny-qwen2"


# --- Aislamiento --------------------------------------------------------------------------

@pytest.mark.parametrize("order", [QUESTIONS, QUESTIONS[::-1], QUESTIONS[2:] + QUESTIONS[:2]])
def test_answers_do_not_depend_on_previous_questions(engine, baseline, order):
    for q in order:
        r = engine.answer(q)
        assert r.output_ids == baseline[q]
        assert r.cache_len_before == len(PREFIX)
    assert engine.state.cache.get_seq_length() == len(PREFIX)


def test_failure_mid_generation_restores_the_cache(engine, baseline):
    def explode(token_id, seen=[]):
        seen.append(token_id)
        if len(seen) == 3:
            raise RuntimeError("falla simulada durante la generación")

    with pytest.raises(RuntimeError, match="falla simulada"):
        engine.answer(QUESTIONS[0], on_token=explode)
    assert engine.state.cache.get_seq_length() == len(PREFIX)  # sin tokens de la consulta fallida
    assert engine.answer(QUESTIONS[1]).output_ids == baseline[QUESTIONS[1]]
    assert engine.recoveries == []


def test_altered_cache_is_recovered_from_disk(engine, baseline):
    with torch.inference_mode():
        engine.state.cache.layers[1].keys[0, 1, 7, 3] += 1.0
    r = engine.answer(QUESTIONS[0])
    assert r.output_ids == baseline[QUESTIONS[0]]
    assert len(engine.recoveries) == 1 and "cambiaron" in engine.recoveries[0]
    assert engine.state.source == "disk"


def test_concurrent_questions_are_serialized(engine, baseline):
    results, errors = {}, []

    def worker(q):
        try:
            results.setdefault(q, []).append(engine.answer(q).output_ids)
        except Exception as exc:  # pragma: no cover - se informa abajo
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(q,)) for q in QUESTIONS * 2]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    for q in QUESTIONS:
        assert results[q] == [baseline[q], baseline[q]]
    assert engine.state.cache.get_seq_length() == len(PREFIX)


def test_streamed_tokens_match_the_result(engine):
    streamed = []
    r = engine.answer(QUESTIONS[0], on_token=streamed.append)
    assert streamed == [t for t in r.output_ids if t != FakeTokenizer.eos_token_id]


# --- Errores y límites de contexto ----------------------------------------------------------

@pytest.mark.parametrize("question", ["", "   ", None])
def test_empty_question_is_rejected(engine, question):
    with pytest.raises(QuestionError, match="vacía"):
        engine.answer(question)


def test_too_long_question_is_rejected(model, tmp_path):
    e = make_engine(model, tmp_path, max_question_tokens=20)
    with pytest.raises(QuestionError, match="caracteres"):
        e.validate_question("a" * 1001)
    with pytest.raises(QuestionError, match="tokens"):
        e.validate_question("a" * 21)
    assert len(e.validate_question("a" * 20)) == 20


def test_question_plus_answer_must_fit_in_the_context(model, tmp_path):
    # Contexto permitido 330: prefijo 300 + pregunta 10 + respuesta 20 entran justo.
    e = make_engine(model, tmp_path, max_context_tokens=330, max_new_tokens=20)
    assert e.context_limit == 330
    assert len(e.validate_question("x" * 10)) == 10
    with pytest.raises(ContextLimitError, match="331"):
        e.validate_question("x" * 11)
    with pytest.raises(ContextLimitError):
        e.validate_question("x" * 10, max_new_tokens=21)


def test_context_limit_is_the_smaller_of_model_and_setting(model, tmp_path):
    assert make_engine(model, tmp_path).context_limit == model.config.max_position_embeddings
    assert make_engine(model, tmp_path, max_context_tokens=10**6).context_limit == model.config.max_position_embeddings


def test_prefix_that_does_not_fit_is_rejected(model, tmp_path):
    with pytest.raises(ContextLimitError, match="prefijo"):
        make_engine(model, tmp_path, max_context_tokens=300)
    make_engine(model, tmp_path, max_context_tokens=301)  # un token libre: se acepta
