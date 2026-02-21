"""Top-level orchestrator: loads config, builds pipeline, runs it."""

import re
from pathlib import Path

from cloding.core.config import PipelineConfig, load_config
from cloding.core.logger import get_logger, init_logging
from cloding.core.progress import ProgressTracker
from cloding.core.workspace import get_diff_summary, prepare_workspace
from cloding.models.cost_tracker import CostTracker
from cloding.pipeline.pipeline import Pipeline
from cloding.pipeline.result import PipelineResult
from cloding.pipeline.state import PipelineState
from cloding.runners.docker_runner import DockerRunner
from cloding.runners.local_runner import LocalRunner

logger = get_logger("orchestrator", category="SYSTEM")


async def run_pipeline(
    request: str,
    config_path: str = "configs/default.yaml",
    workspace: str = ".",
    context_files: list[str] | None = None,
    no_docker: bool = False,
    no_git: bool = False,
    dry_run: bool = False,
    resume_from: str | None = None,
    run_id: str | None = None,
    verbose: bool = False,
    prompts_dir: str = "prompts",
) -> PipelineResult:
    """Run the full Cloding pipeline.

    Args:
        request: The user's coding request
        config_path: Path to YAML config file
        workspace: Path to the target workspace
        context_files: Optional list of key files to examine
        no_docker: If True, use local runner instead of Docker
        no_git: If True, skip git workspace preparation
        dry_run: If True, print config and exit without running
        resume_from: Stage name to resume from
        run_id: Run ID to resume (used with resume_from)
        verbose: Enable debug logging
        prompts_dir: Directory containing prompt templates

    Returns:
        PipelineResult with success status, costs, and stage results
    """
    # Load config
    config = load_config(config_path)
    init_logging("DEBUG" if verbose else config.log_level)

    # Override workspace
    if workspace:
        config.workspace_path = str(Path(workspace).resolve())

    # Handle resume
    if resume_from:
        config.resume_from_stage = resume_from

    logger.info("Cloding Pipeline: %s", config.name)
    logger.info("Workspace: %s", config.workspace_path)
    logger.info("Runner: %s", "local" if no_docker else "docker")

    if dry_run:
        _print_dry_run(config)
        return PipelineResult(success=True, run_id="dry-run")

    # Generate or reuse run_id
    current_run_id = run_id or Pipeline._generate_run_id()

    # Build progress tracker
    progress_tracker = ProgressTracker(
        request=request, config_name=config.name, run_id=current_run_id
    )

    # Prepare workspace (git branch)
    branch = await prepare_workspace(
        workspace=config.workspace_path,
        config_name=config.name,
        no_git=no_git,
    )
    if branch:
        logger.info("Working on branch: %s", branch)

    # Build runner
    if no_docker:
        runner = LocalRunner(workspace_path=config.workspace_path)
    else:
        runner = DockerRunner(
            image=config.docker.image,
            network=config.docker.network,
            workspace_path=config.workspace_path,
        )
        await DockerRunner.ensure_image(config.docker.image)
        await DockerRunner.ensure_network(config.docker.network)

    # Handle resume state
    resume_state = None
    if resume_from and run_id:
        if not re.fullmatch(r"[\w\-]+", run_id):
            raise ValueError(
                f"Invalid run_id '{run_id}': must be alphanumeric, hyphens, or underscores"
            )
        checkpoint = Path("data/runs") / run_id / "state.json"
        if checkpoint.exists():
            resume_state = PipelineState.load_checkpoint(checkpoint)
            logger.info("Resumed from checkpoint: %s", checkpoint)
        else:
            logger.warning("Checkpoint not found: %s, starting fresh", checkpoint)

    # Build and run pipeline
    pipeline = Pipeline(
        config=config,
        runner=runner,
        prompts_dir=prompts_dir,
    )

    # Run with progress tracker TUI
    with progress_tracker:
        result = await pipeline.run(
            user_request=request,
            context_files=context_files,
            resume_state=resume_state,
            progress_tracker=progress_tracker,
        )

    # Get git diff stat for summary
    git_diff_stat = ""
    try:
        git_diff_stat = await get_diff_summary(config.workspace_path)
    except Exception:
        pass  # Non-critical — skip if git unavailable

    # Print rich terminal summary
    _print_summary(result, pipeline.cost_tracker)

    # Save RUN_SUMMARY.md to workspace
    try:
        pipeline.cost_tracker.save_summary_md(
            workspace_path=config.workspace_path,
            run_id=result.run_id,
            user_request=request,
            success=result.success,
            review_passed=result.review_passed if result.review_iterations > 0 else None,
            review_iterations=result.review_iterations,
            git_diff_stat=git_diff_stat,
        )
    except Exception as err:
        logger.warning("Failed to save RUN_SUMMARY.md: %s", err)

    return result


def _print_dry_run(config: PipelineConfig) -> None:
    """Print pipeline config without executing."""
    logger.info("=== DRY RUN ===")
    logger.info("Pipeline: %s", config.name)
    logger.info("Stages:")
    for s in config.stages:
        model = config.models.get(s.model)
        model_id = model.model_id if model else "?"
        logger.info(
            "  %s -> %s (max_turns=%d, timeout=%ds, budget=$%.2f)",
            s.name, model_id, s.max_turns, s.timeout_seconds, s.max_budget_usd,
        )
    logger.info("Models:")
    for name, m in config.models.items():
        logger.info(
            "  %s: %s via %s ($%.2f/$%.2f per Mtok)",
            name, m.model_id, m.provider,
            m.cost_per_mtok_input, m.cost_per_mtok_output,
        )
    if config.fanout.enabled:
        logger.info(
            "Fan-out: enabled (max_parallel=%d)",
            config.fanout.max_parallel,
        )
    logger.info(
        "Review: max %d iterations", config.review.max_iterations,
    )


def _print_summary(result: PipelineResult, cost_tracker: CostTracker) -> None:
    """Print pipeline result summary with rich cost breakdown."""
    BOLD = "\033[1m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print()
    print(f"  {DIM}{'=' * 60}{RESET}")

    if result.success:
        print(f"  {GREEN}{BOLD}Pipeline SUCCEEDED{RESET}")
    else:
        print(f"  {RED}{BOLD}Pipeline FAILED{RESET}: {result.error or 'unknown error'}")

    print(f"  {DIM}Run ID: {result.run_id}{RESET}")

    if result.review_iterations > 0:
        review_color = GREEN if result.review_passed else RED
        print(
            f"  Review: {review_color}"
            f"{'PASSED' if result.review_passed else 'FAILED'}{RESET} "
            f"({result.review_iterations} iteration(s))"
        )

    # Rich cost table
    print(cost_tracker.format_terminal_summary())

    print(f"  {DIM}Stages completed: {len(result.stage_results)}{RESET}")
    print(f"  {DIM}{'=' * 60}{RESET}")
    print()
