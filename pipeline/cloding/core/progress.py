"""Real-time progress tracking for Cloding pipeline using Rich."""

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text


@dataclass
class StageProgress:
    """Status tracking for a single pipeline stage."""

    name: str
    model: str
    status: str = "pending"  # "pending", "running", "completed", "failed"
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    cost_usd: float = 0.0
    progress: int = 0  # 0 to 100
    details: str = ""


class ProgressTracker:
    """TUI tracker for pipeline execution progress."""

    def __init__(self, request: str, config_name: str, run_id: str) -> None:
        self.request = request
        self.config_name = config_name
        self.run_id = run_id
        self.stages: Dict[str, StageProgress] = {}
        self.console = Console()
        self.live: Optional[Live] = None
        self.overall_start_time = time.time()
        self.running_cost = 0.0

    def add_stage(self, name: str, model: str) -> None:
        """Initialize a stage in the tracker."""
        self.stages[name] = StageProgress(name=name, model=model)

    def start_stage(self, name: str) -> None:
        """Mark a stage as running."""
        if name in self.stages:
            self.stages[name].status = "running"
            self.stages[name].start_time = time.time()

    def update_stage(
        self,
        name: str,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        cost: Optional[float] = None,
        details: Optional[str] = None,
    ) -> None:
        """Update stage metrics."""
        if name in self.stages:
            s = self.stages[name]
            if status:
                s.status = status
                if status in ("completed", "failed"):
                    s.end_time = time.time()
            if progress is not None:
                s.progress = progress
            if cost is not None:
                delta = cost - s.cost_usd
                s.cost_usd = cost
                self.running_cost += delta
            if details is not None:
                s.details = details

    def _generate_table(self) -> Table:
        """Build the stages status table."""
        table = Table(box=None, expand=True)
        table.add_column("Stage", width=15)
        table.add_column("Model", width=20)
        table.add_column("Status", width=12)
        table.add_column("Time", width=10, justify="right")
        table.add_column("Cost", width=10, justify="right")
        table.add_column("Progress")

        for name, s in self.stages.items():
            # Icon and style based on status
            if s.status == "running":
                status_text = Text("⏳ Running", style="yellow")
                row_style = "bold white"
            elif s.status == "completed":
                status_text = Text("✅ Done", style="green")
                row_style = "dim"
            elif s.status == "failed":
                status_text = Text("❌ Failed", style="red")
                row_style = "bold red"
            else:
                status_text = Text("○ Pending", style="blue")
                row_style = "dim white"

            # Timing
            duration = ""
            if s.start_time:
                end = s.end_time or time.time()
                d = end - s.start_time
                duration = f"{d:.0f}s"

            cost_str = f"${s.cost_usd:.3f}" if s.cost_usd > 0 else "—"

            # Progress bar for running stages
            progress_bar = ""
            if s.status == "running":
                # Create a mini progress bar string
                filled = int(s.progress / 10)
                progress_bar = f"[{'█' * filled}{'░' * (10 - filled)}] {s.progress}%"
            elif s.status == "completed":
                progress_bar = "██████████ 100%"

            table.add_row(
                name.capitalize(),
                s.model,
                status_text,
                duration,
                cost_str,
                progress_bar,
                style=row_style,
            )

        return table

    def _generate_header(self) -> Panel:
        """Build the top header panel."""
        grid = Table.grid(expand=True)
        grid.add_column(style="bold cyan")
        grid.add_column(justify="right")

        grid.add_row(
            f"🚀 Request: {self.request[:60]}{'...' if len(self.request) > 60 else ''}",
            f"ID: [dim]{self.run_id}[/dim]",
        )
        grid.add_row(
            f"📁 Config: [blue]{self.config_name}[/blue]",
            f"Cost: [green]${self.running_cost:.3f}[/green]",
        )

        return Panel(grid, title="[bold white]Cloding Pipeline[/bold white]", border_style="cyan")

    def __enter__(self) -> "ProgressTracker":
        self.live = Live(
            self._get_renderable(),
            console=self.console,
            refresh_per_second=4,
            auto_refresh=True,
        )
        self.live.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.live:
            self.live.stop()

    def _get_renderable(self) -> Group:
        """Combine all panels into a single renderable group."""
        return Group(
            self._generate_header(),
            self._generate_table(),
        )
