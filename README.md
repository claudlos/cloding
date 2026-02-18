# ⚡ cloding

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

## Docker Mode

When you run Claude Code, it has full access to your machine — your files, your terminal, your `.env`, your SSH keys, everything. It's an LLM agent with root-level power and nothing about that is secure. Nobody seems to care that these models are looking at all your stuff and running wild.

Docker mode puts it in a box. The model can only touch the workspace you mount and nothing else. It can't read your secrets, wreck your system, or do anything outside the container. Non-root user, no access to your host filesystem, resource-limited. Containers still have outbound network access (needed for API calls to OpenRouter).

```bash
cloding docker build                    # Build image (one-time)
cloding docker shell                    # Interactive session
cloding docker run "fix the bug"        # Run a prompt
cloding docker run -m haiku "prompt"    # Specific model
cloding docker run -w ./myproject       # Mount workspace
cloding docker run --memory 4g --cpus 2 # Resource limits
cloding docker status                   # Show running containers
cloding docker stop                     # Stop all containers
cloding docker clean                    # Remove stopped containers
```

Your workspace gets mounted read-write at `/workspace` inside the container. That's the only thing the model can touch.

## Pipeline Mode

Multi-stage coding pipeline: Plan → Explore → Code → Review, with parallel fan-out. Assign different models to different stages — Opus for planning, Qwen for coding.

```bash
cd pipeline && pip install -e .    # Requires Python 3.11+
cloding pipeline "Add auth" --workspace ./myapp --no-docker
cloding pipeline -c configs/qwen-fanout.yaml "Refactor the DB layer"
```

8 pipeline configs included: default, quick, fan-out, opus-plan+qwen-code, human-in-the-loop, and more.

## Configuration

```bash
export OPENROUTER_API_KEY=sk-or-v1-your-key-here   # Required
export CLODING_DEFAULT_MODEL=qwen                    # Optional (default: qwen)
```

Add custom model shortcuts by editing `models.json`.

## Prerequisites

- **Node.js 18+**
- **Claude Code**: `npm install -g @anthropic-ai/claude-code`
- **OpenRouter API key**: [openrouter.ai/keys](https://openrouter.ai/keys)
- **Docker** *(for Docker mode)*: [Docker Desktop](https://docs.docker.com/get-started/get-docker/) · [Windows](https://docs.docker.com/desktop/setup/install/windows-install/) · [Mac](https://docs.docker.com/desktop/setup/install/mac-install/) · [Linux](https://docs.docker.com/desktop/setup/install/linux/) · [Engine only](https://docs.docker.com/engine/install)

## License

MIT
