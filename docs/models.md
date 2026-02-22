# Models & Pricing

cloding supports any model available on [OpenRouter](https://openrouter.ai/models). Use built-in shortcuts for popular models or pass any OpenRouter model ID directly.

## Built-in Shortcuts

| Shortcut | Model | Input $/Mtok | Output $/Mtok | vs Claude Code |
|---|---|---|---|---|
| `qwen` | Qwen 3 Coder | $0.07 | $0.30 | **71x cheaper** |
| `deepseek` | DeepSeek Coder V3 | $0.14 | $0.28 | **36x cheaper** |
| `haiku` | Claude Haiku 4.5 | $0.80 | $4.00 | 6x cheaper |
| `gemini` | Gemini 2.5 Pro | $1.25 | $10.00 | 4x cheaper |
| `sonnet` | Claude Sonnet 4 | $3.00 | $15.00 | 1.7x cheaper |
| `opus` | Claude Opus 4.6 | $15.00 | $75.00 | 3x more expensive |

::: tip Default Model
The default model is **Qwen 3 Coder** (`qwen`). Override with `-m` or the `CLODING_DEFAULT_MODEL` environment variable.
:::

## Using Any Model

Pass any OpenRouter model ID with `-m`:

```bash
cloding -m meta-llama/llama-4-scout
cloding -m google/gemini-2.5-flash
cloding -m anthropic/claude-sonnet-4
```

## List All Models

```bash
cloding --list-models
```

This shows all configured shortcuts with their full model IDs and pricing.

## Cost Comparison

A typical 30-minute coding session with Claude Code costs around **$5**. The same session with different models:

| Model | Estimated Cost | Savings |
|---|---|---|
| Qwen 3 Coder | ~$0.07 | 98.6% |
| DeepSeek Coder V3 | ~$0.14 | 97.2% |
| Claude Haiku 4.5 | ~$0.83 | 83.4% |
| Gemini 2.5 Pro | ~$1.25 | 75.0% |
| Claude Sonnet 4 | ~$3.00 | 40.0% |

## Custom Shortcuts

You can add your own model shortcuts by editing the `models.json` file. See [Custom Models](/custom-models) for details.
