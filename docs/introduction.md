# Introduction

**Agentic Engineering Amplified**

Cloding is a universal wrapper that lets you run **Claude Code**, **Gemini CLI**, **Codex CLI**, **OpenCode**, or **GitHub Copilot CLI** — use OpenRouter, Direct API keys, or link to your paid plan.

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

**Universal CLI wrapper** — Not just Claude Code. Run Gemini CLI, Codex CLI, GitHub Copilot CLI, or OpenCode — all through one interface with consistent flags and Docker support.

**Flexible auth** — Use OpenRouter for any model, direct API keys (Anthropic, Google, OpenAI), or link to your paid plan (Claude, Gemini, ChatGPT, Copilot). Mix and match per session.

**Docker sandboxing** — Run any CLI tool in an isolated container. No access to your secrets, SSH keys, or host filesystem. Just the workspace you mount.

**Pipeline mode** — Multi-stage coding pipelines with parallel fan-out. Assign different models to different stages: Plan → Explore → Code → Review.

**Zero lock-in** — All flags pass through to the underlying CLI. It's the same tools you already know, just cheaper and more flexible.

## How it works

cloding is a thin wrapper that routes API calls through OpenRouter (or your chosen provider) instead of directly to the default API. When you run `cloding`, it:

1. Resolves your model shortcut to a provider + model ID
2. Sets the right environment variables for the chosen CLI tool
3. Spawns the CLI (Claude Code, Gemini, Codex, Copilot, or OpenCode)

That's it. No forks, no patches, no modified binaries. Just configuration.
