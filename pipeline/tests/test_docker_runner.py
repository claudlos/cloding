"""Tests for Docker runner command building."""

from osq.runners.docker_runner import DockerRunner


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
