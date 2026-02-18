"""Combines parallel coding results into a single StageResult."""

from cloding.core.logger import get_logger
from cloding.pipeline.result import StageResult

logger = get_logger("merge", category="SYSTEM")


def merge_results(results: list[StageResult]) -> StageResult:
    """Merge multiple parallel StageResults into a single combined result.

    Args:
        results: List of StageResult objects from parallel tasks

    Returns:
        A single merged StageResult with combined metrics
    """
    if not results:
        return StageResult(
            stage_name="code",
            output="No tasks were executed.",
            success=False,
        )

    all_success = all(r.success for r in results)
    total_tokens_in = sum(r.tokens_in for r in results)
    total_tokens_out = sum(r.tokens_out for r in results)
    total_cost = sum(r.cost_usd for r in results)
    total_duration = max(r.duration_ms for r in results)  # wall-clock = longest task
    total_turns = sum(r.num_turns for r in results)

    # Combine outputs
    output_parts = []
    for r in results:
        status = "OK" if r.success else "FAILED"
        output_parts.append(f"## {r.stage_name} [{status}]\n{r.output}")

    combined_output = "\n\n---\n\n".join(output_parts)

    failed = [r for r in results if not r.success]
    if failed:
        logger.warning(
            "%d/%d parallel tasks failed: %s",
            len(failed),
            len(results),
            ", ".join(r.stage_name for r in failed),
        )

    logger.info(
        "Merged %d results: %d tokens, $%.4f, %s",
        len(results),
        total_tokens_in + total_tokens_out,
        total_cost,
        "all passed" if all_success else f"{len(failed)} failed",
    )

    return StageResult(
        stage_name="code",
        output=combined_output,
        tokens_in=total_tokens_in,
        tokens_out=total_tokens_out,
        cost_usd=total_cost,
        success=all_success,
        model_id=results[0].model_id if results else "",
        provider=results[0].provider if results else "",
        num_turns=total_turns,
        duration_ms=total_duration,
    )
