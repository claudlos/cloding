"""Tests for cost tracking and CSV export."""

from pathlib import Path

import pytest

from osq.models.cost_tracker import CostRecord, CostTracker
from osq.pipeline.result import StageResult


@pytest.fixture
def tracker(tmp_path: Path) -> CostTracker:
    return CostTracker(output_dir=tmp_path)


def _make_result(stage: str, cost: float, tokens_in: int = 100, tokens_out: int = 50) -> StageResult:
    return StageResult(
        stage_name=stage,
        output="test output",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost,
        success=True,
        model_id="test/model",
        provider="openrouter",
        num_turns=5,
        duration_ms=1000,
    )


def test_record_and_summary(tracker: CostTracker):
    tracker.record("plan", _make_result("plan", 0.50))
    tracker.record("code", _make_result("code", 0.10))

    summary = tracker.summary()
    assert summary["total_cost_usd"] == pytest.approx(0.60)
    assert summary["by_stage"]["plan"] == pytest.approx(0.50)
    assert summary["by_stage"]["code"] == pytest.approx(0.10)
    assert summary["total_tokens_in"] == 200
    assert summary["total_tokens_out"] == 100
    assert summary["record_count"] == 2


def test_save_csv(tracker: CostTracker, tmp_path: Path):
    tracker.record("plan", _make_result("plan", 0.42))
    path = tracker.save_csv("test-run-001")

    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "plan" in content
    assert "0.42" in content
    assert "test/model" in content


def test_empty_summary(tracker: CostTracker):
    summary = tracker.summary()
    assert summary["total_cost_usd"] == 0.0
    assert summary["record_count"] == 0
