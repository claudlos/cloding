# CLAUDE.md — Cloding

Claude Code with any model via OpenRouter. 70x cheaper coding.

## Publishing

After every `git push`, always publish to npm:
```bash
npm version patch --no-git-tag-version
npm publish
```
Then commit the version bump separately.

## Quick Commands

```bash
# Simple mode — launch Claude Code with cheap models
npm install -g .          # Install locally
cloding                   # Interactive with Qwen (default)
cloding -m haiku          # Use Haiku
cloding -p "fix the bug"  # Non-interactive single prompt
cloding --list-models     # Show all models + costs
cloding -v                # Show version

# Docker mode — isolated container execution
cloding docker build                    # Build the cloding Docker image
cloding docker shell                    # Interactive claude session in container
cloding docker run "fix the bug"        # Run prompt in container
cloding docker run -m haiku "prompt"    # Container with specific model
cloding docker run -w /path/to/project  # Mount a workspace
cloding docker run --memory 4g --cpus 2 # Resource limits
cloding docker status                   # Show running containers
cloding docker stop                     # Stop all cloding containers
cloding docker clean                    # Remove stopped containers

# Pipeline mode — multi-stage orchestrator (requires Python 3.11+)
cd pipeline && pip install -e .
cloding pipeline "Add auth" --workspace ./myapp --no-docker
cloding pipeline -c configs/qwen-fanout.yaml "Refactor DB layer"
cloding pipeline --dry-run -c configs/default.yaml "anything"
cloding pipeline --resume code --run-id <id> "original request"

# Tests (pipeline)
cd pipeline && pip install -r requirements-dev.txt
cd pipeline && pytest tests/ -v -p no:anchorpy    # 174 tests, all async
cd pipeline && pytest tests/ -v --tb=short         # Shorter output
cd pipeline && pytest tests/ --cov=cloding --cov-report=term-missing  # Coverage (80%+ required)
```

## Architecture

### Simple Mode (Node.js — `bin/cloding.js`)
Zero-dependency Node.js CLI. Sets 4 env vars and spawns `claude`:
- `ANTHROPIC_BASE_URL` → `https://openrouter.ai/api/v1`
- `ANTHROPIC_AUTH_TOKEN` → user's OpenRouter API key
- `ANTHROPIC_API_KEY` → `""` (empty string, required by claude)
- `ANTHROPIC_MODEL` → resolved OpenRouter model ID

Files:
- **bin/cloding.js**: CLI entry point (~850 lines). Arg parsing, model resolution, Docker management, pipeline delegation, claude spawning.
- **models.json**: Model registry with shortcuts, OpenRouter IDs, display names, and $/Mtok costs.
- **package.json**: npm package config. `files` array controls what ships to npm (bin/, models.json, README, LICENSE).

### Docker Mode (Node.js — part of `bin/cloding.js`)
Runs claude inside isolated Docker containers with:
- Non-root `coder` user (UID 1000)
- Network isolation (`cloding-net` bridge network)
- Resource limits (`--memory`, `--cpus`)
- Workspace volume mount (`-w /path` → `/workspace` in container)
- Auto-remove on exit (disable with `--no-rm`)
- Custom container naming (`--name`)

Files:
- **pipeline/docker/Dockerfile**: Multi-stage build. Node 22 slim, installs claude-code, creates non-root user.
- **pipeline/docker/docker-compose.yml**: Compose config with resource defaults (2G memory, 1.0 CPU).

### Pipeline Mode (Python)
4-stage pipeline: Plan → Explore → Code → Review, with parallel fan-out.

- **pipeline/cloding/**: Python package root
  - **`__init__.py`**: Package init, exports `__version__ = "0.1.0"`
  - **`__main__.py`**: Allows `python -m cloding` invocation
  - **orchestrator.py**: Top-level: load config → prepare workspace → build pipeline → run → report
- **pipeline/cloding/core/**: Config loader, errors, logger, workspace git prep
- **pipeline/cloding/pipeline/**: Stage base + concrete stages (Plan/Explore/Code/Review), pipeline sequencer, state, results
- **pipeline/cloding/runners/**: BaseRunner ABC, LocalRunner (direct CLI via asyncio subprocess), DockerRunner (containers)
- **pipeline/cloding/fanout/**: Task splitter, parallel runner (asyncio.Semaphore), merge
- **pipeline/cloding/models/**: Model registry (config-based cost estimation for OpenRouter), cost tracker with CSV export
- **pipeline/cloding/cli/**: Argparse CLI entry point (`cloding-pipeline` script)
- **pipeline/configs/**: 9 YAML pipeline configs (see below)
- **pipeline/prompts/**: Stage prompt templates (plan.txt, explore.txt, code.txt, review.txt)

## Key Files

| File | Purpose |
|------|---------|
| `bin/cloding.js` | Node.js CLI — sets env vars, spawns claude, manages Docker, delegates pipeline |
| `models.json` | Model shortcuts with OpenRouter IDs, names, and costs |
| `pipeline/cloding/orchestrator.py` | Top-level pipeline orchestration |
| `pipeline/cloding/pipeline/pipeline.py` | Pipeline sequencer, review loop, checkpoints |
| `pipeline/cloding/pipeline/stage.py` | Stage ABC + PlanStage, ExploreStage, CodeStage, ReviewStage |
| `pipeline/cloding/core/config.py` | YAML config loading + dataclass hierarchy |
| `pipeline/cloding/core/workspace.py` | Git workspace prep: branch creation (`cloding/`), stash, safety checks |
| `pipeline/cloding/core/tool_handler.py` | Tool handlers for each CLI (ClaudeCode, Gemini, OpenCode, Codex, Copilot) |
| `pipeline/cloding/runners/local_runner.py` | Runs CLI tools via asyncio subprocess |
| `pipeline/cloding/runners/docker_runner.py` | Runs claude CLI in Docker containers |
| `pipeline/cloding/models/registry.py` | Model registry + config-based cost estimation (primary cost source for OpenRouter) |
| `pipeline/cloding/models/cost_tracker.py` | Per-stage cost tracking with CSV export |
| `pipeline/docker/Dockerfile` | Docker image definition (non-root user, resource isolation) |

## Pipeline Configs

| Config | Purpose |
|--------|---------|
| `default.yaml` | Standard 4-stage with Sonnet plan/review, Qwen explore/code |
| `quick.yaml` | Fast 2-stage (plan+code) with Qwen |
| `qwen-fanout.yaml` | Parallel fan-out: splits tasks, runs N workers concurrently |
| `opus-plan-qwen-code.yaml` | Opus for planning, Qwen for coding — best quality/cost ratio |
| `human-loop.yaml` | Human-in-the-loop review: pauses for approval between stages |
| `copilot-test.yaml` | GitHub Copilot CLI integration testing |
| `qwen-tools-test.yaml` | Tests Qwen's tool use capabilities (Read, Write, Grep, Glob, Bash) |
| `test-cheap.yaml` | Minimal config for fast testing |
| `test-fanout.yaml` | Fan-out config for testing parallel execution |

## Models (via OpenRouter)

| Shortcut | Model | Input $/Mtok | Output $/Mtok |
|----------|-------|-------------|---------------|
| qwen | Qwen 3 Coder | $0.12 | $0.75 |
| haiku | Claude Haiku 4.5 | $1.00 | $5.00 |
| sonnet | Claude Sonnet 4 | $3.00 | $15.00 |
| opus | Claude Opus 4.6 | $5.00 | $25.00 |
| deepseek | DeepSeek V3.2 | $0.26 | $0.38 |
| gemini | Gemini 2.5 Pro | $1.25 | $10.00 |

## Direct API Models

| Shortcut | Model | Tool | API Key Env |
|----------|-------|------|-------------|
| gemini-3 | Gemini 3 Pro (Paid Plan) | Gemini CLI | *(none)* |
| gemini-3-a | Gemini 3 Pro (API) | Gemini CLI | `GOOGLE_API_KEY` |
| codex-5 | Codex (Paid Plan) | Codex CLI | *(none)* |
| codex-5-a | Codex 5.3 High (API) | Codex CLI | `OPENAI_API_KEY` |
| copilot | GitHub Copilot | Copilot CLI | `GITHUB_TOKEN` |

Any OpenRouter model ID also works: `cloding -m meta-llama/llama-4-scout`

## Pipeline CLI Flags

| Flag | Purpose |
|------|---------|
| `-c, --config` | Path to YAML pipeline config (default: configs/default.yaml) |
| `-w, --workspace` | Path to target workspace (default: cwd) |
| `-f, --file` | Read request from file instead of argument |
| `--context-files` | Comma-separated list of key files to examine |
| `--no-docker` | Run Claude Code locally instead of in Docker |
| `--no-git` | Skip git workspace preparation (branch creation, stash) |
| `--dry-run` | Print pipeline config and exit without executing |
| `--resume STAGE` | Resume from a specific stage (e.g., 'code') |
| `--run-id ID` | Run ID to resume from (used with --resume) |
| `--prompts-dir` | Directory containing prompt templates (default: prompts) |
| `-v, --verbose` | Enable debug logging |

## Testing

- **174 tests** across 14 test files, all async (pytest-asyncio)
- Test files in `pipeline/tests/`: cli, config, cost_tracker, docker_runner, fanout, local_runner, logger, orchestrator, parallel_runner, pipeline, pipeline_sequencer, registry, stage, workspace
- Dev dependencies: `pytest>=8.0`, `pytest-asyncio>=0.23`, `black`, `isort`, `ruff`, `mypy`, `coverage`
- Coverage: **80.6%** (target: 80%, configured in `pyproject.toml [tool.coverage.report] fail_under = 80`)
- Run: `cd pipeline && pytest tests/ -v -p no:anchorpy`
- Run with coverage: `cd pipeline && pytest tests/ --cov=cloding --cov-report=term-missing`
- Note: `-p no:anchorpy` disables anchorpy plugin if installed (conflicts with pytest-asyncio)

## Code Style

- **Node.js**: Zero dependencies, vanilla JS, CommonJS require. No build step.
- **Python**: Line length 100 (black), type hints, Google-style docstrings
- Custom error hierarchy in `pipeline/cloding/core/errors.py` (ClodingError base → ConfigError, RunnerError, CostError, ReviewRejectedError, WorkspaceError)
- Logger via `get_logger("name", category="CAT")` — categories: SYSTEM, STAGE, DOCKER, COST, REVIEW, FANOUT, WORKSPACE
- Subprocess safety: `asyncio.create_subprocess_exec` (no shell) aliased as `_launch`
- Exit code handling: `process.exit(code ?? 0)` (nullish coalescing, not `||`)

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `OPENROUTER_API_KEY` | Yes | Your OpenRouter API key. Get one at https://openrouter.ai/keys |
| `CLODING_DEFAULT_MODEL` | No | Default model shortcut (default: qwen) |
| `GOOGLE_API_KEY` | For gemini-3-a | Direct Google API key for Gemini models |
| `OPENAI_API_KEY` | For codex-5-a | Direct OpenAI API key for Codex models |
| `GITHUB_TOKEN` | For copilot | GitHub PAT with Copilot access |

Internally set by `bin/cloding.js` when spawning claude (do not set manually):
- `ANTHROPIC_BASE_URL` → `https://openrouter.ai/api/v1`
- `ANTHROPIC_AUTH_TOKEN` → user's OpenRouter API key (Bearer token)
- `ANTHROPIC_API_KEY` → `""` (empty, but must be present)
- `ANTHROPIC_MODEL` → resolved OpenRouter model ID

The `CLAUDECODE` env var is stripped from child processes to prevent nesting errors.
