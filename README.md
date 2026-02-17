# ⚡ cloding

**Claude Code with any model. 70x cheaper.**

Use Claude Code's full power — tools, file editing, terminal access — with Qwen, Haiku, DeepSeek, or any OpenRouter model. Same experience, fraction of the cost.

```
npm install -g cloding
```

## Quick Start

1. **Get an OpenRouter API key** at [openrouter.ai/keys](https://openrouter.ai/keys)

2. **Set your key:**
   ```bash
   export OPENROUTER_API_KEY=sk-or-v1-your-key-here
   ```
   Or create a `.env` file in your project:
   ```
   OPENROUTER_API_KEY=sk-or-v1-your-key-here
   ```

3. **Start coding:**
   ```bash
   cloding
   ```
   That's it. You're now running Claude Code with Qwen 3 Coder at **$0.07/Mtok input** instead of $15/Mtok.

## Usage

```bash
cloding                              # Interactive session with Qwen (default)
cloding -m haiku                     # Use Claude Haiku 4.5
cloding -m sonnet                    # Use Claude Sonnet 4
cloding -m opus                      # Use Claude Opus 4.6
cloding -p "fix the login bug"       # Non-interactive, single prompt
cloding --list-models                # Show all models with pricing
```

Pass any Claude Code flags through:
```bash
cloding --allowedTools Read,Write,Bash
cloding --model qwen/qwen3-coder-next --verbose
```

## Models & Cost Comparison

| Shortcut | Model | Input $/Mtok | Output $/Mtok | vs Opus |
|----------|-------|-------------|---------------|---------|
| `qwen` | Qwen 3 Coder | $0.07 | $0.30 | **250x cheaper** |
| `deepseek` | DeepSeek Coder V3 | $0.14 | $0.28 | **268x cheaper** |
| `haiku` | Claude Haiku 4.5 | $0.80 | $4.00 | 19x cheaper |
| `gemini` | Gemini 2.5 Pro | $1.25 | $10.00 | 8x cheaper |
| `sonnet` | Claude Sonnet 4 | $3.00 | $15.00 | 5x cheaper |
| `opus` | Claude Opus 4.6 | $15.00 | $75.00 | baseline |

> **Real example:** A 30-minute coding session that costs ~$5 with Opus costs ~$0.02 with Qwen. Same tools, same workflow.

You can also pass any OpenRouter model ID directly:
```bash
cloding -m meta-llama/llama-4-scout
```

## How It Works

Cloding is a thin wrapper around Claude Code. It:

1. Reads your OpenRouter API key
2. Sets the right environment variables (`ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`, etc.)
3. Launches `claude` with those vars

That's it. No proxy, no middleware, no overhead. Your prompts go directly from Claude Code → OpenRouter → model.

## Prerequisites

- **Node.js 18+**
- **Claude Code** installed: `npm install -g @anthropic-ai/claude-code`
- **OpenRouter API key** from [openrouter.ai](https://openrouter.ai)

## Configuration

### Default model

Set your preferred default model:
```bash
export CLODING_DEFAULT_MODEL=haiku
```

### Custom models

Edit `models.json` to add your own model shortcuts:
```json
{
  "mymodel": {
    "id": "provider/model-name",
    "name": "My Custom Model",
    "in": 1.00,
    "out": 5.00,
    "description": "My custom model via OpenRouter"
  }
}
```

## Docker Mode

Run Claude Code in isolated Docker containers. Each container gets its own environment with resource limits and security isolation.

```bash
# Build the image first (one-time)
cloding docker build

# Run a prompt in a container
cloding docker run "Add error handling to src/api.js"

# Interactive session in Docker
cloding docker shell

# Use a specific model
cloding docker run -m haiku "Fix the tests"

# Mount a specific workspace
cloding docker shell -w ./myproject

# Manage containers
cloding docker status    # Show running containers
cloding docker stop      # Stop all containers
cloding docker clean     # Remove stopped containers
```

Options for `run` and `shell`:

| Option | Default | Description |
|--------|---------|-------------|
| `-m, --model` | qwen | Model shortcut or OpenRouter ID |
| `-w, --workspace` | cwd | Local directory to mount |
| `--memory` | 2g | Container memory limit |
| `--cpus` | 1.0 | Container CPU limit |
| `--name` | auto | Custom container name |
| `--no-rm` | off | Keep container after exit |

Containers run as a non-root `coder` user with resource limits. Your workspace is mounted read-write at `/workspace` inside the container.

## Pipeline Mode (Advanced)

For multi-stage coding pipelines (Plan → Explore → Code → Review) with parallel task fan-out:

```bash
# Requires Python 3.11+
cd pipeline && pip install -e .

# Run a pipeline
cloding pipeline "Add authentication to the API" --workspace ./myapp --no-docker
cloding pipeline -c configs/qwen-fanout.yaml "Refactor the database layer"
```

Pipeline configs let you assign different models to different stages — e.g., Opus for planning, Qwen for coding.

## Why?

70-80% of coding tasks don't need the smartest model. Searching files, writing boilerplate, making edits, running tests — Qwen handles all of this perfectly through Claude Code's tools. Save the expensive models for architecture and complex reasoning.

## License

MIT
