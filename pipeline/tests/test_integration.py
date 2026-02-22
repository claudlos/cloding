"""Integration tests: config → tool_handler → env routing, cost tracking, error propagation."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from cloding.core.config import ModelConfig, StageConfig, load_config
from cloding.core.tool_handler import get_tool_handler
from cloding.models.cost_tracker import CostTracker
from cloding.pipeline.result import RunResult, StageResult


def _make_model(**kwargs):
    defaults = dict(
        name="test",
        provider="openrouter",
        model_id="test/model",
        api_key_env="OPENROUTER_API_KEY",
        base_url=None,
        cost_per_mtok_input=0.0,
        cost_per_mtok_output=0.0,
    )
    defaults.update(kwargs)
    return ModelConfig(**defaults)


def _make_stage(**kwargs):
    defaults = dict(
        name="code",
        model="test",
        prompt_file="prompts/code.txt",
        max_turns=20,
        max_budget_usd=2.0,
        timeout_seconds=600,
        output_format="json",
    )
    defaults.update(kwargs)
    return StageConfig(**defaults)


class TestProviderRouting:
    """End-to-end: config model → tool handler → correct env vars."""

    def test_openrouter_routing(self):
        """OpenRouter model should produce OpenRouter env vars."""
        model = _make_model(
            name="qwen",
            provider="openrouter",
            model_id="qwen/qwen3-coder-next",
            api_key_env="OPENROUTER_API_KEY",
            base_url="https://openrouter.ai/api",
        )
        handler = get_tool_handler(model.tool)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-test"}):
            env = handler.build_env(model)

        assert env["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"
        assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-or-test"
        assert env["ANTHROPIC_API_KEY"] == ""
        assert env["ANTHROPIC_MODEL"] == "qwen/qwen3-coder-next"
        assert handler.get_binary_name() == "claude"

    def test_anthropic_direct_routing(self):
        """Direct Anthropic model should use native API key."""
        model = _make_model(
            name="sonnet-a",
            provider="anthropic",
            model_id="claude-sonnet-4",
            api_key_env="ANTHROPIC_API_KEY",
        )
        handler = get_tool_handler(model.tool)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            env = handler.build_env(model)

        assert env["ANTHROPIC_API_KEY"] == "sk-ant-test"
        assert env["ANTHROPIC_MODEL"] == "claude-sonnet-4"
        assert "ANTHROPIC_BASE_URL" not in env
        assert "ANTHROPIC_AUTH_TOKEN" not in env

    def test_plan_routing(self):
        """Plan provider should only set model, no auth."""
        model = _make_model(
            name="opus-p",
            provider="plan",
            model_id="claude-opus-4-6",
            api_key_env="",
        )
        handler = get_tool_handler(model.tool)
        env = handler.build_env(model)

        assert env["ANTHROPIC_MODEL"] == "claude-opus-4-6"
        assert env["CLAUDECODE"] == ""
        assert "ANTHROPIC_API_KEY" not in env
        assert "ANTHROPIC_BASE_URL" not in env

    def test_gemini_routing(self):
        """Gemini model should use Gemini handler."""
        model = _make_model(
            name="gemini-3",
            provider="google",
            model_id="gemini-3-pro",
            api_key_env="GOOGLE_API_KEY",
            tool="gemini",
        )
        handler = get_tool_handler(model.tool)
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "gk-test"}):
            env = handler.build_env(model)

        assert env["GOOGLE_API_KEY"] == "gk-test"
        assert handler.get_binary_name() == "gemini"

    def test_codex_api_routing(self):
        """Codex API model should use Codex handler with API key."""
        model = _make_model(
            name="codex-5-a",
            provider="openai",
            model_id="gpt-5.3-codex-high",
            api_key_env="OPENAI_API_KEY",
            tool="codex",
        )
        handler = get_tool_handler(model.tool)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            env = handler.build_env(model)
        stage = _make_stage()
        args = handler.build_cli_args(stage, model, "test prompt")

        assert env["OPENAI_API_KEY"] == "sk-test"
        assert "--full-auto" in args
        assert "--model" in args
        assert "gpt-5.3-codex-high" in args
        assert handler.get_binary_name() == "codex"

    def test_codex_plan_routing(self):
        """Codex plan model should skip API key and --model flag."""
        model = _make_model(
            name="codex-5",
            provider="plan",
            model_id="",
            api_key_env="",
            tool="codex",
        )
        handler = get_tool_handler(model.tool)
        env = handler.build_env(model)
        stage = _make_stage()
        args = handler.build_cli_args(stage, model, "test prompt")

        assert "OPENAI_API_KEY" not in env
        assert "--model" not in args
        assert "--full-auto" in args
        assert handler.get_binary_name() == "codex"


class TestCostTracking:
    """Cost tracker accumulation across stages."""

    def test_multi_stage_accumulation(self):
        """Multiple stage results should accumulate correctly."""
        tracker = CostTracker()

        tracker.record("plan", StageResult(
            stage_name="plan",
            output="plan output",
            tokens_in=1000,
            tokens_out=500,
            cost_usd=0.05,
            model_id="anthropic/claude-sonnet-4",
            provider="openrouter",
            num_turns=3,
            duration_ms=5000,
        ))

        tracker.record("code", StageResult(
            stage_name="code",
            output="code output",
            tokens_in=5000,
            tokens_out=2000,
            cost_usd=0.12,
            model_id="qwen/qwen3-coder-next",
            provider="openrouter",
            num_turns=10,
            duration_ms=30000,
        ))

        tracker.record("review", StageResult(
            stage_name="review",
            output="review output",
            tokens_in=2000,
            tokens_out=800,
            cost_usd=0.03,
            model_id="anthropic/claude-sonnet-4",
            provider="openrouter",
            num_turns=2,
            duration_ms=8000,
        ))

        summary = tracker.summary()
        assert summary["total_cost_usd"] == pytest.approx(0.20)
        assert summary["total_tokens_in"] == 8000
        assert summary["total_tokens_out"] == 3300
        assert summary["total_duration_ms"] == 43000
        assert summary["record_count"] == 3
        assert summary["by_stage"]["plan"] == pytest.approx(0.05)
        assert summary["by_stage"]["code"] == pytest.approx(0.12)
        assert summary["by_stage"]["review"] == pytest.approx(0.03)

    def test_empty_tracker_summary(self):
        """Empty tracker should return zeroes."""
        tracker = CostTracker()
        summary = tracker.summary()
        assert summary["total_cost_usd"] == 0.0
        assert summary["total_tokens_in"] == 0
        assert summary["record_count"] == 0

    def test_cost_records_preserve_provider(self):
        """Cost records should preserve provider info for reporting."""
        tracker = CostTracker()
        tracker.record("plan", StageResult(
            stage_name="plan",
            output="output",
            model_id="claude-sonnet-4",
            provider="plan",
            cost_usd=0.0,
        ))
        tracker.record("code", StageResult(
            stage_name="code",
            output="output",
            model_id="qwen/qwen3-coder-next",
            provider="openrouter",
            cost_usd=0.05,
        ))

        summary = tracker.summary()
        records = summary["records"]
        assert records[0]["provider"] == "plan"
        assert records[1]["provider"] == "openrouter"


class TestErrorPropagation:
    """Non-zero exit codes and error results should propagate correctly."""

    def test_run_result_nonzero_exit(self):
        """Non-zero exit code should be preserved in RunResult."""
        result = RunResult(exit_code=1, stdout="error output", stderr="failed")
        assert result.exit_code == 1
        assert result.stderr == "failed"

    def test_stage_result_failure(self):
        """Failed stage result should have success=False."""
        result = StageResult(
            stage_name="code",
            output="",
            success=False,
            model_id="qwen/qwen3-coder-next",
            provider="openrouter",
        )
        assert not result.success

    def test_stage_result_defaults_to_success(self):
        """StageResult should default to success=True."""
        result = StageResult(stage_name="plan", output="plan")
        assert result.success is True

    def test_run_result_timeout_pattern(self):
        """Timeout pattern should produce exit_code=-1 and descriptive stderr."""
        result = RunResult(
            exit_code=-1,
            stdout="",
            stderr="Docker container timed out after 600 seconds",
        )
        assert result.exit_code == -1
        assert "timed out" in result.stderr


class TestConfigLoadAndValidation:
    """Config loading should handle all provider types."""

    def test_load_config_with_plan_provider(self, tmp_path):
        """Config with plan provider should load without warnings."""
        config_yaml = tmp_path / "test.yaml"
        config_yaml.write_text("""
name: test-plan
models:
  sonnet-p:
    provider: plan
    model_id: claude-sonnet-4
    api_key_env: ""
stages:
  - name: code
    model: sonnet-p
    prompt_file: prompts/code.txt
""", encoding="utf-8")

        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(str(config_yaml))

        assert config.models["sonnet-p"].provider == "plan"
        assert config.models["sonnet-p"].api_key_env == ""
        # No warnings about missing API keys for plan provider
        api_warnings = [x for x in w if "api_key_env" in str(x.message).lower()
                        or "not currently set" in str(x.message).lower()]
        assert len(api_warnings) == 0

    def test_load_config_with_anthropic_provider(self, tmp_path):
        """Config with anthropic provider should load correctly."""
        config_yaml = tmp_path / "test.yaml"
        config_yaml.write_text("""
name: test-anthropic
models:
  sonnet-a:
    provider: anthropic
    model_id: claude-sonnet-4
    api_key_env: ANTHROPIC_API_KEY
stages:
  - name: code
    model: sonnet-a
    prompt_file: prompts/code.txt
""", encoding="utf-8")

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            config = load_config(str(config_yaml))

        assert config.models["sonnet-a"].provider == "anthropic"
        assert config.models["sonnet-a"].api_key_env == "ANTHROPIC_API_KEY"

    def test_load_config_mixed_providers(self, tmp_path):
        """Config with mixed providers should load all correctly."""
        config_yaml = tmp_path / "test.yaml"
        config_yaml.write_text("""
name: test-mixed
models:
  qwen:
    provider: openrouter
    model_id: qwen/qwen3-coder-next
    api_key_env: OPENROUTER_API_KEY
  sonnet-p:
    provider: plan
    model_id: claude-sonnet-4
    api_key_env: ""
  opus-a:
    provider: anthropic
    model_id: claude-opus-4-6
    api_key_env: ANTHROPIC_API_KEY
stages:
  - name: plan
    model: sonnet-p
    prompt_file: prompts/plan.txt
  - name: code
    model: qwen
    prompt_file: prompts/code.txt
  - name: review
    model: opus-a
    prompt_file: prompts/review.txt
""", encoding="utf-8")

        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "sk-or-test",
            "ANTHROPIC_API_KEY": "sk-ant-test",
        }):
            config = load_config(str(config_yaml))

        assert len(config.models) == 3
        assert len(config.stages) == 3
        assert config.models["qwen"].provider == "openrouter"
        assert config.models["sonnet-p"].provider == "plan"
        assert config.models["opus-a"].provider == "anthropic"
