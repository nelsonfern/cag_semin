"""Modelo Qwen2 minúsculo creado en memoria para los tests (sin red, float32, semilla fija)."""

import torch

VOCAB = 500
EOS = 2


class FakeTokenizer:
    eos_token_id = EOS

    def decode(self, ids, skip_special_tokens=True):
        return " ".join(map(str, ids))


def make_tiny_model(max_position_embeddings: int = 2048):
    from transformers import Qwen2Config, Qwen2ForCausalLM

    torch.manual_seed(0)
    config = Qwen2Config(
        vocab_size=VOCAB, hidden_size=64, intermediate_size=128, num_hidden_layers=2,
        num_attention_heads=4, num_key_value_heads=2, max_position_embeddings=max_position_embeddings,
        eos_token_id=EOS, attn_implementation="sdpa",
    )
    model = Qwen2ForCausalLM(config).eval()
    model.generation_config.eos_token_id = EOS
    return model


def random_ids(n: int, seed: int) -> list[int]:
    g = torch.Generator().manual_seed(seed)
    return torch.randint(3, VOCAB, (n,), generator=g).tolist()  # sin EOS


def encode_text(text: str) -> list[int]:
    """Tokenizer de juguete para preguntas: un id por byte, sin tokens especiales."""
    return [3 + b % (VOCAB - 3) for b in text.encode("utf-8")]
