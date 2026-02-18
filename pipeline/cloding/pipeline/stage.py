"""Pipeline stage base class and concrete stage implementations."""

import os
from abc import ABC, abstractmethod
from pathlib import Path

from cloding.core.config import ModelConfig, StageConfig
from cloding.core.logger import get_logger
from cloding.models.registry import ModelRegistry
from cloding.pipeline.result import RunResult, StageResult
from cloding.pipeline.state import PipelineState
from cloding.runners.base import BaseRunner


class Stage(ABC):
    """Base class for all pipeline stages."""

    def __init__(
        self,
        config: StageConfig,
        model_config: ModelConfig,
        prompts_dir: str = "prompts",
    ) -> None:
        self.config = config
        self.model_config = model_config
        self.prompts_dir = prompts_dir
        self.logger = get_logger(f"stage.{config.name}", category="STAGE")

    def build_env(self) -> dict[str, str]:
        """Build environment variables for the Claude Code invocation."""
        env: dict[str, str] = {}
        api_key = os.environ.get(self.model_config.api_key_env, "")

        if not api_key:
            self.logger.warning(
                "API key env '%s' is empty or not set", self.model_config.api_key_env
            )

        if self.model_config.provider == "openrouter":
            env["ANTHROPIC_BASE_URL"] = (
                self.model_config.base_url or "https://openrouter.ai/api"
            )
            env["ANTHROPIC_AUTH_TOKEN"] = api_key
            env["ANTHROPIC_API_KEY"] = ""
            env["ANTHROPIC_MODEL"] = self.model_config.model_id
        else:
            # Direct Anthropic API
            env["ANTHROPIC_API_KEY"] = api_key
            env["ANTHROPIC_MODEL"] = self.model_config.model_id

        return env

    def build_cli_args(self, prompt: str) -> list[str]:
        """Build the claude CLI argument list.

        Note: Model is set via ANTHROPIC_MODEL env var (in build_env),
        not via --model flag — avoids conflicts when routing through OpenRouter.
        """
        args = [
            "-p", prompt,
            "--output-format", self.config.output_format,
            "--max-turns", str(self.config.max_turns),
            "--dangerously-skip-permissions",
        ]

        if self.config.allowed_tools:
            args.extend(["--allowedTools", ",".join(self.config.allowed_tools)])

        if self.config.disallowed_tools:
            args.extend(["--disallowedTools", ",".join(self.config.disallowed_tools)])

        return args

    def load_prompt(self) -> str:
        """Load the prompt template from file."""
        path = Path(self.prompts_dir) / Path(self.config.prompt_file).name
        if not path.exists():
            # Try the prompt_file as-is
            path = Path(self.config.prompt_file)
        if not path.exists():
            self.logger.warning("Prompt file not found: %s, using empty", path)
            return ""
        return path.read_text(encoding="utf-8")

    def _make_result(
        self, run_result: RunResult, model_registry: ModelRegistry | None = None
    ) -> StageResult:
        """Convert a RunResult to a StageResult with cost estimation.

        When using OpenRouter, Claude Code reports costs based on Anthropic's
        native pricing, not the actual OpenRouter rates. We always use our
        config-based estimation for OpenRouter models to report accurate costs.
        For direct Anthropic API usage, we trust Claude Code's reported cost.
        """
        cost = run_result.cost_usd
        has_tokens = run_result.tokens_in or run_result.tokens_out

        if model_registry and has_tokens:
            if self.model_config.provider == "openrouter":
                # OpenRouter: always use our rates — Claude Code's cost is inflated
                cost = model_registry.estimate_cost(
                    self.config.model, run_result.tokens_in, run_result.tokens_out
                )
            elif cost == 0.0:
                # Direct Anthropic: fallback only when cost not reported
                cost = model_registry.estimate_cost(
                    self.config.model, run_result.tokens_in, run_result.tokens_out
                )

        return StageResult(
            stage_name=self.config.name,
            output=run_result.stdout,
            tokens_in=run_result.tokens_in,
            tokens_out=run_result.tokens_out,
            cost_usd=cost,
            success=run_result.exit_code == 0,
            session_id=run_result.session_id,
            model_id=self.model_config.model_id,
            provider=self.model_config.provider,
            num_turns=run_result.num_turns,
            duration_ms=run_result.duration_ms,
        )

    @abstractmethod
    async def build_prompt(self, state: PipelineState) -> str:
        """Build the full prompt for this stage."""
        ...

    async def run(
        self,
        runner: BaseRunner,
        state: PipelineState,
        model_registry: ModelRegistry | None = None,
    ) -> StageResult:
        """Execute this stage."""
        prompt = await self.build_prompt(state)
        env = self.build_env()
        cli_args = self.build_cli_args(prompt)

        self.logger.info(
            "Executing stage '%s' with model '%s' (%s)",
            self.config.name,
            self.model_config.model_id,
            self.model_config.provider,
        )

        run_result = await runner.run(
            env=env,
            cli_args=cli_args,
            timeout=self.config.timeout_seconds,
        )

        result = self._make_result(run_result, model_registry)

        if result.success:
            self.logger.info(
                "Stage '%s' completed: %d tokens, $%.4f",
                self.config.name,
                result.tokens_in + result.tokens_out,
                result.cost_usd,
            )
        else:
            self.logger.error(
                "Stage '%s' failed (exit %d): %s",
                self.config.name,
                run_result.exit_code,
                run_result.stderr[:200] if run_result.stderr else "no stderr",
            )

        return result


class PlanStage(Stage):
    """Opus creates the implementation plan."""

    async def build_prompt(self, state: PipelineState) -> str:
        template = self.load_prompt()
        parts = [template] if template else []
        parts.append(f"\n\nUser request:\n{state.user_request}")
        if state.context_files:
            parts.append(f"\n\nKey files to examine:\n" + "\n".join(state.context_files))
        return "\n".join(parts)


class ExploreStage(Stage):
    """Haiku reads files, searches codebase, gathers context."""

    async def build_prompt(self, state: PipelineState) -> str:
        template = self.load_prompt()
        parts = [template] if template else []
        # Primary plan source is PLAN.md in workspace (read by the model).
        if state.context_files:
            parts.append(f"\n\nKey files to explore:\n" + "\n".join(state.context_files))
        return "\n".join(parts)


class CodeStage(Stage):
    """Qwen writes the actual code based on plan + context."""

    async def build_prompt(self, state: PipelineState) -> str:
        template = self.load_prompt()
        parts = [template] if template else []
        # Primary plan source is PLAN.md in workspace (read by the model).
        # Exploration context is in CONTEXT.md in workspace (read by the model).
        if state.review_feedback:
            parts.append(
                f"\n\nPrevious review feedback (iteration {state.review_iteration}):"
                f"\n{state.review_feedback}"
                f"\n\nFix the issues described above."
            )
        return "\n".join(parts)


class ReviewStage(Stage):
    """Opus reviews the code changes, outputs PASS or FAIL with feedback."""

    async def build_prompt(self, state: PipelineState) -> str:
        template = self.load_prompt()
        parts = [template] if template else []
        # Primary plan source is PLAN.md in workspace (read by the model).
        parts.append(
            "\n\nReview the changes that have been made to the workspace. "
            "Read PLAN.md for the implementation plan, then run `git diff` "
            "to see what changed. Check the code against the plan."
        )
        return "\n".join(parts)


# Stage class registry
STAGE_CLASSES: dict[str, type[Stage]] = {
    "plan": PlanStage,
    "explore": ExploreStage,
    "code": CodeStage,
    "review": ReviewStage,
}


def create_stage(
    config: StageConfig,
    model_config: ModelConfig,
    prompts_dir: str = "prompts",
) -> Stage:
    """
    Factory function to create a stage by name.

    Args:
        config: Stage configuration
        model_config: Model configuration for this stage
        prompts_dir: Directory containing prompt templates

    Returns:
        Instantiated Stage subclass
    """
    cls = STAGE_CLASSES.get(config.name)
    if cls is None:
        raise ValueError(
            f"Unknown stage type: '{config.name}'. "
            f"Available: {list(STAGE_CLASSES.keys())}"
        )
    return cls(config=config, model_config=model_config, prompts_dir=prompts_dir)
