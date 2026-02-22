"""Tests for tool handlers (CopilotHandler, and registry completeness)."""

import os
from unittest.mock import patch

import pytest

from cloding.core.config import ModelConfig, StageConfig
from cloding.core.tool_handler import (
    CopilotHandler,
    ClaudeCodeHandler,
    CodexHandler,
    GeminiHandler,
    OpenCodeHandler,
    TOOL_HANDLERS,
    get_tool_handler,
)


def _make_model(**kwargs):
    defaults = dict(
        name="copilot",
        provider="github",
        model_id="copilot",
        api_key_env="GITHUB_TOKEN",
        base_url=None,
        cost_per_mtok_input=0.0,
        cost_per_mtok_output=0.0,
    )
    defaults.update(kwargs)
    return ModelConfig(**defaults)


def _make_stage_config(**kwargs):
    defaults = dict(
        name="code",
        model="copilot",
        prompt_file="prompts/code.txt",
        max_turns=20,
        max_budget_usd=0.0,
        timeout_seconds=600,
        output_format="json",
    )
    defaults.update(kwargs)
    return StageConfig(**defaults)


class TestCopilotHandler:
    def test_build_env_sets_github_token(self):
        handler = CopilotHandler()
        model = _make_model()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"}):
            env = handler.build_env(model)
        assert env["GITHUB_TOKEN"] == "ghp_test123"

    def test_build_env_empty_token(self):
        handler = CopilotHandler()
        model = _make_model()
        with patch.dict(os.environ, {}, clear=True):
            env = handler.build_env(model)
        assert env["GITHUB_TOKEN"] == ""

    def test_build_cli_args_uses_dash_p(self):
        handler = CopilotHandler()
        model = _make_model()
        stage = _make_stage_config()
        args = handler.build_cli_args(stage, model, "Write some code")
        assert args == ["-p", "Write some code"]

    def test_build_cli_args_with_empty_prompt(self):
        handler = CopilotHandler()
        model = _make_model()
        stage = _make_stage_config()
        args = handler.build_cli_args(stage, model, "")
        assert args == ["-p", ""]

    def test_binary_name(self):
        handler = CopilotHandler()
        assert handler.get_binary_name() == "github-copilot"


class TestToolHandlerRegistry:
    def test_copilot_in_registry(self):
        assert "copilot" in TOOL_HANDLERS
        assert isinstance(TOOL_HANDLERS["copilot"], CopilotHandler)

    def test_all_handlers_registered(self):
        expected = {"claude-code", "gemini", "opencode", "codex", "copilot"}
        assert set(TOOL_HANDLERS.keys()) == expected

    def test_get_tool_handler_copilot(self):
        handler = get_tool_handler("copilot")
        assert isinstance(handler, CopilotHandler)

    def test_get_tool_handler_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            get_tool_handler("nonexistent-tool")


class TestClaudeCodeHandler:
    def test_build_env_openrouter(self):
        handler = ClaudeCodeHandler()
        model = _make_model(
            name="qwen", provider="openrouter",
            model_id="qwen/qwen3-coder-next",
            api_key_env="OPENROUTER_API_KEY",
            base_url="https://openrouter.ai/api",
        )
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-test"}):
            env = handler.build_env(model)
        assert env["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"
        assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-or-test"
        assert env["ANTHROPIC_API_KEY"] == ""
        assert env["ANTHROPIC_MODEL"] == "qwen/qwen3-coder-next"
        assert env["CLAUDECODE"] == ""

    def test_build_env_anthropic(self):
        handler = ClaudeCodeHandler()
        model = _make_model(
            name="sonnet", provider="anthropic",
            model_id="claude-sonnet-4-20250514",
            api_key_env="ANTHROPIC_API_KEY",
        )
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            env = handler.build_env(model)
        assert env["ANTHROPIC_API_KEY"] == "sk-ant-test"
        assert env["ANTHROPIC_MODEL"] == "claude-sonnet-4-20250514"
        assert "ANTHROPIC_BASE_URL" not in env

    def test_binary_name(self):
        assert ClaudeCodeHandler().get_binary_name() == "claude"


class TestGeminiHandler:
    def test_build_env_google(self):
        handler = GeminiHandler()
        model = _make_model(
            name="gemini", provider="google",
            model_id="gemini-2.5-pro",
            api_key_env="GOOGLE_API_KEY",
        )
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "gk-test"}):
            env = handler.build_env(model)
        assert env["GOOGLE_API_KEY"] == "gk-test"
        assert env["GEMINI_API_KEY"] == "gk-test"

    def test_build_cli_args(self):
        handler = GeminiHandler()
        model = _make_model(model_id="gemini-2.5-pro")
        stage = _make_stage_config()
        args = handler.build_cli_args(stage, model, "test prompt")
        assert "-p" in args
        assert "test prompt" in args
        assert "--non-interactive" in args
        assert "--model" in args
        assert "gemini-2.5-pro" in args

    def test_binary_name(self):
        assert GeminiHandler().get_binary_name() == "gemini"


class TestOpenCodeHandler:
    def test_build_env(self):
        handler = OpenCodeHandler()
        model = _make_model(api_key_env="OPENCODE_API_KEY")
        with patch.dict(os.environ, {"OPENCODE_API_KEY": "oc-test"}):
            env = handler.build_env(model)
        assert env["OPENCODE_API_KEY"] == "oc-test"

    def test_build_cli_args(self):
        handler = OpenCodeHandler()
        model = _make_model(model_id="test-model")
        stage = _make_stage_config()
        args = handler.build_cli_args(stage, model, "test prompt")
        assert args[0] == "run"
        assert "test prompt" in args
        assert "--model" in args

    def test_binary_name(self):
        assert OpenCodeHandler().get_binary_name() == "opencode"


class TestCodexHandler:
    def test_build_env(self):
        handler = CodexHandler()
        model = _make_model(api_key_env="OPENAI_API_KEY")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            env = handler.build_env(model)
        assert env["OPENAI_API_KEY"] == "sk-test"

    def test_build_cli_args(self):
        handler = CodexHandler()
        model = _make_model(model_id="gpt-5.3-codex-high")
        stage = _make_stage_config()
        args = handler.build_cli_args(stage, model, "test prompt")
        assert args[0] == "exec"
        assert "test prompt" in args
        assert "--model" in args
        assert "--full-auto" in args

    def test_binary_name(self):
        assert CodexHandler().get_binary_name() == "codex"
