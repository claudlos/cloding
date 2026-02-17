"""Model registry with cost estimation fallback."""

from osq.core.config import ModelConfig


class ModelRegistry:
    """Manages model definitions and provides cost estimation."""

    def __init__(self, models: dict[str, ModelConfig]) -> None:
        self.models = models

    def get(self, name: str) -> ModelConfig:
        """Get a model config by name."""
        if name not in self.models:
            raise KeyError(f"Model '{name}' not found in registry. Available: {list(self.models)}")
        return self.models[name]

    def estimate_cost(self, model_name: str, tokens_in: int, tokens_out: int) -> float:
        """
        Estimate cost for a model invocation using config rates.

        Primary cost source for OpenRouter models (Claude Code reports inflated
        Anthropic pricing). Also used as fallback for direct Anthropic calls
        when Claude Code doesn't report cost_usd.

        Args:
            model_name: Key into models dict
            tokens_in: Input token count
            tokens_out: Output token count

        Returns:
            Estimated cost in USD
        """
        model = self.get(model_name)
        cost_in = tokens_in * model.cost_per_mtok_input / 1_000_000
        cost_out = tokens_out * model.cost_per_mtok_output / 1_000_000
        return cost_in + cost_out

    def list_models(self) -> list[dict]:
        """List all registered models with their configs."""
        return [
            {
                "name": m.name,
                "provider": m.provider,
                "model_id": m.model_id,
                "cost_input": f"${m.cost_per_mtok_input:.2f}/Mtok",
                "cost_output": f"${m.cost_per_mtok_output:.2f}/Mtok",
            }
            for m in self.models.values()
        ]
