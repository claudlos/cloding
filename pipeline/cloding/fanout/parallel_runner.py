"""Semaphore-bounded parallel execution of coding tasks.

Each task gets its own TASK-{n}.md instruction file written to the workspace,
so the coding model reads it alongside PLAN.md and CONTEXT.md. All tasks
share the same workspace but target non-overlapping files.

Safety: Uses asyncio subprocess with argument list (no shell interpretation).
"""

import asyncio
from pathlib import Path

from cloding.core.config import ModelConfig, StageConfig
from cloding.core.logger import get_logger
from cloding.models.registry import ModelRegistry
from cloding.pipeline.result import StageResult
from cloding.pipeline.stage import create_stage
from cloding.pipeline.state import CodingTask, PipelineState
from cloding.runners.base import BaseRunner

logger = get_logger("parallel_runner", category="FANOUT")


async def run_tasks_parallel(
    tasks: list[CodingTask],
    code_config: StageConfig,
    model_config: ModelConfig,
    runner: BaseRunner,
    state: PipelineState,
    workspace_path: str,
    model_registry: ModelRegistry | None = None,
    max_parallel: int = 4,
    prompts_dir: str = "prompts",
) -> list[StageResult]:
    """Run multiple coding tasks in parallel with bounded concurrency.

    For each task, writes a TASK-{n}.md file to the workspace with specific
    instructions. All tasks read PLAN.md and CONTEXT.md but focus on their
    assigned task only.

    Args:
        tasks: List of CodingTask objects to execute
        code_config: Stage config for the code stage
        model_config: Model config for the coder
        runner: The runner to use (Docker or local)
        state: Current pipeline state
        workspace_path: Path to workspace root (for writing task files)
        model_registry: Optional model registry for cost estimation
        max_parallel: Maximum concurrent tasks
        prompts_dir: Directory containing prompt templates

    Returns:
        List of StageResult objects, one per task
    """
    semaphore = asyncio.Semaphore(max_parallel)
    ws = Path(workspace_path)

    logger.info(
        "Running %d tasks in parallel (max %d concurrent)",
        len(tasks), max_parallel,
    )

    # Write per-task instruction files
    for task in tasks:
        _write_task_file(ws, task)

    async def _run_single(task: CodingTask) -> StageResult:
        async with semaphore:
            logger.info("Starting task '%s': %s", task.task_id, task.description[:80])

            # Build a per-task state that tells the model which TASK file to read
            task_state = _build_task_state(state, task)

            stage = create_stage(
                config=code_config,
                model_config=model_config,
                prompts_dir=prompts_dir,
            )

            result = await stage.run(
                runner=runner,
                state=task_state,
                model_registry=model_registry,
            )

            if result.success:
                logger.info("Task '%s' completed: $%.4f", task.task_id, result.cost_usd)
            else:
                logger.error("Task '%s' failed", task.task_id)

            return result

    results = await asyncio.gather(
        *[_run_single(task) for task in tasks],
        return_exceptions=True,
    )

    # Convert exceptions to failed StageResults
    final_results: list[StageResult] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.error("Task '%s' raised exception: %s", tasks[i].task_id, r)
            final_results.append(StageResult(
                stage_name=f"code-{tasks[i].task_id}",
                output=str(r),
                success=False,
                model_id=model_config.model_id,
                provider=model_config.provider,
            ))
        else:
            final_results.append(r)

    # Cleanup task files
    for task in tasks:
        task_file = ws / f"{task.task_id.upper()}.md"
        if task_file.exists():
            task_file.unlink()

    succeeded = sum(1 for r in final_results if r.success)
    logger.info(
        "Parallel execution complete: %d/%d tasks succeeded",
        succeeded, len(final_results),
    )

    return final_results


def _write_task_file(workspace: Path, task: CodingTask) -> None:
    """Write a TASK-{n}.md file with specific instructions for one task."""
    filename = f"{task.task_id.upper()}.md"
    content = f"""# {task.task_id}: {task.description[:100]}

## Your Assignment

You are handling **only this task** from the implementation plan.
Read `PLAN.md` for overall context, but focus exclusively on this task.

## Task Details

- **Description**: {task.description}
- **Files to modify**: {', '.join(f'`{f}`' for f in task.files_to_modify) or 'See description'}
- **Priority**: {task.priority}

## Context

{task.context or 'No additional context. Refer to PLAN.md and CONTEXT.md.'}

## Rules

- ONLY modify the files listed above. Other tasks handle other files.
- Read CONTEXT.md for codebase patterns and conventions.
- Do not modify files that belong to other tasks.
"""
    filepath = workspace / filename
    filepath.write_text(content, encoding="utf-8")
    logger.debug("Wrote task file: %s", filepath)


def _build_task_state(base_state: PipelineState, task: CodingTask) -> PipelineState:
    """Create a copy of state with task-specific review feedback if any."""
    return PipelineState(
        user_request=base_state.user_request,
        context_files=task.files_to_modify or base_state.context_files,
        plan_output=base_state.plan_output,
        exploration_output=base_state.exploration_output,
        review_feedback=base_state.review_feedback,
        review_iteration=base_state.review_iteration,
        run_id=base_state.run_id,
        current_stage="code",
    )
