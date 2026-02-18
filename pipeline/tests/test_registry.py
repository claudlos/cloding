"""Tests for model registry and cost estimation."""

import pytest

from osq.core.config import ModelConfig
from osq.models.registry import ModelRegistry


def _make_model(name="qwen", model_id="qwen/qwen3-coder-next", **kwargs):
    defaults = dict(
        provider="openrouter",
        api_key_env="OPENROUTER_API_KEY",
        cost_per_mtok_input=0.07,
        cost_per_mtok_output=0.30,
    )
    defaults.update(kwargs)
    return ModelConfig(name=name, model_id=model_id, **defaults)


class TestModelRegistry:
    def test_get_existing_model(self):
        reg = ModelRegistry({"qwen": _make_model()})
        m = reg.get("qwen")
        assert m.model_id == "qwen/qwen3-coder-next"

    def test_get_missing_model(self):
        reg = ModelRegistry({"qwen": _make_model()})
        with pytest.raises(KeyError, match="opus"):
            reg.get("opus")

    def test_estimate_cost_zero_tokens(self):
        reg = ModelRegistry({"qwen": _make_model()})
        assert reg.estimate_cost("qwen", 0, 0) == 0.0

    def test_estimate_cost_calculation(self):
        reg = ModelRegistry({"qwen": _make_model()})
        # 1M input tokens at $0.07/Mtok = $0.07
        # 1M output tokens at $0.30/Mtok = $0.30
        cost = reg.estimate_cost("qwen", 1_000_000, 1_000_000)
        assert cost == pytest.approx(0.37)

    def test_estimate_cost_small_tokens(self):
        reg = ModelRegistry({"qwen": _make_model()})
        cost = reg.estimate_cost("qwen", 1000, 500)
        expected = 1000 * 0.07 / 1_000_000 + 500 * 0.30 / 1_000_000
        assert cost == pytest.approx(expected)

    def test_list_models(self):
        reg = ModelRegistry({
            "qwen": _make_model(),
            "opus": _make_model(name="opus", model_id="anthropic/claude-opus-4.6",
                                cost_per_mtok_input=15.0, cost_per_mtok_output=75.0),
        })
        models = reg.list_models()
        assert len(models) == 2
        names = {m["name"] for m in models}
        assert "qwen" in names
        assert "opus" in names

    def test_list_models_format(self):
        reg = ModelRegistry({"qwen": _make_model()})
        models = reg.list_models()
        m = models[0]
        assert "name" in m
        assert "provider" in m
        assert "model_id" in m
        assert "cost_input" in m
        assert "cost_output" in m
        assert "$" in m["cost_input"]
