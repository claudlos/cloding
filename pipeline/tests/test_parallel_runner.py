"""Tests for parallel fan-out runner."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from cloding.core.config import ModelConfig, StageConfig
from cloding.fanout.parallel_runner import _build_task_state, _write_task_file
from cloding.pipeline.state import CodingTask, PipelineState


class TestWriteTaskFile:
    def test_creates_file(self, tmp_path):
        task = CodingTask(
            task_id="task-1",
            description="Implement login",
            files_to_modify=["auth.py", "views.py"],
            priority=1,
        )
        _write_task_file(tmp_path, task)

        filepath = tmp_path / "TASK-1.md"
        assert filepath.exists()
        content = filepath.read_text(encoding="utf-8")
        assert "Implement login" in content
        assert "auth.py" in content
        assert "views.py" in content

    def test_includes_context(self, tmp_path):
        task = CodingTask(
            task_id="task-2",
            description="Add tests",
            context="Use pytest framework",
        )
        _write_task_file(tmp_path, task)

        filepath = tmp_path / "TASK-2.md"
        content = filepath.read_text(encoding="utf-8")
        assert "Use pytest framework" in content

    def test_no_context_fallback(self, tmp_path):
        task = CodingTask(task_id="task-3", description="Refactor")
        _write_task_file(tmp_path, task)

        filepath = tmp_path / "TASK-3.md"
        content = filepath.read_text(encoding="utf-8")
        assert "Refer to PLAN.md" in content

    def test_empty_files_list(self, tmp_path):
        task = CodingTask(task_id="task-4", description="Quick fix")
        _write_task_file(tmp_path, task)

        filepath = tmp_path / "TASK-4.md"
        content = filepath.read_text(encoding="utf-8")
        assert "See description" in content


class TestBuildTaskState:
    def test_copies_base_fields(self):
        base = PipelineState(
            user_request="Add feature",
            context_files=["main.py"],
            plan_output="The plan",
            exploration_output="Context found",
            review_feedback="Fix imports",
            review_iteration=1,
            run_id="run-123",
        )
        task = CodingTask(
            task_id="t1",
            description="Task 1",
            files_to_modify=["a.py", "b.py"],
        )

        state = _build_task_state(base, task)

        assert state.user_request == "Add feature"
        assert state.plan_output == "The plan"
        assert state.exploration_output == "Context found"
        assert state.review_feedback == "Fix imports"
        assert state.review_iteration == 1
        assert state.run_id == "run-123"
        assert state.current_stage == "code"

    def test_uses_task_files(self):
        base = PipelineState(user_request="test", context_files=["fallback.py"])
        task = CodingTask(
            task_id="t1", description="X",
            files_to_modify=["specific.py"],
        )
        state = _build_task_state(base, task)
        assert state.context_files == ["specific.py"]

    def test_falls_back_to_base_context(self):
        base = PipelineState(user_request="test", context_files=["fallback.py"])
        task = CodingTask(task_id="t1", description="X", files_to_modify=[])
        state = _build_task_state(base, task)
        assert state.context_files == ["fallback.py"]


# --- Tests for run_tasks_parallel ---

from cloding.fanout.parallel_runner import run_tasks_parallel
from cloding.pipeline.result import RunResult, StageResult
from cloding.runners.base import BaseRunner


class FakeParallelRunner(BaseRunner):
    """Runner that returns pre-defined results by call index."""

    def __init__(self, results: list[RunResult]):
        self._results = results
        self._idx = 0

    async def run(self, binary_name, env, cli_args, timeout):
        idx = self._idx
        self._idx += 1
        if idx < len(self._results):
            return self._results[idx]
        return RunResult(exit_code=1, stdout="", stderr="no more results")


class ErrorRunner(BaseRunner):
    """Runner that always raises an exception."""

    async def run(self, binary_name, env, cli_args, timeout):
        raise RuntimeError("Boom")


def _make_tasks(n=2):
    return [
        CodingTask(
            task_id=f"task-{i+1}",
            description=f"Task {i+1}",
            files_to_modify=[f"file{i+1}.py"],
            priority=i+1,
        )
        for i in range(n)
    ]


def _make_model_config():
    return ModelConfig(
        name="qwen",
        provider="openrouter",
        model_id="qwen/qwen3-coder-next",
        api_key_env="OPENROUTER_API_KEY",
        cost_per_mtok_input=0.07,
        cost_per_mtok_output=0.30,
    )


def _make_code_config():
    return StageConfig(
        name="code", model="qwen", prompt_file="prompts/code.txt",
    )


@pytest.mark.asyncio(loop_scope="function")
class TestRunTasksParallel:
    async def test_all_tasks_succeed(self, tmp_path):
        tasks = _make_tasks(2)
        runner = FakeParallelRunner(results=[
            RunResult(exit_code=0, stdout="done1", stderr=""),
            RunResult(exit_code=0, stdout="done2", stderr=""),
        ])
        state = PipelineState(user_request="test")
        results = await run_tasks_parallel(
            tasks=tasks,
            code_config=_make_code_config(),
            model_config=_make_model_config(),
            runner=runner,
            state=state,
            workspace_path=str(tmp_path),
            max_parallel=2,
        )
        assert len(results) == 2
        assert all(r.success for r in results)

    async def test_task_failure_reported(self, tmp_path):
        tasks = _make_tasks(2)
        runner = FakeParallelRunner(results=[
            RunResult(exit_code=0, stdout="ok", stderr=""),
            RunResult(exit_code=1, stdout="", stderr="fail"),
        ])
        state = PipelineState(user_request="test")
        results = await run_tasks_parallel(
            tasks=tasks,
            code_config=_make_code_config(),
            model_config=_make_model_config(),
            runner=runner,
            state=state,
            workspace_path=str(tmp_path),
            max_parallel=2,
        )
        assert len(results) == 2
        succeeded = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        assert len(succeeded) == 1
        assert len(failed) == 1

    async def test_exception_converted_to_failed_result(self, tmp_path):
        tasks = _make_tasks(1)
        runner = ErrorRunner()
        state = PipelineState(user_request="test")
        results = await run_tasks_parallel(
            tasks=tasks,
            code_config=_make_code_config(),
            model_config=_make_model_config(),
            runner=runner,
            state=state,
            workspace_path=str(tmp_path),
            max_parallel=2,
        )
        assert len(results) == 1
        assert results[0].success is False
        assert "Boom" in results[0].output

    async def test_task_files_written_and_cleaned_up(self, tmp_path):
        tasks = _make_tasks(2)
        runner = FakeParallelRunner(results=[
            RunResult(exit_code=0, stdout="ok", stderr=""),
            RunResult(exit_code=0, stdout="ok", stderr=""),
        ])
        state = PipelineState(user_request="test")
        await run_tasks_parallel(
            tasks=tasks,
            code_config=_make_code_config(),
            model_config=_make_model_config(),
            runner=runner,
            state=state,
            workspace_path=str(tmp_path),
            max_parallel=2,
        )
        # Task files should be cleaned up after execution
        assert not (tmp_path / "TASK-1.md").exists()
        assert not (tmp_path / "TASK-2.md").exists()

    async def test_semaphore_limits_concurrency(self, tmp_path):
        """With max_parallel=1, tasks run sequentially."""
        import asyncio
        max_concurrent = 0
        concurrent_count = 0

        class TrackingRunner(BaseRunner):
            async def run(self, binary_name, env, cli_args, timeout):
                nonlocal concurrent_count, max_concurrent
                concurrent_count += 1
                max_concurrent = max(max_concurrent, concurrent_count)
                await asyncio.sleep(0.01)
                concurrent_count -= 1
                return RunResult(exit_code=0, stdout="ok", stderr="")

        tasks = _make_tasks(3)
        runner = TrackingRunner()
        state = PipelineState(user_request="test")
        results = await run_tasks_parallel(
            tasks=tasks,
            code_config=_make_code_config(),
            model_config=_make_model_config(),
            runner=runner,
            state=state,
            workspace_path=str(tmp_path),
            max_parallel=1,
        )
        assert len(results) == 3
        assert max_concurrent == 1
