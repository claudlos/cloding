"""Tests for YAML config loading and validation."""

import tempfile
from pathlib import Path

import pytest

from cloding.core.config import (
    DockerConfig,
    FanoutConfig,
    ModelConfig,
    PipelineConfig,
    ReviewConfig,
    StageConfig,
    VerifyAgentConfig,
    VerifyConfig,
    load_config,
)
from cloding.core.errors import ConfigError


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


def test_config_not_a_mapping(tmp_path: Path):
    """YAML that parses to a non-dict (e.g., a string or list) should raise."""
    p = tmp_path / "bad.yaml"
    p.write_text("just a string, not a mapping\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a YAML mapping"):
        load_config(str(p))


def test_config_model_not_a_mapping(tmp_path: Path):
    """A model entry that's not a dict should raise."""
    p = tmp_path / "bad.yaml"
    p.write_text(
        "models:\n  qwen: not-a-dict\n"
        "stages:\n  - name: code\n    model: qwen\n    prompt_file: p.txt\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="Model 'qwen' must be a mapping"):
        load_config(str(p))


def test_config_stage_not_a_mapping(tmp_path: Path):
    """A stage entry that's not a dict should raise."""
    p = tmp_path / "bad.yaml"
    p.write_text(
        "models:\n  x:\n    model_id: foo\n    api_key_env: X\n"
        "stages:\n  - just-a-string\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="Each stage must be a mapping"):
        load_config(str(p))


def test_config_missing_prompt_file(tmp_path: Path, monkeypatch):
    """Stage with empty prompt_file should fail validation."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    p = tmp_path / "bad.yaml"
    p.write_text(
        "models:\n  x:\n    model_id: foo\n    api_key_env: OPENROUTER_API_KEY\n"
        "stages:\n  - name: code\n    model: x\n    prompt_file: \"\"\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="missing prompt_file"):
        load_config(str(p))


def test_config_missing_model_id(tmp_path: Path, monkeypatch):
    """Model with empty model_id should fail validation."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    p = tmp_path / "bad.yaml"
    p.write_text(
        "models:\n  x:\n    model_id: \"\"\n    api_key_env: OPENROUTER_API_KEY\n"
        "stages:\n  - name: code\n    model: x\n    prompt_file: p.txt\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="missing model_id"):
        load_config(str(p))


def test_config_missing_api_key_env(tmp_path: Path):
    """Model with empty api_key_env should fail validation."""
    p = tmp_path / "bad.yaml"
    p.write_text(
        "models:\n  x:\n    model_id: foo\n    api_key_env: \"\"\n"
        "stages:\n  - name: code\n    model: x\n    prompt_file: p.txt\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="missing api_key_env"):
        load_config(str(p))


def test_config_warns_on_missing_api_key(tmp_path: Path, monkeypatch):
    """When the API key env var is not set, should emit a warning."""
    import warnings

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("MY_FAKE_KEY", raising=False)
    p = tmp_path / "config.yaml"
    p.write_text(
        "models:\n  x:\n    model_id: foo\n    api_key_env: MY_FAKE_KEY\n"
        "stages:\n  - name: code\n    model: x\n    prompt_file: p.txt\n",
        encoding="utf-8",
    )
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        load_config(str(p))
    assert any("MY_FAKE_KEY" in str(warning.message) for warning in w)


# --- Verify config tests ---

VERIFY_YAML = """\
name: "verify-test"
models:
  opus:
    provider: openrouter
    model_id: anthropic/claude-opus-4.6
    api_key_env: OPENROUTER_API_KEY
    cost_per_mtok_input: 15.0
    cost_per_mtok_output: 75.0
  qwen:
    provider: openrouter
    model_id: qwen/qwen3-coder-next
    api_key_env: OPENROUTER_API_KEY
    cost_per_mtok_input: 0.07
    cost_per_mtok_output: 0.30

stages:
  - name: code
    model: qwen
    prompt_file: prompts/code.txt

verify:
  enabled: true
  agents:
    - model: opus
      prompt_file: prompts/verify.txt
    - model: qwen
      prompt_file: prompts/custom_verify.txt
  consensus_threshold: 0.75
  max_iterations: 5
"""


def test_load_verify_config(tmp_path, monkeypatch):
    """Verify config section is parsed correctly."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    p = tmp_path / "verify.yaml"
    p.write_text(VERIFY_YAML, encoding="utf-8")
    config = load_config(str(p))

    assert config.verify.enabled is True
    assert len(config.verify.agents) == 2
    assert config.verify.agents[0].model == "opus"
    assert config.verify.agents[0].prompt_file == "prompts/verify.txt"
    assert config.verify.agents[1].model == "qwen"
    assert config.verify.agents[1].prompt_file == "prompts/custom_verify.txt"
    assert config.verify.consensus_threshold == 0.75
    assert config.verify.max_iterations == 5


def test_verify_config_defaults(tmp_path, monkeypatch):
    """Missing verify section should use defaults."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    p = tmp_path / "no-verify.yaml"
    p.write_text(
        "models:\n  x:\n    model_id: foo\n    api_key_env: OPENROUTER_API_KEY\n"
        "stages:\n  - name: code\n    model: x\n    prompt_file: p.txt\n",
        encoding="utf-8",
    )
    config = load_config(str(p))
    assert config.verify.enabled is False
    assert config.verify.agents == []
    assert config.verify.consensus_threshold == 0.67
    assert config.verify.max_iterations == 3


def test_verify_agent_config_defaults():
    """VerifyAgentConfig should have sensible defaults."""
    agent = VerifyAgentConfig(model="opus")
    assert agent.prompt_file == "prompts/verify.txt"


def test_verify_config_empty_agents(tmp_path, monkeypatch):
    """Verify section with enabled=true but no agents is valid."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    p = tmp_path / "empty-agents.yaml"
    p.write_text(
        "models:\n  x:\n    model_id: foo\n    api_key_env: OPENROUTER_API_KEY\n"
        "stages:\n  - name: code\n    model: x\n    prompt_file: p.txt\n"
        "verify:\n  enabled: true\n",
        encoding="utf-8",
    )
    config = load_config(str(p))
    assert config.verify.enabled is True
    assert config.verify.agents == []
