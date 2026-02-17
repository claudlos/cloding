"""Mutable pipeline state threaded through stages."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from osq.pipeline.result import StageResult


@dataclass
class CodingTask:
    """A single unit of work for fan-out coding."""

    task_id: str
    description: str
    files_to_modify: list[str] = field(default_factory=list)
    context: str = ""
    priority: int = 1


@dataclass
class PipelineState:
    """Mutable state threaded through pipeline stages."""

    user_request: str = ""
    context_files: list[str] = field(default_factory=list)

    # Stage outputs
    plan_output: str = ""
    exploration_output: str = ""
    code_outputs: list[str] = field(default_factory=list)
    review_feedback: str = ""

    # Fan-out
    coding_tasks: list[dict] = field(default_factory=list)

    # Review loop
    review_iteration: int = 0
    review_passed: bool = False

    # Tracking
    stage_results: list[dict] = field(default_factory=list)
    session_ids: dict[str, str] = field(default_factory=dict)
    total_cost_usd: float = 0.0

    # Run metadata
    run_id: str = ""
    current_stage: str = ""

    def add_stage_result(self, result: StageResult) -> None:
        """Record a stage result and update totals."""
        self.stage_results.append({
            "stage_name": result.stage_name,
            "cost_usd": result.cost_usd,
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
            "success": result.success,
            "model_id": result.model_id,
        })
        self.total_cost_usd += result.cost_usd
        if result.session_id:
            self.session_ids[result.stage_name] = result.session_id

    def save_checkpoint(self, path: Path) -> None:
        """Serialize state to JSON for resume capability."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load_checkpoint(cls, path: Path) -> "PipelineState":
        """Deserialize state from JSON checkpoint."""
        data = json.loads(path.read_text(encoding="utf-8"))
        try:
            return cls(**data)
        except TypeError as err:
            raise ValueError(
                f"Corrupted checkpoint at {path}: {err}. "
                f"Delete the checkpoint and restart the pipeline."
            ) from err

    def set_coding_tasks(self, tasks: list[CodingTask]) -> None:
        """Store coding tasks as dicts for JSON serialization."""
        self.coding_tasks = [asdict(t) for t in tasks]

    def get_coding_tasks(self) -> list[CodingTask]:
        """Reconstruct CodingTask objects from stored dicts."""
        return [CodingTask(**t) for t in self.coding_tasks]
