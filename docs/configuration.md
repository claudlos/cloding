# Configuration

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENROUTER_API_KEY` | ✅ | — | Your OpenRouter API key |
| `CLODING_DEFAULT_MODEL` | — | `qwen` | Default model shortcut |

## Setting Your API Key

```bash
export OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

To persist across sessions, add it to your shell profile:

```bash
# ~/.bashrc or ~/.zshrc
export OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

## Changing the Default Model

By default, cloding uses Qwen 3 Coder. To change this:

```bash
export CLODING_DEFAULT_MODEL=haiku
```

Or specify per-session with `-m`:

```bash
cloding -m sonnet
```

## Claude Code Passthrough

All Claude Code flags and environment variables work as-is. cloding passes everything through transparently. For example:

```bash
cloding --allowedTools Read,Write,Bash
```

Refer to the [Claude Code documentation](https://docs.anthropic.com/en/docs/claude-code) for all available flags.
