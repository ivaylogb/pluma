## Pluma + Braintrust integration

This directory bridges [Braintrust](https://www.braintrust.dev/) (LLM evaluation
platform) with Pluma's diagnostic methodology. Braintrust produces scored
experiment results — one row per scenario, graded by named scorers.
agent-researcher consumes failing eval scenarios and produces hypotheses for
why they failed. The converter extracts the failing scenarios from a
Braintrust experiment and writes them in the shape agent-researcher's loader
already reads.

## What's here

`experiment_to_failing_evals.py` is a converter that transforms a Braintrust
experiment export (the object shape returned by the Braintrust API) into the
single JSON object `agent_researcher.eval_analyzer.load_eval_result` parses.
Read a Braintrust experiment export, write a Pluma-ready `failing_evals.json`,
point agent-researcher at it. `cli.py` is a thin argparse wrapper.
`braintrust_client.py` is a minimal live-API client. The fixture and golden
output live in `fixtures/`.

## What's new in this version

Four changes over the first adapter. All are additive: a v0.1-shaped caller
(only `score_threshold`, rows without spans or multi-scorer setups) gets the
same recognized fields and the same failing-row set as before.

- **Spans.** The agent's execution trace from the Braintrust row rides along
  on each emitted record, so agent-researcher can localize a defect to a step
  of the run instead of reasoning from source alone.
- **Scorer signature.** Per-scorer pass/fail is preserved, not collapsed to
  the primary scorer's verdict. The pattern is itself diagnostic
  (factuality-fails-but-exact-match-passes is a different bug than the
  reverse).
- **Agent revision.** A git SHA (or similar) for the source that produced the
  experiment is threaded onto the container and every record, so a downstream
  diagnoser pins to the right revision instead of drifted code. Auto-resolved
  from the experiment's own metadata when present.
- **Clustering pre-pass.** An optional pass collapses failing rows that share
  a failure shape into one representative, so diagnosing one systemic cause
  across 30 rows costs one investigation, not 30.

Live mode skips the export-to-disk step. `--braintrust-experiment-id ID`
(or `--braintrust-project NAME --latest`) pulls the experiment from the
Braintrust API, enriches rows with spans, and converts inline. It is
reachable two ways, both backed by the same
`braintrust_client.fetch_experiment_as_failing_evals` helper (resolve →
fetch → convert → optional cluster, pure data in / container out):

- `python -m pluma.integrations.braintrust.cli --braintrust-experiment-id ID --output …` — write the converted file.
- `pluma diagnose-agent --braintrust-experiment-id ID …` — pull, convert, and run agent-researcher in one command (see Usage).

### Field mapping

Each Braintrust row carries `id`, `input`, `expected`, `output`, a `scores`
object (scorer name → numeric score, conventionally 0.0–1.0), an optional
`metadata` dict, a `created` ISO-8601 timestamp, and — when the eval was
instrumented — a `spans` tree. The fields agent-researcher's loader types
against, plus the diagnostic fields overlaid alongside them:

| Output field | Braintrust source |
|---|---|
| `scenario_id` | `id` |
| `expected` | `expected` (stringified) |
| `predicted` | `output` (stringified) |
| `predicted_confidence` | primary scorer's score |
| `passed` | always `false` (only failures are emitted) |
| `notes` | generated: scorer, score, band, experiment |
| `scorer_signature` | per-scorer `{score, passed, is_primary}` over the row's `scores` |
| `spans` | the row's `spans` tree (trimmed; see below), or `null` if absent |
| `metadata.agent_revision` | resolved revision (see below) |

Each emitted record is the original Braintrust row with these fields
overlaid, so everything the platform supplied (`input`, `output`, `scores`,
`created`, `span_id`, …) rides along untouched and reaches the diagnostic
agent through the loader's `raw=record`. `metadata` is the row's own
metadata merged with `experiment_id`, `experiment_name`, `project_name`,
`row_id`, and `agent_revision`. The container keeps `total`, `passed`,
`pass_rate`, `threshold`, and `meets_threshold` over the whole experiment,
and adds `agent_revision` and `score_band`.

### Spans

When a row carries a `spans` list it is preserved on the emitted record, so
the agent's actual execution is available to the diagnoser. A run can produce
hundreds of nested spans; sending all of them inflates the diagnostic prompt
for no marginal benefit. The default keeps the first `DEFAULT_MAX_SPANS`
(50) entries in trace-tree order and appends a marker:

```json
{"_truncated": true, "_dropped": 25}
```

`--max-spans N` (CLI) or `max_spans=N` (API) sets the cap; `--max-spans -1`
/ `max_spans=None` disables trimming. A non-list `spans` value is passed
through as-is. A row with no `spans` (or `spans: null`) yields `spans: null`
on the record.

### Scorer signature

`scorer_signature` maps every scorer in the row's `scores` to
`{score, passed, is_primary}`. The primary scorer's `passed` is judged
against the band (below). Non-primary scorers use a softer floor — `passed`
is `true` iff the score is numeric and `>=` the band's minimum — so a
calibration scorer that under-scores in-band does not mark the row "passed".
The primary scorer is `--scorer NAME`, else the first scorer in the row's
`scores` (Braintrust insertion order).

### Agent revision

`--agent-revision SHA` pins the agent source revision onto the container's
`agent_revision` and each record's `metadata.agent_revision`. If not passed,
the converter reads `agent_revision` (then `git_sha`) from the experiment's
top-level `metadata`, so a CI run that tags the experiment with its commit
gets the downstream diagnoser pinned automatically. An explicit
`--agent-revision` overrides the experiment metadata.

### Continuous scorers (ScoreBand)

A row passes when its primary scorer's score is present and inside the
`ScoreBand`. The default is `ScoreBand(1.0, 1.0)` — equivalent to the
historical "anything not perfect is a failure" threshold. For calibration-
style scorers where over-confidence is also a failure, pass a band with a
real ceiling:

- CLI: `--score-threshold 0.4 --score-band-max 0.8`
- API: `experiment_to_failing_evals(exp, score_band=ScoreBand(0.4, 0.8))`

Backward-compat: passing only `score_threshold` (positional, as before) is
interpreted as `ScoreBand(score_threshold, max(score_threshold, 1.0))`. The
container still reports `threshold` (equal to the band minimum) and
`meets_threshold`, so v0.1 consumers are unaffected.

## Usage

Convert (file mode):

```bash
python -m pluma.integrations.braintrust.cli \
    --input  src/pluma/integrations/braintrust/fixtures/experiment.json \
    --output src/pluma/integrations/braintrust/fixtures/failing_evals.json \
    [--score-threshold 1.0] [--score-band-max 0.8] [--scorer exact_match] \
    [--agent-revision <sha>] [--max-spans 50] [--cluster none|first|worst]
```

A failing record in `fixtures/failing_evals.json`, with the new fields
(spans abbreviated — see the fixture for the full tree and, on the
75-span row, the truncation marker):

```json
{
  "id": "a1c0e003-0b36-4f1a-9c36-000000000003",
  "input": {"message": "I was billed for a seat I removed last week.", "channel": "email"},
  "expected": "billing",
  "output": "account_management",
  "scores": {"exact_match": 0.0, "calibrated_confidence": 0.74, "factuality": 1.0},
  "created": "2026-05-14T09:03:00.000Z",
  "scenario_id": "a1c0e003-0b36-4f1a-9c36-000000000003",
  "predicted": "account_management",
  "predicted_confidence": 0.0,
  "passed": false,
  "score": 0.0,
  "scorer": "exact_match",
  "scorer_signature": {
    "exact_match": {"score": 0.0, "passed": false, "is_primary": true},
    "calibrated_confidence": {"score": 0.74, "passed": false, "is_primary": false},
    "factuality": {"score": 1.0, "passed": true, "is_primary": false}
  },
  "spans": [
    {"span_id": "sp-0003-root", "parent_span_id": null, "name": "classify_intent", "input": {"message": "…", "channel": "email"}, "output": {"intent": "account_management"}, "start": "2026-05-14T09:03:00.100Z", "end": "2026-05-14T09:03:00.940Z", "metadata": {"model": "gpt-4o-mini", "step": "root"}}
  ],
  "metadata": {"model": "gpt-4o-mini", "prompt_version": "v3", "tags": ["prod-traffic"], "experiment_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479", "experiment_name": "routing_classifier_eval_v3", "project_name": "support-router", "row_id": "a1c0e003-0b36-4f1a-9c36-000000000003", "agent_revision": "a1b2c3d4e5f67890abcdef1234567890abcdef12"},
  "notes": "Braintrust scorer 'exact_match' scored 0.0 (band [1.0, 1.0]). expected='billing' output='account_management'. experiment 'routing_classifier_eval_v3' (f47ac10b-58cc-4372-a567-0e02b2c3d479), row a1c0e003-0b36-4f1a-9c36-000000000003."
}
```

Point agent-researcher at a converted file (directly or via Pluma):

```bash
pluma diagnose-agent \
    --target-agent your_agent_dir \
    --eval-result  src/pluma/integrations/braintrust/fixtures/failing_evals.json \
    --output-file   hypotheses.md
```

Or skip the file entirely — pull the experiment live, convert, and
diagnose in one command (`BRAINTRUST_API_KEY` in the env, or
`--braintrust-api-key`):

```bash
pluma diagnose-agent \
    --target-agent your_agent_dir \
    --braintrust-experiment-id <experiment-id> \
    --output-file   hypotheses.md

# or the most recent experiment in a project
pluma diagnose-agent \
    --target-agent your_agent_dir \
    --braintrust-project <project-name> --latest \
    --output-file   hypotheses.md
```

`--eval-result` and the `--braintrust-*` flags are mutually exclusive
(exactly one source). The shaping flags carry through to the converter:
`--scorer`, `--score-band-min`, `--score-band-max`, `--max-spans`,
`--cluster {none,first,worst}` / `--no-cluster`. The live path pulls
spans by default and does not use Pluma's run cache (a live pull is keyed
on an experiment id, not file contents).

## Filtering behavior

A row passes when its primary scorer's score is present and inside the score
band (default `[1.0, 1.0]`). The primary scorer defaults to the first scorer
in each row's `scores`; pass `--scorer NAME` to pin one. Rows missing the
primary scorer are emitted as failures, not silently dropped — a row that
can't be confirmed passing is worth a look. Passing scenarios are dropped
entirely, not carried with a flag: this converter feeds diagnosis, not
analysis. The container's summary counts preserve the audit trail for
everything the filter removed.

## Clustering pre-pass

`cluster_failing_rows(container, representative="first")` collapses the
converted container's failing rows by failure shape. Two rows are in the same
cluster when their scorer-signature pass/fail pattern and their
`(expected, predicted)` pair match. Each cluster emits one representative
carrying `cluster_size` and `cluster_member_ids`; the container gains
`clustered: true` and `cluster_count`, and rows are ordered by descending
cluster size. `representative="first"` (CLI `--cluster first`) keeps the
earliest row by `created`; `"worst"` (`--cluster worst`) keeps the row with
the lowest primary-scorer score. Use clustering when one mechanism produces
many failing rows and you want one investigation with the count as
load-bearing context; use the raw output when each failure needs independent
diagnosis. Clustering is a diagnostic decision, kept out of the conversion
itself.

## Notes on the fixture

`fixtures/experiment.json` is hand-authored to match the documented
Braintrust experiment shape, not captured from a live instance. It models a
generic support-routing intent classifier: 36 scored rows, 25 passing and 11
misrouted across billing / technical-support / account-management /
cancellation / sales / general-inquiry, authored newest-first (the converter
sorts output by `created` ascending). It also exercises the v2 paths: a
synthetic `spans` tree on a subset of rows (one row >50 spans to drive the
trim path; one with `spans: null`; rows with no `spans` key at all), a third
`factuality` scorer on a few rows for mixed multi-scorer signatures (rows
range over one, two, and three scorers), and an experiment-level
`metadata.agent_revision`. `fixtures/failing_evals.json` is the committed
golden output — a diff against a fresh run is the regression test.
