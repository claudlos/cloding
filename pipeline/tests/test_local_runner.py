"""Tests for local runner (mocked subprocess)."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from osq.core.errors import StageError
from osq.runners.base import BaseRunner
from osq.runners.local_runner import LocalRunner


class TestBaseRunnerParsing:
    def test_parse_valid_json(self):
        stdout = json.dumps({
            "type": "result",
            "result": "Code written successfully",
            "cost_usd": 0.042,
            "session_id": "abc123",
            "num_turns": 5,
            "duration_ms": 15000,
            "input_tokens": 1000,
            "output_tokens": 500,
        })
        parsed = BaseRunner.parse_json_output(stdout)
        assert parsed["result"] == "Code written successfully"
        assert parsed["cost_usd"] == 0.042
        assert parsed["input_tokens"] == 1000

    def test_parse_json_with_preamble(self):
        stdout = 'Some startup text\n{"result": "ok", "cost_usd": 0.01}'
        parsed = BaseRunner.parse_json_output(stdout)
        assert parsed["result"] == "ok"

    def test_parse_invalid_json(self):
        parsed = BaseRunner.parse_json_output("not json at all")
        assert parsed == {}

    def test_build_run_result(self):
        """Test with actual Claude Code JSON output format."""
        stdout = json.dumps({
            "type": "result",
            "subtype": "success",
            "result": "done",
            "total_cost_usd": 0.05,
            "usage": {
                "input_tokens": 200,
                "output_tokens": 100,
                "cache_creation_input_tokens": 50,
                "cache_read_input_tokens": 30,
            },
            "session_id": "s1",
            "num_turns": 3,
            "duration_ms": 8000,
        })
        result = BaseRunner.build_run_result(exit_code=0, stdout=stdout, stderr="")
        assert result.stdout == "done"
        assert result.cost_usd == 0.05
        assert result.tokens_in == 280  # 200 + 50 + 30 cache tokens
        assert result.tokens_out == 100
        assert result.session_id == "s1"
        assert result.num_turns == 3
        assert result.duration_ms == 8000


class TestLocalRunner:
    def test_raises_if_claude_not_found(self):
        runner = LocalRunner()
        with patch("shutil.which", return_value=None):
            with pytest.raises(StageError, match="Claude Code CLI not found"):
                import asyncio
                asyncio.get_event_loop().run_until_complete(
                    runner.run(env={}, cli_args=["-p", "test"], timeout=60)
                )
