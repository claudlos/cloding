"""Git workspace preparation: branch creation, stash, and safety checks.

Safety: Uses asyncio subprocess with argument list (no shell interpretation).
This is equivalent to Node's child_process.execFile, not exec.
"""

import asyncio
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from cloding.core.errors import WorkspaceError
from cloding.core.logger import get_logger

logger = get_logger("workspace", category="SYSTEM")

# asyncio safe subprocess launcher (list args, no shell)
_launch = asyncio.create_subprocess_exec


async def _run_git(*args: str, cwd: str) -> tuple[int, str, str]:
    """Run a git command and return (exit_code, stdout, stderr)."""
    git_path = shutil.which("git")
    if not git_path:
        raise WorkspaceError("git not found in PATH.")

    proc = await _launch(
        git_path, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout_b, stderr_b = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout_b.decode("utf-8", errors="replace").strip(),
        stderr_b.decode("utf-8", errors="replace").strip(),
    )


async def is_git_repo(workspace: str) -> bool:
    """Check if workspace is inside a git repository."""
    code, _, _ = await _run_git("rev-parse", "--is-inside-work-tree", cwd=workspace)
    return code == 0


async def has_uncommitted_changes(workspace: str) -> bool:
    """Check if there are uncommitted changes in the workspace."""
    code, stdout, _ = await _run_git("status", "--porcelain", cwd=workspace)
    return bool(stdout.strip())


async def stash_changes(workspace: str) -> bool:
    """Stash any uncommitted changes. Returns True if something was stashed."""
    code, stdout, _ = await _run_git("stash", "push", "-m", "cloding-auto-stash", cwd=workspace)
    return "No local changes" not in stdout


async def get_current_branch(workspace: str) -> str:
    """Get the current git branch name."""
    code, stdout, _ = await _run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=workspace)
    if code != 0:
        raise WorkspaceError("Failed to get current git branch.")
    return stdout


async def create_branch(workspace: str, config_name: str) -> str:
    """Create and checkout a new cloding feature branch.

    Args:
        workspace: Path to the git workspace
        config_name: Pipeline config name for the branch prefix

    Returns:
        The name of the created branch
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    branch_name = f"cloding/{config_name}-{timestamp}"

    code, _, stderr = await _run_git("checkout", "-b", branch_name, cwd=workspace)
    if code != 0:
        raise WorkspaceError(f"Failed to create branch '{branch_name}': {stderr}")

    logger.info("Created branch: %s", branch_name)
    return branch_name


async def get_diff_summary(workspace: str) -> str:
    """Get a summary of changes made on the current branch."""
    code, stdout, _ = await _run_git("diff", "--stat", cwd=workspace)
    return stdout


def calculate_workspace_hash(workspace_path: str) -> str:
    """
    Calculate a hash of the current workspace files to detect changes.
    Used for caching exploration results.
    """
    ws = Path(workspace_path)
    hasher = hashlib.sha256()

    # Files to ignore during hashing
    ignore_patterns = {
        ".git", ".venv", "venv", "__pycache__", "data", "node_modules",
        ".claude", "PLAN.md", "CONTEXT.md", "RUN_SUMMARY.md"
    }

    # Collect and sort files for deterministic hashing
    files = []
    for path in ws.rglob("*"):
        if path.is_file():
            # Check if any part of the path is in ignore_patterns
            if any(part in ignore_patterns for part in path.parts):
                continue
            files.append(path)

    files.sort()

    for f in files:
        # Hash relative path and mtime/size for speed, or content for accuracy
        # Here we hash relative path + size + mtime as a good heuristic
        try:
            stat = f.stat()
            hasher.update(str(f.relative_to(ws)).encode())
            hasher.update(str(stat.st_size).encode())
            hasher.update(str(stat.st_mtime).encode())
        except OSError:
            continue

    return hasher.hexdigest()


async def prepare_workspace(
    workspace: str,
    config_name: str,
    no_git: bool = False,
) -> str:
    """Prepare the workspace for a pipeline run.

    1. Verify it's a git repo (unless --no-git)
    2. Stash any uncommitted changes
    3. Create a new feature branch

    Args:
        workspace: Path to the workspace directory
        config_name: Pipeline config name
        no_git: If True, skip all git operations

    Returns:
        The created branch name (empty string if no_git)
    """
    ws_path = Path(workspace).resolve()
    if not ws_path.is_dir():
        raise WorkspaceError(f"Workspace directory does not exist: {workspace}")

    if no_git:
        logger.info("Skipping git operations (--no-git)")
        return ""

    ws = str(ws_path)

    if not await is_git_repo(ws):
        raise WorkspaceError(
            f"'{workspace}' is not a git repository. "
            "Use --no-git to skip git safety checks."
        )

    original_branch = await get_current_branch(ws)
    logger.info("Current branch: %s", original_branch)

    if await has_uncommitted_changes(ws):
        logger.info("Uncommitted changes detected, stashing...")
        stashed = await stash_changes(ws)
        if stashed:
            logger.info("Changes stashed as 'cloding-auto-stash'")

    branch = await create_branch(ws, config_name)
    return branch
