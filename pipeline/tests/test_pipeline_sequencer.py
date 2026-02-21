"""Tests for Pipeline sequencer: review checking, state routing, stage selection."""

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
)
from cloding.core.errors import ReviewRejectedError, StageError
from cloding.models.registry import ModelRegistry
from cloding.pipeline.pipeline import Pipeline
from cloding.pipeline.result import StageResult, VerifyAgentResult
from cloding.pipeline.state import PipelineState
from cloding.runners.base import BaseRunner
from cloding.pipeline.result import RunResult


class FakeRunner(BaseRunner):
    """Fake runner that returns canned results."""

    def __init__(self, results=None):
        self.results = results or []
        self.call_count = 0

    async def run(self, env, cli_args, timeout):
        if self.call_count < len(self.results):
            result = self.results[self.call_count]
        else:
            result = RunResult(exit_code=0, stdout="ok", stderr="")
        self.call_count += 1
        return result


def _make_config(**kwargs):
    defaults = dict(
        name="test",
        models={
            "qwen": ModelConfig(
                name="qwen",
                provider="openrouter",
                model_id="qwen/qwen3-coder-next",
                api_key_env="OPENROUTER_API_KEY",
                cost_per_mtok_input=0.07,
                cost_per_mtok_output=0.30,
            ),
        },
        stages=[
            StageConfig(name="plan", model="qwen", prompt_file="prompts/plan.txt"),
            StageConfig(name="code", model="qwen", prompt_file="prompts/code.txt"),
        ],
        fanout=FanoutConfig(),
        review=ReviewConfig(max_iterations=2, pass_threshold="PASS"),
        docker=DockerConfig(),
    )
    defaults.update(kwargs)
    return PipelineConfig(**defaults)


class TestCheckReview:
    """Test the _check_review method of Pipeline."""

    def _make_pipeline(self):
        config = _make_config()
        runner = FakeRunner()
        return Pipeline(config=config, runner=runner, prompts_dir="/nonexistent")

    def test_pass_at_start(self):
        pipe = self._make_pipeline()
        state = PipelineState(user_request="test")
        result = pipe._check_review("PASS\nLooks great", state)
        assert result is True
        assert state.review_passed is True

    def test_fail_at_start(self):
        pipe = self._make_pipeline()
        state = PipelineState(user_request="test")
        result = pipe._check_review("FAIL\nMissing tests", state)
        assert result is False
        assert state.review_passed is False
        assert state.review_iteration == 1

    def test_pass_in_body_markdown(self):
        pipe = self._make_pipeline()
        state = PipelineState(user_request="test")
        result = pipe._check_review("## Review Result\n\n**PASS**\n\nCode looks good.", state)
        assert result is True

    def test_fail_in_body(self):
        pipe = self._make_pipeline()
        state = PipelineState(user_request="test")
        result = pipe._check_review("## Review\n\nFAIL: Missing error handling", state)
        assert result is False
        assert "Missing error handling" in state.review_feedback

    def test_pass_and_fail_both_present_but_starts_with_pass(self):
        pipe = self._make_pipeline()
        state = PipelineState(user_request="test")
        # Starts with PASS -> startswith check wins immediately
        result = pipe._check_review("PASS on tests, but FAIL on coverage", state)
        assert result is True

    def test_pass_and_fail_both_in_body_treats_as_fail(self):
        pipe = self._make_pipeline()
        state = PipelineState(user_request="test")
        # PASS and FAIL both present in body (not starting with PASS) -> fail
        result = pipe._check_review("## Review\n\nPASS on tests, but FAIL on coverage", state)
        assert result is False

    def test_no_verdict_treats_as_fail(self):
        pipe = self._make_pipeline()
        state = PipelineState(user_request="test")
        result = pipe._check_review("The code needs more work.", state)
        assert result is False

    def test_case_insensitive(self):
        pipe = self._make_pipeline()
        state = PipelineState(user_request="test")
        result = pipe._check_review("pass - all good", state)
        assert result is True

    def test_verdict_pass_colon_format(self):
        pipe = self._make_pipeline()
        state = PipelineState(user_request="test")
        result = pipe._check_review("Verdict: PASS", state)
        assert result is True


class TestUpdateState:
    def _make_pipeline(self):
        config = _make_config()
        return Pipeline(config=config, runner=FakeRunner(), prompts_dir="/nonexistent")

    def test_plan_output(self):
        pipe = self._make_pipeline()
        state = PipelineState(user_request="test")
        result = StageResult(stage_name="plan", output="the plan")
        pipe._update_state(state, "plan", result)
        assert state.plan_output == "the plan"

    def test_explore_output(self):
        pipe = self._make_pipeline()
        state = PipelineState(user_request="test")
        result = StageResult(stage_name="explore", output="explored context")
        pipe._update_state(state, "explore", result)
        assert state.exploration_output == "explored context"

    def test_code_output_appends(self):
        pipe = self._make_pipeline()
        state = PipelineState(user_request="test")
        pipe._update_state(state, "code", StageResult(stage_name="code", output="code1"))
        pipe._update_state(state, "code", StageResult(stage_name="code", output="code2"))
        assert state.code_outputs == ["code1", "code2"]

    def test_review_does_not_route(self):
        pipe = self._make_pipeline()
        state = PipelineState(user_request="test")
        pipe._update_state(state, "review", StageResult(stage_name="review", output="PASS"))
        # Review output is handled by _check_review, not _update_state
        assert state.plan_output == ""


class TestGetStagesToRun:
    def test_all_stages(self):
        config = _make_config()
        pipe = Pipeline(config=config, runner=FakeRunner(), prompts_dir="/nonexistent")
        state = PipelineState(user_request="test")
        stages = pipe._get_stages_to_run(state)
        assert [s.name for s in stages] == ["plan", "code"]

    def test_resume_from_code(self):
        config = _make_config()
        config.resume_from_stage = "code"
        pipe = Pipeline(config=config, runner=FakeRunner(), prompts_dir="/nonexistent")
        state = PipelineState(user_request="test")
        stages = pipe._get_stages_to_run(state)
        assert [s.name for s in stages] == ["code"]

    def test_resume_from_invalid_stage(self):
        config = _make_config()
        config.resume_from_stage = "nonexistent"
        pipe = Pipeline(config=config, runner=FakeRunner(), prompts_dir="/nonexistent")
        state = PipelineState(user_request="test")
        with pytest.raises(StageError, match="not found"):
            pipe._get_stages_to_run(state)


class TestFindStageConfig:
    def test_found(self):
        pipe = Pipeline(
            config=_make_config(), runner=FakeRunner(), prompts_dir="/nonexistent"
        )
        assert pipe._find_stage_config("plan") is not None
        assert pipe._find_stage_config("plan").name == "plan"

    def test_not_found(self):
        pipe = Pipeline(
            config=_make_config(), runner=FakeRunner(), prompts_dir="/nonexistent"
        )
        assert pipe._find_stage_config("missing") is None


class TestGenerateRunId:
    def test_format(self):
        run_id = Pipeline._generate_run_id()
        # Format: YYYYMMDD-HHMMSS-hexhex
        parts = run_id.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 8  # date
        assert len(parts[1]) == 6  # time
        assert len(parts[2]) == 6  # short uuid

    def test_unique(self):
        ids = {Pipeline._generate_run_id() for _ in range(10)}
        assert len(ids) == 10  # all unique


@pytest.mark.asyncio(loop_scope="function")
class TestPipelineRun:
    """Test the full Pipeline.run() method."""

    async def test_run_success_two_stages(self, tmp_path):
        """Run a simple 2-stage pipeline (plan+code) to completion."""
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="The plan", stderr=""),
            RunResult(exit_code=0, stdout="Code written", stderr=""),
        ])
        config = _make_config()
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        result = await pipe.run(user_request="Add auth")
        assert result.success is True
        assert len(result.stage_results) == 2
        assert runner.call_count == 2

    async def test_run_stage_failure_stops_pipeline(self, tmp_path):
        """A failing stage should stop the pipeline and return failure."""
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="The plan", stderr=""),
            RunResult(exit_code=1, stdout="", stderr="error occurred"),
        ])
        config = _make_config()
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        result = await pipe.run(user_request="test")
        assert result.success is False
        assert "failed" in result.error.lower()
        assert len(result.stage_results) == 2

    async def test_run_with_review_pass(self, tmp_path):
        """Pipeline with review stage that passes immediately."""
        stages = [
            StageConfig(name="plan", model="qwen", prompt_file="prompts/plan.txt"),
            StageConfig(name="code", model="qwen", prompt_file="prompts/code.txt"),
            StageConfig(name="review", model="qwen", prompt_file="prompts/review.txt"),
        ]
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="plan", stderr=""),
            RunResult(exit_code=0, stdout="code", stderr=""),
            RunResult(exit_code=0, stdout="PASS\nAll good", stderr=""),
        ])
        config = _make_config(stages=stages)
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        result = await pipe.run(user_request="test")
        assert result.success is True
        assert result.review_passed is True
        assert runner.call_count == 3

    async def test_run_with_review_fail_then_pass(self, tmp_path):
        """Review fails, code re-runs, then review passes."""
        stages = [
            StageConfig(name="plan", model="qwen", prompt_file="prompts/plan.txt"),
            StageConfig(name="code", model="qwen", prompt_file="prompts/code.txt"),
            StageConfig(name="review", model="qwen", prompt_file="prompts/review.txt"),
        ]
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="plan", stderr=""),
            RunResult(exit_code=0, stdout="code v1", stderr=""),
            RunResult(exit_code=0, stdout="FAIL\nNeeds tests", stderr=""),
            RunResult(exit_code=0, stdout="code v2", stderr=""),
            RunResult(exit_code=0, stdout="PASS\nAll fixed", stderr=""),
        ])
        config = _make_config(stages=stages)
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        result = await pipe.run(user_request="test")
        assert result.success is True
        assert result.review_passed is True
        assert runner.call_count == 5

    async def test_run_review_max_iterations_exceeded(self, tmp_path):
        """Review fails beyond max_iterations → ReviewRejectedError."""
        stages = [
            StageConfig(name="plan", model="qwen", prompt_file="prompts/plan.txt"),
            StageConfig(name="code", model="qwen", prompt_file="prompts/code.txt"),
            StageConfig(name="review", model="qwen", prompt_file="prompts/review.txt"),
        ]
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="plan", stderr=""),
            RunResult(exit_code=0, stdout="code", stderr=""),
            RunResult(exit_code=0, stdout="FAIL\nBad code", stderr=""),
            RunResult(exit_code=0, stdout="code v2", stderr=""),
            RunResult(exit_code=0, stdout="FAIL\nStill bad", stderr=""),
        ])
        config = _make_config(
            stages=stages,
            review=ReviewConfig(max_iterations=2, pass_threshold="PASS"),
        )
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        result = await pipe.run(user_request="test")
        assert result.success is False
        assert "did not pass review" in result.error.lower()

    async def test_run_saves_checkpoints(self, tmp_path):
        """Pipeline should save checkpoint after each stage."""
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="plan output", stderr=""),
            RunResult(exit_code=0, stdout="code output", stderr=""),
        ])
        config = _make_config()
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        result = await pipe.run(user_request="test")
        assert result.success is True
        checkpoint_files = list(tmp_path.rglob("state.json"))
        assert len(checkpoint_files) == 1

    async def test_run_with_resume_state(self, tmp_path):
        """Pipeline should accept a resume_state to continue from."""
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="plan", stderr=""),
            RunResult(exit_code=0, stdout="code", stderr=""),
        ])
        config = _make_config()
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        resume = PipelineState(user_request="test", run_id="existing-run")
        result = await pipe.run(user_request="ignored", resume_state=resume)
        assert result.success is True
        assert result.run_id == "existing-run"

    async def test_run_fanout_no_plan_md_raises(self, tmp_path):
        """Fan-out without PLAN.md in workspace should raise StageError."""
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="plan", stderr=""),
        ])
        config = _make_config(
            stages=[
                StageConfig(name="plan", model="qwen", prompt_file="prompts/plan.txt"),
                StageConfig(name="code", model="qwen", prompt_file="prompts/code.txt"),
            ],
            fanout=FanoutConfig(enabled=True, max_parallel=2),
        )
        config.workspace_path = str(tmp_path)
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path / "data"))
        result = await pipe.run(user_request="test")
        assert result.success is False
        assert "PLAN.md" in result.error

    async def test_run_fanout_with_plan_md(self, tmp_path):
        """Fan-out should split PLAN.md into tasks and run them."""
        plan_md = tmp_path / "PLAN.md"
        plan_md.write_text("""# Plan
### Task 1: Add login
- **Description**: Implement login page
- **Files**: `auth.py`, `views.py`
- **Priority**: 1

### Task 2: Add tests
- **Description**: Write unit tests
- **Files**: `test_auth.py`
- **Priority**: 2
""", encoding="utf-8")

        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="plan done", stderr=""),
            RunResult(exit_code=0, stdout="task 1 done", stderr=""),
            RunResult(exit_code=0, stdout="task 2 done", stderr=""),
        ])
        config = _make_config(
            stages=[
                StageConfig(name="plan", model="qwen", prompt_file="prompts/plan.txt"),
                StageConfig(name="code", model="qwen", prompt_file="prompts/code.txt"),
            ],
            fanout=FanoutConfig(enabled=True, max_parallel=2),
        )
        config.workspace_path = str(tmp_path)
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path / "data"))
        result = await pipe.run(user_request="test")
        assert result.success is True
        assert runner.call_count >= 2


class TestCheckQualityGate:
    """Test the _check_quality_gate method of Pipeline."""

    def _make_pipeline(self):
        config = _make_config()
        runner = FakeRunner()
        return Pipeline(config=config, runner=runner, prompts_dir="/nonexistent")

    def test_pass_at_start(self):
        pipe = self._make_pipeline()
        assert pipe._check_quality_gate("PASS\nAll tests pass", "test") is True

    def test_fail_at_start(self):
        pipe = self._make_pipeline()
        assert pipe._check_quality_gate("FAIL\n3 tests failing", "test") is False

    def test_pass_in_tail(self):
        pipe = self._make_pipeline()
        output = "Running tests...\n" * 30 + "\nPASS\nAll 42 tests passed."
        assert pipe._check_quality_gate(output, "test") is True

    def test_fail_in_tail(self):
        pipe = self._make_pipeline()
        output = "Running linters...\n" * 30 + "\nFAIL\n2 violations remain."
        assert pipe._check_quality_gate(output, "lint") is False

    def test_pass_markdown_wrapped(self):
        pipe = self._make_pipeline()
        output = "## Lint Results\n\n**PASS**\n\nAll clean."
        assert pipe._check_quality_gate(output, "lint") is True

    def test_no_verdict_returns_false(self):
        pipe = self._make_pipeline()
        output = "Ran some checks. Everything seems fine but no verdict."
        assert pipe._check_quality_gate(output, "test") is False

    def test_pass_case_insensitive(self):
        pipe = self._make_pipeline()
        assert pipe._check_quality_gate("pass - all good", "test") is True

    def test_empty_output_returns_false(self):
        pipe = self._make_pipeline()
        assert pipe._check_quality_gate("", "test") is False

    def test_whitespace_only_returns_false(self):
        pipe = self._make_pipeline()
        assert pipe._check_quality_gate("   \n  \n  ", "lint") is False


@pytest.mark.asyncio(loop_scope="function")
class TestPipelineRunWithQualityGates:
    """Test full pipeline execution with test/lint quality gates."""

    async def test_run_with_test_stage_pass(self, tmp_path):
        """Pipeline with test stage that passes."""
        stages = [
            StageConfig(name="plan", model="qwen", prompt_file="prompts/plan.txt"),
            StageConfig(name="code", model="qwen", prompt_file="prompts/code.txt"),
            StageConfig(name="test", model="qwen", prompt_file="prompts/test.txt"),
        ]
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="plan", stderr=""),
            RunResult(exit_code=0, stdout="code", stderr=""),
            RunResult(exit_code=0, stdout="PASS\nAll tests pass", stderr=""),
        ])
        config = _make_config(stages=stages)
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        result = await pipe.run(user_request="test")
        assert result.success is True
        assert len(result.stage_results) == 3
        assert runner.call_count == 3

    async def test_run_with_test_stage_fail_continues(self, tmp_path):
        """Pipeline with failing test stage continues (quality gates are informational)."""
        stages = [
            StageConfig(name="plan", model="qwen", prompt_file="prompts/plan.txt"),
            StageConfig(name="code", model="qwen", prompt_file="prompts/code.txt"),
            StageConfig(name="test", model="qwen", prompt_file="prompts/test.txt"),
            StageConfig(name="review", model="qwen", prompt_file="prompts/review.txt"),
        ]
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="plan", stderr=""),
            RunResult(exit_code=0, stdout="code", stderr=""),
            RunResult(exit_code=0, stdout="FAIL\n2 tests still failing", stderr=""),
            RunResult(exit_code=0, stdout="PASS\nCode looks good", stderr=""),
        ])
        config = _make_config(stages=stages)
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        result = await pipe.run(user_request="test")
        assert result.success is True
        assert len(result.stage_results) == 4

    async def test_run_with_lint_stage(self, tmp_path):
        """Pipeline with lint stage."""
        stages = [
            StageConfig(name="plan", model="qwen", prompt_file="prompts/plan.txt"),
            StageConfig(name="code", model="qwen", prompt_file="prompts/code.txt"),
            StageConfig(name="lint", model="qwen", prompt_file="prompts/lint.txt"),
        ]
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="plan", stderr=""),
            RunResult(exit_code=0, stdout="code", stderr=""),
            RunResult(exit_code=0, stdout="PASS\nAll clean", stderr=""),
        ])
        config = _make_config(stages=stages)
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        result = await pipe.run(user_request="test")
        assert result.success is True

    async def test_run_full_pipeline_with_quality_gates(self, tmp_path):
        """Full pipeline: plan → code → test → lint → review."""
        stages = [
            StageConfig(name="plan", model="qwen", prompt_file="prompts/plan.txt"),
            StageConfig(name="code", model="qwen", prompt_file="prompts/code.txt"),
            StageConfig(name="test", model="qwen", prompt_file="prompts/test.txt"),
            StageConfig(name="lint", model="qwen", prompt_file="prompts/lint.txt"),
            StageConfig(name="review", model="qwen", prompt_file="prompts/review.txt"),
        ]
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="plan", stderr=""),
            RunResult(exit_code=0, stdout="code", stderr=""),
            RunResult(exit_code=0, stdout="PASS\nAll 42 tests pass", stderr=""),
            RunResult(exit_code=0, stdout="PASS\nNo lint issues", stderr=""),
            RunResult(exit_code=0, stdout="PASS\nCode approved", stderr=""),
        ])
        config = _make_config(stages=stages)
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        result = await pipe.run(user_request="test")
        assert result.success is True
        assert result.review_passed is True
        assert len(result.stage_results) == 5
        assert runner.call_count == 5


@pytest.mark.asyncio(loop_scope="function")
class TestReviewLoop:
    """Test the _review_loop method specifically."""

    async def test_review_loop_code_rework_fails(self, tmp_path):
        """If code rework fails, review loop should raise StageError."""
        stages = [
            StageConfig(name="code", model="qwen", prompt_file="prompts/code.txt"),
            StageConfig(name="review", model="qwen", prompt_file="prompts/review.txt"),
        ]
        runner = FakeRunner(results=[
            RunResult(exit_code=1, stdout="", stderr="code failed"),
        ])
        config = _make_config(stages=stages)
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        state = PipelineState(
            user_request="test",
            review_feedback="Fix the bug",
            review_iteration=0,
        )
        with pytest.raises(StageError, match="Code rework.*failed"):
            await pipe._review_loop(state, tmp_path)

    async def test_review_loop_review_rework_fails(self, tmp_path):
        """If re-review fails, review loop should raise StageError."""
        stages = [
            StageConfig(name="code", model="qwen", prompt_file="prompts/code.txt"),
            StageConfig(name="review", model="qwen", prompt_file="prompts/review.txt"),
        ]
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="fixed code", stderr=""),
            RunResult(exit_code=1, stdout="", stderr="review error"),
        ])
        config = _make_config(stages=stages)
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        state = PipelineState(
            user_request="test",
            review_feedback="Fix it",
            review_iteration=0,
        )
        with pytest.raises(StageError, match="Review iteration.*failed"):
            await pipe._review_loop(state, tmp_path)

    async def test_review_loop_no_code_stage_raises(self, tmp_path):
        """Review loop without code stage config should raise StageError."""
        stages = [
            StageConfig(name="review", model="qwen", prompt_file="prompts/review.txt"),
        ]
        runner = FakeRunner()
        config = _make_config(stages=stages)
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        state = PipelineState(
            user_request="test",
            review_feedback="Fix it",
            review_iteration=0,
        )
        with pytest.raises(StageError, match="No 'code' stage"):
            await pipe._review_loop(state, tmp_path)

    async def test_review_loop_no_review_stage_raises(self, tmp_path):
        """Review loop without review stage config should raise StageError."""
        stages = [
            StageConfig(name="code", model="qwen", prompt_file="prompts/code.txt"),
        ]
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="code", stderr=""),
        ])
        config = _make_config(stages=stages)
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        state = PipelineState(
            user_request="test",
            review_feedback="Fix it",
            review_iteration=0,
        )
        with pytest.raises(StageError, match="No 'review' stage"):
            await pipe._review_loop(state, tmp_path)


# --- Multi-agent verification tests ---


def _make_verify_config(
    agents=None,
    enabled=True,
    consensus_threshold=0.67,
    max_iterations=3,
    **config_kwargs,
):
    """Create a PipelineConfig with verify settings."""
    if agents is None:
        agents = [
            VerifyAgentConfig(model="qwen", prompt_file="prompts/verify.txt"),
        ]
    verify = VerifyConfig(
        enabled=enabled,
        agents=agents,
        consensus_threshold=consensus_threshold,
        max_iterations=max_iterations,
    )
    return _make_config(verify=verify, **config_kwargs)


class TestCheckVerifyVerdict:
    """Test the _check_verify_verdict method of Pipeline."""

    def _make_pipeline(self):
        config = _make_config()
        runner = FakeRunner()
        return Pipeline(config=config, runner=runner, prompts_dir="/nonexistent")

    def test_pass_at_start(self):
        pipe = self._make_pipeline()
        assert pipe._check_verify_verdict("PASS\nAll checks passed.") is True

    def test_fail_at_start(self):
        pipe = self._make_pipeline()
        assert pipe._check_verify_verdict("FAIL\nMissing tests.") is False

    def test_pass_in_tail(self):
        pipe = self._make_pipeline()
        output = "Reviewing...\n" * 30 + "\nPASS\nAll verified."
        assert pipe._check_verify_verdict(output) is True

    def test_fail_in_tail(self):
        pipe = self._make_pipeline()
        output = "Checking code...\n" * 30 + "\nFAIL\n2 issues found."
        assert pipe._check_verify_verdict(output) is False

    def test_pass_markdown(self):
        pipe = self._make_pipeline()
        assert pipe._check_verify_verdict("## Result\n\n**PASS**\n\nLooks good.") is True

    def test_fail_markdown(self):
        pipe = self._make_pipeline()
        assert pipe._check_verify_verdict("## Result\n\n**FAIL**\n\nBad code.") is False

    def test_empty_output_returns_false(self):
        pipe = self._make_pipeline()
        assert pipe._check_verify_verdict("") is False

    def test_whitespace_only_returns_false(self):
        pipe = self._make_pipeline()
        assert pipe._check_verify_verdict("   \n  \n  ") is False

    def test_no_verdict_returns_false(self):
        pipe = self._make_pipeline()
        assert pipe._check_verify_verdict("The code needs more work.") is False

    def test_case_insensitive(self):
        pipe = self._make_pipeline()
        assert pipe._check_verify_verdict("pass - all good") is True

    def test_pass_and_fail_in_body_prefers_tail(self):
        pipe = self._make_pipeline()
        # FAIL in tail should win
        output = "Some PASS here.\n" * 5 + "\nFAIL: issues found."
        assert pipe._check_verify_verdict(output) is False

    def test_pass_colon_format(self):
        pipe = self._make_pipeline()
        assert pipe._check_verify_verdict("Verdict: PASS") is True


@pytest.mark.asyncio(loop_scope="function")
class TestRunVerifyAgents:
    """Test _run_verify_agents: parallel execution of verification agents."""

    async def test_single_agent_pass(self, tmp_path):
        """One verify agent that passes."""
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="PASS\nAll good", stderr=""),
        ])
        config = _make_verify_config(
            agents=[VerifyAgentConfig(model="qwen")],
        )
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        state = PipelineState(user_request="test")
        results = await pipe._run_verify_agents(state)
        assert len(results) == 1
        assert results[0].passed is True
        assert results[0].model == "qwen/qwen3-coder-next"

    async def test_single_agent_fail(self, tmp_path):
        """One verify agent that fails."""
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="FAIL\nMissing tests", stderr=""),
        ])
        config = _make_verify_config(
            agents=[VerifyAgentConfig(model="qwen")],
        )
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        state = PipelineState(user_request="test")
        results = await pipe._run_verify_agents(state)
        assert len(results) == 1
        assert results[0].passed is False
        assert results[0].feedback != ""

    async def test_multiple_agents(self, tmp_path):
        """Multiple agents run in parallel."""
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="PASS\nAgent 1 ok", stderr=""),
            RunResult(exit_code=0, stdout="PASS\nAgent 2 ok", stderr=""),
            RunResult(exit_code=0, stdout="FAIL\nAgent 3 found issues", stderr=""),
        ])
        config = _make_verify_config(
            agents=[
                VerifyAgentConfig(model="qwen"),
                VerifyAgentConfig(model="qwen"),
                VerifyAgentConfig(model="qwen"),
            ],
        )
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        state = PipelineState(user_request="test")
        results = await pipe._run_verify_agents(state)
        assert len(results) == 3
        passes = sum(1 for r in results if r.passed)
        assert passes == 2

    async def test_agent_exception_handled(self, tmp_path):
        """Agent that raises exception should be caught and marked as failed."""
        runner = FakeRunner(results=[
            RunResult(exit_code=1, stdout="", stderr="crash"),
        ])
        config = _make_verify_config(
            agents=[VerifyAgentConfig(model="qwen")],
        )
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        state = PipelineState(user_request="test")
        # Stage fails (exit_code=1) but doesn't throw an exception from gather
        # The agent runs and produces a result with "no output"
        results = await pipe._run_verify_agents(state)
        assert len(results) == 1


@pytest.mark.asyncio(loop_scope="function")
class TestRunVerification:
    """Test _run_verification: the full verify loop with consensus and re-code."""

    async def test_consensus_pass_first_round(self, tmp_path):
        """All agents pass on first round → consensus immediately."""
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="PASS\nok", stderr=""),
            RunResult(exit_code=0, stdout="PASS\nok", stderr=""),
        ])
        config = _make_verify_config(
            agents=[
                VerifyAgentConfig(model="qwen"),
                VerifyAgentConfig(model="qwen"),
            ],
            consensus_threshold=0.5,
        )
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        state = PipelineState(user_request="test")
        results, consensus = await pipe._run_verification(state, [], tmp_path)
        assert consensus is True
        assert len(results) == 2

    async def test_consensus_fail_max_iterations(self, tmp_path):
        """All agents fail every round → consensus=False after max_iterations."""
        # With max_iterations=2 and 1 agent: round 1 fail + recode + round 2 fail
        runner = FakeRunner(results=[
            # Round 1: verify agent fails
            RunResult(exit_code=0, stdout="FAIL\nBad code", stderr=""),
            # Re-code
            RunResult(exit_code=0, stdout="fixed code", stderr=""),
            # Round 2: verify agent still fails
            RunResult(exit_code=0, stdout="FAIL\nStill bad", stderr=""),
        ])
        config = _make_verify_config(
            agents=[VerifyAgentConfig(model="qwen")],
            consensus_threshold=1.0,
            max_iterations=2,
            stages=[
                StageConfig(name="code", model="qwen", prompt_file="prompts/code.txt"),
            ],
        )
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        state = PipelineState(user_request="test")
        results, consensus = await pipe._run_verification(state, [], tmp_path)
        assert consensus is False

    async def test_consensus_threshold_met(self, tmp_path):
        """2 of 3 agents pass with threshold=0.67 → consensus."""
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="PASS\nok", stderr=""),
            RunResult(exit_code=0, stdout="PASS\nok", stderr=""),
            RunResult(exit_code=0, stdout="FAIL\nnope", stderr=""),
        ])
        config = _make_verify_config(
            agents=[
                VerifyAgentConfig(model="qwen"),
                VerifyAgentConfig(model="qwen"),
                VerifyAgentConfig(model="qwen"),
            ],
            consensus_threshold=0.67,
        )
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        state = PipelineState(user_request="test")
        results, consensus = await pipe._run_verification(state, [], tmp_path)
        assert consensus is True

    async def test_consensus_threshold_not_met(self, tmp_path):
        """1 of 3 agents pass with threshold=0.67 → no consensus, triggers re-code."""
        # max_iterations=1 so only 1 round, no re-code
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="PASS\nok", stderr=""),
            RunResult(exit_code=0, stdout="FAIL\nnope", stderr=""),
            RunResult(exit_code=0, stdout="FAIL\nalso nope", stderr=""),
        ])
        config = _make_verify_config(
            agents=[
                VerifyAgentConfig(model="qwen"),
                VerifyAgentConfig(model="qwen"),
                VerifyAgentConfig(model="qwen"),
            ],
            consensus_threshold=0.67,
            max_iterations=1,
        )
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        state = PipelineState(user_request="test")
        results, consensus = await pipe._run_verification(state, [], tmp_path)
        assert consensus is False

    async def test_verify_disabled_skips(self, tmp_path):
        """Verification disabled should not run any agents."""
        runner = FakeRunner()
        config = _make_verify_config(enabled=False)
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        # Call run() and check that no verify agents were invoked
        result = await pipe.run(user_request="test")
        assert result.success is True
        assert result.verify_results == []
        assert result.verify_consensus is False

    async def test_verify_no_agents_skips(self, tmp_path):
        """Verification enabled but no agents configured should skip."""
        runner = FakeRunner()
        config = _make_verify_config(agents=[], enabled=True)
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        result = await pipe.run(user_request="test")
        assert result.success is True
        assert result.verify_results == []

    async def test_recode_failure_stops_verification(self, tmp_path):
        """If re-code fails during verify loop, verification should stop."""
        runner = FakeRunner(results=[
            # Round 1: verify fails
            RunResult(exit_code=0, stdout="FAIL\nBad", stderr=""),
            # Re-code fails
            RunResult(exit_code=1, stdout="", stderr="code error"),
        ])
        config = _make_verify_config(
            agents=[VerifyAgentConfig(model="qwen")],
            consensus_threshold=1.0,
            max_iterations=3,
            stages=[
                StageConfig(name="code", model="qwen", prompt_file="prompts/code.txt"),
            ],
        )
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        state = PipelineState(user_request="test")
        results, consensus = await pipe._run_verification(state, [], tmp_path)
        assert consensus is False

    async def test_no_code_stage_for_recode(self, tmp_path):
        """Verify loop without code stage should return failure instead of crashing."""
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="FAIL\nBad", stderr=""),
        ])
        config = _make_verify_config(
            agents=[VerifyAgentConfig(model="qwen")],
            consensus_threshold=1.0,
            max_iterations=3,
            stages=[
                StageConfig(name="review", model="qwen", prompt_file="prompts/review.txt"),
            ],
        )
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        state = PipelineState(user_request="test")
        results, consensus = await pipe._run_verification(state, [], tmp_path)
        assert consensus is False


@pytest.mark.asyncio(loop_scope="function")
class TestPipelineRunWithVerification:
    """Test full pipeline execution with multi-agent verification."""

    async def test_full_pipeline_with_verify_pass(self, tmp_path):
        """Full pipeline: plan → code → verify (pass)."""
        stages = [
            StageConfig(name="plan", model="qwen", prompt_file="prompts/plan.txt"),
            StageConfig(name="code", model="qwen", prompt_file="prompts/code.txt"),
        ]
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="plan", stderr=""),
            RunResult(exit_code=0, stdout="code", stderr=""),
            # Verify agents
            RunResult(exit_code=0, stdout="PASS\nAll good", stderr=""),
            RunResult(exit_code=0, stdout="PASS\nVerified", stderr=""),
        ])
        config = _make_verify_config(
            stages=stages,
            agents=[
                VerifyAgentConfig(model="qwen"),
                VerifyAgentConfig(model="qwen"),
            ],
            consensus_threshold=0.5,
        )
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        result = await pipe.run(user_request="test")
        assert result.success is True
        assert result.verify_consensus is True
        assert len(result.verify_results) == 2

    async def test_full_pipeline_with_verify_fail(self, tmp_path):
        """Full pipeline: plan → code → verify (fail, max_iterations=1)."""
        stages = [
            StageConfig(name="plan", model="qwen", prompt_file="prompts/plan.txt"),
            StageConfig(name="code", model="qwen", prompt_file="prompts/code.txt"),
        ]
        runner = FakeRunner(results=[
            RunResult(exit_code=0, stdout="plan", stderr=""),
            RunResult(exit_code=0, stdout="code", stderr=""),
            # Verify agents - both fail
            RunResult(exit_code=0, stdout="FAIL\nBad", stderr=""),
            RunResult(exit_code=0, stdout="FAIL\nAlso bad", stderr=""),
        ])
        config = _make_verify_config(
            stages=stages,
            agents=[
                VerifyAgentConfig(model="qwen"),
                VerifyAgentConfig(model="qwen"),
            ],
            consensus_threshold=1.0,
            max_iterations=1,
        )
        pipe = Pipeline(config=config, runner=runner, prompts_dir="/nonexistent",
                        data_dir=str(tmp_path))
        result = await pipe.run(user_request="test")
        # Pipeline still succeeds (verify is informational), but consensus is False
        assert result.success is True
        assert result.verify_consensus is False
        assert len(result.verify_results) == 2
