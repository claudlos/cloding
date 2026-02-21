"""Tests for exploration result caching."""

import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cloding.core.config import PipelineConfig, StageConfig, ModelConfig
from cloding.pipeline.pipeline import Pipeline
from cloding.pipeline.result import RunResult
from cloding.runners.base import BaseRunner


class FakeRunner(BaseRunner):
    async def run(self, env, cli_args, timeout):
        return RunResult(exit_code=0, stdout="Success", stderr="")


@pytest.fixture
def pipeline_config(tmp_path):
    return PipelineConfig(
        name="test",
        workspace_path=str(tmp_path / "workspace"),
        models={
            "qwen": ModelConfig(name="qwen", provider="openrouter", model_id="q", api_key_env="K")
        },
        stages=[
            StageConfig(name="explore", model="qwen", prompt_file="explore.txt")
        ]
    )


@pytest.mark.asyncio
async def test_explore_caching(tmp_path, pipeline_config):
    workspace = Path(pipeline_config.workspace_path)
    workspace.mkdir(parents=True)
    (workspace / "file.py").write_text("print('hello')", encoding="utf-8")
    
    # Mock runner
    runner = FakeRunner()
    
    # First run - should call runner and cache
    pipeline = Pipeline(
        config=pipeline_config,
        runner=runner,
        prompts_dir=str(tmp_path / "prompts"),
        data_dir=str(tmp_path / "runs"),
        cache_dir=str(tmp_path / "cache"),
    )
    
    # Create a fake CONTEXT.md during first run (simulated by stage)
    async def mock_run_with_side_effect(*args, **kwargs):
        (workspace / "CONTEXT.md").write_text("Gathered context", encoding="utf-8")
        return RunResult(exit_code=0, stdout="Success", stderr="")

    with patch.object(FakeRunner, "run", side_effect=mock_run_with_side_effect) as mock_run:
        with patch("cloding.pipeline.pipeline.create_stage") as mock_create_stage:
            mock_stage = AsyncMock()
            mock_stage.run.return_value = StageResult(
                stage_name="explore", output="ok", success=True, model_id="q"
            )
            # Need to actually write CONTEXT.md in the mock
            async def side_effect(*args, **kwargs):
                (workspace / "CONTEXT.md").write_text("Gathered context", encoding="utf-8")
                return mock_stage.run.return_value
            mock_stage.run.side_effect = side_effect
            mock_create_stage.return_value = mock_stage
            
            result = await pipeline.run(user_request="test")
            assert mock_stage.run.called
            assert (tmp_path / "cache" / "explore").exists()
            assert len(list((tmp_path / "cache" / "explore").iterdir())) == 1

    # Second run - should skip runner and use cache
    # Delete CONTEXT.md to ensure it's restored from cache
    (workspace / "CONTEXT.md").unlink()
    
    pipeline2 = Pipeline(
        config=pipeline_config,
        runner=runner,
        prompts_dir=str(tmp_path / "prompts"),
        data_dir=str(tmp_path / "runs"),
        cache_dir=str(tmp_path / "cache"),
    )
    
    with patch("cloding.pipeline.pipeline.create_stage") as mock_create_stage:
        mock_stage = AsyncMock()
        mock_create_stage.return_value = mock_stage
        
        result = await pipeline2.run(user_request="test")
        
        # Verify stage was NOT created/run
        assert not mock_create_stage.called
        assert result.success
        assert result.stage_results[0].model_id == "cache"
        assert (workspace / "CONTEXT.md").read_text(encoding="utf-8") == "Gathered context"

from cloding.pipeline.result import StageResult
