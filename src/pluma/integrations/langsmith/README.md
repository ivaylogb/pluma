## Pluma + LangSmith integration

This directory bridges [LangSmith](https://smith.langchain.com/) with
Pluma's diagnostic methodology. LangSmith's primary entity is a **run**:
one agent execution captured as a trace tree of parent + nested child
runs (one per LLM/tool call). Evaluations attach to runs as *feedback*,
not as a scored row. The run tree is the highest-leverage diagnostic
input — it lets agent-researcher localize a defect to a step of the
agent's reasoning instead of reading source alone.

Two workflows produce failing evals, exposed as two entry points that
share ~70% of their internals and emit the identical
`FailingEvalContainer` (agent-diagnosis-spec v0.2) the Braintrust
adapter does.

## Workflow A — Dataset-Experiment

`client.evaluate(...)` ran a dataset of reference cases, producing an
experiment (a tracing session) with a fixed scenario set. Each root run
points at the dataset `Example` it was scored against; reference
outputs live on that Example.

```bash
python -m pluma.integrations.langsmith.cli \
    --experiment-id <tracing-session-id> \
    --primary-feedback-key correctness \
    --threshold 1.0 \
    --agent-revision <sha> \
    --output failing_evals.json
```

The adapter lists the experiment's root runs
(`list_runs(project_id=<experiment>, is_root=True)`), fetches their
feedback in batches, walks each failing run's tree, resolves
`reference_example_id → read_example → example.outputs` for `expected`,
and emits the container.

## Workflow B — Project-traced production

Agent runs flow into a project as they happen; there is no experiment
boundary and no dataset. Feedback comes from online evaluators, human
review, or programmatic checks.

```bash
python -m pluma.integrations.langsmith.cli \
    --project <project-name> \
    --filter 'and(gt(start_time, "2026-05-01T00:00:00Z"), eq(feedback_key, "correctness"))' \
    --primary-feedback-key correctness \
    --threshold 1.0 \
    --reference-feedback-key reference_answer \
    --agent-revision <sha> \
    --output failing_evals.json
```

`--filter` is a LangSmith filter-DSL string passed through verbatim.
There is no dataset Example, so `expected` is the `unknown` sentinel
unless `--reference-feedback-key` names a feedback entry whose value is
the reference output.

Both are also reachable through Pluma in one command (pull → convert →
diagnose), mutually exclusive with `--eval-result` and the
`--braintrust-*` flags:

```bash
pluma diagnose-agent --target-agent your_agent_dir \
    --langsmith-experiment-id <id> --primary-feedback-key correctness \
    --output-file hypotheses.md

pluma diagnose-agent --target-agent your_agent_dir \
    --langsmith-project <name> --filter '<expr>' \
    --primary-feedback-key correctness --output-file hypotheses.md
```

## Field mapping

| Output field | LangSmith source (workflow A) | LangSmith source (workflow B) |
|---|---|---|
| `scenario_id` | `reference_example_id` (stable across reruns) | run `id` |
| `expected` | `read_example(reference_example_id).outputs` (stringified) | `unknown`, or a `--reference-feedback-key` feedback `value` |
| `predicted` | run `outputs` (stringified) | run `outputs` (stringified) |
| `predicted_confidence` / `score` | primary feedback's numeric score | primary feedback's numeric score |
| `passed` | always `false` (only failures emitted) | always `false` |
| `scorer` | primary feedback key | primary feedback key (or first failing key) |
| `scorer_signature` | per-feedback-key `{score, passed, is_primary}` | same |
| `spans` | depth/budget-bounded run tree | same |
| `notes` | generated: scorer, score, threshold, run, project | same |
| `metadata.run_id` / `trace_id` / `project_name` | run `id` / `trace_id` / project | same |
| `metadata.agent_revision` | `--agent-revision` only (never auto-resolved) | same |

Each record carries the run's `inputs`/`outputs` (`input`/`output`) so
everything LangSmith supplied reaches the diagnostic agent through the
loader's `raw=record`. The container keeps `total`/`passed`/`pass_rate`
/`threshold`/`meets_threshold`; `total` is the runs the filter walked
(LangSmith has no cheap experiment-wide count — a lower bound, as the
Braintrust live path also reports).

## Configuration

- **`--threshold`** (default `1.0`) — minimum passing numeric score.
- **`--primary-feedback-key`** — the feedback key that decides
  pass/fail. LangSmith does not standardize key names (evaluators
  choose their own), so there is no auto-detect list. With a key set, a
  run fails if that key is absent (cannot be confirmed passing) or its
  score is below threshold. Omitted, a run fails if **any** feedback
  key scores below threshold; a run with no feedback is not a failure.
- **`--reference-feedback-key`** (workflow B only) — feedback key whose
  `value` is the reference output for `expected`.
- **`--max-tree-depth`** (default `4`) — run-tree BFS depth bound,
  root = 0.
- **`--max-total-nodes`** (default `50`) — global cap on span nodes
  per run across the whole subtree. When it bites, root→error-leaf
  paths are kept intact and sibling leaves are dropped first; a
  `{"_truncated": true, "_dropped": N, "_max_nodes": M}` marker is
  appended.
- **`--agent-revision`** — git SHA (or similar) for the agent source.
  Unlike the Braintrust adapter, this is **never auto-resolved**:
  LangSmith has no git-SHA convention (SHAs may be in tags, `extra`,
  or absent), so guessing would silently pin diagnosis to the wrong
  revision. Set it explicitly or it stays `null`.

## API rate considerations

LangSmith exposes no single descendants endpoint, so the run-tree
walker queries children per level via `list_runs(parent_run_id=...)`:
the span fetch for one failing run is **O(tree-size)** API calls (one
per non-leaf node, paginated). Feedback is a separate resource fetched
in batches via `list_feedback(run_ids=[...])` (one request per
`_FEEDBACK_BATCH=100` runs), and workflow A issues one cached
`read_example` per distinct dataset example. The depth bound caps the
number of levels walked but not the per-level fan-out — a run with
thousands of sibling tool calls at one level will still page through
all of them before the node-budget selection trims them. Keep
`--max-tree-depth` tight on very wide agents. A future optimization is
a single `list_runs(trace_id=...)` per trace with client-side tree
reconstruction (O(1) requests per failing run); the per-level walker is
shipped here because it is the documented, stable access path.

## Notes on the fixtures

`fixtures/experiment.json` (workflow A) and `fixtures/project_runs.json`
(workflow B) are hand-authored to the verified LangSmith REST shapes
(`Run` / `Feedback` / `Example`, May 2026 SDK), not captured from a
live instance. Experiment: 10 root runs, 3 failing on `correctness`
(one with a depth-2 run tree whose deepest node carries the error).
Project: 15 root runs, 5 failing under the no-primary fallback (plus
two non-root runs an `is_root` query excludes), one with a depth-2
erroring tree and one with a `reference_answer` feedback for the
`--reference-feedback-key` path. `fixtures/failing_evals_experiment.json`
and `fixtures/failing_evals_project.json` are the committed goldens —
a diff against a fresh run is the regression test (`test_*_workflow_
basic`), and both validate against agent-diagnosis-spec v0.2's
`failing-eval-container.schema.json`.

## Status

A structural sketch. The network shapes match the published
SDK/REST docs but have not been exercised against a live LangSmith
instance; the converter logic and the run-tree walker are covered by
synthetic fixtures and unit tests with transport faked (no network, no
spend). Treat as v0.1 of this adapter — same posture the OTel and
first Braintrust adapters shipped with. The six LangSmith API-shape
assumptions in the upstream bundle draft were each checked against the
docs and found wrong; the divergences are documented at the top of
`runs_to_failing_evals.py`.
