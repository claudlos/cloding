"""Top-level orchestrator: loads config, builds pipeline, runs it."""

from pathlib import Path

from osq.core.config import PipelineConfig, load_config
from osq.core.logger import get_logger, init_logging
from osq.core.workspace import get_diff_summary, prepare_workspace
from osq.models.cost_tracker import CostTracker
from osq.pipeline.pipeline import Pipeline
from osq.pipeline.result import PipelineResult
from osq.pipeline.state import PipelineState
from osq.runners.docker_runner import DockerRunner
from osq.runners.local_runner import LocalRunner

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

    result = await pipeline.run(
        user_request=request,
        context_files=context_files,
        resume_state=resume_state,
    )

    # Print summary
    _print_summary(result, config.workspace_path)

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


def _print_summary(result: PipelineResult, workspace: str) -> None:
    """Print pipeline result summary."""
    logger.info("=" * 60)
    if result.success:
        logger.info("Pipeline SUCCEEDED")
    else:
        logger.info("Pipeline FAILED: %s", result.error or "unknown error")

    logger.info("Run ID: %s", result.run_id)
    logger.info("Total cost: $%.4f", result.total_cost_usd)

    if result.cost_breakdown:
        logger.info("Cost breakdown:")
        for stage, cost in result.cost_breakdown.items():
            logger.info("  %s: $%.4f", stage, cost)

    logger.info("Review: %s (%d iterations)",
                "PASSED" if result.review_passed else "NOT PASSED",
                result.review_iterations)

    logger.info("Stages completed: %d", len(result.stage_results))
    logger.info("=" * 60)
