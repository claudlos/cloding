"""Pipeline sequencer: executes stages, manages review loop, checkpoints."""

import asyncio
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cloding.core.config import PipelineConfig, StageConfig
from cloding.core.errors import CostLimitError, ReviewRejectedError, StageError
from cloding.core.logger import get_logger
from cloding.core.progress import ProgressTracker
from cloding.core.tool_handler import get_tool_handler
from cloding.core.workspace import calculate_workspace_hash
from cloding.fanout.merge import merge_results
from cloding.fanout.parallel_runner import run_tasks_parallel
from cloding.fanout.task_splitter import split_tasks
from cloding.models.cost_tracker import CostTracker
from cloding.models.registry import ModelRegistry
from cloding.pipeline.result import PipelineResult, StageResult, VerifyAgentResult
from cloding.pipeline.stage import create_stage
from cloding.pipeline.state import PipelineState
from cloding.runners.base import BaseRunner

logger = get_logger("pipeline", category="SYSTEM")


class Pipeline:
    """Executes the multi-stage pipeline with review loop and checkpoints."""

    def __init__(
        self,
        config: PipelineConfig,
        runner: BaseRunner,
        prompts_dir: str = "prompts",
        data_dir: str = "data/runs",
        cache_dir: str = "data/cache",
    ) -> None:
        self.config = config
        self.runner = runner
        self.prompts_dir = prompts_dir
        self.data_dir = Path(data_dir)
        self.cache_dir = Path(cache_dir)
        self.model_registry = ModelRegistry(config.models)
        self.cost_tracker = CostTracker()
        self.logger = get_logger("pipeline", category="SYSTEM")

    async def run(
        self,
        user_request: str,
        context_files: list[str] | None = None,
        resume_state: PipelineState | None = None,
        progress_tracker: Optional[ProgressTracker] = None,
    ) -> PipelineResult:
        """Execute the full pipeline.

        Args:
            user_request: The user's coding request
            context_files: Optional list of key files to examine
            resume_state: Optional state to resume from a checkpoint
            progress_tracker: Optional TUI progress tracker

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

            # Initialize progress tracker with stages
            if progress_tracker:
                for s in stages_to_run:
                    model_cfg = self.model_registry.get(s.model)
                    progress_tracker.add_stage(s.name, model_cfg.model_id)

            for stage_config in stages_to_run:
                state.current_stage = stage_config.name
                model_config = self.model_registry.get(stage_config.model)

                if progress_tracker:
                    progress_tracker.start_stage(stage_config.name)
                    progress_tracker.update_stage(stage_config.name, progress=10)

                # Check for explore cache
                if stage_config.name == "explore":
                    cached_context = self._get_cached_explore()
                    if cached_context:
                        self.logger.info("Using cached exploration result (CONTEXT.md)")
                        if progress_tracker:
                            progress_tracker.update_stage(
                                "explore", details="Using cached result"
                            )
                        
                        # Write cached context to workspace
                        ws_context = Path(self.config.workspace_path) / "CONTEXT.md"
                        ws_context.write_text(cached_context, encoding="utf-8")
                        
                        result = StageResult(
                            stage_name="explore",
                            output="Loaded from cache",
                            success=True,
                            model_id="cache",
                        )
                        stage_results.append(result)
                        state.add_stage_result(result)
                        self.cost_tracker.record("explore", result, tool="cache")
                        self._update_state(state, "explore", result)
                        
                        if progress_tracker:
                            progress_tracker.update_stage(
                                "explore", status="completed", progress=100
                            )
                        continue

                # Fan-out: parallel coding when enabled and this is the code stage
                if stage_config.name == "code" and self.config.fanout.enabled:
                    result = await self._run_fanout(
                        stage_config, model_config, state, progress_tracker
                    )
                    # Fanout records per-task costs in _run_fanout; record the
                    # merged result here so the summary includes a top-level row.
                    tool_name = get_tool_handler(
                        stage_config.tool or model_config.tool or "claude-code"
                    ).get_binary_name()
                    self.cost_tracker.record(stage_config.name, result, tool=tool_name)
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
                    self.cost_tracker.record(
                        stage_config.name, result, tool=stage.tool_handler.get_binary_name()
                    )

                stage_results.append(result)
                state.add_stage_result(result)

                if progress_tracker:
                    status = "completed" if result.success else "failed"
                    progress_tracker.update_stage(
                        stage_config.name,
                        status=status,
                        progress=100,
                        cost=self.cost_tracker.summary()["total_cost_usd"],
                    )

                if not result.success:
                    raise StageError(
                        f"Stage '{stage_config.name}' failed. "
                        f"Check logs for details."
                    )

                # Route output to the correct state field
                self._update_state(state, stage_config.name, result)

                # Handle test/lint quality gates
                if stage_config.name in ("test", "lint"):
                    gate_passed = self._check_quality_gate(
                        result.output, stage_config.name
                    )
                    if not gate_passed:
                        self.logger.warning(
                            "Quality gate '%s' did not pass — "
                            "continuing pipeline (agent attempted fixes within session)",
                            stage_config.name,
                        )

                # Cache exploration result
                if stage_config.name == "explore" and result.success:
                    self._cache_explore()

                # Handle review loop
                if stage_config.name == "review":
                    review_passed = self._check_review(result.output, state)
                    if not review_passed:
                        loop_results = await self._review_loop(
                            state, checkpoint_dir, progress_tracker
                        )
                        stage_results.extend(loop_results)

                # Checkpoint after each stage
                state.save_checkpoint(checkpoint_dir / "state.json")

            # Multi-agent verification (after all stages complete)
            verify_results: list[VerifyAgentResult] = []
            verify_consensus = False
            if self.config.verify.enabled and self.config.verify.agents:
                verify_results, verify_consensus = await self._run_verification(
                    state, stage_results, checkpoint_dir
                )

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
                verify_results=verify_results,
                verify_consensus=verify_consensus,
            )

        except (StageError, CostLimitError, ReviewRejectedError) as err:
            self.logger.error("Pipeline failed: %s", err)
            state.save_checkpoint(checkpoint_dir / "state.json")
            self.cost_tracker.save_csv(state.run_id)
            if progress_tracker:
                progress_tracker.update_stage(state.current_stage, status="failed")
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
        self,
        code_config: StageConfig,
        model_config,
        state: PipelineState,
        progress_tracker: Optional[ProgressTracker] = None,
    ) -> StageResult:
        """Run the code stage as parallel fan-out tasks.

        Reads PLAN.md from the workspace, splits into independent tasks,
        runs them in parallel with bounded concurrency, and merges results.

        Args:
            code_config: Stage config for the code stage
            model_config: Model config for the coding model
            state: Current pipeline state
            progress_tracker: Optional progress tracker

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

        if progress_tracker:
            progress_tracker.update_stage(
                "code", details=f"Running {len(tasks)} parallel tasks"
            )

        # Run tasks in parallel
        # Note: We'd need to modify run_tasks_parallel to report progress per task
        # for a truly detailed TUI, but for now we'll just track the overall stage.
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
            tool = get_tool_handler(code_config.tool or model_config.tool or "claude-code").get_binary_name()
            self.cost_tracker.record(f"code-{tasks[i].task_id}", tr, tool=tool)

        # Merge into a single StageResult
        merged = merge_results(task_results)
        return merged

    async def _review_loop(
        self,
        state: PipelineState,
        checkpoint_dir: Path,
        progress_tracker: Optional[ProgressTracker] = None,
    ) -> list[StageResult]:
        """Run the code->review loop until pass or max iterations."""
        loop_results: list[StageResult] = []
        max_iterations = self.config.review.max_iterations

        while not state.review_passed and state.review_iteration < max_iterations:
            self.logger.info(
                "Review iteration %d/%d \u2014 re-running code stage",
                state.review_iteration, max_iterations,
            )

            if progress_tracker:
                progress_tracker.update_stage(
                    "review", details=f"Rework iteration {state.review_iteration}"
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
            self.cost_tracker.record(f"code-rework-{state.review_iteration}", code_result, tool=code_stage.tool_handler.get_binary_name())

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
            self.cost_tracker.record(f"review-{state.review_iteration}", review_result, tool=review_stage.tool_handler.get_binary_name())

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
        sometimes add preamble (headers, thinking, bullet points, etc.) before
        the verdict. We search strategically:

        1. First line (ideal case — reviewer followed instructions)
        2. Last 50 lines (verdict often at the end after analysis)
        3. Full output as fallback

        Handles common patterns:
        - "PASS", "FAIL"
        - "**PASS**", "**FAIL**"
        - "Verdict: PASS", "Result: FAIL"
        - "## PASS", "# FAIL"
        - Markdown-wrapped: "```\\nPASS\\n```"
        """
        threshold = self.config.review.pass_threshold.upper()
        output_stripped = output.strip()
        output_upper = output_stripped.upper()

        # Check if output starts with the threshold (ideal case)
        if output_upper.startswith(threshold):
            state.review_passed = True
            self.logger.info("Review PASSED")
            return True

        # Patterns that match PASS/FAIL as standalone verdicts
        # Avoids matching words like "PASSING", "FAILED", "bypass"
        pass_pattern = re.compile(
            r"(?:^|[\s*#:>`\n])PASS(?:[\s*#:>`\n.,!]|$)", re.MULTILINE
        )
        fail_pattern = re.compile(
            r"(?:^|[\s*#:>`\n])FAIL(?:[\s*#:>`\n.,!]|$)", re.MULTILINE
        )

        # Priority: check last 50 lines first (models often put verdict at end)
        lines = output_stripped.split("\n")
        tail = "\n".join(lines[-50:]).upper()

        tail_pass = bool(pass_pattern.search(tail))
        tail_fail = bool(fail_pattern.search(tail))

        # Clear verdict in the tail
        if tail_pass and not tail_fail:
            state.review_passed = True
            self.logger.info("Review PASSED (verdict found in output tail)")
            return True
        if tail_fail and not tail_pass:
            state.review_iteration += 1
            state.review_feedback = output_stripped
            self.logger.info(
                "Review FAILED (iteration %d): %s",
                state.review_iteration,
                output_stripped[:200],
            )
            return False

        # Fallback: search full output
        has_pass = bool(pass_pattern.search(output_upper))
        has_fail = bool(fail_pattern.search(output_upper))

        if has_pass and not has_fail:
            state.review_passed = True
            self.logger.info("Review PASSED (found in full output)")
            return True

        # FAIL found, or ambiguous (both PASS and FAIL present), or no verdict at all
        # All treated as failure — safer to re-review than to pass bad code
        state.review_iteration += 1
        state.review_feedback = output_stripped
        if has_pass and has_fail:
            self.logger.warning(
                "Review output contains both PASS and FAIL — treating as FAIL"
            )
        self.logger.info(
            "Review FAILED (iteration %d): %s",
            state.review_iteration,
            output_stripped[:200],
        )
        return False

    def _check_quality_gate(self, output: str, gate_name: str) -> bool:
        """Check if a quality gate (test/lint) output indicates pass.

        Quality gates are informational — they don't trigger a review loop.
        The test/lint agent runs within its Claude Code session and attempts
        to fix issues itself. We check the output to log status.

        Args:
            output: The stage output text
            gate_name: "test" or "lint"

        Returns:
            True if the output indicates PASS, False otherwise
        """
        output_stripped = output.strip().upper()

        # Check start of output
        if output_stripped.startswith("PASS"):
            self.logger.info("Quality gate '%s' PASSED", gate_name)
            return True

        # Check tail (last 20 lines)
        lines = output_stripped.split("\n")
        tail = "\n".join(lines[-20:])

        pass_pattern = re.compile(
            r"(?:^|[\s*#:>`\n])PASS(?:[\s*#:>`\n.,!]|$)", re.MULTILINE
        )
        fail_pattern = re.compile(
            r"(?:^|[\s*#:>`\n])FAIL(?:[\s*#:>`\n.,!]|$)", re.MULTILINE
        )

        tail_pass = bool(pass_pattern.search(tail))
        tail_fail = bool(fail_pattern.search(tail))

        if tail_pass and not tail_fail:
            self.logger.info("Quality gate '%s' PASSED", gate_name)
            return True

        if tail_fail:
            self.logger.warning("Quality gate '%s' FAILED", gate_name)
            return False

        # No clear verdict — check full output
        has_pass = bool(pass_pattern.search(output_stripped))
        if has_pass:
            self.logger.info(
                "Quality gate '%s' PASSED (found in full output)", gate_name
            )
            return True

        self.logger.warning(
            "Quality gate '%s' — no clear verdict in output", gate_name
        )
        return False

    async def _run_verification(
        self,
        state: PipelineState,
        stage_results: list[StageResult],
        checkpoint_dir: Path,
    ) -> tuple[list[VerifyAgentResult], bool]:
        """Run multi-agent verification with parallel agents and consensus voting.

        Spawns N verification agents in parallel, each independently reviewing
        the code changes. Aggregates their verdicts into a consensus score.
        If consensus fails, triggers re-code and re-verify up to max_iterations.

        Args:
            state: Current pipeline state
            stage_results: Accumulated stage results (for appending verify results)
            checkpoint_dir: Directory for checkpoints

        Returns:
            Tuple of (list of agent results, consensus bool)
        """
        verify_config = self.config.verify
        all_verify_results: list[VerifyAgentResult] = []
        iteration = 0

        while iteration < verify_config.max_iterations:
            iteration += 1
            self.logger.info(
                "--- Verification round %d/%d (%d agents) ---",
                iteration, verify_config.max_iterations, len(verify_config.agents),
            )

            # Run all verify agents in parallel
            agent_results = await self._run_verify_agents(state)
            all_verify_results.extend(agent_results)

            # Check consensus
            passes = sum(1 for r in agent_results if r.passed)
            total = len(agent_results)
            ratio = passes / total if total > 0 else 0.0

            self.logger.info(
                "Verification consensus: %d/%d PASS (%.0f%%, threshold %.0f%%)",
                passes, total, ratio * 100, verify_config.consensus_threshold * 100,
            )

            if ratio >= verify_config.consensus_threshold:
                self.logger.info("Verification PASSED by consensus")
                return all_verify_results, True

            # Consensus failed — collect feedback from failing agents
            if iteration >= verify_config.max_iterations:
                self.logger.warning(
                    "Verification failed after %d iteration(s) — "
                    "consensus not reached",
                    iteration,
                )
                return all_verify_results, False

            # Merge feedback from failing agents for re-code
            fail_feedback = []
            for r in agent_results:
                if not r.passed and r.feedback:
                    fail_feedback.append(f"[{r.model}]: {r.feedback}")

            merged_feedback = "\n\n".join(fail_feedback) if fail_feedback else "Verification failed — no specific feedback"
            state.review_feedback = merged_feedback
            state.review_iteration += 1

            self.logger.info(
                "Re-running code stage with merged verification feedback "
                "(iteration %d)",
                state.review_iteration,
            )

            # Re-run code stage with feedback
            code_config = self._find_stage_config("code")
            if not code_config:
                self.logger.warning("No 'code' stage found for verification loop — skipping re-code")
                return all_verify_results, False

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
            stage_results.append(code_result)
            state.add_stage_result(code_result)
            self.cost_tracker.record(
                f"code-verify-rework-{iteration}", code_result, tool=code_stage.tool_handler.get_binary_name()
            )

            if not code_result.success:
                self.logger.error("Code rework for verification failed")
                return all_verify_results, False

            self._update_state(state, "code", code_result)
            state.save_checkpoint(checkpoint_dir / "state.json")

        return all_verify_results, False

    async def _run_verify_agents(
        self, state: PipelineState
    ) -> list[VerifyAgentResult]:
        """Run all verification agents in parallel.

        Args:
            state: Current pipeline state

        Returns:
            List of VerifyAgentResult from each agent
        """
        verify_config = self.config.verify
        tasks = []

        for i, agent_config in enumerate(verify_config.agents):
            model_config = self.model_registry.get(agent_config.model)

            # Create a stage config for the verify agent
            stage_config = StageConfig(
                name="verify",
                model=agent_config.model,
                prompt_file=agent_config.prompt_file,
                max_turns=20,
                max_budget_usd=2.0,
                timeout_seconds=300,
                disallowed_tools=["Edit", "Write"],
            )

            stage = create_stage(
                config=stage_config,
                model_config=model_config,
                prompts_dir=self.prompts_dir,
            )

            tasks.append(self._run_single_verify_agent(
                stage, state, agent_config.model, model_config.model_id, i
            ))

        # Run all agents in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        agent_results: list[VerifyAgentResult] = []
        for i, result in enumerate(results):
            model_name = verify_config.agents[i].model
            model_id = self.model_registry.get(model_name).model_id

            if isinstance(result, Exception):
                self.logger.error(
                    "Verify agent %d (%s) failed with exception: %s",
                    i, model_id, result,
                )
                agent_results.append(VerifyAgentResult(
                    model=model_id,
                    passed=False,
                    feedback=f"Agent failed with exception: {result}",
                ))
            else:
                agent_results.append(result)

        return agent_results

    async def _run_single_verify_agent(
        self,
        stage,
        state: PipelineState,
        model_name: str,
        model_id: str,
        agent_index: int,
    ) -> VerifyAgentResult:
        """Run a single verification agent and parse its output.

        Args:
            stage: The verify stage instance
            state: Current pipeline state
            model_name: Config model key
            model_id: Full model ID string
            agent_index: Index of this agent in the verify config

        Returns:
            VerifyAgentResult with parsed verdict
        """
        self.logger.info(
            "Starting verify agent %d: %s", agent_index, model_id,
        )

        result = await stage.run(
            runner=self.runner,
            state=state,
            model_registry=self.model_registry,
        )

        # Record cost
        self.cost_tracker.record(f"verify-{model_name}", result, tool=stage.tool_handler.get_binary_name())

        # Parse PASS/FAIL verdict
        passed = self._check_verify_verdict(result.output)

        self.logger.info(
            "Verify agent %d (%s): %s",
            agent_index, model_id, "PASS" if passed else "FAIL",
        )

        return VerifyAgentResult(
            model=model_id,
            passed=passed,
            feedback=result.output if not passed else "",
            cost_usd=result.cost_usd,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
        )

    def _check_verify_verdict(self, output: str) -> bool:
        """Check if a verification agent's output indicates PASS or FAIL.

        Uses the same pattern-matching approach as _check_quality_gate.

        Args:
            output: The verify agent's output text

        Returns:
            True if output indicates PASS, False otherwise
        """
        output_stripped = output.strip().upper()

        if not output_stripped:
            return False

        # Check start of output (ideal case)
        if output_stripped.startswith("PASS"):
            return True
        if output_stripped.startswith("FAIL"):
            return False

        # Check tail
        lines = output_stripped.split("\n")
        tail = "\n".join(lines[-20:])

        pass_pattern = re.compile(
            r"(?:^|[\s*#:>`\n])PASS(?:[\s*#:>`\n.,!]|$)", re.MULTILINE
        )
        fail_pattern = re.compile(
            r"(?:^|[\s*#:>`\n])FAIL(?:[\s*#:>`\n.,!]|$)", re.MULTILINE
        )

        tail_pass = bool(pass_pattern.search(tail))
        tail_fail = bool(fail_pattern.search(tail))

        if tail_pass and not tail_fail:
            return True
        if tail_fail:
            return False

        # Full output scan
        has_pass = bool(pass_pattern.search(output_stripped))
        return has_pass

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
        # test/lint output is handled by _check_quality_gate

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

    def _get_cached_explore(self) -> Optional[str]:
        """Try to load a cached CONTEXT.md for the current workspace."""
        ws_hash = calculate_workspace_hash(self.config.workspace_path)
        cache_file = self.cache_dir / "explore" / f"{ws_hash}.md"
        if cache_file.exists():
            return cache_file.read_text(encoding="utf-8")
        return None

    def _cache_explore(self) -> None:
        """Save CONTEXT.md to cache for the current workspace."""
        ws_context = Path(self.config.workspace_path) / "CONTEXT.md"
        if ws_context.exists():
            ws_hash = calculate_workspace_hash(self.config.workspace_path)
            cache_dir = self.cache_dir / "explore"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / f"{ws_hash}.md"
            cache_file.write_text(ws_context.read_text(encoding="utf-8"), encoding="utf-8")
            self.logger.debug("Exploration result cached to %s", cache_file)
