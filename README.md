# cloding

**Code with any model via OpenRouter.**

Claude Code costs $5/$25 per Mtok. Qwen 3 Coder costs $0.07/$0.30. That's 71x cheaper on input, 83x cheaper on output.

Cloding lets you run Claude Code — tools, file editing, terminal access, the whole thing — with any OpenRouter model. Same experience, fraction of the cost.

```
npm install -g cloding
```

## Quick Start

```bash
export OPENROUTER_API_KEY=sk-or-v1-your-key-here
cloding
```

You're now running Claude Code with Qwen 3 Coder at **$0.07/Mtok input** instead of $5/Mtok.

## Usage

```bash
cloding                              # Interactive session with Qwen (default)
cloding -m haiku                     # Use Claude Haiku 4.5
cloding -m sonnet                    # Use Claude Sonnet 4
cloding -m opus                      # Use Claude Opus 4.6
cloding -m deepseek                  # Use DeepSeek Coder V3
cloding -m gemini                    # Use Gemini 2.5 Pro (via Gemini CLI)
cloding -p "add dark mode"           # Non-interactive, single prompt
cloding --list-models                # Show all models with pricing
cloding -m meta-llama/llama-4-scout  # Any OpenRouter model ID works
```

All Claude Code flags pass through:
```bash
cloding --allowedTools Read,Write,Bash
```

## Models & Cost

| Shortcut | Model | Input $/Mtok | Output $/Mtok | vs Claude Code |
|----------|-------|-------------|---------------|----------------|
| `qwen` | Qwen 3 Coder | $0.07 | $0.30 | **71x cheaper** |
| `deepseek` | DeepSeek Coder V3 | $0.14 | $0.28 | **36x cheaper** |
| `haiku` | Claude Haiku 4.5 | $0.80 | $4.00 | 6x cheaper |
| `gemini` | Gemini 2.5 Pro | $1.25 | $10.00 | 4x cheaper |
| `sonnet` | Claude Sonnet 4 | $3.00 | $15.00 | 1.7x cheaper |
| `opus` | Claude Opus 4.6 | $15.00 | $75.00 | 3x more expensive |

> A 30-minute coding session that costs ~$5 with Claude Code costs ~$0.07 with Qwen. Same tools, same workflow.

## Multi-Tool Support

Cloding isn't locked to Claude Code. Models can declare a `tool` field in `models.json` that routes them to the right CLI:

| Tool | CLI | Models |
|------|-----|--------|
| `claude` (default) | Claude Code | qwen, haiku, sonnet, opus, deepseek |
| `gemini` | Gemini CLI | gemini, gemini-3 |
| `codex` | Codex CLI | codex-5 |
| `opencode` | OpenCode CLI | (any OpenCode-compatible model) |

```bash
cloding -m gemini                 # Launches Gemini CLI instead of Claude Code
cloding -m gemini-3               # Gemini 3 Pro via direct Google API
cloding -m codex-5                # Codex 5.3 via Codex CLI
```

Each tool handler builds the right env vars and CLI args automatically. In the pipeline, models can specify `tool: gemini` in the YAML config and stages will dispatch to the correct binary.

## Docker Mode

When you run Claude Code, it has full access to your machine — your files, your terminal, your `.env`, your SSH keys, everything. Docker mode puts it in a box. The model can only touch the workspace you mount and nothing else.

```bash
cloding docker build                    # Build image (one-time)
cloding docker shell                    # Interactive session
cloding docker run "fix the bug"        # Run a prompt
cloding docker run -m haiku "prompt"    # Specific model
cloding docker run -m gemini "prompt"   # Gemini CLI in Docker
cloding docker run -w ./myproject       # Mount workspace
cloding docker run --memory 4g --cpus 2 # Resource limits
cloding docker status                   # Show running containers
cloding docker stop                     # Stop all containers
cloding docker clean                    # Remove stopped containers
```

Your workspace gets mounted read-write at `/workspace` inside the container. That's the only thing the model can touch.

## Pipeline Mode

Multi-stage coding pipeline with parallel fan-out, quality gates, and multi-agent verification. Assign different models and different tools to different stages.

```bash
cd pipeline && pip install -e .    # Requires Python 3.11+
cloding pipeline "Add auth" --workspace ./myapp --no-docker
cloding pipeline -c configs/qwen-fanout.yaml "Refactor the DB layer"
cloding pipeline -c configs/gemini-test.yaml "Build the API"
cloding pipeline --dry-run -c configs/default.yaml "anything"
```

### Default Pipeline

```
Plan (Opus) → Explore (Haiku) → Code (Qwen) → Test (Qwen) → Lint (Qwen) → Review (Opus)
```

The default config (`configs/default.yaml`) runs a 6-stage pipeline with cost budgets per stage, allowed tool lists, and parallel fan-out enabled.

### New Stages

**Test stage** — Runs the project's test suite, fixes failures, re-runs until green or out of turns. Output starts with PASS or FAIL.

**Lint stage** — Runs linters and type checkers (ruff, eslint, mypy, etc.), fixes violations, re-runs until clean. Output starts with PASS or FAIL.

Both are quality gates: the pipeline logs a warning if they don't pass but continues execution (the agent already attempted fixes within its session).

### Multi-Agent Verification

After all stages complete, independent verification agents review the code changes in parallel. Configure in your pipeline YAML:

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

Each agent independently reads the plan, reviews the diff, runs tests, and votes PASS or FAIL. The pipeline passes verification when the consensus threshold is met (e.g., 2 of 3 agents agree).

### Exploration Caching

The explore stage caches its output (CONTEXT.md) keyed by workspace file hash. Subsequent runs against the same codebase skip exploration entirely and load the cached context, saving time and cost on repeated runs.

### TUI Progress Tracker

Pipeline runs display a live Rich terminal UI showing:
- Per-stage status (pending, running, completed, failed)
- Elapsed time and running cost
- Mini progress bars per stage
- Request summary and run ID

### Pipeline Configs

| Config | Pipeline | Notes |
|--------|----------|-------|
| `default.yaml` | Plan → Explore → Code → Test → Lint → Review | Full pipeline with verify, fan-out |
| `quick.yaml` | Plan → Code | Fast 2-stage with Qwen |
| `qwen-fanout.yaml` | Plan → Code (parallel) | Splits tasks, N workers |
| `opus-plan-qwen-code.yaml` | Plan (Opus) → Code (Qwen) | Best quality/cost ratio |
| `human-loop.yaml` | Plan → Code → Review | Pauses for human approval |
| `gemini-test.yaml` | Plan → Code | Gemini CLI integration test |
| `test-cheap.yaml` | Minimal | Fast testing |
| `test-fanout.yaml` | Fan-out | Parallel execution testing |

### Pipeline CLI Flags

```
-c, --config         Path to YAML config (default: configs/default.yaml)
-w, --workspace      Target workspace (default: cwd)
-f, --file           Read request from file
--context-files      Comma-separated key files to examine
--no-docker          Run locally instead of Docker
--no-git             Skip git branch creation
--dry-run            Print config and exit
--resume STAGE       Resume from a stage (e.g., 'code')
--run-id ID          Run ID to resume from
--prompts-dir        Prompt templates directory
-v, --verbose        Debug logging
```

## Configuration

```bash
export OPENROUTER_API_KEY=sk-or-v1-your-key-here   # Required
export CLODING_DEFAULT_MODEL=qwen                    # Optional (default: qwen)
```

For Gemini direct (not through OpenRouter):
```bash
export GOOGLE_API_KEY=your-google-api-key
```

For Codex direct:
```bash
export OPENAI_API_KEY=your-openai-api-key
```

Add custom model shortcuts by editing `models.json`. Set the `tool` field to route to a different CLI.

## Prerequisites

- **Node.js 18+**
- **Claude Code**: `npm install -g @anthropic-ai/claude-code`
- **OpenRouter API key**: [openrouter.ai/keys](https://openrouter.ai/keys)
- **Docker** *(for Docker mode)*: [Docker Desktop](https://docs.docker.com/get-started/get-docker/)
- **Python 3.11+** *(for pipeline mode)*
- `npm install -g @anthropic-ai/claude-code` is not needed if you only use gemini
- **Gemini CLI** *(for gemini models)*: (https://geminicli.com/docs/)
- **Codex CLI** *(for codex models)*: (https://developers.openai.com/codex/cli)

## Testing

```bash
cd pipeline && pip install -r requirements-dev.txt
pytest tests/ -v -p no:anchorpy          # 174+ tests
pytest tests/ --cov=cloding --cov-report=term-missing  # Coverage (80%+ target)
```

## License

MIT
