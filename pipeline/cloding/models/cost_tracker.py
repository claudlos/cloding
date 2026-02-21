"""Per-stage token usage and cost tracking with CSV export."""

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from cloding.core.logger import get_logger
from cloding.pipeline.result import StageResult


@dataclass
class CostRecord:
    """A single cost record for one stage execution."""

    timestamp: str
    stage_name: str
    model_id: str
    provider: str
    tool: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    num_turns: int = 0
    duration_ms: int = 0


class CostTracker:
    """Tracks per-stage token usage and estimated costs."""

    def __init__(self, output_dir: Path | None = None) -> None:
        self.records: list[CostRecord] = []
        self.output_dir = output_dir or Path("data/costs")
        self.logger = get_logger("cost_tracker", category="COST")

    def record(self, stage_name: str, result: StageResult, tool: str = "claude") -> None:
        """Record cost from a stage result."""
        rec = CostRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            stage_name=stage_name,
            model_id=result.model_id,
            provider=result.provider,
            tool=tool,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
            num_turns=result.num_turns,
            duration_ms=result.duration_ms,
        )
        self.records.append(rec)
        self.logger.info(
            "%s | tool=%s | model=%s | in=%d out=%d | $%.4f",
            stage_name,
            tool,
            rec.model_id,
            rec.tokens_in,
            rec.tokens_out,
            rec.cost_usd,
        )

    def summary(self) -> dict:
        """Return a summary dict of costs by stage."""
        by_stage: dict[str, float] = {}
        for r in self.records:
            by_stage[r.stage_name] = by_stage.get(r.stage_name, 0.0) + r.cost_usd

        total_tokens_in = sum(r.tokens_in for r in self.records)
        total_tokens_out = sum(r.tokens_out for r in self.records)
        total_cost = sum(r.cost_usd for r in self.records)
        total_duration_ms = sum(r.duration_ms for r in self.records)

        return {
            "total_cost_usd": total_cost,
            "by_stage": by_stage,
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "total_duration_ms": total_duration_ms,
            "record_count": len(self.records),
            "records": [asdict(r) for r in self.records],
        }

    def save_csv(self, run_id: str) -> Path:
        """Save cost records to CSV."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{run_id}_costs.csv"
        fieldnames = [
            "timestamp", "stage_name", "model_id", "provider", "tool",
            "tokens_in", "tokens_out", "cost_usd", "num_turns", "duration_ms",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for rec in self.records:
                writer.writerow(asdict(rec))
        self.logger.info("Cost report saved to %s", path)
        return path

    def generate_summary_md(
        self,
        run_id: str,
        user_request: str,
        success: bool,
        review_passed: bool | None = None,
        review_iterations: int = 0,
        git_diff_stat: str = "",
        verify_results: list[dict] | None = None,
    ) -> str:
        """Generate a human-readable RUN_SUMMARY.md report.

        Args:
            run_id: Pipeline run ID
            user_request: Original user request
            success: Whether the pipeline succeeded overall
            review_passed: Whether the review stage passed (None if no review)
            review_iterations: Number of review iterations
            git_diff_stat: Output of `git diff --stat` (empty if unavailable)
            verify_results: List of verification agent results (for multi-verify)

        Returns:
            Markdown string suitable for writing to RUN_SUMMARY.md
        """
        summary = self.summary()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        status = "PASS" if success else "FAIL"
        status_icon = "\\u2705" if success else "\\u274c"

        lines = [
            f"# Run Summary — {now}",
            "",
            "## Request",
            f'"{user_request}"',
            "",
            f"## Result: {status_icon} {status}",
        ]

        # Review info
        if review_passed is not None:
            review_status = "PASS" if review_passed else "FAIL"
            lines.append(f"- Review: {review_status} (after {review_iterations} iteration(s))")

        # Verification info
        if verify_results:
            lines.append("")
            lines.append("### Verification Consensus")
            passes = sum(1 for v in verify_results if v.get("passed"))
            total = len(verify_results)
            lines.append(f"- **{passes}/{total}** verifiers agreed: {status}")
            for v in verify_results:
                v_icon = "\\u2705" if v.get("passed") else "\\u274c"
                lines.append(f"  - {v.get('model', '?')}: {v_icon}")

        lines.append("")
        lines.append("## Cost Breakdown")
        lines.append("")
        lines.append("| Stage | Model | Tokens In | Tokens Out | Cost | Time |")
        lines.append("|-------|-------|-----------|------------|------|------|")

        for rec in self.records:
            time_str = _format_duration(rec.duration_ms)
            tokens_in_str = f"{rec.tokens_in:,}" if rec.tokens_in else "—"
            tokens_out_str = f"{rec.tokens_out:,}" if rec.tokens_out else "—"
            cost_str = f"${rec.cost_usd:.4f}" if rec.cost_usd > 0 else "—"
            model_short = rec.model_id.split("/")[-1] if "/" in rec.model_id else rec.model_id
            lines.append(
                f"| {rec.stage_name} | {model_short} | {tokens_in_str} | "
                f"{tokens_out_str} | {cost_str} | {time_str} |"
            )

        # Totals row
        total_in = f"{summary['total_tokens_in']:,}" if summary["total_tokens_in"] else "—"
        total_out = f"{summary['total_tokens_out']:,}" if summary["total_tokens_out"] else "—"
        total_cost = f"${summary['total_cost_usd']:.4f}"
        total_time = _format_duration(summary["total_duration_ms"])
        lines.append(f"| **Total** | | **{total_in}** | **{total_out}** | **{total_cost}** | **{total_time}** |")

        # Files changed
        if git_diff_stat:
            lines.extend(["", "## Files Changed", "", "```", git_diff_stat, "```"])

        lines.extend(["", f"---", f"Run ID: `{run_id}`", ""])
        return "\n".join(lines)

    def save_summary_md(
        self,
        workspace_path: str,
        run_id: str,
        user_request: str,
        success: bool,
        review_passed: bool | None = None,
        review_iterations: int = 0,
        git_diff_stat: str = "",
        verify_results: list[dict] | None = None,
    ) -> Path:
        """Generate and save RUN_SUMMARY.md to the workspace.

        Returns:
            Path to the written file
        """
        md = self.generate_summary_md(
            run_id=run_id,
            user_request=user_request,
            success=success,
            review_passed=review_passed,
            review_iterations=review_iterations,
            git_diff_stat=git_diff_stat,
            verify_results=verify_results,
        )
        path = Path(workspace_path) / "RUN_SUMMARY.md"
        path.write_text(md, encoding="utf-8")
        self.logger.info("Run summary saved to %s", path)
        return path

    def format_terminal_summary(self) -> str:
        """Format a colorized terminal summary for printing after a run.

        Returns:
            Multi-line string with ANSI colors for terminal display
        """
        summary = self.summary()
        if not self.records:
            return "  No cost records."

        GREEN = "\033[32m"
        CYAN = "\033[36m"
        YELLOW = "\033[33m"
        BOLD = "\033[1m"
        DIM = "\033[2m"
        RESET = "\033[0m"

        lines = [
            "",
            f"  {BOLD}Cost Breakdown{RESET}",
            f"  {'Stage':<25} {'Model':<25} {'Tokens':>12} {'Cost':>10} {'Time':>8}",
            f"  {DIM}{'—' * 82}{RESET}",
        ]

        for rec in self.records:
            total_tokens = rec.tokens_in + rec.tokens_out
            tokens_str = f"{total_tokens:,}" if total_tokens else "—"
            cost_str = f"${rec.cost_usd:.4f}" if rec.cost_usd > 0 else "—"
            time_str = _format_duration(rec.duration_ms)
            model_short = rec.model_id.split("/")[-1] if "/" in rec.model_id else rec.model_id
            if len(model_short) > 24:
                model_short = model_short[:21] + "..."

            lines.append(
                f"  {rec.stage_name:<25} {model_short:<25} {tokens_str:>12} "
                f"{YELLOW}{cost_str:>10}{RESET} {DIM}{time_str:>8}{RESET}"
            )

        total_tokens = summary["total_tokens_in"] + summary["total_tokens_out"]
        lines.append(f"  {DIM}{'—' * 82}{RESET}")
        lines.append(
            f"  {BOLD}{'Total':<25} {'':<25} {total_tokens:>12,} "
            f"{GREEN}${summary['total_cost_usd']:.4f}{RESET}{'':<1} "
            f"{DIM}{_format_duration(summary['total_duration_ms']):>7}{RESET}"
        )
        lines.append("")

        return "\n".join(lines)


def _format_duration(ms: int) -> str:
    """Format milliseconds into a human-readable string."""
    if ms <= 0:
        return "—"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m{secs:02d}s"
