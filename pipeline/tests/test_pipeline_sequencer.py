"""Tests for Pipeline sequencer: review checking, state routing, stage selection."""

import pytest

from osq.core.config import (
    DockerConfig,
    FanoutConfig,
    ModelConfig,
    PipelineConfig,
    ReviewConfig,
    StageConfig,
)
from osq.core.errors import ReviewRejectedError, StageError
from osq.models.registry import ModelRegistry
from osq.pipeline.pipeline import Pipeline
from osq.pipeline.result import StageResult
from osq.pipeline.state import PipelineState
from osq.runners.base import BaseRunner
from osq.pipeline.result import RunResult


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
