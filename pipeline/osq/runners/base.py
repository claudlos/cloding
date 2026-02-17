"""Abstract base runner for executing Claude Code."""

import json
import re
from abc import ABC, abstractmethod

from osq.pipeline.result import RunResult


class BaseRunner(ABC):
    """Abstract base for running Claude Code (Docker or local)."""

    @abstractmethod
    async def run(
        self, env: dict[str, str], cli_args: list[str], timeout: int
    ) -> RunResult:
        """
        Execute Claude Code with the given environment and CLI args.

        Args:
            env: Environment variables to set
            cli_args: Claude CLI arguments (e.g., ["-p", "prompt", "--output-format", "json"])
            timeout: Timeout in seconds

        Returns:
            RunResult with exit code, stdout, stderr, and parsed metrics
        """
        ...

    @staticmethod
    def parse_json_output(stdout: str) -> dict:
        """
        Parse Claude Code's JSON output format.

        The --output-format json flag produces:
        {
            "type": "result",
            "subtype": "success" | "error_max_turns" | ...,
            "cost_usd": 0.042,
            "duration_ms": 15234,
            "duration_api_ms": 14100,
            "is_error": false,
            "num_turns": 5,
            "result": "The actual text output...",
            "session_id": "abc123-def456"
        }
        """
        # Try to find the last JSON object in stdout (in case of preamble text)
        stdout = stdout.strip()

        # First try direct parse
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            pass

        # Try to find JSON object at end of output
        brace_depth = 0
        json_start = -1
        json_end = -1
        for i in range(len(stdout) - 1, -1, -1):
            if stdout[i] == "}":
                if brace_depth == 0:
                    json_end = i + 1
                brace_depth += 1
            elif stdout[i] == "{":
                brace_depth -= 1
                if brace_depth == 0:
                    json_start = i
                    break

        if json_start >= 0 and json_end > json_start:
            try:
                return json.loads(stdout[json_start:json_end])
            except json.JSONDecodeError:
                pass

        return {}

    @staticmethod
    def build_run_result(exit_code: int, stdout: str, stderr: str) -> RunResult:
        """Parse stdout JSON and build a RunResult.

        Handles the Claude Code JSON output format which nests token counts
        inside a "usage" object and uses "total_cost_usd" for cost.
        """
        parsed = BaseRunner.parse_json_output(stdout)

        # Token counts live inside "usage" sub-object
        usage = parsed.get("usage", {})
        tokens_in = usage.get("input_tokens", 0)
        tokens_out = usage.get("output_tokens", 0)

        # Also add cache tokens to input count for accurate cost tracking
        tokens_in += usage.get("cache_creation_input_tokens", 0)
        tokens_in += usage.get("cache_read_input_tokens", 0)

        # Cost field is "total_cost_usd" in Claude Code output
        cost = parsed.get("total_cost_usd", parsed.get("cost_usd", 0.0))

        result_text = parsed.get("result", stdout)

        # Detect API credit errors (e.g. OpenRouter 402) for clearer messaging
        is_error = parsed.get("is_error", False)
        if is_error and "402" in result_text and "credits" in result_text.lower():
            stderr = (
                f"API credits exhausted. {result_text[:300]}\n"
                "Top up at https://openrouter.ai/settings/keys"
            )

        return RunResult(
            exit_code=exit_code,
            stdout=result_text,
            stderr=stderr,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            session_id=parsed.get("session_id", ""),
            cost_usd=cost,
            num_turns=parsed.get("num_turns", 0),
            duration_ms=parsed.get("duration_ms", 0),
        )
