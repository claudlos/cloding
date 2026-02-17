"""YAML config loader and dataclass hierarchy for Cloding pipeline configuration."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from osq.core.errors import ConfigError


@dataclass(frozen=True)
class ModelConfig:
    """Configuration for a single model provider."""

    name: str
    provider: str  # "openrouter" or "anthropic"
    model_id: str  # e.g., "anthropic/claude-opus-4.6" or "qwen/qwen3-coder-next"
    api_key_env: str  # env var name: "OPENROUTER_API_KEY" or "ANTHROPIC_API_KEY"
    base_url: Optional[str] = None  # "https://openrouter.ai/api" for OpenRouter
    cost_per_mtok_input: float = 0.0
    cost_per_mtok_output: float = 0.0
    max_context_tokens: int = 200_000


@dataclass(frozen=True)
class StageConfig:
    """Configuration for a single pipeline stage."""

    name: str  # "plan", "explore", "code", "review"
    model: str  # key into models dict
    prompt_file: str  # path to prompt template
    max_turns: int = 50
    max_budget_usd: float = 2.0
    timeout_seconds: int = 600
    allowed_tools: Optional[list[str]] = None
    disallowed_tools: Optional[list[str]] = None
    output_format: str = "json"


@dataclass(frozen=True)
class FanoutConfig:
    """Configuration for parallel fan-out coding."""

    enabled: bool = False
    max_parallel: int = 4
    memory_limit: str = "2g"
    cpu_limit: float = 1.0


@dataclass(frozen=True)
class ReviewConfig:
    """Configuration for the review loop."""

    max_iterations: int = 3
    pass_threshold: str = "PASS"


@dataclass(frozen=True)
class DockerConfig:
    """Configuration for Docker containers."""

    image: str = "cloding:latest"
    network: str = "cloding-net"
    workspace_volume: str = "cloding-workspace"


@dataclass
class PipelineConfig:
    """Top-level pipeline configuration loaded from YAML."""

    name: str = "default"
    models: dict[str, ModelConfig] = field(default_factory=dict)
    stages: list[StageConfig] = field(default_factory=list)
    fanout: FanoutConfig = field(default_factory=FanoutConfig)
    review: ReviewConfig = field(default_factory=ReviewConfig)
    docker: DockerConfig = field(default_factory=DockerConfig)
    workspace_path: str = ""
    log_level: str = "INFO"
    resume_from_stage: Optional[str] = None


def load_config(path: str) -> PipelineConfig:
    """
    Load and validate a YAML pipeline config.

    Args:
        path: Path to the YAML config file

    Returns:
        Validated PipelineConfig dataclass
    """
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"Config file must be a YAML mapping: {path}")

    models = {}
    for name, m in raw.get("models", {}).items():
        if not isinstance(m, dict):
            raise ConfigError(f"Model '{name}' must be a mapping")
        models[name] = ModelConfig(
            name=name,
            provider=m.get("provider", "openrouter"),
            model_id=m["model_id"],
            api_key_env=m.get("api_key_env", "OPENROUTER_API_KEY"),
            base_url=m.get("base_url"),
            cost_per_mtok_input=float(m.get("cost_per_mtok_input", 0.0)),
            cost_per_mtok_output=float(m.get("cost_per_mtok_output", 0.0)),
            max_context_tokens=int(m.get("max_context_tokens", 200_000)),
        )

    stages = []
    for s in raw.get("stages", []):
        if not isinstance(s, dict):
            raise ConfigError("Each stage must be a mapping")
        stages.append(StageConfig(
            name=s["name"],
            model=s["model"],
            prompt_file=s["prompt_file"],
            max_turns=int(s.get("max_turns", 50)),
            max_budget_usd=float(s.get("max_budget_usd", 2.0)),
            timeout_seconds=int(s.get("timeout_seconds", 600)),
            allowed_tools=s.get("allowed_tools"),
            disallowed_tools=s.get("disallowed_tools"),
            output_format=s.get("output_format", "json"),
        ))

    fanout_raw = raw.get("fanout", {})
    review_raw = raw.get("review", {})
    docker_raw = raw.get("docker", {})

    config = PipelineConfig(
        name=raw.get("name", "default"),
        models=models,
        stages=stages,
        fanout=FanoutConfig(**fanout_raw) if fanout_raw else FanoutConfig(),
        review=ReviewConfig(**review_raw) if review_raw else ReviewConfig(),
        docker=DockerConfig(**docker_raw) if docker_raw else DockerConfig(),
        workspace_path=raw.get("workspace_path", ""),
        log_level=raw.get("log_level", "INFO"),
    )

    _validate_config(config)
    return config


def _validate_config(config: PipelineConfig) -> None:
    """Validate the loaded config, raising ConfigError for issues."""
    if not config.models:
        raise ConfigError("No models defined in config.")
    if not config.stages:
        raise ConfigError("No stages defined in config.")

    for stage in config.stages:
        if stage.model not in config.models:
            raise ConfigError(
                f"Stage '{stage.name}' references model '{stage.model}' "
                f"which is not defined in the models section."
            )
        if not stage.prompt_file:
            raise ConfigError(f"Stage '{stage.name}' missing prompt_file.")

    for name, model in config.models.items():
        if not model.model_id:
            raise ConfigError(f"Model '{name}' missing model_id.")
        if not model.api_key_env:
            raise ConfigError(f"Model '{name}' missing api_key_env.")

    # Warn (but don't error) if API keys aren't set -- they may be set at runtime
    for name, model in config.models.items():
        key = os.environ.get(model.api_key_env, "")
        if not key:
            import warnings
            warnings.warn(
                f"Model '{name}' requires env var {model.api_key_env} "
                f"which is not currently set.",
                stacklevel=2,
            )
