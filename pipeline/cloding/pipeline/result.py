"""Result dataclasses for pipeline stages and runs."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RunResult:
    """Raw result from a Claude Code CLI execution."""

    exit_code: int
    stdout: str
    stderr: str
    tokens_in: int = 0
    tokens_out: int = 0
    session_id: str = ""
    cost_usd: float = 0.0
    num_turns: int = 0
    duration_ms: int = 0


@dataclass
class StageResult:
    """Processed result from a single pipeline stage."""

    stage_name: str
    output: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    success: bool = True
    session_id: str = ""
    model_id: str = ""
    provider: str = ""
    num_turns: int = 0
    duration_ms: int = 0


@dataclass
class VerifyAgentResult:
    """Result from a single verification agent."""

    model: str
    passed: bool
    feedback: str = ""
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class PipelineResult:
    """Final result of a complete pipeline run."""

    success: bool
    total_cost_usd: float = 0.0
    cost_breakdown: dict = field(default_factory=dict)
    stage_results: list[StageResult] = field(default_factory=list)
    review_passed: bool = False
    review_iterations: int = 0
    run_id: str = ""
    error: Optional[str] = None
    verify_results: list[VerifyAgentResult] = field(default_factory=list)
    verify_consensus: bool = False
