# GitHub Copilot CLI Integration

**Branch:** `feature/multi-tool`
**Date:** 2026-02-21
**Status:** Complete, all 325 tests passing

## Summary

Added GitHub Copilot CLI (`@github/copilot-cli`) as the 5th supported coding tool in Cloding, alongside Claude Code, Gemini CLI, Codex CLI, and OpenCode.

## Usage

```bash
# Simple mode
cloding -m copilot                       # Interactive session via Copilot CLI
cloding -m copilot -p "fix the bug"      # One-shot prompt

# Docker mode
cloding docker run -m copilot "fix linting"

# Pipeline mode
cloding pipeline -c configs/copilot-test.yaml "Write docs" --no-docker
```

## Requirements

- **npm package:** `@github/copilot-cli` (`npm install -g @github/copilot-cli`)
- **Binary name:** `github-copilot`
- **Auth:** `GITHUB_TOKEN` environment variable (GitHub PAT with Copilot subscription access)
- **Pricing:** $0/token (subscription-based, no per-token cost)

## Files Changed (10)

### Core Implementation

| File | Change |
|------|--------|
| `models.json` | Added `copilot` entry: tool=copilot, provider=github, api_key_env=GITHUB_TOKEN, $0 pricing |
| `pipeline/cloding/core/tool_handler.py` | Added `CopilotHandler` class + registered in `TOOL_HANDLERS` dict |
| `pipeline/cloding/runners/local_runner.py` | Added copilot error message + Windows `.cmd` wrapper handling |
| `bin/cloding.js` | 7 edit points: env setup, prompt args (simple+docker), Docker env file, Docker entrypoint mapping, spawn binary mapping, help text |
| `pipeline/docker/Dockerfile` | Added `@github/copilot-cli` to npm install |
| `pipeline/configs/copilot-test.yaml` | New pipeline config for Copilot CLI stages |

### Tests

| File | Change |
|------|--------|
| `pipeline/tests/test_tool_handler.py` | **New file** - 22 tests covering all 5 tool handlers + registry |
| `pipeline/tests/test_local_runner.py` | Added 3 copilot binary resolution tests |

### Documentation

| File | Change |
|------|--------|
| `README.md` | Added copilot across: intro, examples, tables (Direct API, Multi-Tool Architecture, Prerequisites, Pipeline Configs, Env Vars) |
| `CLAUDE.md` | Added copilot to: key files, pipeline configs, Direct API Models table, env vars |

## Technical Details

### Binary Name Mapping

The tool name in `models.json` is `"copilot"` but the actual binary is `"github-copilot"`. This required mapping in two places in `bin/cloding.js`:

```javascript
// Simple mode spawn
let spawnTool = tool === "copilot" ? "github-copilot" : tool;

// Docker entrypoint
const entrypoint = tool === "copilot" ? "github-copilot" : tool;
cmd.push("--entrypoint", entrypoint);
```

### CopilotHandler

```python
class CopilotHandler(ToolHandler):
    def build_env(self, model_config):
        return {"GITHUB_TOKEN": os.environ.get(model_config.api_key_env, "")}

    def build_cli_args(self, stage_config, model_config, prompt):
        return ["-p", prompt]  # Same flag as Claude/Gemini

    def get_binary_name(self):
        return "github-copilot"
```

### Windows Handling

On Windows, the `.cmd` wrapper for `github-copilot` falls back to `cmd /c <path>` (same as Claude's generic fallback). Unlike Claude, copilot does not have a `cli.js` resolution path.

### cloding.js Edit Points

1. **Env setup** (simple mode): `runEnv.GITHUB_TOKEN = apiKey`
2. **Prompt args** (simple mode): Added `|| tool === "copilot"` to `-p` flag condition
3. **Docker env file**: Added `GITHUB_TOKEN=${apiKey}` line
4. **Docker prompt args**: Added `|| tool === "copilot"` to `-p` flag condition
5. **Docker entrypoint**: Maps `copilot` -> `github-copilot`
6. **Simple mode spawn**: Maps `copilot` -> `github-copilot`
7. **Help text**: Added `copilot    GitHub Copilot       $0 (subscription)`

### Pipeline Config (copilot-test.yaml)

```yaml
name: "copilot-test"
models:
  copilot:
    provider: github
    model_id: copilot
    tool: copilot
    api_key_env: GITHUB_TOKEN
    cost_per_mtok_input: 0.0
    cost_per_mtok_output: 0.0
stages:
  - name: plan
    model: copilot
    prompt_file: prompts/plan.txt
    max_turns: 10
  - name: code
    model: copilot
    prompt_file: prompts/code.txt
    max_turns: 20
fanout:
  enabled: false
review:
  max_iterations: 0
```

## Test Results

```
325 passed, 2 warnings in 2.48s
```

New tests added:
- `test_tool_handler.py`: 22 tests (CopilotHandler, ClaudeCodeHandler, GeminiHandler, OpenCodeHandler, CodexHandler, registry)
- `test_local_runner.py`: 3 tests (copilot not-found, Linux path, Windows cmd fallback) + 1 generic binary not-found test

## All Supported Tools

| Tool | CLI Binary | npm Package | Provider | Auth Env |
|------|-----------|-------------|----------|----------|
| claude (default) | `claude` | `@anthropic-ai/claude-code` | openrouter/anthropic | `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` |
| gemini | `gemini` | `@google/gemini-cli` | openrouter/google | `OPENROUTER_API_KEY` / `GOOGLE_API_KEY` |
| codex | `codex` | `@openai/codex` | openai | `OPENAI_API_KEY` |
| copilot | `github-copilot` | `@github/copilot-cli` | github | `GITHUB_TOKEN` |
| opencode | `opencode` | `opencode-ai` | openrouter | `OPENROUTER_API_KEY` |
