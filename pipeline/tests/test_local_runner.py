"""Tests for local runner (mocked subprocess) and binary resolution."""

import asyncio
import json
import os
import platform
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cloding.core.errors import StageError
from cloding.runners.base import BaseRunner
from cloding.runners.local_runner import LocalRunner, _resolve_binary

_MODULE = "cloding.runners.local_runner"


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

    def test_parse_empty_string(self):
        parsed = BaseRunner.parse_json_output("")
        assert parsed == {}

    def test_parse_json_with_nested_objects(self):
        """JSON with nested objects should parse correctly (tests brace depth tracking)."""
        stdout = 'Preamble text\n{"result": {"nested": "value"}, "cost": 0.01}'
        parsed = BaseRunner.parse_json_output(stdout)
        assert parsed["result"] == {"nested": "value"}
        assert parsed["cost"] == 0.01

    def test_parse_invalid_json_between_braces(self):
        """Stdout with braces wrapping invalid JSON should fall through to empty dict."""
        stdout = "some text {this is not valid json} more text"
        parsed = BaseRunner.parse_json_output(stdout)
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

    def test_build_run_result_no_json(self):
        result = BaseRunner.build_run_result(exit_code=1, stdout="error text", stderr="fail")
        assert result.exit_code == 1
        assert result.stdout == "error text"
        assert result.tokens_in == 0

    def test_build_run_result_is_error_402(self):
        stdout = json.dumps({
            "result": "402 error: insufficient credits",
            "is_error": True,
        })
        result = BaseRunner.build_run_result(exit_code=1, stdout=stdout, stderr="")
        assert "credits" in result.stderr.lower()


class TestResolveBinary:
    def test_not_found_raises(self):
        with patch("shutil.which", return_value=None):
            with pytest.raises(StageError, match="Claude Code CLI not found"):
                _resolve_binary("claude")

    def test_copilot_not_found_raises(self):
        with patch("shutil.which", return_value=None):
            with pytest.raises(StageError, match="GitHub Copilot CLI not found"):
                _resolve_binary("github-copilot")

    def test_generic_binary_not_found_raises(self):
        with patch("shutil.which", return_value=None):
            with pytest.raises(StageError, match="Binary 'some-tool' not found"):
                _resolve_binary("some-tool")

    def test_copilot_linux_returns_path(self):
        with patch("shutil.which", return_value="/usr/local/bin/github-copilot"):
            with patch("platform.system", return_value="Linux"):
                exe, prefix = _resolve_binary("github-copilot")
                assert exe == "/usr/local/bin/github-copilot"
                assert prefix == []

    def test_copilot_windows_cmd_fallback(self, tmp_path):
        """On Windows with .CMD wrapper for copilot, should fall back to cmd /c."""
        cmd_path = str(tmp_path / "github-copilot.cmd")

        with patch("shutil.which", return_value=cmd_path):
            with patch("platform.system", return_value="Windows"):
                with patch.dict(os.environ, {"COMSPEC": "C:\\Windows\\cmd.exe"}):
                    exe, prefix = _resolve_binary("github-copilot")
                    assert exe == "C:\\Windows\\cmd.exe"
                    assert "/c" in prefix
                    assert cmd_path in prefix

    def test_non_windows_returns_path(self):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            with patch("platform.system", return_value="Linux"):
                exe, prefix = _resolve_binary("claude")
                assert exe == "/usr/local/bin/claude"
                assert prefix == []

    def test_windows_cmd_wrapper_with_cli_js(self, tmp_path):
        """On Windows with .CMD wrapper, should resolve to node + cli.js."""
        cmd_path = str(tmp_path / "claude.cmd")
        # Create the cli.js file where expected
        cli_js_dir = tmp_path / "node_modules" / "@anthropic-ai" / "claude-code"
        cli_js_dir.mkdir(parents=True)
        cli_js = cli_js_dir / "cli.js"
        cli_js.write_text("// cli", encoding="utf-8")

        with patch("shutil.which", return_value=cmd_path):
            with patch("platform.system", return_value="Windows"):
                # Also mock shutil.which for node
                original_which = __import__("shutil").which

                def _patched_which(name):
                    if name == "claude":
                        return cmd_path
                    if name == "node":
                        return "/usr/bin/node"
                    return original_which(name)

                with patch("shutil.which", side_effect=_patched_which):
                    exe, prefix = _resolve_binary("claude")
                    assert exe == "/usr/bin/node"
                    assert str(cli_js) in prefix

    def test_windows_cmd_wrapper_cli_js_exists_but_no_node(self, tmp_path):
        """On Windows with .CMD wrapper and cli.js, but node not found, should fall back."""
        cmd_path = str(tmp_path / "claude.cmd")
        cli_js_dir = tmp_path / "node_modules" / "@anthropic-ai" / "claude-code"
        cli_js_dir.mkdir(parents=True)
        cli_js = cli_js_dir / "cli.js"
        cli_js.write_text("// cli", encoding="utf-8")

        with patch("shutil.which", return_value=cmd_path):
            with patch("platform.system", return_value="Windows"):
                def _patched_which(name):
                    if name == "claude":
                        return cmd_path
                    # node is NOT found, claude.exe is NOT found
                    return None

                with patch("shutil.which", side_effect=_patched_which):
                    with patch.dict(os.environ, {"COMSPEC": "C:\\Windows\\cmd.exe"}):
                        exe, prefix = _resolve_binary("claude")
                        # Should fall through to COMSPEC since node is not found
                        assert exe == "C:\\Windows\\cmd.exe"
                        assert "/c" in prefix

    def test_windows_cmd_wrapper_fallback_to_comspec(self, tmp_path):
        """On Windows with .CMD wrapper but no cli.js, falls back to cmd /c."""
        cmd_path = str(tmp_path / "claude.cmd")

        with patch("shutil.which", return_value=cmd_path):
            with patch("platform.system", return_value="Windows"):
                # No claude.exe either
                def _patched_which(name):
                    if name == "claude":
                        return cmd_path
                    return None

                with patch("shutil.which", side_effect=_patched_which):
                    with patch.dict(os.environ, {"COMSPEC": "C:\\Windows\\cmd.exe"}):
                        exe, prefix = _resolve_binary("claude")
                        assert exe == "C:\\Windows\\cmd.exe"
                        assert "/c" in prefix

    def test_windows_cmd_wrapper_comspec_default(self, tmp_path):
        """On Windows with .CMD wrapper and no COMSPEC env, should default to cmd.exe."""
        cmd_path = str(tmp_path / "claude.cmd")

        with patch("shutil.which", return_value=cmd_path):
            with patch("platform.system", return_value="Windows"):
                def _patched_which(name):
                    if name == "claude":
                        return cmd_path
                    return None

                with patch("shutil.which", side_effect=_patched_which):
                    with patch.dict(os.environ, {}, clear=True):
                        exe, prefix = _resolve_binary("claude")
                        assert exe == "cmd.exe"
                        assert "/c" in prefix

    def test_windows_cmd_fallback_to_claude_exe(self, tmp_path):
        """On Windows with .CMD wrapper, no cli.js but claude.exe exists."""
        cmd_path = str(tmp_path / "claude.cmd")

        with patch("shutil.which", return_value=cmd_path):
            with patch("platform.system", return_value="Windows"):
                def _patched_which(name):
                    if name == "claude":
                        return cmd_path
                    if name == "claude.exe":
                        return "C:\\Program Files\\claude.exe"
                    return None

                with patch("shutil.which", side_effect=_patched_which):
                    exe, prefix = _resolve_binary("claude")
                    assert exe == "C:\\Program Files\\claude.exe"
                    assert prefix == []


@pytest.mark.asyncio(loop_scope="function")
class TestLocalRunnerRun:
    async def test_successful_run(self):
        runner = LocalRunner(workspace_path="/tmp/workspace")
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(b'{"result":"ok","total_cost_usd":0.01}', b"")
        )

        with patch(f"{_MODULE}._resolve_binary", return_value=("/usr/bin/claude", [])):
            with patch(f"{_MODULE}._launch", return_value=mock_proc):
                result = await runner.run(
                    binary_name="claude",
                    env={"ANTHROPIC_MODEL": "qwen"},
                    cli_args=["-p", "test"],
                    timeout=60,
                )
        assert result.exit_code == 0

    async def test_timeout_returns_error(self):
        runner = LocalRunner()
        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch(f"{_MODULE}._resolve_binary", return_value=("/usr/bin/claude", [])):
            with patch(f"{_MODULE}._launch", return_value=mock_proc):
                result = await runner.run(binary_name="claude", env={}, cli_args=[], timeout=1)
        assert result.exit_code == -1
        assert "Timed out" in result.stderr

    async def test_timeout_with_proc_already_exited(self):
        """Timeout where process already exited should skip kill."""
        runner = LocalRunner()
        mock_proc = AsyncMock()
        mock_proc.returncode = 1  # Already exited
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch(f"{_MODULE}._resolve_binary", return_value=("/usr/bin/claude", [])):
            with patch(f"{_MODULE}._launch", return_value=mock_proc):
                result = await runner.run(binary_name="claude", env={}, cli_args=[], timeout=1)
        assert result.exit_code == -1
        assert "Timed out" in result.stderr
        mock_proc.kill.assert_not_called()

    async def test_os_error_raises_stage_error(self):
        runner = LocalRunner()
        with patch(f"{_MODULE}._resolve_binary", return_value=("/usr/bin/claude", [])):
            with patch(f"{_MODULE}._launch", side_effect=OSError("exec failed")):
                with pytest.raises(StageError, match="Local runner failed"):
                    await runner.run(binary_name="claude", env={}, cli_args=[], timeout=60)

    async def test_os_error_kills_running_proc(self):
        """When OSError occurs after proc is launched, proc should be killed."""
        runner = LocalRunner()
        mock_proc = AsyncMock()
        mock_proc.returncode = None  # proc still running
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=OSError("broken pipe"))

        async def _fake_launch(*args, **kwargs):
            return mock_proc

        with patch(f"{_MODULE}._resolve_binary", return_value=("/usr/bin/claude", [])):
            with patch(f"{_MODULE}._launch", side_effect=_fake_launch):
                with pytest.raises(StageError, match="Local runner failed"):
                    await runner.run(binary_name="claude", env={}, cli_args=[], timeout=60)

        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_awaited_once()

    async def test_claudecode_env_stripped(self):
        """CLAUDECODE env var should be removed from child process."""
        runner = LocalRunner()
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"{}", b""))

        captured_env = {}

        async def _capture_launch(*args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return mock_proc

        with patch(f"{_MODULE}._resolve_binary", return_value=("/usr/bin/claude", [])):
            with patch(f"{_MODULE}._launch", side_effect=_capture_launch):
                with patch.dict(os.environ, {"CLAUDECODE": "1"}):
                    await runner.run(binary_name="claude", env={}, cli_args=[], timeout=60)

        assert "CLAUDECODE" not in captured_env
