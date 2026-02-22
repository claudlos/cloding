# Introduction

Claude Code is a powerful agentic coding tool — it edits files, runs terminal commands, and manages your entire development workflow. But it costs **$5/Mtok input** and **$25/Mtok output**.

**cloding** lets you run the exact same Claude Code experience with any model on [OpenRouter](https://openrouter.ai). Same tools, same file editing, same terminal access — just swap the model underneath.

## Why cloding?

| | Claude Code | cloding + Qwen |
|---|---|---|
| **Input cost** | $5.00/Mtok | $0.12/Mtok |
| **Output cost** | $25.00/Mtok | $0.75/Mtok |
| **Tools & editing** | ✅ | ✅ |
| **Terminal access** | ✅ | ✅ |
| **30-min session** | ~$5.00 | ~$0.12 |

> A typical 30-minute coding session that costs ~$5 with Claude Code costs ~$0.12 with Qwen 3 Coder. That's **42x cheaper on input**.

## Key Features

**One-line install** — Standalone binary, no Node.js required. `curl | bash` on Mac/Linux, `irm | iex` on Windows. Run `cloding setup` to install all 5 CLI tools automatically.

**Model flexibility** — Use any OpenRouter model by ID or pick from built-in shortcuts. Mix models based on the task: Opus for planning, Qwen for execution.

**Docker sandboxing** — Claude Code has full access to your machine by default. cloding's Docker mode isolates the agent in a container with access to only the workspace you mount.

**Pipeline mode** — Multi-stage coding pipelines with parallel fan-out. Assign different models to different stages: Plan → Explore → Code → Review.

**Zero lock-in** — All Claude Code flags pass through. It's the same CLI you already know, just cheaper.

## How it works

cloding is a thin wrapper around Claude Code that routes API calls through OpenRouter instead of directly to Anthropic. When you run `cloding`, it:

1. Starts Claude Code with the `--provider openrouter` flag
2. Routes all API calls through your OpenRouter API key
3. Uses whatever model you specify (defaults to Qwen 3 Coder)

That's it. No forks, no patches, no modified binaries. Just configuration.
