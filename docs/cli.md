# CLI Reference

## `cloding`

Start an interactive coding session.

```bash
cloding [options]
```

### Options

| Flag | Description |
|---|---|
| `-m, --model <name>` | Model shortcut or OpenRouter model ID |
| `-p, --prompt <text>` | Run a single prompt (non-interactive) |
| `--list-models` | Show all available models with pricing |
| `-v, --version` | Show version |
| `-h, --help` | Show help |

All additional flags are passed through to Claude Code.

### Examples

```bash
cloding                              # Interactive with default model
cloding -m haiku                     # Use Claude Haiku 4.5
cloding -p "add dark mode"           # Single prompt
cloding -m meta-llama/llama-4-scout  # Any OpenRouter model
cloding --allowedTools Read,Write    # Claude Code flags pass through
```

## `cloding setup`

Detect and install all supported CLI tools.

```bash
cloding setup [options]
```

### Options

| Flag | Description |
|---|---|
| `--check` | Status report only — don't install anything |
| `--force` | Reinstall all CLI tools |

### What it checks

**Prerequisites** (detected, with install hints):
- Node.js 18+
- Python 3.11+
- Docker

**CLI Tools** (detected + installed):
- Claude Code — installed via native installer (`curl | bash` / `irm | iex`)
- Gemini CLI — installed via npm
- Codex CLI — installed via npm
- GitHub Copilot CLI — installed via npm
- OpenCode — installed via npm

### Examples

```bash
cloding setup              # Check and install missing tools
cloding setup --check      # Just show what's installed
cloding setup --force      # Reinstall everything
```

## `cloding docker`

Manage Docker-sandboxed sessions.

### Subcommands

| Command | Description |
|---|---|
| `cloding docker build` | Build the Docker image (one-time) |
| `cloding docker shell` | Start an interactive sandboxed session |
| `cloding docker run <prompt>` | Run a prompt in a container |
| `cloding docker status` | Show running containers |
| `cloding docker stop` | Stop all cloding containers |
| `cloding docker clean` | Remove stopped containers |

### Docker Run Options

| Flag | Description |
|---|---|
| `-m, --model <name>` | Model to use |
| `-w, --workspace <path>` | Workspace directory to mount (default: `.`) |
| `--memory <limit>` | Memory limit (e.g., `4g`) |
| `--cpus <count>` | CPU limit (e.g., `2`) |

### Examples

```bash
cloding docker build
cloding docker run "fix the bug"
cloding docker run -m haiku -w ./myproject "add tests"
cloding docker run --memory 4g --cpus 2 "refactor"
```

## `cloding pipeline`

Run multi-stage coding pipelines.

```bash
cloding pipeline <prompt> [options]
```

### Options

| Flag | Description |
|---|---|
| `-c, --config <path>` | Pipeline config YAML file |
| `--workspace <path>` | Project workspace directory |
| `--no-docker` | Run without Docker isolation |

### Examples

```bash
cloding pipeline "Add auth" --workspace ./myapp --no-docker
cloding pipeline -c configs/qwen-fanout.yaml "Refactor the DB layer"
```
