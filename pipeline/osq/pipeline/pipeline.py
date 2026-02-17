"""Pipeline sequencer: executes stages, manages review loop, checkpoints."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from osq.core.config import PipelineConfig
from osq.core.errors import CostLimitError, ReviewRejectedError, StageError
from osq.core.logger import get_logger
from osq.fanout.merge import merge_results
from osq.fanout.parallel_runner import run_tasks_parallel
from osq.fanout.task_splitter import split_tasks
from osq.models.cost_tracker import CostTracker
from osq.models.registry import ModelRegistry
from osq.pipeline.result import PipelineResult, StageResult
from osq.pipeline.stage import create_stage
from osq.pipeline.state import PipelineState
from osq.runners.base import BaseRunner

logger = get_logger("pipeline", category="SYSTEM")


class Pipeline:
    """Executes the multi-stage pipeline with review loop and checkpoints."""

    def __init__(
        self,
        config: PipelineConfig,
        runner: BaseRunner,
        prompts_dir: str = "prompts",
        data_dir: str = "data/runs",
    ) -> None:
        self.config = config
        self.runner = runner
        self.prompts_dir = prompts_dir
        self.data_dir = Path(data_dir)
        self.model_registry = ModelRegistry(config.models)
        self.cost_tracker = CostTracker()
        self.logger = get_logger("pipeline", category="SYSTEM")

    async def run(
        self,
        user_request: str,
        context_files: list[str] | None = None,
        resume_state: PipelineState | None = None,
    ) -> PipelineResult:
        """Execute the full pipeline.

        Args:
            user_request: The user's coding request
            context_files: Optional list of key files to examine
            resume_state: Optional state to resume from a checkpoint

        Returns:
            PipelineResult with success status, costs, and stage results
        """
        state = resume_state or PipelineState(
            user_request=user_request,
            context_files=context_files or [],
            run_id=self._generate_run_id(),
        )

        self.logger.info("Pipeline run '%s' starting", state.run_id)
        checkpoint_dir = self.data_dir / state.run_id
        stage_results: list[StageResult] = []

        try:
            stages_to_run = self._get_stages_to_run(state)

            for stage_config in stages_to_run:
                state.current_stage = stage_config.name
                model_config = self.model_registry.get(stage_config.model)

                # Fan-out: parallel coding when enabled and this is the code stage
                if stage_config.name == "code" and self.config.fanout.enabled:
                    result = await self._run_fanout(
                        stage_config, model_config, state
                    )
                else:
                    stage = create_stage(
                        config=stage_config,
                        model_config=model_config,
                        prompts_dir=self.prompts_dir,
                    )

                    self.logger.info(
                        "--- Stage: %s (model: %s) ---",
                        stage_config.name, model_config.model_id,
                    )

                    result = await stage.run(
                        runner=self.runner,
                        state=state,
                        model_registry=self.model_registry,
                    )

                stage_results.append(result)
                state.add_stage_result(result)
                self.cost_tracker.record(stage_config.name, result)

                if not result.success:
                    raise StageError(
                        f"Stage '{stage_config.name}' failed. "
                        f"Check logs for details."
                    )

                # Route output to the correct state field
                self._update_state(state, stage_config.name, result)

                # Handle review loop
                if stage_config.name == "review":
                    review_passed = self._check_review(result.output, state)
                    if not review_passed:
                        loop_results = await self._review_loop(state, checkpoint_dir)
                        stage_results.extend(loop_results)

                # Checkpoint after each stage
                state.save_checkpoint(checkpoint_dir / "state.json")

            # Save cost report
            self.cost_tracker.save_csv(state.run_id)

            summary = self.cost_tracker.summary()
            self.logger.info(
                "Pipeline complete: $%.4f total (%d stages)",
                summary["total_cost_usd"],
                summary["record_count"],
            )

            return PipelineResult(
                success=True,
                total_cost_usd=state.total_cost_usd,
                cost_breakdown=summary.get("by_stage", {}),
                stage_results=stage_results,
                review_passed=state.review_passed,
                review_iterations=state.review_iteration,
                run_id=state.run_id,
            )

        except (StageError, CostLimitError, ReviewRejectedError) as err:
            self.logger.error("Pipeline failed: %s", err)
            state.save_checkpoint(checkpoint_dir / "state.json")
            self.cost_tracker.save_csv(state.run_id)
            return PipelineResult(
                success=False,
                total_cost_usd=state.total_cost_usd,
                cost_breakdown=self.cost_tracker.summary().get("by_stage", {}),
                stage_results=stage_results,
                review_passed=state.review_passed,
                review_iterations=state.review_iteration,
                run_id=state.run_id,
                error=str(err),
            )

    async def _run_fanout(
        self, code_config, model_config, state: PipelineState
    ) -> StageResult:
        """Run the code stage as parallel fan-out tasks.

        Reads PLAN.md from the workspace, splits into independent tasks,
        runs them in parallel with bounded concurrency, and merges results.

        Args:
            code_config: Stage config for the code stage
            model_config: Model config for the coding model
            state: Current pipeline state

        Returns:
            Merged StageResult combining all parallel task results
        """
        workspace = Path(self.config.workspace_path)
        plan_path = workspace / "PLAN.md"

        if not plan_path.exists():
            raise StageError(
                "Fan-out enabled but PLAN.md not found in workspace. "
                "Ensure the plan stage ran successfully."
            )

        plan_md = plan_path.read_text(encoding="utf-8")

        self.logger.info("--- Stage: code (fan-out, model: %s) ---", model_config.model_id)

        # Parse PLAN.md into independent tasks
        tasks = split_tasks(plan_md)
        state.set_coding_tasks(tasks)
        self.logger.info("Split plan into %d independent tasks", len(tasks))

        # Run tasks in parallel
        task_results = await run_tasks_parallel(
            tasks=tasks,
            code_config=code_config,
            model_config=model_config,
            runner=self.runner,
            state=state,
            workspace_path=str(workspace),
            model_registry=self.model_registry,
            max_parallel=self.config.fanout.max_parallel,
            prompts_dir=self.prompts_dir,
        )

        # Record individual task costs
        for i, tr in enumerate(task_results):
            self.cost_tracker.record(f"code-{tasks[i].task_id}", tr)

        # Merge into a single StageResult
        merged = merge_results(task_results)
        return merged

    async def _review_loop(
        self, state: PipelineState, checkpoint_dir: Path
    ) -> list[StageResult]:
        """Run the code->review loop until pass or max iterations."""
        loop_results: list[StageResult] = []
        max_iterations = self.config.review.max_iterations

        while not state.review_passed and state.review_iteration < max_iterations:
            self.logger.info(
                "Review iteration %d/%d — re-running code stage",
                state.review_iteration, max_iterations,
            )

            # Re-run code stage with feedback
            code_config = self._find_stage_config("code")
            if not code_config:
                raise StageError("No 'code' stage found for review loop.")

            code_model = self.model_registry.get(code_config.model)
            code_stage = create_stage(
                config=code_config,
                model_config=code_model,
                prompts_dir=self.prompts_dir,
            )

            code_result = await code_stage.run(
                runner=self.runner,
                state=state,
                model_registry=self.model_registry,
            )
            loop_results.append(code_result)
            state.add_stage_result(code_result)
            self.cost_tracker.record(f"code-rework-{state.review_iteration}", code_result)

            if not code_result.success:
                raise StageError(
                    f"Code rework iteration {state.review_iteration} failed."
                )

            self._update_state(state, "code", code_result)

            # Re-run review
            review_config = self._find_stage_config("review")
            if not review_config:
                raise StageError("No 'review' stage found for review loop.")

            review_model = self.model_registry.get(review_config.model)
            review_stage = create_stage(
                config=review_config,
                model_config=review_model,
                prompts_dir=self.prompts_dir,
            )

            review_result = await review_stage.run(
                runner=self.runner,
                state=state,
                model_registry=self.model_registry,
            )
            loop_results.append(review_result)
            state.add_stage_result(review_result)
            self.cost_tracker.record(f"review-{state.review_iteration}", review_result)

            if not review_result.success:
                raise StageError(
                    f"Review iteration {state.review_iteration} failed."
                )

            self._check_review(review_result.output, state)
            state.save_checkpoint(checkpoint_dir / "state.json")

        if not state.review_passed:
            raise ReviewRejectedError(
                f"Code did not pass review after {max_iterations} iterations. "
                f"Last feedback: {state.review_feedback[:200]}"
            )

        return loop_results

    def _check_review(self, output: str, state: PipelineState) -> bool:
        """Check if review output indicates pass or fail.

        The reviewer is instructed to start output with PASS or FAIL, but models
        sometimes add preamble (headers, bullet points, etc.) before the verdict.
        We search the full output for the verdict keyword.
        """
        threshold = self.config.review.pass_threshold.upper()
        output_stripped = output.strip()
        output_upper = output_stripped.upper()

        # Check if output starts with the threshold (ideal case)
        if output_upper.startswith(threshold):
            state.review_passed = True
            self.logger.info("Review PASSED")
            return True

        # Search more broadly: look for "PASS" as a standalone word
        # Common patterns: "PASS", "**PASS**", "Verdict: PASS", "## PASS"
        import re
        pass_pattern = re.compile(
            r"(?:^|\b|[*#:\s])PASS(?:\b|[*#:\s]|$)", re.MULTILINE | re.IGNORECASE
        )
        fail_pattern = re.compile(
            r"(?:^|\b|[*#:\s])FAIL(?:\b|[*#:\s]|$)", re.MULTILINE | re.IGNORECASE
        )

        has_pass = bool(pass_pattern.search(output_upper))
        has_fail = bool(fail_pattern.search(output_upper))

        # If PASS found and FAIL not found, treat as pass
        if has_pass and not has_fail:
            state.review_passed = True
            self.logger.info("Review PASSED (found in output body)")
            return True

        # Extract feedback after FAIL (or ambiguous/missing verdict)
        state.review_iteration += 1
        state.review_feedback = output_stripped
        self.logger.info(
            "Review FAILED (iteration %d): %s",
            state.review_iteration,
            output_stripped[:200],
        )
        return False

    def _update_state(
        self, state: PipelineState, stage_name: str, result: StageResult
    ) -> None:
        """Route stage output to the correct PipelineState field."""
        if stage_name == "plan":
            state.plan_output = result.output
        elif stage_name == "explore":
            state.exploration_output = result.output
        elif stage_name == "code":
            state.code_outputs.append(result.output)
        # review output is handled by _check_review

    def _find_stage_config(self, name: str):
        """Find a stage config by name."""
        for s in self.config.stages:
            if s.name == name:
                return s
        return None

    def _get_stages_to_run(self, state: PipelineState) -> list:
        """Determine which stages to run, handling resume."""
        if not self.config.resume_from_stage:
            return list(self.config.stages)

        resume_from = self.config.resume_from_stage
        stage_names = [s.name for s in self.config.stages]

        if resume_from not in stage_names:
            raise StageError(
                f"Resume stage '{resume_from}' not found. "
                f"Available: {stage_names}"
            )

        idx = stage_names.index(resume_from)
        self.logger.info(
            "Resuming from stage '%s' (skipping %d stages)",
            resume_from, idx,
        )
        return list(self.config.stages[idx:])

    @staticmethod
    def _generate_run_id() -> str:
        """Generate a unique run ID."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        short_uuid = uuid.uuid4().hex[:6]
        return f"{ts}-{short_uuid}"
