# cloding

**AI coding with any model, any CLI, one command.**

Cloding is a universal wrapper that lets you run Claude Code, Gemini CLI, Codex CLI, OpenCode, or GitHub Copilot CLI with any model — through OpenRouter or direct API keys. Same agentic coding experience, your choice of model and tool.
░█████╗░██╗░░░░░░█████╗░██████╗░██╗███╗░░██╗░██████╗░
██╔══██╗██║░░░░░██╔══██╗██╔══██╗██║████╗░██║██╔════╝░
██║░░╚═╝██║░░░░░██║░░██║██║░░██║██║██╔██╗██║██║░░██╗░
██║░░██╗██║░░░░░██║░░██║██║░░██║██║██║╚██╗██║██║░░╚██╗
╚█████╔╝███████╗╚█████╔╝██████╔╝██║██║░╚████║╚██████╔╝
░╚════╝░╚══════╝░╚════╝░╚═════╝░╚═╝╚═╝░░╚═══╝░╚═════╝

**Code with any model via OpenRouter.**

Claude Opus 4.6 costs $5/$25 per Mtok.
Qwen 3 Coder Next costs $0.07/$0.30.
That's 71x cheaper on input, 83x cheaper on output.

Code with any LLM in a Docker sandbox. Configurable multi-stage code orchestration via Claude Code + OpenRouter.

## Quick Start
```bash
Install Claude Code

macOS, Linux, WSL:
curl -fsSL https://claude.ai/install.sh | bash

Windows PowerShell:
irm https://claude.ai/install.ps1 | iex

npm install -g @anthropic-ai/claude-code

Install Cloding

npm install -g cloding
export OPENROUTER_API_KEY=sk-or-v1-your-key-here
cloding
```

Runs Claude Code with Qwen 3 Coder Next. $0.07/Mtok input vs $5/Mtok.

Switch models anytime:
```bash
export OPENROUTER_API_KEY=sk-or-v1-your-key-here
cloding                    # Start coding with Qwen 3 Coder ($0.12/Mtok)
```

That's it. You're running Claude Code with Qwen at 42x cheaper input cost than Claude Opus.
cloding -m sonnet          # Claude Sonnet 4.6
cloding -m qwen            # Qwen 3 Coder Next
cloding --list-models      # see all options + pricing
```

Run sandboxed in Docker:
```bash
cloding docker build && cloding docker shell
```

## How It Works

Cloding sets the right environment variables and spawns the right CLI. Each model in `models.json` has a `tool` field that determines which CLI gets launched:

```
cloding -m qwen       →  spawns Claude Code   (via OpenRouter)
cloding -m gemini     →  spawns Gemini CLI    (via OpenRouter)
cloding -m gemini-3   →  spawns Gemini CLI    (via Google API directly)
cloding -m codex-5    →  spawns Codex CLI     (via OpenAI API directly)
cloding -m copilot    →  spawns Copilot CLI   (via GitHub, subscription)
```

No config files to edit. No environment variables to juggle. Just pick a model and go.

## All Commands

### Simple Mode

Run any model interactively or with a single prompt.

```bash
# Basic usage
cloding                                  # Interactive session (default: Qwen)
cloding -m haiku                         # Use Claude Haiku 4.5
cloding -m sonnet                        # Use Claude Sonnet 4
cloding -m opus                          # Use Claude Opus 4.6
cloding -m deepseek                      # Use DeepSeek V3.2
cloding -p "fix the bug"                 # Non-interactive single prompt
cloding -m opus -p "review architecture" # One-shot with specific model

# Multi-tool models
cloding -m gemini                        # Gemini 2.5 Pro via Gemini CLI
cloding -m gemini-3                      # Gemini 3 Pro via direct Google API
cloding -m codex-5                       # Codex 5.3 via Codex CLI
cloding -m copilot                       # GitHub Copilot via Copilot CLI

# Any OpenRouter model ID
cloding -m meta-llama/llama-4-scout      # Use any model on OpenRouter
cloding -m mistralai/mistral-large       # Full model ID as shortcut

# Utility
cloding --list-models                    # Show all models with pricing
cloding -v                               # Show version
cloding -h                               # Show help

# Claude Code passthrough (all flags work)
cloding --allowedTools Read,Write,Bash
cloding --output-format json
```

### Docker Mode

Sandboxed execution. The model can only touch the workspace you mount — no access to your filesystem, SSH keys, or environment.

```bash
# Setup
cloding docker build                             # Build the Docker image (one-time)

# Run prompts in containers
cloding docker run "fix the bug"                 # Run a prompt
cloding docker run -m haiku "add tests"          # Specific model
cloding docker run -m gemini "build the API"     # Gemini CLI in Docker
cloding docker run -m codex-5 "refactor utils"   # Codex CLI in Docker
cloding docker run -m copilot "fix linting"      # Copilot CLI in Docker
cloding docker run -w ./myproject "fix tests"    # Mount a workspace
cloding docker run --memory 4g --cpus 2 "prompt" # Resource limits
cloding docker run --name my-task "prompt"       # Custom container name
cloding docker run --no-rm "prompt"              # Keep container after exit

# Interactive sessions
cloding docker shell                             # Interactive Claude session
cloding docker shell -m sonnet                   # Interactive with specific model
cloding docker shell -w /path/to/project         # Mount a workspace

# Management
cloding docker status                            # Show running containers
cloding docker stop                              # Stop all cloding containers
cloding docker clean                             # Remove stopped containers
cloding docker help                              # Show Docker help
```

Docker run/shell options:

| Flag | Default | Description |
|------|---------|-------------|
| `-m, --model` | qwen | Model shortcut or OpenRouter ID |
| `-p, --prompt` | — | Prompt text (alternative to positional arg) |
| `-w, --workspace` | cwd | Mount a local directory as `/workspace` |
| `--memory` | 2g | Container memory limit |
| `--cpus` | 1.0 | Container CPU limit |
| `--name` | auto | Custom container name |
| `--no-rm` | false | Don't auto-remove container on exit |
| Shortcut | Model | Input $/Mtok | Output $/Mtok | vs Claude Code |
|----------|-------|-------------|---------------|----------------|
| `qwen` | Qwen 3 Coder Next | $0.07 | $0.30 | **71x cheaper** |
| `deepseek` | DeepSeek Coder V3 | $0.14 | $0.28 | **36x cheaper** |
| `haiku` | Claude Haiku 4.5 | $0.80 | $4.00 | 6x cheaper |
| `gemini` | Gemini 2.5 Pro | $1.25 | $10.00 | 4x cheaper |
| `sonnet` | Claude Sonnet 4 | $3.00 | $15.00 | 1.7x cheaper |
| `opus` | Claude Opus 4.6 | $15.00 | $75.00 | 3x more expensive |

## Docker Mode

### Pipeline Mode

Multi-stage coding pipeline with parallel fan-out, quality gates, and multi-agent verification. Assign different models and tools to different stages.

```bash
# Setup (one-time)
cd pipeline && pip install -e .                                     # Requires Python 3.11+

# Run pipelines
cloding pipeline "Add auth" --workspace ./myapp --no-docker         # Standard pipeline
cloding pipeline -c configs/qwen-fanout.yaml "Refactor DB layer"    # Parallel fan-out
cloding pipeline -c configs/gemini-test.yaml "Build the API"        # Gemini CLI stages
cloding pipeline -c configs/codex-test.yaml "Add error handling"    # Codex CLI stages
cloding pipeline -c configs/copilot-test.yaml "Write docs"         # Copilot CLI stages
cloding pipeline -c configs/opus-plan-qwen-code.yaml "Add caching"  # Mix models
cloding pipeline --dry-run -c configs/default.yaml "anything"       # Preview config
cloding pipeline --resume code --run-id <id> "original request"     # Resume from stage
cloding pipeline -f request.txt -w ./myapp                         # Read request from file
cloding pipeline -v "Debug this" --no-git                          # Verbose, skip git
```

Pipeline CLI flags:

| Flag | Default | Description |
|------|---------|-------------|
| `-c, --config` | `configs/default.yaml` | Path to YAML pipeline config |
| `-w, --workspace` | cwd | Target workspace directory |
| `-f, --file` | — | Read request from file instead of argument |
| `--context-files` | — | Comma-separated key files to examine |
| `--no-docker` | false | Run locally instead of in Docker containers |
| `--no-git` | false | Skip git branch creation and stash |
| `--dry-run` | false | Print pipeline config and exit |
| `--resume STAGE` | — | Resume from a specific stage (e.g., `code`) |
| `--run-id ID` | — | Run ID to resume from (used with `--resume`) |
| `--prompts-dir` | `prompts` | Directory containing prompt templates |
| `-v, --verbose` | false | Enable debug logging |

## Models & Pricing

### OpenRouter Models

These models route through OpenRouter. You only need `OPENROUTER_API_KEY`.

| Shortcut | Model | Input $/Mtok | Output $/Mtok | Tool | vs Opus |
|----------|-------|-------------|---------------|------|---------|
| `qwen` | Qwen 3 Coder | $0.12 | $0.75 | Claude Code | **42x cheaper** |
| `deepseek` | DeepSeek V3.2 | $0.26 | $0.38 | Claude Code | **66x cheaper** |
| `haiku` | Claude Haiku 4.5 | $1.00 | $5.00 | Claude Code | 5x cheaper |
| `gemini` | Gemini 2.5 Pro | $1.25 | $10.00 | Gemini CLI | 2.5x cheaper |
| `sonnet` | Claude Sonnet 4 | $3.00 | $15.00 | Claude Code | 1.7x cheaper |
| `opus` | Claude Opus 4.6 | $5.00 | $25.00 | Claude Code | baseline |

### Direct API Models

These models bypass OpenRouter and call the provider's API directly. Set the provider's API key instead.

| Shortcut | Model | Tool | API Key |
|----------|-------|------|---------|
| `gemini-3` | Gemini 3 Pro | Gemini CLI | `GOOGLE_API_KEY` |
| `codex-5` | Codex 5.3 High | Codex CLI | `OPENAI_API_KEY` |
| `copilot` | GitHub Copilot | Copilot CLI | `GITHUB_TOKEN` |

Any OpenRouter model ID also works as a shortcut: `cloding -m meta-llama/llama-4-scout`

## Multi-Tool Architecture

Cloding dispatches to five different coding CLIs based on the model's `tool` field in `models.json`:

| Tool | CLI | How It's Used |
|------|-----|---------------|
| `claude` (default) | [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | Models without a `tool` field use Claude Code via OpenRouter |
| `gemini` | [Gemini CLI](https://github.com/google-gemini/gemini-cli) | Models with `"tool": "gemini"` launch the Gemini CLI |
| `codex` | [Codex CLI](https://github.com/openai/codex) | Models with `"tool": "codex"` launch the Codex CLI |
| `copilot` | [GitHub Copilot CLI](https://github.com/github/copilot-cli) | Models with `"tool": "copilot"` launch the Copilot CLI |
| `opencode` | [OpenCode](https://github.com/opencode-ai/opencode) | Models with `"tool": "opencode"` launch OpenCode |

Each tool handler automatically:
- Sets the right environment variables (`ANTHROPIC_*`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `GITHUB_TOKEN`, etc.)
- Builds the correct CLI arguments (`-p` for prompts, `--model` for model selection)
- Overrides the Docker entrypoint for non-Claude tools
- Handles Windows/WSL routing for Codex

### Adding Custom Models

Edit `models.json` to add your own shortcuts:

```json
{
  "my-model": {
    "id": "your-provider/model-id",
    "name": "My Custom Model",
    "tool": "gemini",
    "provider": "google",
    "api_key_env": "GOOGLE_API_KEY",
    "in": 0.0,
    "out": 0.0,
    "description": "My custom model via Gemini CLI."
  }
}
```

Fields:
- `id` — OpenRouter model ID or provider model ID (required)
- `name` — Display name (required)
- `in` / `out` — Cost per million tokens, input/output (required)
- `tool` — Which CLI to use: `claude`, `gemini`, `codex`, `copilot`, `opencode` (default: `claude`)
- `provider` — `openrouter` or direct provider name (default: `openrouter`)
- `api_key_env` — Environment variable for the API key (default: `OPENROUTER_API_KEY`)

## Pipeline Features

### Default Pipeline

```
Plan (Opus) → Explore (Haiku) → Code (Qwen) → Test (Qwen) → Lint (Qwen) → Review (Opus)
```

Each stage uses the best model for the job. Expensive models plan and review. Cheap models do the heavy lifting.

### Parallel Fan-Out

The planner splits large tasks into independent subtasks. Each subtask runs in its own container with its own agent, all in parallel:

```bash
cloding pipeline -c configs/qwen-fanout.yaml "Refactor the entire API layer"
```

### Quality Gates

**Test stage** — Runs the project's test suite, fixes failures, re-runs until green or out of turns.

**Lint stage** — Runs linters and type checkers (ruff, eslint, mypy, etc.), fixes violations, re-runs until clean.

Both stages output PASS or FAIL. The pipeline logs a warning if they don't pass but continues.

### Multi-Agent Verification

After all stages complete, independent agents review the changes in parallel. Configure in your pipeline YAML:

```yaml
verify:
  enabled: true
  agents:
    - model: opus
      prompt_file: prompts/verify.txt
    - model: haiku
      prompt_file: prompts/verify.txt
    - model: qwen
      prompt_file: prompts/verify.txt
  consensus_threshold: 0.67
  max_iterations: 3
```

Each agent independently reads the plan, reviews the diff, runs tests, and votes PASS or FAIL. The pipeline passes when the consensus threshold is met (e.g., 2 of 3 agents agree).

### Exploration Caching

The explore stage caches its output (CONTEXT.md) keyed by workspace file hash. Subsequent runs against the same codebase skip exploration entirely, saving time and cost.

### TUI Progress Tracker

Pipeline runs display a live terminal UI showing per-stage status, elapsed time, running cost, mini progress bars, and run ID.

### Pipeline Configs

| Config | Pipeline | Notes |
|--------|----------|-------|
| `default.yaml` | Plan → Explore → Code → Test → Lint → Review | Full pipeline, fan-out, verification |
| `quick.yaml` | Plan → Code | Fast 2-stage with Qwen |
| `qwen-fanout.yaml` | Plan → Code (parallel) | Splits tasks, N workers |
| `opus-plan-qwen-code.yaml` | Plan (Opus) → Code (Qwen) | Best quality/cost ratio |
| `human-loop.yaml` | Plan → Code → Review | Pauses for human approval |
| `gemini-test.yaml` | Plan → Code | Gemini CLI integration |
| `codex-test.yaml` | Plan → Code | Codex CLI integration |
| `copilot-test.yaml` | Plan → Code | GitHub Copilot CLI integration |
| `qwen-tools-test.yaml` | Plan → Code | Tests Qwen's tool use |
| `test-cheap.yaml` | Minimal | Fast testing |
| `test-fanout.yaml` | Fan-out | Parallel execution testing |

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENROUTER_API_KEY` | Yes | Your OpenRouter API key. Get one at [openrouter.ai/keys](https://openrouter.ai/keys) |
| `CLODING_DEFAULT_MODEL` | No | Default model shortcut (default: `qwen`) |
| `GOOGLE_API_KEY` | For `gemini-3` | Direct Google API key for Gemini models |
| `OPENAI_API_KEY` | For `codex-5` | Direct OpenAI API key for Codex models |
| `GITHUB_TOKEN` | For `copilot` | GitHub PAT with Copilot access |

```bash
# Required for OpenRouter models
export OPENROUTER_API_KEY=sk-or-v1-your-key-here

# Optional: change default model
export CLODING_DEFAULT_MODEL=haiku

# Optional: direct provider keys (bypass OpenRouter)
export GOOGLE_API_KEY=your-google-api-key
export OPENAI_API_KEY=your-openai-api-key
export GITHUB_TOKEN=your-github-pat
```

## Prerequisites

- **Node.js 18+** — required for all modes
- **OpenRouter API key** — [openrouter.ai/keys](https://openrouter.ai/keys)

Per-tool requirements (only install what you need):

| Tool | Install | Needed For |
|------|---------|------------|
| Claude Code | `npm install -g @anthropic-ai/claude-code` | `qwen`, `haiku`, `sonnet`, `opus`, `deepseek`, and any custom OpenRouter model |
| Gemini CLI | [github.com/google-gemini/gemini-cli](https://github.com/google-gemini/gemini-cli) | `gemini`, `gemini-3` |
| Codex CLI | [github.com/openai/codex](https://github.com/openai/codex) | `codex-5` |
| Copilot CLI | `npm install -g @github/copilot-cli` | `copilot` |
| Docker | [Docker Desktop](https://docs.docker.com/get-started/get-docker/) | Docker mode |
| Python 3.11+ | [python.org](https://python.org) | Pipeline mode |

## Testing

```bash
cd pipeline && pip install -r requirements-dev.txt
pytest tests/ -v -p no:anchorpy          # 174+ tests
pytest tests/ --cov=cloding --cov-report=term-missing  # Coverage (80%+ target)
```

## License

MIT
