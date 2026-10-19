"""Configuración de capas en GPU (``LLAMACPP_GPU_LAYERS``): lectura del .env y error claro sin CUDA."""

import pytest

from app.cag.llamacpp_engine import gpu_layers_from_env


@pytest.mark.parametrize("raw, expected", [(None, 0), ("", 0), ("0", 0), (" 20 ", 20), ("-1", -1)])
def test_gpu_layers_from_env(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("LLAMACPP_GPU_LAYERS", raising=False)
    else:
        monkeypatch.setenv("LLAMACPP_GPU_LAYERS", raw)
    assert gpu_layers_from_env() == expected


@pytest.mark.parametrize("raw", ["veinte", "1.5", "-2"])
def test_gpu_layers_invalid(monkeypatch, raw):
    monkeypatch.setenv("LLAMACPP_GPU_LAYERS", raw)
    with pytest.raises(ValueError, match="LLAMACPP_GPU_LAYERS"):
        gpu_layers_from_env()


def test_gpu_layers_without_cuda_fail_loudly():
    """Si se piden capas en GPU y el binario es solo CPU, el motor no arranca en silencio en CPU."""
    llama_cpp = pytest.importorskip("llama_cpp")
    if llama_cpp.llama_supports_gpu_offload():
        pytest.skip("este llama-cpp-python tiene soporte de GPU")
    from pathlib import Path

    from app.cag.llamacpp_engine import GGUFModel, LlamaCppEngine

    model = GGUFModel(path=Path("no-existe.gguf"), model_id="x", revision=None, quant="Q4_K_M")
    with pytest.raises(RuntimeError, match="sin soporte de GPU"):
        LlamaCppEngine(model, "corpus", n_gpu_layers=20)
