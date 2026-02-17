"""Tests for YAML config loading and validation."""

import tempfile
from pathlib import Path

import pytest

from osq.core.config import (
    DockerConfig,
    FanoutConfig,
    ModelConfig,
    PipelineConfig,
    ReviewConfig,
    StageConfig,
    load_config,
)
from osq.core.errors import ConfigError


VALID_YAML = """\
name: "test-pipeline"
models:
  opus:
    provider: openrouter
    model_id: anthropic/claude-opus-4.6
    api_key_env: OPENROUTER_API_KEY
    base_url: "https://openrouter.ai/api"
    cost_per_mtok_input: 15.0
    cost_per_mtok_output: 75.0
  qwen:
    provider: openrouter
    model_id: qwen/qwen3-coder-next
    api_key_env: OPENROUTER_API_KEY
    base_url: "https://openrouter.ai/api"
    cost_per_mtok_input: 0.07
    cost_per_mtok_output: 0.30

stages:
  - name: plan
    model: opus
    prompt_file: prompts/plan.txt
    max_turns: 30
  - name: code
    model: qwen
    prompt_file: prompts/code.txt
    max_turns: 100

fanout:
  enabled: true
  max_parallel: 4

review:
  max_iterations: 2
  pass_threshold: "PASS"

docker:
  image: test-image:latest
  network: test-net
"""


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    """Write a valid config to a temp file."""
    p = tmp_path / "test.yaml"
    p.write_text(VALID_YAML, encoding="utf-8")
    return p


def test_load_valid_config(config_file: Path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    config = load_config(str(config_file))

    assert config.name == "test-pipeline"
    assert "opus" in config.models
    assert "qwen" in config.models
    assert len(config.stages) == 2
    assert config.stages[0].name == "plan"
    assert config.stages[1].name == "code"
    assert config.fanout.enabled is True
    assert config.fanout.max_parallel == 4
    assert config.review.max_iterations == 2
    assert config.docker.image == "test-image:latest"


def test_model_config_fields(config_file: Path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    config = load_config(str(config_file))

    opus = config.models["opus"]
    assert opus.provider == "openrouter"
    assert opus.model_id == "anthropic/claude-opus-4.6"
    assert opus.cost_per_mtok_input == 15.0
    assert opus.cost_per_mtok_output == 75.0

    qwen = config.models["qwen"]
    assert qwen.cost_per_mtok_input == 0.07
    assert qwen.cost_per_mtok_output == 0.30


def test_config_file_not_found():
    with pytest.raises(ConfigError, match="not found"):
        load_config("/nonexistent/path.yaml")


def test_config_no_models(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("name: bad\nstages:\n  - name: plan\n    model: x\n    prompt_file: p.txt\n")
    with pytest.raises(ConfigError, match="No models"):
        load_config(str(p))


def test_config_no_stages(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("name: bad\nmodels:\n  x:\n    model_id: foo\n    api_key_env: X\n")
    with pytest.raises(ConfigError, match="No stages"):
        load_config(str(p))


def test_config_bad_model_ref(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    p = tmp_path / "bad.yaml"
    p.write_text(
        "models:\n  x:\n    model_id: foo\n    api_key_env: OPENROUTER_API_KEY\n"
        "stages:\n  - name: plan\n    model: nonexistent\n    prompt_file: p.txt\n"
    )
    with pytest.raises(ConfigError, match="not defined"):
        load_config(str(p))
