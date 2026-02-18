"""Tests for pipeline stages: build_env, build_cli_args, load_prompt, and stage types."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from cloding.core.config import ModelConfig, StageConfig
from cloding.pipeline.stage import (
    CodeStage,
    ExploreStage,
    PlanStage,
    ReviewStage,
    create_stage,
    STAGE_CLASSES,
)
from cloding.pipeline.state import PipelineState


def _make_model(**kwargs):
    defaults = dict(
        name="qwen",
        provider="openrouter",
        model_id="qwen/qwen3-coder-next",
        api_key_env="OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api",
        cost_per_mtok_input=0.07,
        cost_per_mtok_output=0.30,
    )
    defaults.update(kwargs)
    return ModelConfig(**defaults)


def _make_stage_config(**kwargs):
    defaults = dict(
        name="code",
        model="qwen",
        prompt_file="prompts/code.txt",
        max_turns=50,
        max_budget_usd=2.0,
        timeout_seconds=600,
        output_format="json",
    )
    defaults.update(kwargs)
    return StageConfig(**defaults)


class TestBuildEnv:
    def test_openrouter_env(self):
        stage = CodeStage(
            config=_make_stage_config(),
            model_config=_make_model(),
        )
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test-123"}):
            env = stage.build_env()

        assert env["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"
        assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-test-123"
        assert env["ANTHROPIC_API_KEY"] == ""
        assert env["ANTHROPIC_MODEL"] == "qwen/qwen3-coder-next"

    def test_anthropic_env(self):
        model = _make_model(
            name="sonnet", provider="anthropic",
            model_id="claude-sonnet-4-20250514",
            api_key_env="ANTHROPIC_API_KEY",
        )
        stage = CodeStage(config=_make_stage_config(), model_config=model)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-123"}):
            env = stage.build_env()

        assert "ANTHROPIC_BASE_URL" not in env
        assert env["ANTHROPIC_API_KEY"] == "sk-ant-123"
        assert env["ANTHROPIC_MODEL"] == "claude-sonnet-4-20250514"

    def test_missing_api_key_warns(self, caplog):
        stage = CodeStage(
            config=_make_stage_config(),
            model_config=_make_model(),
        )
        with patch.dict(os.environ, {}, clear=True):
            env = stage.build_env()
        # Should still produce env, just with empty token
        assert env["ANTHROPIC_AUTH_TOKEN"] == ""

    def test_base_url_fallback(self):
        model = _make_model(base_url=None)
        stage = CodeStage(config=_make_stage_config(), model_config=model)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "key"}):
            env = stage.build_env()
        assert env["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"


class TestBuildCliArgs:
    def test_basic_args(self):
        stage = CodeStage(
            config=_make_stage_config(),
            model_config=_make_model(),
        )
        args = stage.build_cli_args("Write some code")
        assert "-p" in args
        assert "Write some code" in args
        assert "--output-format" in args
        assert "json" in args
        assert "--max-turns" in args
        assert "--dangerously-skip-permissions" in args

    def test_allowed_tools(self):
        config = _make_stage_config(allowed_tools=["Read", "Write", "Bash"])
        stage = CodeStage(config=config, model_config=_make_model())
        args = stage.build_cli_args("prompt")
        assert "--allowedTools" in args
        idx = args.index("--allowedTools")
        assert args[idx + 1] == "Read,Write,Bash"

    def test_disallowed_tools(self):
        config = _make_stage_config(disallowed_tools=["Bash"])
        stage = CodeStage(config=config, model_config=_make_model())
        args = stage.build_cli_args("prompt")
        assert "--disallowedTools" in args
        idx = args.index("--disallowedTools")
        assert args[idx + 1] == "Bash"

    def test_no_tool_restrictions(self):
        config = _make_stage_config(allowed_tools=None, disallowed_tools=None)
        stage = CodeStage(config=config, model_config=_make_model())
        args = stage.build_cli_args("prompt")
        assert "--allowedTools" not in args
        assert "--disallowedTools" not in args


class TestLoadPrompt:
    def test_load_from_prompts_dir(self, tmp_path):
        prompt_file = tmp_path / "code.txt"
        prompt_file.write_text("You are a coder.", encoding="utf-8")
        config = _make_stage_config(prompt_file="prompts/code.txt")
        stage = CodeStage(config=config, model_config=_make_model(), prompts_dir=str(tmp_path))
        text = stage.load_prompt()
        assert text == "You are a coder."

    def test_load_fallback_path(self, tmp_path):
        # prompt_file itself is a valid path
        prompt_file = tmp_path / "custom.txt"
        prompt_file.write_text("Custom prompt", encoding="utf-8")
        config = _make_stage_config(prompt_file=str(prompt_file))
        stage = CodeStage(config=config, model_config=_make_model(), prompts_dir="/nonexistent")
        text = stage.load_prompt()
        assert text == "Custom prompt"

    def test_load_missing_prompt_returns_empty(self):
        config = _make_stage_config(prompt_file="prompts/missing.txt")
        stage = CodeStage(config=config, model_config=_make_model(), prompts_dir="/nonexistent")
        text = stage.load_prompt()
        assert text == ""


class TestCreateStage:
    def test_creates_plan_stage(self):
        config = _make_stage_config(name="plan")
        stage = create_stage(config, _make_model())
        assert isinstance(stage, PlanStage)

    def test_creates_explore_stage(self):
        config = _make_stage_config(name="explore")
        stage = create_stage(config, _make_model())
        assert isinstance(stage, ExploreStage)

    def test_creates_code_stage(self):
        config = _make_stage_config(name="code")
        stage = create_stage(config, _make_model())
        assert isinstance(stage, CodeStage)

    def test_creates_review_stage(self):
        config = _make_stage_config(name="review")
        stage = create_stage(config, _make_model())
        assert isinstance(stage, ReviewStage)

    def test_unknown_stage_raises(self):
        config = _make_stage_config(name="unknown")
        with pytest.raises(ValueError, match="Unknown stage type"):
            create_stage(config, _make_model())

    def test_stage_classes_registry(self):
        assert set(STAGE_CLASSES.keys()) == {"plan", "explore", "code", "review"}


@pytest.mark.asyncio(loop_scope="function")
class TestBuildPrompt:
    async def test_plan_stage_includes_request(self):
        config = _make_stage_config(name="plan", prompt_file="prompts/plan.txt")
        stage = PlanStage(config=config, model_config=_make_model(), prompts_dir="/nonexistent")
        state = PipelineState(user_request="Add auth", context_files=["auth.py"])
        prompt = await stage.build_prompt(state)
        assert "Add auth" in prompt
        assert "auth.py" in prompt

    async def test_explore_stage_includes_files(self):
        config = _make_stage_config(name="explore", prompt_file="prompts/explore.txt")
        stage = ExploreStage(config=config, model_config=_make_model(), prompts_dir="/nonexistent")
        state = PipelineState(user_request="test", context_files=["main.py", "utils.py"])
        prompt = await stage.build_prompt(state)
        assert "main.py" in prompt
        assert "utils.py" in prompt

    async def test_explore_stage_no_context_files(self):
        config = _make_stage_config(name="explore", prompt_file="prompts/explore.txt")
        stage = ExploreStage(config=config, model_config=_make_model(), prompts_dir="/nonexistent")
        state = PipelineState(user_request="test", context_files=None)
        prompt = await stage.build_prompt(state)
        assert "Key files to explore" not in prompt

    async def test_code_stage_with_review_feedback(self):
        config = _make_stage_config(name="code", prompt_file="prompts/code.txt")
        stage = CodeStage(config=config, model_config=_make_model(), prompts_dir="/nonexistent")
        state = PipelineState(
            user_request="test",
            review_feedback="Missing error handling",
            review_iteration=1,
        )
        prompt = await stage.build_prompt(state)
        assert "Missing error handling" in prompt
        assert "iteration 1" in prompt

    async def test_code_stage_no_feedback(self):
        config = _make_stage_config(name="code", prompt_file="prompts/code.txt")
        stage = CodeStage(config=config, model_config=_make_model(), prompts_dir="/nonexistent")
        state = PipelineState(user_request="test")
        prompt = await stage.build_prompt(state)
        # No dynamic feedback section should be appended
        assert "Previous review feedback" not in prompt

    async def test_review_stage_prompt(self):
        config = _make_stage_config(name="review", prompt_file="prompts/review.txt")
        stage = ReviewStage(config=config, model_config=_make_model(), prompts_dir="/nonexistent")
        state = PipelineState(user_request="test")
        prompt = await stage.build_prompt(state)
        assert "PLAN.md" in prompt
        assert "git diff" in prompt


# --- Tests for _make_result ---

from cloding.pipeline.result import RunResult
from cloding.models.registry import ModelRegistry


class TestMakeResult:
    def _stage(self, provider="openrouter", **model_kw):
        model = _make_model(provider=provider, **model_kw)
        config = _make_stage_config()
        return CodeStage(config=config, model_config=model)

    def test_openrouter_uses_registry_cost(self):
        """For OpenRouter, cost should come from registry, not RunResult."""
        stage = self._stage(provider="openrouter")
        run_result = RunResult(
            exit_code=0, stdout="ok", stderr="",
            tokens_in=1_000_000, tokens_out=500_000,
            cost_usd=99.99,  # inflated Anthropic price
        )
        registry = ModelRegistry({"qwen": _make_model()})
        result = stage._make_result(run_result, model_registry=registry)
        # Expected: 1M * 0.07/1M + 500K * 0.30/1M = 0.07 + 0.15 = 0.22
        assert abs(result.cost_usd - 0.22) < 0.001
        assert result.success is True

    def test_anthropic_uses_reported_cost(self):
        """For direct Anthropic, should use Claude Code's reported cost."""
        stage = self._stage(
            provider="anthropic",
            api_key_env="ANTHROPIC_API_KEY",
        )
        run_result = RunResult(
            exit_code=0, stdout="ok", stderr="",
            tokens_in=1000, tokens_out=500,
            cost_usd=0.05,
        )
        registry = ModelRegistry({"qwen": _make_model()})
        result = stage._make_result(run_result, model_registry=registry)
        assert result.cost_usd == 0.05  # uses reported cost

    def test_anthropic_fallback_when_zero_cost(self):
        """For direct Anthropic with zero cost, use registry estimation."""
        stage = self._stage(
            provider="anthropic",
            api_key_env="ANTHROPIC_API_KEY",
        )
        run_result = RunResult(
            exit_code=0, stdout="ok", stderr="",
            tokens_in=1_000_000, tokens_out=500_000,
            cost_usd=0.0,
        )
        registry = ModelRegistry({"qwen": _make_model()})
        result = stage._make_result(run_result, model_registry=registry)
        assert result.cost_usd > 0  # fallback estimation used

    def test_no_registry_uses_raw_cost(self):
        """Without a registry, should use the raw RunResult cost."""
        stage = self._stage()
        run_result = RunResult(
            exit_code=0, stdout="ok", stderr="",
            tokens_in=1000, tokens_out=500,
            cost_usd=0.42,
        )
        result = stage._make_result(run_result, model_registry=None)
        assert result.cost_usd == 0.42

    def test_no_tokens_skips_estimation(self):
        """With zero tokens, registry estimation should be skipped."""
        stage = self._stage()
        run_result = RunResult(
            exit_code=0, stdout="ok", stderr="",
            tokens_in=0, tokens_out=0,
            cost_usd=0.01,
        )
        registry = ModelRegistry({"qwen": _make_model()})
        result = stage._make_result(run_result, model_registry=registry)
        assert result.cost_usd == 0.01  # raw cost preserved

    def test_result_fields_populated(self):
        """All fields from RunResult should map to StageResult."""
        stage = self._stage()
        run_result = RunResult(
            exit_code=0, stdout="output text", stderr="",
            tokens_in=100, tokens_out=50,
            cost_usd=0.01, session_id="sess-1",
            num_turns=3, duration_ms=5000,
        )
        result = stage._make_result(run_result)
        assert result.stage_name == "code"
        assert result.output == "output text"
        assert result.tokens_in == 100
        assert result.tokens_out == 50
        assert result.session_id == "sess-1"
        assert result.num_turns == 3
        assert result.duration_ms == 5000
        assert result.model_id == "qwen/qwen3-coder-next"
        assert result.provider == "openrouter"

    def test_failure_exit_code(self):
        """Non-zero exit code should result in success=False."""
        stage = self._stage()
        run_result = RunResult(exit_code=1, stdout="", stderr="error")
        result = stage._make_result(run_result)
        assert result.success is False


# --- Tests for Stage.run() ---

from cloding.runners.base import BaseRunner


class FakeStageRunner(BaseRunner):
    """Simple runner that returns a pre-set RunResult."""

    def __init__(self, result: RunResult):
        self._result = result

    async def run(self, env, cli_args, timeout):
        return self._result


@pytest.mark.asyncio(loop_scope="function")
class TestStageRun:
    async def test_run_success(self):
        config = _make_stage_config()
        model = _make_model()
        stage = CodeStage(config=config, model_config=model, prompts_dir="/nonexistent")
        runner = FakeStageRunner(RunResult(
            exit_code=0, stdout="code written", stderr="",
            tokens_in=500, tokens_out=200,
        ))
        state = PipelineState(user_request="test")
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            result = await stage.run(runner=runner, state=state)
        assert result.success is True
        assert result.output == "code written"
        assert result.tokens_in == 500
        assert result.tokens_out == 200

    async def test_run_failure(self):
        config = _make_stage_config()
        model = _make_model()
        stage = CodeStage(config=config, model_config=model, prompts_dir="/nonexistent")
        runner = FakeStageRunner(RunResult(
            exit_code=1, stdout="", stderr="compile error",
        ))
        state = PipelineState(user_request="test")
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            result = await stage.run(runner=runner, state=state)
        assert result.success is False

    async def test_run_with_registry(self):
        config = _make_stage_config()
        model = _make_model()
        stage = CodeStage(config=config, model_config=model, prompts_dir="/nonexistent")
        runner = FakeStageRunner(RunResult(
            exit_code=0, stdout="ok", stderr="",
            tokens_in=1_000_000, tokens_out=500_000,
            cost_usd=99.0,  # inflated price
        ))
        registry = ModelRegistry({"qwen": model})
        state = PipelineState(user_request="test")
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            result = await stage.run(
                runner=runner, state=state, model_registry=registry
            )
        # Should use registry cost, not 99.0
        assert result.cost_usd < 1.0

    async def test_run_plan_stage(self):
        config = _make_stage_config(name="plan", prompt_file="prompts/plan.txt")
        model = _make_model()
        stage = PlanStage(config=config, model_config=model, prompts_dir="/nonexistent")
        runner = FakeStageRunner(RunResult(
            exit_code=0, stdout="the plan", stderr="",
        ))
        state = PipelineState(user_request="Add auth", context_files=["auth.py"])
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            result = await stage.run(runner=runner, state=state)
        assert result.success is True
        assert result.stage_name == "plan"
