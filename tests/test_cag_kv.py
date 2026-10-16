"""Reutilización y aislamiento de la caché KV con un modelo Qwen2 minúsculo.

El modelo se crea en memoria (2 capas, pesos aleatorios con semilla fija, float32): no hace
falta red ni descargar nada, y en float32 las comparaciones pueden ser exactas.
"""

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")

from app.cag.cache_builder import build_kv_cache, prefill  # noqa: E402
from app.cag.engine import (  # noqa: E402
    CacheContaminationError, answer_with_cache, answer_without_cache, reset_to_prefix, verify_base_state,
)

VOCAB = 500
EOS = 2


class FakeTokenizer:
    eos_token_id = EOS

    def decode(self, ids, skip_special_tokens=True):
        return " ".join(map(str, ids))


@pytest.fixture(scope="module")
def model():
    from transformers import Qwen2Config, Qwen2ForCausalLM
    torch.manual_seed(0)
    config = Qwen2Config(
        vocab_size=VOCAB, hidden_size=64, intermediate_size=128, num_hidden_layers=2,
        num_attention_heads=4, num_key_value_heads=2, max_position_embeddings=2048,
        eos_token_id=EOS, attn_implementation="sdpa",
    )
    m = Qwen2ForCausalLM(config).eval()
    m.generation_config.eos_token_id = EOS
    return m


def ids(n, seed):
    g = torch.Generator().manual_seed(seed)
    return torch.randint(3, VOCAB, (n,), generator=g).tolist()  # sin EOS


PREFIX = ids(300, 1)
Q1, Q2 = ids(12, 2), ids(9, 3)


def test_chunked_prefill_equals_single_pass(model):
    from transformers import DynamicCache
    single = prefill(model, PREFIX, DynamicCache(config=model.config), chunk_size=10_000)
    chunked = prefill(model, PREFIX, DynamicCache(config=model.config), chunk_size=64)
    assert torch.allclose(single, chunked, atol=1e-5)


def test_cache_matches_baseline_and_questions_are_isolated(model):
    tok = FakeTokenizer()
    state = build_kv_cache(model, PREFIX, chunk_size=64)
    base1 = answer_without_cache(model, tok, PREFIX, Q1, max_new_tokens=15, chunk_size=64)
    base2 = answer_without_cache(model, tok, PREFIX, Q2, max_new_tokens=15, chunk_size=64)

    cag1 = answer_with_cache(model, tok, state, Q1, max_new_tokens=15)
    cag2 = answer_with_cache(model, tok, state, Q2, max_new_tokens=15)  # después de Q1

    assert cag1.output_ids == base1.output_ids
    assert cag2.output_ids == base2.output_ids  # base2 nunca vio Q1: no hay contaminación
    assert torch.allclose(cag2.first_token_logits, base2.first_token_logits, atol=1e-5)
    assert cag2.cache_len_before == len(PREFIX)
    assert cag1.cache_len_after_generation > len(PREFIX)  # la generación sí usó la caché...
    verify_base_state(state)                              # ...y quedó restaurada al prefijo


def test_without_reset_the_previous_answer_contaminates(model):
    tok = FakeTokenizer()
    state = build_kv_cache(model, PREFIX, chunk_size=64)
    answer_with_cache(model, tok, state, Q1, max_new_tokens=10, reset=False)
    contaminated = answer_with_cache(model, tok, state, Q2, max_new_tokens=10, reset=False)
    clean = answer_without_cache(model, tok, PREFIX, Q2, max_new_tokens=10, chunk_size=64)
    assert contaminated.cache_len_before > len(PREFIX)
    assert not torch.allclose(contaminated.first_token_logits, clean.first_token_logits, atol=1e-5)
    with pytest.raises(CacheContaminationError):
        verify_base_state(state)
    reset_to_prefix(state)
    verify_base_state(state)  # restaurar recupera exactamente el estado base


def test_tampered_prefix_is_detected(model):
    state = build_kv_cache(model, PREFIX, chunk_size=64)
    with torch.inference_mode():  # los tensores de la caché se crearon en inference_mode
        state.cache.layers[0].values[0, 0, 5, 0] += 1.0
    with pytest.raises(CacheContaminationError, match="cambiaron"):
        verify_base_state(state)


def test_crop_requires_negative_count_in_this_transformers_version(model):
    state = build_kv_cache(model, PREFIX[:50], chunk_size=64)
    with pytest.raises(ValueError):
        state.cache.crop(10)  # API anterior (largo final): ya no se acepta


def test_prefix_longer_than_context_is_rejected(model):
    with pytest.raises(ValueError, match="no entra"):
        build_kv_cache(model, ids(model.config.max_position_embeddings, 9))
