# Cloding Upgrade Plan

## What You Asked For

> "I wanted orchestration because I'm failing to do what I want. I want multiple agents running to verify my code is good code. I want to be able to plan a project and just sit back and make sure it works right. I want to see the price of what I just did and the code that backs it."

## Current State of the Codebase

### What Exists (and works)
- **241 tests, all passing** — the foundation is solid
- **`bin/cloding.js`** (947 lines) — Zero-dependency Node.js CLI that wraps Claude Code with OpenRouter routing
- **Python pipeline** (`pipeline/cloding/`) — Multi-stage pipeline: Plan → Explore → Code → Review
- **Fan-out parallel coding** — Splits PLAN.md into tasks, runs them concurrently with semaphore-bounded asyncio
- **Review loop** — Code → Review → re-Code cycle up to N iterations
- **Cost tracking** — Per-stage CostTracker that exports CSV to `data/costs/`
- **8 YAML configs** — default, quick, opus-plan-qwen-code, qwen-fanout, human-loop, test-cheap, test-fanout, qwen-tools-test
- **Docker isolation** — Full container mode with resource limits, network isolation, non-root user
- **Git workspace safety** — Auto-stash, feature branch creation, checkpoint/resume

### What's Missing / Broken

| Problem | Impact | Root Cause |
|---------|--------|------------|
| **No multi-agent verification** | You can't run 2+ agents checking each other's work | Review stage is single-agent, single-pass. No parallel verification, no consensus |
| **No test stage** | Code gets reviewed but never actually tested | Pipeline has plan/explore/code/review but no "run the tests" stage |
| **No lint/typecheck stage** | Static analysis is missing | Same gap — no automated quality gates |
| **Cost reporting is hidden** | You said "I want to see the price" — it's in a CSV file nobody reads | `cost_tracker.py` writes to `data/costs/{run_id}_costs.csv` but the CLI summary is a tiny print statement |
| **No real-time progress** | You can't "sit back and watch it work" | No live stage progress, no streaming, no dashboard. Just logs |
| **No verification consensus** | Single reviewer = single point of failure | If the reviewer model hallucinates PASS, bad code ships |
| **Review prompt is fragile** | `_check_review()` searches for PASS/FAIL with regex | Models prepend thinking/preamble that breaks detection |
| **No post-run summary file** | After a run, there's no artifact you can read | Cost CSV exists but no human-readable summary with what changed + what it cost |
| **Pipeline configs reference wrong prompt paths** | `prompts/plan.txt` is relative, breaks depending on CWD | Stage prompt loading uses relative paths from config |
| **No `cloding verify` command** | No way to run verification independently of a pipeline | You can only review as part of a pipeline run |
| **Version mismatch** | `package.json` says 0.1.2, `__init__.py` says 0.1.0 | Minor but sloppy |

---

## The Plan: 6 Upgrades

### Upgrade 1: Multi-Agent Verification System

**What:** Add a `verify` stage type that runs N parallel verification agents with different models and aggregates their verdicts into a consensus score.

**Why:** Right now you have 1 reviewer. If it says PASS, you trust it blindly. With 3 reviewers (e.g., Opus + Sonnet + Qwen), you get majority-vote confidence. If 2/3 say FAIL, it fails — even if one hallucinated PASS.

**Files to create/modify:**
- `pipeline/cloding/pipeline/stage.py` — Add `VerifyStage` class
- `pipeline/cloding/pipeline/pipeline.py` — Wire verify stage into execution, add consensus logic
- `pipeline/cloding/core/config.py` — Add `VerifyConfig` dataclass (num_agents, models, consensus_threshold)
- `pipeline/prompts/verify.txt` — New prompt template for verification agents
- `pipeline/cloding/configs/default.yaml` — Update to include verify stage
- New configs: `pipeline/cloding/configs/multi-verify.yaml`

**How it works:**
```
Code Stage Output
       │
       ▼
┌──────────────────────────┐
│   Verify Stage (parallel) │
│                          │
│  Agent 1 (Opus)    ──→ PASS/FAIL + issues  │
│  Agent 2 (Sonnet)  ──→ PASS/FAIL + issues  │
│  Agent 3 (Qwen)    ──→ PASS/FAIL + issues  │
│                          │
│  Consensus: 2/3 PASS → PASS               │
│  Consensus: 2/3 FAIL → FAIL + merged issues│
└──────────────────────────┘
       │
       ▼
  If FAIL → Re-code with merged feedback
  If PASS → Done
```

**Config format:**
```yaml
verify:
  enabled: true
  agents:
    - model: opus
      prompt_file: prompts/verify.txt
    - model: sonnet
      prompt_file: prompts/verify.txt
    - model: qwen
      prompt_file: prompts/verify.txt
  consensus_threshold: 0.67  # 2/3 must agree
  max_iterations: 3
```

---

### Upgrade 2: Test & Lint Quality Gates

**What:** Add `test` and `lint` stage types that run actual commands (pytest, npm test, eslint, mypy, etc.) and gate the pipeline on their results.

**Why:** The current review stage only *reads* code. It never *runs* it. A model can say PASS on code that doesn't even compile. Quality gates actually execute the code.

**Files to create/modify:**
- `pipeline/cloding/pipeline/stage.py` — Add `TestStage`, `LintStage` classes
- `pipeline/cloding/pipeline/pipeline.py` — Wire quality gates into pipeline flow
- `pipeline/cloding/core/config.py` — Add quality gate config fields
- `pipeline/prompts/test.txt` — Prompt template for test runner
- `pipeline/prompts/lint.txt` — Prompt template for lint runner

**How it works:**
```yaml
stages:
  - name: plan
    model: opus
    # ...
  - name: code
    model: qwen
    # ...
  - name: test     # NEW — runs project test suite
    model: qwen
    prompt_file: prompts/test.txt
    max_turns: 30
    allowed_tools: [Read, Bash]
  - name: lint     # NEW — runs static analysis
    model: qwen
    prompt_file: prompts/lint.txt
    max_turns: 15
    allowed_tools: [Read, Bash]
  - name: verify   # Multi-agent review (Upgrade 1)
    # ...
```

The test/lint stages use Claude Code as a test-runner: the prompt says "run the test suite, read the output, fix any failures, and repeat until green or give up." This is more reliable than raw `bash pytest` because the agent can read errors and fix code.

---

### Upgrade 3: Rich Cost Reporting & Run Summary

**What:** After every pipeline run, generate a detailed `RUN_SUMMARY.md` file in the workspace AND print a rich terminal summary with cost breakdown, token usage, time, and a diff stat.

**Why:** You said "I want to see the price of what I just did and the code that backs it." Right now cost data is buried in a CSV. This puts it front and center.

**Files to create/modify:**
- `pipeline/cloding/models/cost_tracker.py` — Add `generate_summary_md()` method
- `pipeline/cloding/orchestrator.py` — Call summary generator, enhance `_print_summary()`
- `pipeline/cloding/pipeline/pipeline.py` — Thread timing data through results
- `pipeline/cloding/pipeline/result.py` — Add timing fields to PipelineResult

**What the summary looks like:**

```markdown
# Run Summary — 2026-02-19T14:32:00Z

## Request
"Add user authentication with JWT tokens"

## Result: ✅ PASS (3/3 verifiers agreed)

## Cost Breakdown

| Stage    | Model              | Tokens In | Tokens Out | Cost     | Time    |
|----------|--------------------|-----------|------------|----------|---------|
| Plan     | claude-opus-4.6    | 12,400    | 3,200      | $0.47    | 45s     |
| Explore  | claude-haiku-4.5   | 8,100     | 2,100      | $0.02    | 22s     |
| Code×3   | qwen3-coder-next   | 45,000    | 18,000     | $0.01    | 2m 10s  |
| Verify×3 | opus/sonnet/qwen   | 15,000    | 4,500      | $0.52    | 1m 05s  |
| **Total**|                    | **80,500**| **27,800** |**$1.02** |**4m 22s**|

## Files Changed
 src/auth/jwt.py       | 142 ++++++++++++
 src/auth/middleware.py |  58 +++++
 src/routes/login.py   |  34 +--
 tests/test_auth.py    |  87 +++++++++
 4 files changed, 321 insertions(+)

## Verification
- Opus: PASS ✅
- Sonnet: PASS ✅
- Qwen: PASS ✅
```

And in the terminal, same data with color codes and formatting.

---

### Upgrade 4: Real-Time Progress Streaming

**What:** Add a live progress display that shows what stage is running, which agent is active, elapsed time, and running cost — updating in real-time.

**Why:** "Sit back and make sure it works right" requires being able to *see* what's happening. Right now you stare at logs.

**Files to create/modify:**
- `pipeline/cloding/core/progress.py` — New file: `ProgressTracker` class with rich terminal output
- `pipeline/cloding/pipeline/pipeline.py` — Emit progress events to tracker
- `pipeline/cloding/orchestrator.py` — Initialize and wire progress tracker

**What you see in the terminal:**
```
╭─── cloding pipeline ───────────────────────────────╮
│                                                     │
│  Request: "Add user authentication with JWT"        │
│  Config:  opus-plan-qwen-code                       │
│  Run ID:  abc123                                    │
│                                                     │
│  ✅ Plan    (opus)     45s   $0.47                  │
│  ✅ Explore (haiku)    22s   $0.02                  │
│  ⏳ Code×3  (qwen)     1m02s $0.008  [████░░] 2/3  │
│  ○ Verify  (multi)    —     —                       │
│                                                     │
│  Running cost: $0.498                               │
╰─────────────────────────────────────────────────────╯
```

---

### Upgrade 5: `cloding verify` Standalone Command

**What:** Add a `cloding verify` subcommand to the Node.js CLI that runs multi-agent verification on the current workspace without running a full pipeline.

**Why:** Sometimes you already wrote the code. You just want multiple agents to check it. This decouples verification from the pipeline.

**Files to create/modify:**
- `bin/cloding.js` — Add `verify` subcommand parsing and execution
- `pipeline/cloding/cli/main.py` — Add `verify` subcommand
- New config: `pipeline/configs/verify-only.yaml`

**Usage:**
```bash
# Verify current changes with 3 agents
cloding verify

# Verify with specific models
cloding verify -m opus,sonnet,qwen

# Verify with custom threshold
cloding verify --threshold 1.0  # all must agree
```

---

### Upgrade 6: Bug Fixes & Polish

**What:** Fix existing issues found during the audit.

| Fix | File | Details |
|-----|------|---------|
| Version sync | `pipeline/cloding/__init__.py` | Change `0.1.0` → `0.1.2` to match `package.json` |
| Prompt path resolution | `pipeline/cloding/pipeline/stage.py` | Make prompt_file paths resolve relative to config file location, not CWD |
| Review PASS/FAIL detection | `pipeline/cloding/pipeline/pipeline.py` | Make `_check_review()` more robust — scan last 50 lines, handle markdown-wrapped verdicts |
| Coroutine warning | `pipeline/cloding/orchestrator.py` | Fix the `RuntimeWarning: coroutine 'run_pipeline' was never awaited` in test_config |
| Windows encoding | `pipeline/cloding/core/logger.py` | Already handled, but verify the UTF-8 wrapper works for all Unicode chars in verify output |
| Missing `__init__.py` files | Various | Ensure all packages have proper `__init__.py` |
| Cost tracker edge case | `pipeline/cloding/models/cost_tracker.py` | Handle case where token counts are 0 (don't divide by zero in per-token cost calc) |

---

## Implementation Order

```
Phase 1: Foundation (bug fixes + quality of life)
  └─ Upgrade 6: Bug fixes & polish
  └─ Upgrade 3: Cost reporting (RUN_SUMMARY.md + rich terminal output)

Phase 2: Quality Gates (make the pipeline reliable)
  └─ Upgrade 2: Test & lint stages
  └─ Upgrade 1: Multi-agent verification system

Phase 3: UX (sit back and watch)
  └─ Upgrade 4: Real-time progress streaming
  └─ Upgrade 5: `cloding verify` standalone command
```

Each phase builds on the previous. Phase 1 fixes what's broken. Phase 2 makes the pipeline produce trustworthy output. Phase 3 makes it a pleasure to use.

---

## File Map

### New Files
```
pipeline/cloding/core/progress.py          # Real-time progress tracker
pipeline/prompts/verify.txt                 # Verification agent prompt
pipeline/prompts/test.txt                   # Test runner prompt
pipeline/prompts/lint.txt                   # Lint runner prompt
pipeline/configs/multi-verify.yaml          # Full pipeline with multi-agent verify
pipeline/configs/verify-only.yaml           # Standalone verification config
```

### Modified Files
```
bin/cloding.js                              # Add 'verify' subcommand
pipeline/cloding/__init__.py                # Version sync → 0.1.2
pipeline/cloding/cli/main.py                # Add 'verify' subcommand
pipeline/cloding/core/config.py             # Add VerifyConfig, quality gate fields
pipeline/cloding/models/cost_tracker.py     # Add generate_summary_md()
pipeline/cloding/orchestrator.py            # Rich summary, progress hooks, fix warning
pipeline/cloding/pipeline/pipeline.py       # Multi-verify, quality gates, progress events, robust PASS/FAIL detection
pipeline/cloding/pipeline/result.py         # Add timing + verify fields to PipelineResult
pipeline/cloding/pipeline/stage.py          # Add VerifyStage, TestStage, LintStage + fix prompt path resolution
pipeline/configs/default.yaml               # Add verify stage to default config
```

### Test Files (new tests for new features)
```
pipeline/tests/test_verify_stage.py         # Multi-agent verification tests
pipeline/tests/test_quality_gates.py        # Test + lint stage tests
pipeline/tests/test_progress.py             # Progress tracker tests
pipeline/tests/test_cost_summary.py         # RUN_SUMMARY.md generation tests
```

---

## Estimated Scope

- **~1,200 lines of new Python** across pipeline modules
- **~200 lines of new JS** in `bin/cloding.js` for verify command
- **~400 lines of new tests** covering the new features
- **~150 lines of config/prompts** (YAML + prompt templates)
- **Total: ~1,950 lines** of new/modified code

All 241 existing tests will continue to pass throughout.
