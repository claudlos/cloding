"""Local runner: runs Claude Code CLI directly on the host."""

import asyncio
import os
import platform
import shutil
from pathlib import Path

from cloding.core.errors import StageError
from cloding.core.logger import get_logger
from cloding.pipeline.result import RunResult
from cloding.runners.base import BaseRunner

# Safe alias for subprocess creation
_launch = asyncio.create_subprocess_exec


def _resolve_binary(binary_name: str) -> tuple[str, list[str]]:
    """Resolve the actual binary, handling Windows .CMD wrappers for Claude."""
    binary_path = shutil.which(binary_name)
    if not binary_path:
        # Special case for 'claude' if not found but 'claude.cmd' might be
        if binary_name == "claude":
            raise StageError(
                "Claude Code CLI not found in PATH. "
                "Install with: npm i -g @anthropic-ai/claude-code"
            )
        raise StageError(f"Binary '{binary_name}' not found in PATH.")

    # On Windows, .CMD wrappers for 'claude' need special handling
    if binary_name == "claude" and platform.system() == "Windows" and binary_path.lower().endswith(".cmd"):
        # The .CMD wrapper calls: node "<dir>/node_modules/@anthropic-ai/claude-code/cli.js" %*
        cmd_dir = Path(binary_path).parent
        cli_js = cmd_dir / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"

        if cli_js.exists():
            node_path = shutil.which("node")
            if node_path:
                return node_path, [str(cli_js)]

        # Fallback: try to find claude.exe (if installed differently)
        claude_exe = shutil.which("claude.exe")
        if claude_exe and not claude_exe.lower().endswith(".cmd"):
            return claude_exe, []

        # Last resort: use cmd /c to run the .CMD properly
        return os.environ.get("COMSPEC", "cmd.exe"), ["/c", binary_path]

    return binary_path, []


class LocalRunner(BaseRunner):
    """Runs CLI tools directly on the host (no Docker).

    Uses asyncio.create_subprocess_exec which is safe from shell injection
    as it calls the binary directly without shell interpretation.
    On Windows, resolves .CMD wrappers for Claude to their underlying node binary.
    """

    def __init__(self, workspace_path: str = "") -> None:
        self.workspace_path = workspace_path
        self.logger = get_logger("local_runner", category="SYSTEM")

    async def run(
        self, binary_name: str, env: dict[str, str], cli_args: list[str], timeout: int
    ) -> RunResult:
        """
        Run CLI tool locally via subprocess.

        Args:
            binary_name: Tool binary name (e.g. "claude", "gemini")
            env: Environment variables to inject
            cli_args: CLI arguments
            timeout: Timeout in seconds

        Returns:
            RunResult with parsed output
        """
        exe_path, prefix_args = _resolve_binary(binary_name)

        # Build subprocess environment
        run_env = os.environ.copy()
        run_env.update(env)

        # Remove CLAUDECODE env var so child processes don't think they're
        # nested inside another Claude Code session (they're independent).
        run_env.pop("CLAUDECODE", None)

        cwd = self.workspace_path or None

        full_args = prefix_args + cli_args

        self.logger.info(
            "Running: %s %s",
            Path(exe_path).name,
            " ".join(full_args[:4]) + "...",
        )
        self.logger.debug("Executable: %s", exe_path)
        self.logger.debug("Full args: %s", full_args)

        proc = None
        try:
            proc = await _launch(
                exe_path,
                *full_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=run_env,
                cwd=cwd,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            self.logger.debug("Exit code: %d", proc.returncode or 0)
            self.logger.debug("Raw stdout (%d chars): %s", len(stdout), stdout[:2000])
            self.logger.debug("Raw stderr (%d chars): %s", len(stderr), stderr[:1000])

            return self.build_run_result(
                exit_code=proc.returncode or 0,
                stdout=stdout,
                stderr=stderr,
            )

        except asyncio.TimeoutError:
            self.logger.error("Claude Code timed out after %d seconds", timeout)
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()
            return RunResult(
                exit_code=-1,
                stdout="",
                stderr=f"Timed out after {timeout} seconds",
            )
        except OSError as ose:
            self.logger.error("Failed to run Claude Code: %s", ose)
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise StageError(f"Local runner failed: {ose}") from ose
