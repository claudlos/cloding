"""Docker runner: runs Claude Code inside Docker containers.

Safety: Uses asyncio subprocess with argument list (no shell interpretation).
This is equivalent to Node's child_process.execFile, not exec.
"""

import asyncio
import shutil
from pathlib import Path
from typing import Optional

from cloding.core.errors import DockerError, StageError
from cloding.core.logger import get_logger
from cloding.pipeline.result import RunResult
from cloding.runners.base import BaseRunner

# asyncio safe subprocess launcher (list args, no shell)
_launch = asyncio.create_subprocess_exec


class DockerRunner(BaseRunner):
    """Runs Claude Code in isolated Docker containers.

    Each stage/task gets its own container with:
    - Workspace mounted as a volume
    - Resource limits (memory, CPU)
    - Network isolation
    - Non-root user (coder)
    - Auto-cleanup on exit (--rm)
    """

    def __init__(
        self,
        image: str = "cloding:latest",
        network: str = "cloding-net",
        workspace_path: str = "",
        memory_limit: str = "2g",
        cpu_limit: float = 1.0,
        container_name: str = "",
    ) -> None:
        self.image = image
        self.network = network
        self.workspace_path = workspace_path
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.container_name = container_name
        self.logger = get_logger("docker_runner", category="DOCKER")

    async def run(
        self, binary_name: str, env: dict[str, str], cli_args: list[str], timeout: int
    ) -> RunResult:
        """
        Run CLI tool in a Docker container.

        Args:
            binary_name: Tool binary name (e.g. "claude", "gemini")
            env: Environment variables to inject
            cli_args: CLI arguments
            timeout: Timeout in seconds

        Returns:
            RunResult with parsed output
        """
        docker_path = shutil.which("docker")
        if not docker_path:
            raise DockerError(
                "Docker not found in PATH. Install Docker Desktop:\n"
                "  https://docs.docker.com/get-docker/"
            )

        cmd = self._build_command(binary_name, env, cli_args)

        self.logger.info(
            "Running in Docker: %s (tool: %s, model: %s)",
            self.image,
            binary_name,
            env.get("ANTHROPIC_MODEL", env.get("GEMINI_MODEL", "unknown")),
        )
        if self.container_name:
            self.logger.info("Container: %s", self.container_name)
        self.logger.debug("Full command: %s", " ".join(cmd))

        proc: Optional[asyncio.subprocess.Process] = None
        try:
            proc = await _launch(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            self.logger.debug("Container exit code: %d", proc.returncode or 0)
            if stderr.strip():
                self.logger.debug("Stderr: %s", stderr[:500])

            return self.build_run_result(
                exit_code=proc.returncode or 0,
                stdout=stdout,
                stderr=stderr,
            )

        except asyncio.TimeoutError:
            self.logger.error(
                "Docker container timed out after %d seconds", timeout
            )
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()
            # Also try to stop the named container
            if self.container_name:
                await self._stop_container(self.container_name)
            return RunResult(
                exit_code=-1,
                stdout="",
                stderr=f"Docker container timed out after {timeout} seconds",
            )
        except OSError as err:
            self.logger.error("Docker runner failed: %s", err)
            raise StageError(f"Docker runner failed: {err}") from err

    def _build_command(
        self, binary_name: str, env: dict[str, str], cli_args: list[str]
    ) -> list[str]:
        """Build the full docker run command as an argument list."""
        cmd = [
            "docker", "run", "--rm",
            "--network", self.network,
            "--memory", self.memory_limit,
            "--cpus", str(self.cpu_limit),
        ]

        # Named container for easier management
        if self.container_name:
            cmd.extend(["--name", self.container_name])

        # Mount workspace
        if self.workspace_path:
            cmd.extend(["-v", f"{self.workspace_path}:/workspace"])

        # Inject environment variables
        for key, value in env.items():
            cmd.extend(["-e", f"{key}={value}"])

        # Always strip CLAUDECODE to prevent nesting errors
        if "CLAUDECODE" not in env:
            cmd.extend(["-e", "CLAUDECODE="])

        # Override entrypoint for non-claude tools (must come before image name)
        if binary_name != "claude":
            cmd.extend(["--entrypoint", binary_name])

        cmd.append(self.image)

        cmd.extend(cli_args)
        return cmd

    @staticmethod
    async def _stop_container(name: str) -> None:
        """Stop a named container (best-effort)."""
        try:
            proc = await _launch(
                "docker", "stop", "-t", "5", name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except OSError:
            pass

    @staticmethod
    async def ensure_image(
        image: str = "cloding:latest",
        dockerfile_dir: str | None = None,
    ) -> None:
        """Build Docker image if not present.

        Args:
            image: Image tag to check/build.
            dockerfile_dir: Directory containing the Dockerfile.
                If None, looks for pipeline/docker/ relative to this file.
        """
        logger = get_logger("docker_runner", category="DOCKER")

        # Check if image exists
        proc = await _launch(
            "docker", "images", "-q", image,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if stdout.strip():
            logger.info("Docker image %s found", image)
            return

        # Resolve dockerfile directory
        if not dockerfile_dir:
            # Default: pipeline/docker/ relative to this file
            dockerfile_dir = str(
                Path(__file__).parent.parent.parent / "docker"
            )

        dockerfile = Path(dockerfile_dir) / "Dockerfile"
        if not dockerfile.exists():
            raise DockerError(
                f"Dockerfile not found at {dockerfile}.\n"
                f"Build manually: docker build -t {image} pipeline/docker/"
            )

        logger.info("Building Docker image: %s ...", image)
        proc = await _launch(
            "docker", "build", "-t", image, str(dockerfile_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        if proc.returncode != 0:
            raise DockerError(
                f"Failed to build image {image}:\n"
                f"{stderr_bytes.decode(errors='replace')}"
            )
        logger.info("Image %s built successfully", image)

    @staticmethod
    async def ensure_network(network: str = "cloding-net") -> None:
        """Create Docker network if not present."""
        logger = get_logger("docker_runner", category="DOCKER")
        proc = await _launch(
            "docker", "network", "create", network,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_bytes = await proc.communicate()
        if proc.returncode != 0:
            stderr = stderr_bytes.decode(errors="replace")
            if "already exists" not in stderr:
                raise DockerError(f"Failed to create Docker network '{network}': {stderr}")

    @staticmethod
    async def cleanup_containers(prefix: str = "cloding-worker") -> int:
        """Stop and remove all containers matching the prefix.

        Returns:
            Number of containers cleaned up.
        """
        logger = get_logger("docker_runner", category="DOCKER")

        # List running containers with the prefix
        proc = await _launch(
            "docker", "ps", "-a", "--filter", f"name={prefix}",
            "--format", "{{.Names}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        names = [n.strip() for n in stdout.decode().strip().split("\n") if n.strip()]

        if not names:
            return 0

        # Stop and remove
        for name in names:
            proc = await _launch(
                "docker", "rm", "-f", name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            logger.info("Removed container: %s", name)

        return len(names)
