# Quick Start

## Install cloding

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/claudlos/cloding/master/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/claudlos/cloding/master/install.ps1 | iex
```

Or via npm: `npm install -g cloding`

## Set up tools

Install all CLI tools in one command:

```bash
cloding setup
```

## Set your API key

```bash
export OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

## Start coding

```bash
cloding
```

That's it. You're now running Claude Code with **Qwen 3 Coder** at $0.12/Mtok instead of $5/Mtok.

## Choose a model

```bash
cloding                    # Qwen 3 Coder (default)
cloding -m haiku           # Claude Haiku 4.5
cloding -m sonnet          # Claude Sonnet 4
cloding -m opus            # Claude Opus 4.6
cloding -m deepseek        # DeepSeek Coder V3
cloding -m gemini          # Gemini 2.5 Pro
```

## Run a single prompt

Don't need an interactive session? Pass `-p`:

```bash
cloding -p "add dark mode to the settings page"
```

## Use any OpenRouter model

Not limited to the built-in shortcuts — pass any OpenRouter model ID:

```bash
cloding -m meta-llama/llama-4-scout
```

## Pass Claude Code flags

All Claude Code flags work as-is:

```bash
cloding --allowedTools Read,Write,Bash
```

## What's next?

- **[Models & Pricing](/models)** — Full comparison of all supported models
- **[Docker Mode](/docker)** — Run models in a sandboxed container
- **[Pipeline Mode](/pipeline)** — Multi-stage coding with parallel fan-out
- **[Configuration](/configuration)** — Environment variables and defaults
