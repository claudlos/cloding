# Cloding

**Agentic Engineering Amplified**

Cloding is a universal wrapper that lets you run Claude Code, Gemini CLI, Codex CLI, OpenCode, or GitHub Copilot CLI — use OpenRouter, Direct API keys, or link to your paid plan.

░█████╗░██╗░░░░░░█████╗░██████╗░██╗███╗░░██╗░██████╗░
██╔══██╗██║░░░░░██╔══██╗██╔══██╗██║████╗░██║██╔════╝░
██║░░╚═╝██║░░░░░██║░░██║██║░░██║██║██╔██╗██║██║░░██╗░
██║░░██╗██║░░░░░██║░░██║██║░░██║██║██║╚██╗██║██║░░╚██╗
╚█████╔╝███████╗╚█████╔╝██████╔╝██║██║░╚████║╚██████╔╝
░╚════╝░╚══════╝░╚════╝░╚═════╝░╚═╝╚═╝░░╚═══╝░╚═════╝

---

**Code with any LLM in a Docker sandbox. Configurable multi-stage code orchestration**

Claude Opus 4.6 costs $5/$25 per Mtok.  
Qwen 3 Coder Next costs $0.12/$0.75 per Mtok.  
*That's 42x cheaper on input, 33x cheaper on output.*

Run multiple coding CLIs from one command, with model shortcuts and optional pipeline orchestration.

**Supported tools:**
- Claude Code (`claude`)
- Gemini CLI (`gemini`)
- Codex CLI (`codex`)
- GitHub Copilot CLI (`copilot`)
- OpenCode (`opencode`, via custom model entries)

---

## Capabilities

Cloding enhances your development workflow through:

### Universal Access
Seamlessly switch between leading AI coding assistants using a single, unified interface.

### Cost Control
Leverage deeply discounted models via OpenRouter while maintaining high performance. Avoid expensive subscription lock-ins.

### Container Security
Run AI-generated code safely. The built-in Docker mode executes tools in an isolated sandbox with configurable CPU/memory limits, preventing untrusted code from accessing your host system.

### Advanced Automation
The Python-based orchestrator enables multi-stage workflows:
- **Plan:** Analyze requirements and design solutions.
- **Explore:** Gather context from large codebases.
- **Code:** Implement the planned changes.
- **Review:** Automatically verify and refine the code.

### Extensive Documentation
Read our comprehensive [documentation site](https://claudlos.github.io/cloding/) for in-depth walkthroughs and a dedicated [Troubleshooting guide](https://claudlos.github.io/cloding/troubleshooting).

---

## Installation

### Standalone Binary (Recommended)

No Node.js required — download a single standalone binary:

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/claudlos/cloding/master/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/claudlos/cloding/master/install.ps1 | iex
```

### npm

If you already have Node.js 18+ installed:

```bash
npm i -g cloding
```

**Installing Node.js 18+**  
If you don't have Node.js installed, you can quickly install the latest version using the following commands:

**macOS / Linux (via nvm):**
```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
nvm install node
```

**Windows (PowerShell via winget):**
```powershell
winget install OpenJS.NodeJS
```
*(Alternatively, you can download the official installer directly from [nodejs.org](https://nodejs.org/))*

---

## Quick Start

```bash
# 1. Set your OpenRouter API key
export OPENROUTER_API_KEY=sk-or-v1-your-key-here

# 2. Install all CLI tools (Claude Code, Gemini, Codex, Copilot, OpenCode)
cloding setup

# 3. Start coding!
cloding
```

### Basic usage:

```bash
cloding                              # interactive (default: qwen)
cloding -m sonnet                    # choose a specific shortcut
cloding -p "fix failing tests"       # one-shot prompt
cloding --list-models                # list shortcuts and prices
cloding -h                           # view help
```

## Setup Command

`cloding setup` detects and installs all supported CLI tools:

```bash
cloding setup              # check status + install missing tools
cloding setup --check      # status report only, no installation
cloding setup --force      # reinstall all tools
```

It checks for:

**Prerequisites** (detected, not installed):
- Node.js 18+
- Python 3.11+ (for pipeline mode)
- Docker (for Docker mode)

**CLI Tools** (detected + installed automatically):
- Claude Code — via native installer
- Gemini CLI — via npm
- Codex CLI — via npm
- GitHub Copilot CLI — via npm
- OpenCode — via npm

## Authentication

Each Anthropic model (haiku, sonnet, opus) supports three routing modes:

| Suffix | Provider | Env Var | Cost |
|--------|----------|---------|------|
| *(none)* or `-o` | OpenRouter | `OPENROUTER_API_KEY` | Pay-per-token via OpenRouter |
| `-a` | Anthropic API | `ANTHROPIC_API_KEY` | Pay-per-token via Anthropic |
| `-p` | Claude paid plan | *(none)* | Uses your Claude subscription |

Examples:

```bash
cloding -m sonnet        # Sonnet via OpenRouter (default)
cloding -m sonnet-o      # Sonnet via OpenRouter (explicit)
cloding -m sonnet-a      # Sonnet via your Anthropic API key
cloding -m sonnet-p      # Sonnet via your Claude paid plan
```

Other tools use their own auth:

| Model Shortcut | Tool | Env Var |
|---|---|---|
| `qwen`, `deepseek` | Claude Code via OpenRouter | `OPENROUTER_API_KEY` required |
| `gemini` | Gemini CLI via OpenRouter | `OPENROUTER_API_KEY` or linked Gemini CLI account |
| `gemini-3` | Gemini CLI (Gemini plan) | Uses your Gemini subscription |
| `gemini-3-a` | Gemini CLI (Google API) | `GOOGLE_API_KEY` required |
| `codex-5` | Codex CLI (ChatGPT plan) | Uses your ChatGPT subscription |
| `codex-5-a` | Codex CLI (OpenAI API) | `OPENAI_API_KEY` required |
| `copilot` | GitHub Copilot CLI | `GITHUB_TOKEN` or linked Copilot CLI account |

### .env Template

```bash
OPENROUTER_API_KEY=sk-or-v1-your-key-here
CLODING_DEFAULT_MODEL=qwen

# Direct Anthropic API key (for -a variants: haiku-a, sonnet-a, opus-a)
ANTHROPIC_API_KEY=sk-ant-your-key-here

# Optional direct-provider keys
GOOGLE_API_KEY=your-google-api-key
OPENAI_API_KEY=your-openai-api-key
GITHUB_TOKEN=your-github-token
```

### Account Linking (Gemini / Copilot)

If you want to use account linking instead of API keys, open each CLI directly once and complete sign-in:

```bash
gemini
copilot
```

With current behavior:
- `cloding -m gemini` can run with linked account; if `OPENROUTER_API_KEY` is unset, `cloding` uses Gemini CLI account mode.
- `cloding -m gemini-3` can run with linked account; `GOOGLE_API_KEY` is optional in that case.
- `cloding -m copilot` can run with linked account; `GITHUB_TOKEN` is optional in that case.

## Model Shortcuts

### OpenRouter Models (via Claude Code)

| Shortcut | Model | Input $/Mtok | Output $/Mtok |
|---|---|---:|---:|
| `qwen` | Qwen 3 Coder | 0.12 | 0.75 |
| `deepseek` | DeepSeek V3.2 | 0.26 | 0.38 |

### Anthropic Models (3 routing modes each)

| Shortcut | Model | Provider | Input $/Mtok | Output $/Mtok |
|---|---|---|---:|---:|
| `haiku` / `haiku-o` | Claude Haiku 4.5 | OpenRouter | 1.00 | 5.00 |
| `haiku-a` | Claude Haiku 4.5 | Anthropic API | 1.00 | 5.00 |
| `haiku-p` | Claude Haiku 4.5 | Paid plan | 0.00 | 0.00 |
| `sonnet` / `sonnet-o` | Claude Sonnet 4 | OpenRouter | 3.00 | 15.00 |
| `sonnet-a` | Claude Sonnet 4 | Anthropic API | 3.00 | 15.00 |
| `sonnet-p` | Claude Sonnet 4 | Paid plan | 0.00 | 0.00 |
| `opus` / `opus-o` | Claude Opus 4.6 | OpenRouter | 5.00 | 25.00 |
| `opus-a` | Claude Opus 4.6 | Anthropic API | 5.00 | 25.00 |
| `opus-p` | Claude Opus 4.6 | Paid plan | 0.00 | 0.00 |

### Direct Tool Models

| Shortcut | Model | Tool | Env Var |
|---|---|---|---|
| `gemini` | Gemini 2.5 Pro | Gemini CLI | `OPENROUTER_API_KEY` |
| `gemini-3` | Gemini 3 Pro (Paid Plan) | Gemini CLI | *(none)* |
| `gemini-3-a` | Gemini 3 Pro (API) | Gemini CLI | `GOOGLE_API_KEY` |
| `codex-5` | Codex (Paid Plan) | Codex CLI | *(none)* |
| `codex-5-a` | Codex 5.3 High (API) | Codex CLI | `OPENAI_API_KEY` |
| `copilot` | GitHub Copilot | Copilot CLI | `GITHUB_TOKEN` |

Any OpenRouter model ID can be passed directly:

```bash
cloding -m meta-llama/llama-4-scout
```

## Commands

### Simple Mode

```bash
cloding -m qwen
cloding -m sonnet-a -p "review this file"   # direct Anthropic API
cloding -m opus-p                            # use Claude paid plan
cloding -m codex-5 "implement retry logic"
cloding -m codex-5-a "implement retry logic"
cloding -m copilot
```

Unknown flags are passed through to the underlying CLI.

### Docker Mode

```bash
cloding docker build
cloding docker run "fix lint errors"
cloding docker run -m sonnet-a "build endpoint tests"
cloding docker run -m codex-5 "debug my code"
cloding docker run -m opus-p "make a plan"
cloding docker shell -m sonnet
cloding docker status
cloding docker stop
cloding docker clean
```

Docker options:

```bash
cloding docker run -w /path/to/project "prompt"   # mount workspace
cloding docker run --memory 4g --cpus 2 "prompt"   # resource limits
cloding docker run --name my-container "prompt"     # custom name
cloding docker run --no-rm "prompt"                 # keep after exit
```

Important current behavior:
- `cloding docker run/shell` requires the selected model's auth env var (for example: `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, or `GITHUB_TOKEN`).
- Plan mode (`-p` variants) does not require any API key.
- Docker images include all supported CLIs.

### Pipeline Mode

```bash
cd pipeline
pip install -e .

cloding pipeline "Add auth middleware" --workspace ./myapp --no-docker
cloding pipeline -c configs/default.yaml "Refactor API layer"
cloding pipeline --dry-run -c configs/default.yaml "preview only"
cloding pipeline --resume code --run-id <run-id> "original request"
```

Pipeline flags:
- `-c, --config` — Path to YAML pipeline config
- `-w, --workspace` — Path to target workspace
- `-f, --file` — Read request from file
- `--context-files` — Comma-separated list of key files
- `--no-docker` — Run locally instead of in Docker
- `--no-git` — Skip git workspace preparation
- `--dry-run` — Print config and exit
- `--resume STAGE` — Resume from a specific stage
- `--run-id ID` — Run ID to resume from
- `--prompts-dir` — Prompt templates directory
- `-v, --verbose` — Debug logging

## Prerequisites

- **OpenRouter key** — for default/OpenRouter shortcuts ([get one here](https://openrouter.ai/keys))
- **Node.js 18+** — required for CLI tool installs (Claude Code, Gemini, etc.)
- **Node.js 24+** — if you want to run `copilot` / `cloding -m copilot`
- **Docker** — optional, for Docker mode
- **Python 3.11+** — optional, for pipeline mode

> **Tip:** Run `cloding setup` to automatically detect and install all CLI tools.

## Custom Models
Add entries in `models.json`:

```json
{
  "my-model": {
    "id": "provider/model-id",
    "name": "My Model",
    "tool": "gemini",
    "provider": "google",
    "api_key_env": "GOOGLE_API_KEY",
    "in": 0.0,
    "out": 0.0
  }
}
```

Supported `tool` values: `claude` (default), `gemini`, `codex`, `copilot`, `opencode`

Supported `provider` values: `openrouter` (default), `anthropic`, `plan`, `google`, `openai`, `github`

## License

MIT
