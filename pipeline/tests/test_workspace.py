"""Tests for workspace git preparation (mocked subprocess)."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from cloding.core.errors import WorkspaceError

# We mock _launch globally so no real git commands run
_MODULE = "cloding.core.workspace"


@pytest.fixture
def mock_git():
    """Mock _launch to simulate git commands."""
    async def _fake_launch(*args, **kwargs):
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    with patch(f"{_MODULE}._launch", side_effect=_fake_launch) as m:
        yield m


@pytest.fixture
def mock_which_git():
    """Mock shutil.which to return a fake git path."""
    with patch(f"{_MODULE}.shutil.which", return_value="/usr/bin/git"):
        yield


@pytest.mark.asyncio(loop_scope="function")
class TestRunGit:
    async def test_run_git_returns_tuple(self, mock_which_git, mock_git):
        from cloding.core.workspace import _run_git
        code, stdout, stderr = await _run_git("status", cwd="/tmp")
        assert code == 0

    async def test_run_git_no_git_in_path(self):
        from cloding.core.workspace import _run_git
        with patch(f"{_MODULE}.shutil.which", return_value=None):
            with pytest.raises(WorkspaceError, match="git not found"):
                await _run_git("status", cwd="/tmp")


@pytest.mark.asyncio(loop_scope="function")
class TestIsGitRepo:
    async def test_is_git_repo_true(self, mock_which_git, mock_git):
        from cloding.core.workspace import is_git_repo
        result = await is_git_repo("/tmp/myrepo")
        assert result is True

    async def test_is_git_repo_false(self, mock_which_git):
        async def _fail(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 128
            proc.communicate = AsyncMock(return_value=(b"", b"not a repo"))
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_fail):
            from cloding.core.workspace import is_git_repo
            result = await is_git_repo("/tmp/notagit")
            assert result is False


@pytest.mark.asyncio(loop_scope="function")
class TestHasUncommittedChanges:
    async def test_clean_repo(self, mock_which_git):
        async def _clean(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_clean):
            from cloding.core.workspace import has_uncommitted_changes
            assert await has_uncommitted_changes("/tmp") is False

    async def test_dirty_repo(self, mock_which_git):
        async def _dirty(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b" M file.py\n", b""))
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_dirty):
            from cloding.core.workspace import has_uncommitted_changes
            assert await has_uncommitted_changes("/tmp") is True


@pytest.mark.asyncio(loop_scope="function")
class TestStashChanges:
    async def test_stash_when_dirty(self, mock_which_git):
        async def _stash(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(
                return_value=(b"Saved working directory", b"")
            )
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_stash):
            from cloding.core.workspace import stash_changes
            assert await stash_changes("/tmp") is True

    async def test_stash_when_clean(self, mock_which_git):
        async def _no_stash(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(
                return_value=(b"No local changes to save", b"")
            )
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_no_stash):
            from cloding.core.workspace import stash_changes
            assert await stash_changes("/tmp") is False


@pytest.mark.asyncio(loop_scope="function")
class TestGetCurrentBranch:
    async def test_returns_branch_name(self, mock_which_git):
        async def _branch(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"main\n", b""))
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_branch):
            from cloding.core.workspace import get_current_branch
            assert await get_current_branch("/tmp") == "main"

    async def test_raises_on_failure(self, mock_which_git):
        async def _fail(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 1
            proc.communicate = AsyncMock(return_value=(b"", b"error"))
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_fail):
            from cloding.core.workspace import get_current_branch
            with pytest.raises(WorkspaceError, match="Failed to get"):
                await get_current_branch("/tmp")


@pytest.mark.asyncio(loop_scope="function")
class TestCreateBranch:
    async def test_creates_branch(self, mock_which_git, mock_git):
        from cloding.core.workspace import create_branch
        branch = await create_branch("/tmp", "default")
        assert branch.startswith("cloding/default-")

    async def test_raises_on_failure(self, mock_which_git):
        async def _fail(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 1
            proc.communicate = AsyncMock(return_value=(b"", b"already exists"))
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_fail):
            from cloding.core.workspace import create_branch
            with pytest.raises(WorkspaceError, match="Failed to create branch"):
                await create_branch("/tmp", "default")


@pytest.mark.asyncio(loop_scope="function")
class TestGetDiffSummary:
    async def test_returns_diff(self, mock_which_git):
        async def _diff(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(
                return_value=(b" file.py | 3 +++\n 1 file changed", b"")
            )
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_diff):
            from cloding.core.workspace import get_diff_summary
            result = await get_diff_summary("/tmp")
            assert "file.py" in result


@pytest.mark.asyncio(loop_scope="function")
class TestPrepareWorkspace:
    async def test_no_git_skips_everything(self, tmp_path):
        from cloding.core.workspace import prepare_workspace
        result = await prepare_workspace(str(tmp_path), "test", no_git=True)
        assert result == ""

    async def test_nonexistent_workspace_raises(self):
        from cloding.core.workspace import prepare_workspace
        with pytest.raises(WorkspaceError, match="does not exist"):
            await prepare_workspace("/nonexistent/path/xyz", "test")

    async def test_not_a_git_repo_raises(self, tmp_path, mock_which_git):
        async def _not_repo(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 128
            proc.communicate = AsyncMock(return_value=(b"", b"not a repo"))
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_not_repo):
            from cloding.core.workspace import prepare_workspace
            with pytest.raises(WorkspaceError, match="not a git repository"):
                await prepare_workspace(str(tmp_path), "test")

    async def test_full_git_path_with_dirty_repo(self, tmp_path, mock_which_git):
        """Full prepare_workspace: is_git_repo → get_branch → has_changes → stash → create_branch."""
        call_log = []

        async def _smart_git(*args, **kwargs):
            # args[0] is the git binary, rest are git args
            git_args = args[1:] if len(args) > 1 else ()
            proc = AsyncMock()
            proc.returncode = 0

            if "rev-parse" in git_args and "--is-inside-work-tree" in git_args:
                call_log.append("is_git_repo")
                proc.communicate = AsyncMock(return_value=(b"true", b""))
            elif "rev-parse" in git_args and "--abbrev-ref" in git_args:
                call_log.append("get_branch")
                proc.communicate = AsyncMock(return_value=(b"main", b""))
            elif "status" in git_args and "--porcelain" in git_args:
                call_log.append("has_changes")
                proc.communicate = AsyncMock(return_value=(b" M dirty.py\n", b""))
            elif "stash" in git_args:
                call_log.append("stash")
                proc.communicate = AsyncMock(return_value=(b"Saved working directory", b""))
            elif "checkout" in git_args and "-b" in git_args:
                call_log.append("create_branch")
                proc.communicate = AsyncMock(return_value=(b"", b""))
            else:
                proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_smart_git):
            from cloding.core.workspace import prepare_workspace
            branch = await prepare_workspace(str(tmp_path), "default")

        assert branch.startswith("cloding/default-")
        assert "is_git_repo" in call_log
        assert "get_branch" in call_log
        assert "has_changes" in call_log
        assert "stash" in call_log
        assert "create_branch" in call_log

    async def test_full_git_path_dirty_repo_stash_noop(self, tmp_path, mock_which_git):
        """Dirty repo where stash reports 'No local changes' (e.g., only untracked files)."""
        async def _smart_git(*args, **kwargs):
            git_args = args[1:] if len(args) > 1 else ()
            proc = AsyncMock()
            proc.returncode = 0

            if "rev-parse" in git_args and "--is-inside-work-tree" in git_args:
                proc.communicate = AsyncMock(return_value=(b"true", b""))
            elif "rev-parse" in git_args and "--abbrev-ref" in git_args:
                proc.communicate = AsyncMock(return_value=(b"main", b""))
            elif "status" in git_args and "--porcelain" in git_args:
                proc.communicate = AsyncMock(return_value=(b"?? untracked.py\n", b""))
            elif "stash" in git_args:
                # Stash says no local changes (untracked files aren't stashed by default)
                proc.communicate = AsyncMock(return_value=(b"No local changes to save", b""))
            elif "checkout" in git_args and "-b" in git_args:
                proc.communicate = AsyncMock(return_value=(b"", b""))
            else:
                proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_smart_git):
            from cloding.core.workspace import prepare_workspace
            branch = await prepare_workspace(str(tmp_path), "default")

        assert branch.startswith("cloding/default-")

    async def test_full_git_path_clean_repo(self, tmp_path, mock_which_git):
        """Full prepare_workspace with clean repo: should skip stash."""
        call_log = []

        async def _smart_git(*args, **kwargs):
            git_args = args[1:] if len(args) > 1 else ()
            proc = AsyncMock()
            proc.returncode = 0

            if "rev-parse" in git_args and "--is-inside-work-tree" in git_args:
                call_log.append("is_git_repo")
                proc.communicate = AsyncMock(return_value=(b"true", b""))
            elif "rev-parse" in git_args and "--abbrev-ref" in git_args:
                call_log.append("get_branch")
                proc.communicate = AsyncMock(return_value=(b"main", b""))
            elif "status" in git_args and "--porcelain" in git_args:
                call_log.append("has_changes")
                proc.communicate = AsyncMock(return_value=(b"", b""))  # clean
            elif "checkout" in git_args and "-b" in git_args:
                call_log.append("create_branch")
                proc.communicate = AsyncMock(return_value=(b"", b""))
            else:
                proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_smart_git):
            from cloding.core.workspace import prepare_workspace
            branch = await prepare_workspace(str(tmp_path), "quick")

        assert branch.startswith("cloding/quick-")
        assert "stash" not in call_log
        assert "create_branch" in call_log
