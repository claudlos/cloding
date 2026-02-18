"""Tests for fan-out: task splitter (Markdown parsing) and merge."""

import pytest

from osq.core.errors import StageError
from osq.fanout.merge import merge_results
from osq.fanout.task_splitter import split_tasks
from osq.pipeline.result import StageResult
from osq.pipeline.state import CodingTask


# -- Sample PLAN.md content for tests --

SAMPLE_PLAN_MD = """\
# Implementation Plan

## Overview
Add authentication to the FastAPI app.

### Task 1: Add login endpoint

- **Files**: `src/auth.py`, `src/routes.py`
- **Priority**: 1
- **Description**: Create a login endpoint that accepts username/password and returns a JWT token.
- **Context**: Use the existing UserModel in models.py.

### Task 2: Add signup endpoint

- **Files**: `src/signup.py`
- **Priority**: 2
- **Description**: Create a signup endpoint that validates input and creates a new user.
- **Context**: Follow the validation patterns in validators.py.
"""

SAMPLE_PLAN_NO_BACKTICKS = """\
### Task 1: Setup config

- **Files**: config.py, settings.py
- **Priority**: 1
- **Description**: Add configuration loading from environment variables.
"""

SAMPLE_PLAN_REVERSED_PRIORITY = """\
### Task 1: Low priority task

- **Priority**: 3
- **Description**: Documentation updates

### Task 2: High priority task

- **Priority**: 1
- **Description**: Critical bugfix
"""


class TestTaskSplitter:
    def test_split_valid_markdown(self):
        tasks = split_tasks(SAMPLE_PLAN_MD)
        assert len(tasks) == 2
        assert tasks[0].task_id == "task-1"
        assert tasks[0].priority == 1
        assert tasks[0].files_to_modify == ["src/auth.py", "src/routes.py"]
        assert "login endpoint" in tasks[0].description
        assert "UserModel" in tasks[0].context
        assert tasks[1].task_id == "task-2"
        assert tasks[1].files_to_modify == ["src/signup.py"]

    def test_split_sorted_by_priority(self):
        tasks = split_tasks(SAMPLE_PLAN_REVERSED_PRIORITY)
        assert tasks[0].task_id == "task-2"  # priority 1
        assert tasks[0].priority == 1
        assert tasks[1].task_id == "task-1"  # priority 3
        assert tasks[1].priority == 3

    def test_split_no_tasks(self):
        with pytest.raises(StageError, match="no tasks"):
            split_tasks("# Plan\n\nJust some text, no task headers.")

    def test_split_empty_string(self):
        with pytest.raises(StageError, match="no tasks"):
            split_tasks("")

    def test_split_files_without_backticks(self):
        """Files field without backticks should fall back to comma splitting."""
        tasks = split_tasks(SAMPLE_PLAN_NO_BACKTICKS)
        assert len(tasks) == 1
        assert "config.py" in tasks[0].files_to_modify
        assert "settings.py" in tasks[0].files_to_modify

    def test_split_uses_title_when_no_description(self):
        plan = """\
### Task 1: Implement the widget factory

- **Files**: `widget.py`
- **Priority**: 1
"""
        tasks = split_tasks(plan)
        assert len(tasks) == 1
        assert "widget factory" in tasks[0].description

    def test_split_default_priority_from_task_number(self):
        plan = """\
### Task 5: Some task

- **Description**: Do something.
"""
        tasks = split_tasks(plan)
        assert tasks[0].priority == 5

    def test_split_skips_empty_tasks(self):
        plan = """\
### Task 1: Good task

- **Description**: Real work here.

### Task 2:

"""
        tasks = split_tasks(plan)
        # Task 2 has no description and empty title — should be skipped
        assert len(tasks) == 1
        assert tasks[0].task_id == "task-1"

    def test_split_context_optional(self):
        plan = """\
### Task 1: No context task

- **Files**: `foo.py`
- **Priority**: 1
- **Description**: Do something simple.
"""
        tasks = split_tasks(plan)
        assert tasks[0].context == ""

    def test_split_multiline_description(self):
        plan = """\
### Task 1: Complex task

- **Description**: This is a complex task that spans
  multiple lines and has details.
- **Files**: `complex.py`
"""
        tasks = split_tasks(plan)
        assert "complex task" in tasks[0].description
        assert tasks[0].files_to_modify == ["complex.py"]

    def test_split_invalid_priority_falls_back_to_task_number(self):
        """When priority can't be parsed, should fall back to task number."""
        plan = """\
### Task 3: Some task

- **Priority**: not-a-number
- **Description**: Do something.
"""
        tasks = split_tasks(plan)
        assert tasks[0].priority == 3

    def test_split_skips_task_with_no_description_and_no_title(self):
        """A task header like '### Task 1: ' with empty title and no description."""
        plan = """\
### Task 1: Good task

- **Description**: Real work.

### Task 2: \t

"""
        tasks = split_tasks(plan)
        assert len(tasks) == 1
        assert tasks[0].task_id == "task-1"

    def test_file_overlap_warning(self, caplog):
        """Multiple tasks modifying the same file should log a warning."""
        import logging

        plan = """\
### Task 1: First task

- **Files**: `shared.py`, `other.py`
- **Priority**: 1
- **Description**: Task one.

### Task 2: Second task

- **Files**: `shared.py`
- **Priority**: 2
- **Description**: Task two.
"""
        with caplog.at_level(logging.WARNING, logger="osq.task_splitter"):
            tasks = split_tasks(plan)

        assert len(tasks) == 2
        assert any("shared.py" in msg for msg in caplog.messages)


class TestMergeResults:
    def test_merge_all_success(self):
        results = [
            StageResult(
                stage_name="code-t1", output="done1",
                tokens_in=100, tokens_out=50, cost_usd=0.10,
                success=True, model_id="qwen", provider="openrouter",
                num_turns=5, duration_ms=3000,
            ),
            StageResult(
                stage_name="code-t2", output="done2",
                tokens_in=200, tokens_out=80, cost_usd=0.20,
                success=True, model_id="qwen", provider="openrouter",
                num_turns=8, duration_ms=5000,
            ),
        ]

        merged = merge_results(results)
        assert merged.success is True
        assert merged.tokens_in == 300
        assert merged.tokens_out == 130
        assert merged.cost_usd == pytest.approx(0.30)
        assert merged.duration_ms == 5000  # wall-clock = longest
        assert merged.num_turns == 13
        assert "code-t1" in merged.output
        assert "code-t2" in merged.output

    def test_merge_with_failure(self):
        results = [
            StageResult(stage_name="code-t1", output="ok", success=True,
                        duration_ms=1000, model_id="q", provider="or"),
            StageResult(stage_name="code-t2", output="fail", success=False,
                        duration_ms=2000, model_id="q", provider="or"),
        ]
        merged = merge_results(results)
        assert merged.success is False
        assert "FAILED" in merged.output

    def test_merge_empty(self):
        merged = merge_results([])
        assert merged.success is False
        assert "No tasks" in merged.output
