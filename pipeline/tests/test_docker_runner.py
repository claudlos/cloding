"""Tests for Docker runner: command building, run, ensure_image, ensure_network, cleanup."""

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cloding.core.errors import DockerError, StageError
from cloding.runners.docker_runner import DockerRunner

_MODULE = "cloding.runners.docker_runner"


class TestDockerCommandBuild:
    def test_basic_command(self):
        runner = DockerRunner(
            image="test:latest",
            network="test-net",
            workspace_path="/home/user/project",
            memory_limit="4g",
            cpu_limit=2.0,
        )
        cli_args = ["-p", "write code", "--output-format", "json"]

        cmd = runner._build_command("claude", "/tmp/test.env", cli_args)

        assert cmd[0] == "docker"
        assert cmd[1] == "run"
        assert "--rm" in cmd
        assert "--network" in cmd
        idx = cmd.index("--network")
        assert cmd[idx + 1] == "test-net"
        assert "--memory" in cmd
        assert "4g" in cmd
        assert "--cpus" in cmd
        assert "2.0" in cmd
        assert "-v" in cmd
        assert "/home/user/project:/workspace" in cmd
        assert "test:latest" in cmd
        # cli_args should come after the image
        img_idx = cmd.index("test:latest")
        assert cmd[img_idx + 1:] == cli_args

    def test_no_workspace(self):
        runner = DockerRunner(image="img:v1", workspace_path="")
        cmd = runner._build_command("claude", "/tmp/test.env", ["-p", "test"])
        assert "-v" not in cmd

    def test_env_file_used_not_e_flags(self):
        """Should use --env-file instead of individual -e flags."""
        runner = DockerRunner(image="img:v1")
        cmd = runner._build_command("claude", "/tmp/secrets.env", [])

        assert "--env-file" in cmd
        idx = cmd.index("--env-file")
        assert cmd[idx + 1] == "/tmp/secrets.env"
        # No individual -e flags should be present
        assert "-e" not in cmd

    def test_named_container(self):
        runner = DockerRunner(image="img:v1", container_name="my-worker")
        cmd = runner._build_command("claude", "/tmp/test.env", [])
        assert "--name" in cmd
        idx = cmd.index("--name")
        assert cmd[idx + 1] == "my-worker"

    def test_non_claude_binary_sets_entrypoint(self):
        """Non-claude binaries should override entrypoint."""
        runner = DockerRunner(image="img:v1")
        cmd = runner._build_command("gemini", "/tmp/test.env", ["-p", "test"])
        assert "--entrypoint" in cmd
        idx = cmd.index("--entrypoint")
        assert cmd[idx + 1] == "gemini"

    def test_claude_binary_no_entrypoint(self):
        """Claude binary should NOT set --entrypoint (uses image default)."""
        runner = DockerRunner(image="img:v1")
        cmd = runner._build_command("claude", "/tmp/test.env", ["-p", "test"])
        assert "--entrypoint" not in cmd

    def test_windows_backslash_path_normalized(self):
        """Windows-style backslash paths should be converted to forward slashes."""
        runner = DockerRunner(
            image="img:v1",
            workspace_path="C:\\Users\\Carlos\\project",
        )
        cmd = runner._build_command("claude", "/tmp/test.env", [])
        assert "-v" in cmd
        v_idx = cmd.index("-v")
        volume_mount = cmd[v_idx + 1]
        assert "\\" not in volume_mount
        assert "C:/Users/Carlos/project:/workspace" == volume_mount

    def test_unix_path_unchanged(self):
        """Unix-style paths should pass through unchanged."""
        runner = DockerRunner(
            image="img:v1",
            workspace_path="/home/user/project",
        )
        cmd = runner._build_command("claude", "/tmp/test.env", [])
        v_idx = cmd.index("-v")
        assert cmd[v_idx + 1] == "/home/user/project:/workspace"


@pytest.mark.asyncio(loop_scope="function")
class TestDockerRunnerRun:
    async def test_docker_not_found_raises(self):
        runner = DockerRunner()
        with patch("shutil.which", return_value=None):
            with pytest.raises(DockerError, match="Docker not found"):
                await runner.run(binary_name="claude", env={}, cli_args=[], timeout=60)

    async def test_successful_run(self):
        runner = DockerRunner(image="test:latest")
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(b'{"result":"done"}', b"")
        )

        with patch("shutil.which", return_value="/usr/bin/docker"):
            with patch(f"{_MODULE}._launch", return_value=mock_proc):
                result = await runner.run(
                    binary_name="claude",
                    env={"KEY": "val"},
                    cli_args=["-p", "test"],
                    timeout=60,
                )
        assert result.exit_code == 0
        assert "done" in result.stdout

    async def test_timeout_returns_error_result(self):
        runner = DockerRunner(image="test:latest")
        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.communicate = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch("shutil.which", return_value="/usr/bin/docker"):
            with patch(f"{_MODULE}._launch", return_value=mock_proc):
                result = await runner.run(
                    binary_name="claude",
                    env={},
                    cli_args=[],
                    timeout=1,
                )
        assert result.exit_code == -1
        assert "timed out" in result.stderr

    async def test_timeout_with_proc_already_exited(self):
        """Timeout where process already exited should skip kill."""
        runner = DockerRunner(image="test:latest")
        mock_proc = AsyncMock()
        mock_proc.returncode = 1  # Already exited
        mock_proc.communicate = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch("shutil.which", return_value="/usr/bin/docker"):
            with patch(f"{_MODULE}._launch", return_value=mock_proc):
                result = await runner.run(
                    binary_name="claude",
                    env={},
                    cli_args=[],
                    timeout=1,
                )
        assert result.exit_code == -1
        assert "timed out" in result.stderr
        # proc.kill should NOT have been called since returncode is not None
        mock_proc.kill.assert_not_called()

    async def test_successful_run_with_named_container(self):
        """When container_name is set, should log the container name."""
        runner = DockerRunner(image="test:latest", container_name="my-worker-1")
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(b'{"result":"ok"}', b"")
        )

        with patch("shutil.which", return_value="/usr/bin/docker"):
            with patch(f"{_MODULE}._launch", return_value=mock_proc):
                result = await runner.run(
                    binary_name="claude",
                    env={"KEY": "val"},
                    cli_args=["-p", "test"],
                    timeout=60,
                )
        assert result.exit_code == 0

    async def test_successful_run_with_stderr(self):
        """When stderr has content, should log it."""
        runner = DockerRunner(image="test:latest")
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(b'{"result":"ok"}', b"some warning output")
        )

        with patch("shutil.which", return_value="/usr/bin/docker"):
            with patch(f"{_MODULE}._launch", return_value=mock_proc):
                result = await runner.run(
                    binary_name="claude",
                    env={},
                    cli_args=["-p", "test"],
                    timeout=60,
                )
        assert result.exit_code == 0

    async def test_timeout_with_named_container_stops_it(self):
        """Timeout with a named container should call _stop_container."""
        runner = DockerRunner(image="test:latest", container_name="timeout-worker")
        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        mock_stop_proc = AsyncMock()
        mock_stop_proc.communicate = AsyncMock(return_value=(b"", b""))

        call_count = 0

        async def _smart_launch(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_proc
            return mock_stop_proc

        with patch("shutil.which", return_value="/usr/bin/docker"):
            with patch(f"{_MODULE}._launch", side_effect=_smart_launch):
                result = await runner.run(binary_name="claude", env={}, cli_args=[], timeout=1)

        assert result.exit_code == -1
        assert "timed out" in result.stderr
        # _stop_container should have been called (second _launch call)
        assert call_count == 2

    async def test_os_error_raises_stage_error(self):
        runner = DockerRunner(image="test:latest")
        with patch("shutil.which", return_value="/usr/bin/docker"):
            with patch(f"{_MODULE}._launch", side_effect=OSError("no such file")):
                with pytest.raises(StageError, match="Docker runner failed"):
                    await runner.run(binary_name="claude", env={}, cli_args=[], timeout=60)

    async def test_env_file_contains_claudecode_and_vars(self):
        """Env file should contain CLAUDECODE="" and user-provided vars."""
        runner = DockerRunner(image="test:latest")
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b'{}', b''))

        env_file_content = None

        async def _capture_launch(*args, **kwargs):
            nonlocal env_file_content
            args_list = list(args)
            for i, arg in enumerate(args_list):
                if arg == "--env-file" and i + 1 < len(args_list):
                    with open(args_list[i + 1], "r") as f:
                        env_file_content = f.read()
            return mock_proc

        with patch("shutil.which", return_value="/usr/bin/docker"):
            with patch(f"{_MODULE}._launch", side_effect=_capture_launch):
                await runner.run(
                    binary_name="claude",
                    env={"MY_KEY": "my_val", "ANTHROPIC_MODEL": "test-model"},
                    cli_args=["-p", "test"],
                    timeout=60,
                )

        assert env_file_content is not None
        assert "CLAUDECODE=" in env_file_content
        assert "MY_KEY=my_val" in env_file_content
        assert "ANTHROPIC_MODEL=test-model" in env_file_content

    async def test_env_file_cleaned_up_after_run(self):
        """Temp env file should be deleted after run() completes."""
        runner = DockerRunner(image="test:latest")
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b'{}', b''))

        env_file_path = None

        async def _capture_launch(*args, **kwargs):
            nonlocal env_file_path
            args_list = list(args)
            for i, arg in enumerate(args_list):
                if arg == "--env-file" and i + 1 < len(args_list):
                    env_file_path = args_list[i + 1]
                    # Verify file exists during the run
                    assert os.path.exists(env_file_path)
            return mock_proc

        with patch("shutil.which", return_value="/usr/bin/docker"):
            with patch(f"{_MODULE}._launch", side_effect=_capture_launch):
                await runner.run(binary_name="claude", env={}, cli_args=[], timeout=60)

        assert env_file_path is not None
        assert not os.path.exists(env_file_path), "Env file should be cleaned up after run"

    async def test_env_file_cleaned_up_on_error(self):
        """Temp env file should be cleaned up even when an error occurs."""
        runner = DockerRunner(image="test:latest")

        env_file_path = None

        async def _capture_and_fail(*args, **kwargs):
            nonlocal env_file_path
            args_list = list(args)
            for i, arg in enumerate(args_list):
                if arg == "--env-file" and i + 1 < len(args_list):
                    env_file_path = args_list[i + 1]
            raise OSError("docker crashed")

        with patch("shutil.which", return_value="/usr/bin/docker"):
            with patch(f"{_MODULE}._launch", side_effect=_capture_and_fail):
                with pytest.raises(StageError):
                    await runner.run(binary_name="claude", env={}, cli_args=[], timeout=60)

        assert env_file_path is not None
        assert not os.path.exists(env_file_path), "Env file should be cleaned up on error"

    async def test_existing_claudecode_in_env_not_duplicated(self):
        """If CLAUDECODE is already in env dict, should not add a second one."""
        runner = DockerRunner(image="test:latest")
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b'{}', b''))

        env_file_content = None

        async def _capture_launch(*args, **kwargs):
            nonlocal env_file_content
            args_list = list(args)
            for i, arg in enumerate(args_list):
                if arg == "--env-file" and i + 1 < len(args_list):
                    with open(args_list[i + 1], "r") as f:
                        env_file_content = f.read()
            return mock_proc

        with patch("shutil.which", return_value="/usr/bin/docker"):
            with patch(f"{_MODULE}._launch", side_effect=_capture_launch):
                await runner.run(
                    binary_name="claude",
                    env={"CLAUDECODE": "already-set"},
                    cli_args=[],
                    timeout=60,
                )

        assert env_file_content is not None
        # Should only appear once
        assert env_file_content.count("CLAUDECODE=") == 1


@pytest.mark.asyncio(loop_scope="function")
class TestEnsureNetwork:
    async def test_creates_network_when_not_exists(self):
        """When network doesn't exist, should check then create."""
        call_count = 0

        async def _fake_launch(*args, **kwargs):
            nonlocal call_count
            proc = AsyncMock()
            proc.returncode = 0
            if call_count == 0:
                # First call: docker network ls --filter (not found)
                proc.communicate = AsyncMock(return_value=(b"", b""))
            else:
                # Second call: docker network create (success)
                proc.communicate = AsyncMock(return_value=(b"abc123", b""))
            call_count += 1
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_fake_launch):
            await DockerRunner.ensure_network("test-net")

        assert call_count == 2

    async def test_network_already_exists_skips_create(self):
        """When network already exists in ls output, should skip create."""
        call_count = 0

        async def _fake_launch(*args, **kwargs):
            nonlocal call_count
            proc = AsyncMock()
            proc.returncode = 0
            # First call: docker network ls --filter (found)
            proc.communicate = AsyncMock(return_value=(b"test-net\n", b""))
            call_count += 1
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_fake_launch):
            await DockerRunner.ensure_network("test-net")

        # Should only call ls, not create
        assert call_count == 1

    async def test_network_creation_fails_raises(self):
        """When network create fails (not 'already exists'), should raise."""
        call_count = 0

        async def _fake_launch(*args, **kwargs):
            nonlocal call_count
            proc = AsyncMock()
            if call_count == 0:
                # First call: ls (not found)
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            else:
                # Second call: create (fail)
                proc.returncode = 1
                proc.communicate = AsyncMock(
                    return_value=(b"", b"permission denied")
                )
            call_count += 1
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_fake_launch):
            with pytest.raises(DockerError, match="Failed to create Docker network"):
                await DockerRunner.ensure_network("test-net")

    async def test_network_race_condition_already_exists_ok(self):
        """Race condition: ls says no, create says 'already exists' — should not raise."""
        call_count = 0

        async def _fake_launch(*args, **kwargs):
            nonlocal call_count
            proc = AsyncMock()
            if call_count == 0:
                # ls: not found
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            else:
                # create: race condition, another process created it
                proc.returncode = 1
                proc.communicate = AsyncMock(
                    return_value=(b"", b"network test-net already exists")
                )
            call_count += 1
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_fake_launch):
            # Should not raise
            await DockerRunner.ensure_network("test-net")


@pytest.mark.asyncio(loop_scope="function")
class TestEnsureImage:
    async def test_image_exists_skips_build(self):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"abc123\n", b""))

        with patch(f"{_MODULE}._launch", return_value=mock_proc):
            await DockerRunner.ensure_image("test:latest")

    async def test_image_missing_no_dockerfile_raises(self):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        # Empty stdout means image not found
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch(f"{_MODULE}._launch", return_value=mock_proc):
            with pytest.raises(DockerError, match="Dockerfile not found"):
                await DockerRunner.ensure_image(
                    "test:latest",
                    dockerfile_dir="/nonexistent/dir",
                )

    async def test_image_missing_builds_successfully(self, tmp_path):
        # Create Dockerfile
        (tmp_path / "Dockerfile").write_text("FROM node:22\n", encoding="utf-8")

        call_count = 0

        async def _fake_launch(*args, **kwargs):
            nonlocal call_count
            proc = AsyncMock()
            if call_count == 0:
                # First call: docker images -q (not found)
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            else:
                # Second call: docker build (success)
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"built", b""))
            call_count += 1
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_fake_launch):
            await DockerRunner.ensure_image("test:latest", dockerfile_dir=str(tmp_path))

    async def test_image_missing_default_dockerfile_dir_resolves(self, tmp_path):
        """When image is missing and no dockerfile_dir is given, should resolve default path."""
        call_count = 0

        async def _fake_launch(*args, **kwargs):
            nonlocal call_count
            proc = AsyncMock()
            if call_count == 0:
                # First call: docker images -q (not found)
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            else:
                # Second call: docker build (success)
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"built", b""))
            call_count += 1
            return proc

        # Patch Path(__file__) resolution so it points to tmp_path structure
        # The default dockerfile_dir = Path(__file__).parent.parent.parent / "docker"
        # Create the expected Dockerfile at the resolved path
        fake_docker_dir = tmp_path / "docker"
        fake_docker_dir.mkdir()
        (fake_docker_dir / "Dockerfile").write_text("FROM node:22\n", encoding="utf-8")

        # Patch __file__ in the module so the resolution goes to our tmp_path
        fake_file = str(tmp_path / "cloding" / "runners" / "docker_runner.py")
        with patch(f"{_MODULE}.__file__", fake_file):
            with patch(f"{_MODULE}._launch", side_effect=_fake_launch):
                await DockerRunner.ensure_image("test:default-dir")

        # Should have called _launch twice (check + build)
        assert call_count == 2

    async def test_image_build_failure_raises(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM node:22\n", encoding="utf-8")

        call_count = 0

        async def _fake_launch(*args, **kwargs):
            nonlocal call_count
            proc = AsyncMock()
            if call_count == 0:
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            else:
                proc.returncode = 1
                proc.communicate = AsyncMock(return_value=(b"", b"build error"))
            call_count += 1
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_fake_launch):
            with pytest.raises(DockerError, match="Failed to build image"):
                await DockerRunner.ensure_image("test:latest", dockerfile_dir=str(tmp_path))


@pytest.mark.asyncio(loop_scope="function")
class TestCleanupContainers:
    async def test_no_containers(self):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch(f"{_MODULE}._launch", return_value=mock_proc):
            count = await DockerRunner.cleanup_containers("test-prefix")
        assert count == 0

    async def test_cleans_up_containers(self):
        call_count = 0

        async def _fake_launch(*args, **kwargs):
            nonlocal call_count
            proc = AsyncMock()
            proc.returncode = 0
            if call_count == 0:
                # docker ps -a listing
                proc.communicate = AsyncMock(
                    return_value=(b"test-prefix-1\ntest-prefix-2\n", b"")
                )
            else:
                # docker rm -f
                proc.communicate = AsyncMock(return_value=(b"", b""))
            call_count += 1
            return proc

        with patch(f"{_MODULE}._launch", side_effect=_fake_launch):
            count = await DockerRunner.cleanup_containers("test-prefix")
        assert count == 2


@pytest.mark.asyncio(loop_scope="function")
class TestStopContainer:
    async def test_stop_container_success(self):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch(f"{_MODULE}._launch", return_value=mock_proc):
            await DockerRunner._stop_container("my-container")

    async def test_stop_container_os_error_ignored(self):
        with patch(f"{_MODULE}._launch", side_effect=OSError("fail")):
            # Should not raise
            await DockerRunner._stop_container("my-container")
