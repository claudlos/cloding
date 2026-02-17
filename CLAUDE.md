# CLAUDE.md — Cloding

Claude Code with any model via OpenRouter. 70x cheaper coding.

## Quick Commands

```bash
# Simple mode — launch Claude Code with cheap models
npm install -g .          # Install locally
cloding                   # Interactive with Qwen (default)
cloding -m haiku          # Use Haiku
cloding -p "fix the bug"  # Non-interactive single prompt
cloding --list-models     # Show all models

# Pipeline mode — multi-stage orchestrator (requires Python 3.11+)
cd pipeline && pip install -e .
cloding pipeline "Add auth" --workspace ./myapp --no-docker
cloding pipeline -c configs/qwen-fanout.yaml "Refactor DB layer"

# Tests (pipeline)
cd pipeline && pytest tests/ -v -p no:anchorpy
```

## Architecture

### Simple Mode (Node.js)
- **bin/cloding.js**: CLI entry point. Sets OpenRouter env vars, spawns `claude`.
- **models.json**: Model registry with shortcuts (qwen, haiku, sonnet, opus, etc.)
- **package.json**: npm package config

### Pipeline Mode (Python)
4-stage pipeline: Plan → Explore → Code → Review, with parallel fan-out.

- **pipeline/osq/core/**: Config loader, errors, logger, workspace git prep
- **pipeline/osq/pipeline/**: Stage base + concrete stages, pipeline sequencer, state, results
- **pipeline/osq/runners/**: BaseRunner ABC, LocalRunner (direct CLI), DockerRunner (containers)
- **pipeline/osq/fanout/**: Task splitter, parallel runner (asyncio.Semaphore), merge
- **pipeline/osq/models/**: Model registry, cost tracker with CSV export
- **pipeline/osq/cli/**: Argparse CLI entry point
- **pipeline/osq/orchestrator.py**: Top-level: load config, build pipeline, run
- **pipeline/configs/**: YAML pipeline configs (default.yaml, quick.yaml, qwen-fanout.yaml)
- **pipeline/prompts/**: Stage prompt templates (plan.txt, explore.txt, code.txt, review.txt)

## Key Files

| File | Purpose |
|------|---------|
| `bin/cloding.js` | Node.js CLI — sets env vars, spawns claude |
| `models.json` | Model shortcuts with OpenRouter IDs and costs |
| `pipeline/osq/pipeline/pipeline.py` | Pipeline sequencer, review loop, checkpoints |
| `pipeline/osq/pipeline/stage.py` | Stage ABC + PlanStage, ExploreStage, CodeStage, ReviewStage |
| `pipeline/osq/core/config.py` | YAML config loading + validation |
| `pipeline/osq/runners/local_runner.py` | Runs claude CLI via asyncio subprocess |
| `pipeline/configs/default.yaml` | Default 4-stage pipeline config with all models |

## Models (via OpenRouter)

| Shortcut | Model | Input $/Mtok | Output $/Mtok |
|----------|-------|-------------|---------------|
| qwen | Qwen 3 Coder | $0.07 | $0.30 |
| haiku | Claude Haiku 4.5 | $0.80 | $4.00 |
| sonnet | Claude Sonnet 4 | $3.00 | $15.00 |
| opus | Claude Opus 4.6 | $15.00 | $75.00 |
| deepseek | DeepSeek Coder V3 | $0.14 | $0.28 |
| gemini | Gemini 2.5 Pro | $1.25 | $10.00 |

## Code Style

- **Node.js**: No dependencies, vanilla JS, ES module imports avoided for compatibility
- **Python**: Line length 100 (black), type hints, Google-style docstrings
- Custom error hierarchy in `pipeline/osq/core/errors.py` (OSQError base)
- Logger via `get_logger("name", category="CAT")`
- Subprocess safety: `asyncio.create_subprocess_exec` (no shell) aliased as `_launch`

## Environment Variables

- `OPENROUTER_API_KEY`: Required. Get one at https://openrouter.ai/keys
- `CLODING_DEFAULT_MODEL`: Optional. Default model shortcut (default: qwen)
- See `.env.example` for template
