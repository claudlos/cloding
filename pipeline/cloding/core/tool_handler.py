"""Tool handlers for different CLI providers (Claude Code, Gemini, OpenCode, Codex)."""

import os
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from cloding.core.config import ModelConfig, StageConfig


class ToolHandler(ABC):
    """Abstract base for tool handlers."""

    @abstractmethod
    def build_env(self, model_config: ModelConfig) -> Dict[str, str]:
        """Build environment variables for the tool."""
        ...

    @abstractmethod
    def build_cli_args(self, stage_config: StageConfig, model_config: ModelConfig, prompt: str) -> List[str]:
        """Build CLI arguments for the tool."""
        ...

    @abstractmethod
    def get_binary_name(self) -> str:
        """Get the binary name or path for the tool."""
        ...


class ClaudeCodeHandler(ToolHandler):
    """Handler for Anthropic's Claude Code CLI."""

    def build_env(self, model_config: ModelConfig) -> Dict[str, str]:
        env = {}
        api_key = os.environ.get(model_config.api_key_env, "")

        if model_config.provider == "openrouter":
            env["ANTHROPIC_BASE_URL"] = (
                model_config.base_url or "https://openrouter.ai/api"
            )
            env["ANTHROPIC_AUTH_TOKEN"] = api_key
            env["ANTHROPIC_API_KEY"] = ""
            env["ANTHROPIC_MODEL"] = model_config.model_id
        else:
            env["ANTHROPIC_API_KEY"] = api_key
            env["ANTHROPIC_MODEL"] = model_config.model_id
        
        # Strip CLAUDECODE to prevent nesting errors
        env["CLAUDECODE"] = ""
        return env

    def build_cli_args(self, stage_config: StageConfig, model_config: ModelConfig, prompt: str) -> List[str]:
        args = [
            "-p", prompt,
            "--output-format", stage_config.output_format,
            "--max-turns", str(stage_config.max_turns),
            "--dangerously-skip-permissions",
        ]

        if stage_config.allowed_tools:
            args.extend(["--allowedTools", ",".join(stage_config.allowed_tools)])

        if stage_config.disallowed_tools:
            args.extend(["--disallowedTools", ",".join(stage_config.disallowed_tools)])

        return args

    def get_binary_name(self) -> str:
        return "claude"


class GeminiHandler(ToolHandler):
    """Handler for Gemini CLI."""

    def build_env(self, model_config: ModelConfig) -> Dict[str, str]:
        env = {}
        api_key = os.environ.get(model_config.api_key_env, "")
        
        if model_config.provider == "openrouter":
            env["GEMINI_API_KEY"] = api_key
        else:
            # Direct Google API
            env["GOOGLE_API_KEY"] = api_key
            env["GEMINI_API_KEY"] = api_key  # Some versions use this
        return env

    def build_cli_args(self, stage_config: StageConfig, model_config: ModelConfig, prompt: str) -> List[str]:
        # Based on Gemini CLI docs: headless mode for scripting
        # Assuming 'gemini -p "prompt"' or similar. 
        # Refined based on https://geminicli.com/docs/
        args = [
            "-p", prompt,
            "--non-interactive",
        ]
        if model_config.model_id:
            args.extend(["--model", model_config.model_id])
        
        return args

    def get_binary_name(self) -> str:
        return "gemini"


class OpenCodeHandler(ToolHandler):
    """Handler for OpenCode CLI."""

    def build_env(self, model_config: ModelConfig) -> Dict[str, str]:
        env = {}
        api_key = os.environ.get(model_config.api_key_env, "")
        env["OPENCODE_API_KEY"] = api_key
        return env

    def build_cli_args(self, stage_config: StageConfig, model_config: ModelConfig, prompt: str) -> List[str]:
        # Based on search: opencode run "prompt"
        args = ["run", prompt]
        if model_config.model_id:
            args.extend(["--model", model_config.model_id])
        return args

    def get_binary_name(self) -> str:
        return "opencode"


class CodexHandler(ToolHandler):
    """Handler for Codex CLI."""

    def build_env(self, model_config: ModelConfig) -> Dict[str, str]:
        env = {}
        api_key = os.environ.get(model_config.api_key_env, "")

        if model_config.provider == "openrouter":
            # For Codex CLI via OpenRouter (if supported)
            env["OPENAI_API_KEY"] = api_key
        else:
            # Direct OpenAI API
            env["OPENAI_API_KEY"] = api_key
        return env

    def build_cli_args(self, stage_config: StageConfig, model_config: ModelConfig, prompt: str) -> List[str]:
        # Based on: codex exec "prompt"
        args = ["exec", prompt]
        if model_config.model_id:
            args.extend(["--model", model_config.model_id])

        # Add full-auto for non-interactive coding
        args.append("--full-auto")
        return args

    def get_binary_name(self) -> str:
        return "codex"


class CopilotHandler(ToolHandler):
    """Handler for GitHub Copilot CLI."""

    def build_env(self, model_config: ModelConfig) -> Dict[str, str]:
        env = {}
        api_key = os.environ.get(model_config.api_key_env, "")
        env["GITHUB_TOKEN"] = api_key
        return env

    def build_cli_args(self, stage_config: StageConfig, model_config: ModelConfig, prompt: str) -> List[str]:
        # Copilot CLI uses -p for prompts (like Claude/Gemini)
        return ["-p", prompt]

    def get_binary_name(self) -> str:
        return "github-copilot"


TOOL_HANDLERS: Dict[str, ToolHandler] = {
    "claude-code": ClaudeCodeHandler(),
    "gemini": GeminiHandler(),
    "opencode": OpenCodeHandler(),
    "codex": CodexHandler(),
    "copilot": CopilotHandler(),
}


def get_tool_handler(tool_name: str) -> ToolHandler:
    """Get the appropriate tool handler."""
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        raise ValueError(f"Unknown tool: {tool_name}. Available: {list(TOOL_HANDLERS.keys())}")
    return handler
