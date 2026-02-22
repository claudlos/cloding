# Custom Models

cloding ships with built-in shortcuts for popular models, but you can add your own by editing the `models.json` file.

## models.json Format

The `models.json` file maps shortcut names to OpenRouter model IDs and metadata:

```json
{
  "qwen": {
    "id": "qwen/qwen3-coder",
    "name": "Qwen 3 Coder",
    "input_cost": 0.07,
    "output_cost": 0.30
  },
  "deepseek": {
    "id": "deepseek/deepseek-coder-v3",
    "name": "DeepSeek Coder V3",
    "input_cost": 0.14,
    "output_cost": 0.28
  }
}
```

## Adding a Model

To add a new model shortcut, add an entry to `models.json`:

```json
{
  "my-model": {
    "id": "provider/model-name",
    "name": "My Custom Model",
    "input_cost": 1.00,
    "output_cost": 2.00
  }
}
```

Then use it:

```bash
cloding -m my-model
```

## Finding Model IDs

Browse available models at [openrouter.ai/models](https://openrouter.ai/models). The model ID is the string shown in the model's URL and API reference — for example, `meta-llama/llama-4-scout`.

::: tip
You don't need to add models to `models.json` to use them. You can always pass any OpenRouter model ID directly with `-m`:

```bash
cloding -m meta-llama/llama-4-scout
```

The `models.json` shortcuts are just for convenience and to show pricing in `--list-models`.
:::
