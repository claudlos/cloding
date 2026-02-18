"""Tests for Docker runner: command building, run, ensure_image, ensure_network, cleanup."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osq.core.errors import DockerError, StageError
from osq.runners.docker_runner import DockerRunner

_MODULE = "osq.runners.docker_runner"


class TestDockerCommandBuild:
    def test_basic_command(self):
        runner = DockerRunner(
            image="test:latest",
            network="test-net",
            workspace_path="/home/user/project",
            memory_limit="4g",
            cpu_limit=2.0,
        )
        env = {
            "ANTHROPIC_BASE_URL": "https://openrouter.ai/api",
            "ANTHROPIC_MODEL": "qwen/qwen3-coder-next",
        }
        cli_args = ["-p", "write code", "--output-format", "json"]

        cmd = runner._build_command(env, cli_args)

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
        cmd = runner._build_command({}, ["-p", "test"])
        assert "-v" not in cmd

    def test_env_vars_injected(self):
        runner = DockerRunner(image="img:v1")
        env = {"KEY1": "val1", "KEY2": "val2"}
        cmd = runner._build_command(env, [])

        # Each env var should have -e KEY=VALUE
        e_indices = [i for i, x in enumerate(cmd) if x == "-e"]
        env_values = [cmd[i + 1] for i in e_indices]
        assert "KEY1=val1" in env_values
        assert "KEY2=val2" in env_values

    def test_claudecode_stripped(self):
        runner = DockerRunner(image="img:v1")
        cmd = runner._build_command({}, [])
        e_indices = [i for i, x in enumerate(cmd) if x == "-e"]
        env_values = [cmd[i + 1] for i in e_indices]
        assert "CLAUDECODE=" in env_values

    def test_named_container(self):
        runner = DockerRunner(image="img:v1", container_name="my-worker")
        cmd = runner._build_command({}, [])
        assert "--name" in cmd
        idx = cmd.index("--name")
        assert cmd[idx + 1] == "my-worker"


@pytest.mark.asyncio(loop_scope="function")
class TestDockerRunnerRun:
    async def test_docker_not_found_raises(self):
        runner = DockerRunner()
        with patch("shutil.which", return_value=None):
            with pytest.raises(DockerError, match="Docker not found"):
                await runner.run(env={}, cli_args=[], timeout=60)

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
                result = await runner.run(env={}, cli_args=[], timeout=1)

        assert result.exit_code == -1
        assert "timed out" in result.stderr
        # _stop_container should have been called (second _launch call)
        assert call_count == 2

    async def test_os_error_raises_stage_error(self):
        runner = DockerRunner(image="test:latest")
        with patch("shutil.which", return_value="/usr/bin/docker"):
            with patch(f"{_MODULE}._launch", side_effect=OSError("no such file")):
                with pytest.raises(StageError, match="Docker runner failed"):
                    await runner.run(env={}, cli_args=[], timeout=60)


@pytest.mark.asyncio(loop_scope="function")
class TestEnsureNetwork:
    async def test_creates_network(self):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"abc123", b""))

        with patch(f"{_MODULE}._launch", return_value=mock_proc):
            await DockerRunner.ensure_network("test-net")

    async def test_network_already_exists_ok(self):
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(
            return_value=(b"", b"network test-net already exists")
        )

        with patch(f"{_MODULE}._launch", return_value=mock_proc):
            # Should not raise
            await DockerRunner.ensure_network("test-net")

    async def test_network_creation_fails_raises(self):
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(
            return_value=(b"", b"permission denied")
        )

        with patch(f"{_MODULE}._launch", return_value=mock_proc):
            with pytest.raises(DockerError, match="Failed to create Docker network"):
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
        fake_file = str(tmp_path / "osq" / "runners" / "docker_runner.py")
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
