"""Tests for pipeline sequencer, state, and result dataclasses."""

import json
from pathlib import Path

import pytest

from cloding.pipeline.result import PipelineResult, RunResult, StageResult
from cloding.pipeline.state import CodingTask, PipelineState


class TestRunResult:
    def test_defaults(self):
        r = RunResult(exit_code=0, stdout="hello", stderr="")
        assert r.tokens_in == 0
        assert r.cost_usd == 0.0
        assert r.session_id == ""

    def test_all_fields(self):
        r = RunResult(
            exit_code=0, stdout="ok", stderr="",
            tokens_in=100, tokens_out=50,
            session_id="abc", cost_usd=0.42,
            num_turns=3, duration_ms=5000,
        )
        assert r.tokens_in == 100
        assert r.cost_usd == 0.42


class TestStageResult:
    def test_defaults(self):
        r = StageResult(stage_name="plan", output="test")
        assert r.success is True
        assert r.cost_usd == 0.0

    def test_failed(self):
        r = StageResult(stage_name="code", output="error", success=False)
        assert r.success is False


class TestPipelineState:
    def test_add_stage_result(self):
        state = PipelineState(user_request="test")
        result = StageResult(
            stage_name="plan", output="ok",
            cost_usd=0.50, tokens_in=100, tokens_out=50,
            session_id="sess-1", model_id="opus",
        )
        state.add_stage_result(result)

        assert len(state.stage_results) == 1
        assert state.total_cost_usd == pytest.approx(0.50)
        assert state.session_ids["plan"] == "sess-1"

    def test_checkpoint_roundtrip(self, tmp_path: Path):
        state = PipelineState(
            user_request="add auth",
            plan_output="the plan",
            review_iteration=2,
            total_cost_usd=1.23,
            run_id="test-run",
        )
        checkpoint = tmp_path / "state.json"
        state.save_checkpoint(checkpoint)

        loaded = PipelineState.load_checkpoint(checkpoint)
        assert loaded.user_request == "add auth"
        assert loaded.plan_output == "the plan"
        assert loaded.review_iteration == 2
        assert loaded.total_cost_usd == pytest.approx(1.23)
        assert loaded.run_id == "test-run"

    def test_coding_tasks_roundtrip(self):
        state = PipelineState(user_request="test")
        tasks = [
            CodingTask(task_id="t1", description="Do X", files_to_modify=["a.py"]),
            CodingTask(task_id="t2", description="Do Y", priority=2),
        ]
        state.set_coding_tasks(tasks)

        recovered = state.get_coding_tasks()
        assert len(recovered) == 2
        assert recovered[0].task_id == "t1"
        assert recovered[0].files_to_modify == ["a.py"]
        assert recovered[1].priority == 2


class TestPipelineResult:
    def test_success(self):
        r = PipelineResult(success=True, total_cost_usd=0.75, run_id="r1")
        assert r.success is True
        assert r.error is None

    def test_failure(self):
        r = PipelineResult(success=False, error="Stage failed", run_id="r2")
        assert r.success is False
        assert r.error == "Stage failed"
