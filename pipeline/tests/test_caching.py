"""Tests for exploration result caching."""

import asyncio
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cloding.core.config import PipelineConfig, StageConfig, ModelConfig
from cloding.pipeline.pipeline import Pipeline
from cloding.pipeline.result import RunResult, StageResult
from cloding.runners.base import BaseRunner


class FakeRunner(BaseRunner):
    async def run(self, binary_name, env, cli_args, timeout):
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
    
    # Need to mock create_stage to simulate CONTEXT.md creation
    with patch("cloding.pipeline.pipeline.create_stage") as mock_create_stage:
        mock_stage = MagicMock()
        
        # We use a regular function that returns a future/coroutine to avoid pickling issues with AsyncMock
        async def mock_run_impl(*args, **kwargs):
            (workspace / "CONTEXT.md").write_text("Gathered context", encoding="utf-8")
            return StageResult(
                stage_name="explore", output="ok", success=True, model_id="q"
            )
            
        mock_stage.run = mock_run_impl
        mock_stage.tool_handler = MagicMock()
        mock_stage.tool_handler.get_binary_name.return_value = "claude"
        mock_create_stage.return_value = mock_stage
        
        result = await pipeline.run(user_request="test")
        assert result.success
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
        result = await pipeline2.run(user_request="test")
        
        # Verify stage was NOT created/run (because it was loaded from cache)
        assert not mock_create_stage.called
        assert result.success
        assert result.stage_results[0].model_id == "cache"
        assert (workspace / "CONTEXT.md").read_text(encoding="utf-8") == "Gathered context"
