"""Tests for orchestrator: run_id validation, dry run, config loading, summary."""

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osq.core.config import (
    DockerConfig,
    FanoutConfig,
    ModelConfig,
    PipelineConfig,
    ReviewConfig,
    StageConfig,
)
from osq.orchestrator import _print_dry_run, _print_summary
from osq.pipeline.result import PipelineResult
from osq.pipeline.state import PipelineState


class TestRunIdValidation:
    """Test the run_id regex validation used in orchestrator.py."""

    def test_valid_run_ids(self):
        valid = [
            "20250216-123456-abc123",
            "test-run",
            "simple",
            "with_underscores",
            "MixedCase123",
        ]
        for rid in valid:
            assert re.fullmatch(r"[\w\-]+", rid), f"Should be valid: {rid}"

    def test_invalid_run_ids(self):
        invalid = [
            "../etc/passwd",
            "../../secret",
            "path/traversal",
            "has spaces",
            "has;semicolon",
            "",
            "run$id",
        ]
        for rid in invalid:
            assert not re.fullmatch(r"[\w\-]+", rid), f"Should be invalid: {rid}"


class TestCheckpointResumeValidation:
    def test_corrupted_checkpoint_raises_valueerror(self, tmp_path):
        # Write a JSON file with an extra unknown field
        checkpoint = tmp_path / "state.json"
        checkpoint.write_text('{"user_request": "test", "bogus_field": 42}', encoding="utf-8")

        with pytest.raises(ValueError, match="Corrupted checkpoint"):
            PipelineState.load_checkpoint(checkpoint)

    def test_valid_checkpoint_loads(self, tmp_path):
        state = PipelineState(user_request="hello", run_id="r1")
        checkpoint = tmp_path / "state.json"
        state.save_checkpoint(checkpoint)
        loaded = PipelineState.load_checkpoint(checkpoint)
        assert loaded.user_request == "hello"
        assert loaded.run_id == "r1"


def _make_config(**kwargs):
    defaults = dict(
        name="test-pipeline",
        models={
            "qwen": ModelConfig(
                name="qwen",
                provider="openrouter",
                model_id="qwen/qwen3-coder-next",
                api_key_env="OPENROUTER_API_KEY",
                cost_per_mtok_input=0.07,
                cost_per_mtok_output=0.30,
            ),
        },
        stages=[
            StageConfig(name="plan", model="qwen", prompt_file="prompts/plan.txt"),
            StageConfig(name="code", model="qwen", prompt_file="prompts/code.txt"),
        ],
        fanout=FanoutConfig(),
        review=ReviewConfig(max_iterations=2, pass_threshold="PASS"),
        docker=DockerConfig(),
    )
    defaults.update(kwargs)
    return PipelineConfig(**defaults)


class TestPrintDryRun:
    """Test the _print_dry_run function."""

    def test_dry_run_does_not_raise(self):
        config = _make_config()
        # Should not raise
        _print_dry_run(config)

    def test_dry_run_with_fanout(self):
        config = _make_config(fanout=FanoutConfig(enabled=True, max_parallel=3))
        _print_dry_run(config)


class TestPrintSummary:
    """Test the _print_summary function."""

    def test_success_summary(self):
        result = PipelineResult(
            success=True,
            run_id="test-123",
            total_cost_usd=0.05,
            cost_breakdown={"plan": 0.02, "code": 0.03},
            review_passed=True,
            review_iterations=1,
            stage_results=[],
        )
        # Should not raise
        _print_summary(result, "/workspace")

    def test_failure_summary(self):
        result = PipelineResult(
            success=False,
            run_id="test-456",
            error="Stage 'code' failed",
        )
        _print_summary(result, "/workspace")

    def test_no_cost_breakdown(self):
        result = PipelineResult(
            success=True,
            run_id="test-789",
        )
        _print_summary(result, "/workspace")


@pytest.mark.asyncio(loop_scope="function")
class TestRunPipelineDryRun:
    """Test the run_pipeline function in dry-run mode."""

    async def test_dry_run_returns_success(self, tmp_path):
        """dry_run should return success without running stages."""
        # Create a minimal valid config file
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
name: test
models:
  qwen:
    provider: openrouter
    model_id: qwen/qwen3-coder-next
    api_key_env: OPENROUTER_API_KEY
    cost_per_mtok_input: 0.07
    cost_per_mtok_output: 0.30
stages:
  - name: plan
    model: qwen
    prompt_file: prompts/plan.txt
  - name: code
    model: qwen
    prompt_file: prompts/code.txt
""", encoding="utf-8")

        from osq.orchestrator import run_pipeline
        result = await run_pipeline(
            request="test request",
            config_path=str(config_file),
            workspace=str(tmp_path),
            dry_run=True,
        )
        assert result.success is True
        assert result.run_id == "dry-run"

    async def test_dry_run_no_workspace_override(self, tmp_path):
        """dry_run with empty workspace should not override config's workspace_path."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
name: test
models:
  qwen:
    provider: openrouter
    model_id: qwen/qwen3-coder-next
    api_key_env: OPENROUTER_API_KEY
    cost_per_mtok_input: 0.07
    cost_per_mtok_output: 0.30
stages:
  - name: code
    model: qwen
    prompt_file: prompts/code.txt
""", encoding="utf-8")

        from osq.orchestrator import run_pipeline
        result = await run_pipeline(
            request="test request",
            config_path=str(config_file),
            workspace="",
            dry_run=True,
        )
        assert result.success is True

    async def test_invalid_run_id_raises(self, tmp_path):
        """Invalid run_id should raise ValueError."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
name: test
models:
  qwen:
    provider: openrouter
    model_id: qwen/qwen3-coder-next
    api_key_env: OPENROUTER_API_KEY
    cost_per_mtok_input: 0.07
    cost_per_mtok_output: 0.30
stages:
  - name: code
    model: qwen
    prompt_file: prompts/code.txt
""", encoding="utf-8")

        from osq.orchestrator import run_pipeline
        with patch("osq.orchestrator.prepare_workspace", new_callable=AsyncMock, return_value=""):
            with patch("osq.orchestrator.LocalRunner") as MockRunner:
                MockRunner.return_value = MagicMock()
                with pytest.raises(ValueError, match="Invalid run_id"):
                    await run_pipeline(
                        request="test",
                        config_path=str(config_file),
                        workspace=str(tmp_path),
                        no_docker=True,
                        no_git=True,
                        resume_from="code",
                        run_id="../../../etc/passwd",
                    )


@pytest.mark.asyncio(loop_scope="function")
class TestRunPipelineFullPath:
    """Test the full run_pipeline paths (local + Docker)."""

    def _write_config(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
name: test
models:
  qwen:
    provider: openrouter
    model_id: qwen/qwen3-coder-next
    api_key_env: OPENROUTER_API_KEY
    cost_per_mtok_input: 0.07
    cost_per_mtok_output: 0.30
stages:
  - name: plan
    model: qwen
    prompt_file: prompts/plan.txt
  - name: code
    model: qwen
    prompt_file: prompts/code.txt
""", encoding="utf-8")
        return str(config_file)

    async def test_local_runner_full_run(self, tmp_path):
        """Full pipeline run with local runner (no Docker)."""
        from osq.orchestrator import run_pipeline
        from osq.pipeline.result import PipelineResult, StageResult

        config_path = self._write_config(tmp_path)

        mock_pipeline_result = PipelineResult(
            success=True,
            run_id="test-run",
            total_cost_usd=0.05,
            cost_breakdown={"plan": 0.02, "code": 0.03},
            stage_results=[
                StageResult(stage_name="plan", output="plan", success=True),
                StageResult(stage_name="code", output="code", success=True),
            ],
        )

        with patch("osq.orchestrator.prepare_workspace", new_callable=AsyncMock, return_value="cloding/test-branch"):
            with patch("osq.orchestrator.Pipeline") as MockPipeline:
                mock_pipe = MagicMock()
                mock_pipe.run = AsyncMock(return_value=mock_pipeline_result)
                MockPipeline.return_value = mock_pipe

                result = await run_pipeline(
                    request="Add auth",
                    config_path=config_path,
                    workspace=str(tmp_path),
                    no_docker=True,
                    no_git=True,
                )

        assert result.success is True
        assert result.run_id == "test-run"
        MockPipeline.assert_called_once()

    async def test_docker_runner_path(self, tmp_path):
        """Full pipeline run with Docker runner."""
        from osq.orchestrator import run_pipeline
        from osq.pipeline.result import PipelineResult

        config_path = self._write_config(tmp_path)

        mock_result = PipelineResult(success=True, run_id="docker-run")

        with patch("osq.orchestrator.prepare_workspace", new_callable=AsyncMock, return_value=""):
            with patch("osq.orchestrator.DockerRunner") as MockDocker:
                mock_docker_inst = MagicMock()
                MockDocker.return_value = mock_docker_inst
                MockDocker.ensure_image = AsyncMock()
                MockDocker.ensure_network = AsyncMock()

                with patch("osq.orchestrator.Pipeline") as MockPipeline:
                    mock_pipe = MagicMock()
                    mock_pipe.run = AsyncMock(return_value=mock_result)
                    MockPipeline.return_value = mock_pipe

                    result = await run_pipeline(
                        request="Add auth",
                        config_path=config_path,
                        workspace=str(tmp_path),
                        no_docker=False,
                        no_git=True,
                    )

        assert result.success is True
        MockDocker.ensure_image.assert_awaited_once()
        MockDocker.ensure_network.assert_awaited_once()

    async def test_resume_checkpoint_not_found(self, tmp_path):
        """Resume with missing checkpoint should log warning and start fresh."""
        from osq.orchestrator import run_pipeline
        from osq.pipeline.result import PipelineResult

        config_path = self._write_config(tmp_path)
        mock_result = PipelineResult(success=True, run_id="fresh")

        with patch("osq.orchestrator.prepare_workspace", new_callable=AsyncMock, return_value=""):
            with patch("osq.orchestrator.Pipeline") as MockPipeline:
                mock_pipe = MagicMock()
                mock_pipe.run = AsyncMock(return_value=mock_result)
                MockPipeline.return_value = mock_pipe

                result = await run_pipeline(
                    request="test",
                    config_path=config_path,
                    workspace=str(tmp_path),
                    no_docker=True,
                    no_git=True,
                    resume_from="code",
                    run_id="nonexistent-run",
                )

        # Should succeed (starts fresh when checkpoint not found)
        assert result.success is True

    async def test_resume_with_existing_checkpoint(self, tmp_path):
        """Resume with an existing checkpoint file should load state."""
        from osq.orchestrator import run_pipeline
        from osq.pipeline.result import PipelineResult
        from osq.pipeline.state import PipelineState

        config_path = self._write_config(tmp_path)

        # Create a valid checkpoint file
        state = PipelineState(user_request="original", run_id="existing-run")
        checkpoint_dir = Path("data/runs/existing-run")
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = checkpoint_dir / "state.json"
        state.save_checkpoint(checkpoint)

        mock_result = PipelineResult(success=True, run_id="existing-run")

        try:
            with patch("osq.orchestrator.prepare_workspace", new_callable=AsyncMock, return_value=""):
                with patch("osq.orchestrator.Pipeline") as MockPipeline:
                    mock_pipe = MagicMock()
                    mock_pipe.run = AsyncMock(return_value=mock_result)
                    MockPipeline.return_value = mock_pipe

                    result = await run_pipeline(
                        request="test",
                        config_path=config_path,
                        workspace=str(tmp_path),
                        no_docker=True,
                        no_git=True,
                        resume_from="code",
                        run_id="existing-run",
                    )

            assert result.success is True
            # Pipeline should have been called with resume_state
            call_kwargs = MockPipeline.return_value.run.call_args
            assert call_kwargs[1].get("resume_state") is not None
        finally:
            # Clean up the checkpoint file
            import shutil
            if Path("data/runs/existing-run").exists():
                shutil.rmtree("data/runs/existing-run")
            # Clean up empty parent dirs
            if Path("data/runs").exists() and not list(Path("data/runs").iterdir()):
                Path("data/runs").rmdir()
            if Path("data").exists() and not list(Path("data").iterdir()):
                Path("data").rmdir()

    async def test_verbose_sets_debug(self, tmp_path):
        """verbose=True should set DEBUG logging."""
        from osq.orchestrator import run_pipeline
        from osq.pipeline.result import PipelineResult

        config_path = self._write_config(tmp_path)
        mock_result = PipelineResult(success=True, run_id="v")

        with patch("osq.orchestrator.prepare_workspace", new_callable=AsyncMock, return_value=""):
            with patch("osq.orchestrator.Pipeline") as MockPipeline:
                mock_pipe = MagicMock()
                mock_pipe.run = AsyncMock(return_value=mock_result)
                MockPipeline.return_value = mock_pipe

                with patch("osq.orchestrator.init_logging") as mock_init:
                    result = await run_pipeline(
                        request="test",
                        config_path=config_path,
                        workspace=str(tmp_path),
                        no_docker=True,
                        no_git=True,
                        verbose=True,
                    )
                    mock_init.assert_called_with("DEBUG")
