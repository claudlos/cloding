# Pipeline Mode

Pipeline mode runs multi-stage coding workflows: **Plan → Explore → Code → Review**, with parallel fan-out. Assign different models to different stages — Opus for planning, Qwen for coding.

## Setup

Pipeline mode requires **Python 3.11+**:

```bash
cd pipeline && pip install -e .
```

## Usage

```bash
cloding pipeline "Add authentication" --workspace ./myapp --no-docker
```

With a specific config:

```bash
cloding pipeline -c configs/qwen-fanout.yaml "Refactor the DB layer"
```

## Pipeline Stages

A typical pipeline runs through these stages:

1. **Plan** — Analyze the task and create a development plan
2. **Explore** — Examine the codebase to understand the current state
3. **Code** — Implement the changes (can fan out to multiple parallel agents)
4. **Review** — Review the changes for correctness and quality

Each stage can use a different model. Use a powerful model for planning and a fast, cheap model for execution.

## Built-in Configs

8 pipeline configurations are included:

| Config | Description |
|---|---|
| `default` | Standard 4-stage pipeline |
| `quick` | Fast 2-stage: plan + code |
| `fan-out` | Parallel coding with multiple agents |
| `opus-plan+qwen-code` | Opus for planning, Qwen for coding |
| `human-in-the-loop` | Pauses for human approval between stages |
| And more... | Check `pipeline/configs/` for all options |

## Custom Pipelines

Create a YAML config to define your own pipeline:

```yaml
stages:
  - name: plan
    model: opus
    prompt: "Analyze and plan: {task}"
  - name: code
    model: qwen
    parallel: 3
    prompt: "Implement: {plan}"
  - name: review
    model: sonnet
    prompt: "Review these changes: {code}"
```

Place your config in the `pipeline/configs/` directory and reference it with `-c`.
