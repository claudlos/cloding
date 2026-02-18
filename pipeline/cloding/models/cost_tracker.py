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

    def record(self, stage_name: str, result: StageResult) -> None:
        """Record cost from a stage result."""
        rec = CostRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            stage_name=stage_name,
            model_id=result.model_id,
            provider=result.provider,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
            num_turns=result.num_turns,
            duration_ms=result.duration_ms,
        )
        self.records.append(rec)
        self.logger.info(
            "%s | model=%s | in=%d out=%d | $%.4f",
            stage_name,
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
        return {
            "total_cost_usd": sum(r.cost_usd for r in self.records),
            "by_stage": by_stage,
            "total_tokens_in": sum(r.tokens_in for r in self.records),
            "total_tokens_out": sum(r.tokens_out for r in self.records),
            "record_count": len(self.records),
        }

    def save_csv(self, run_id: str) -> Path:
        """Save cost records to CSV."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{run_id}_costs.csv"
        fieldnames = [
            "timestamp", "stage_name", "model_id", "provider",
            "tokens_in", "tokens_out", "cost_usd", "num_turns", "duration_ms",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for rec in self.records:
                writer.writerow(asdict(rec))
        self.logger.info("Cost report saved to %s", path)
        return path
