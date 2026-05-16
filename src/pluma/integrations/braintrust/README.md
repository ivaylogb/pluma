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
point agent-researcher at it. `cli.py` is a thin argparse wrapper. The
fixture and golden output live in `fixtures/`.

### Field mapping

Each Braintrust row carries `id`, `input`, `expected`, `output`, a `scores`
object (scorer name → numeric score, conventionally 0.0–1.0), an optional
`metadata` dict, and a `created` ISO-8601 timestamp. The six fields
agent-researcher's loader types against:

| agent-researcher field | Braintrust source |
|---|---|
| `scenario_id` | `id` |
| `expected` | `expected` (stringified) |
| `predicted` | `output` (stringified) |
| `predicted_confidence` | primary scorer's score |
| `passed` | always `false` (only failures are emitted) |
| `notes` | generated: scorer, score, threshold, experiment |

Each emitted record is the original Braintrust row with those six fields
overlaid, so everything the platform supplied (`input`, `output`, `scores`,
`created`, `span_id`, …) rides along untouched and reaches the diagnostic
agent through the loader's `raw=record`. `metadata` is the row's own
metadata merged with `experiment_id`, `experiment_name`, `project_name`, and
`row_id`, so a diagnosed scenario traces back to its source. The container
keeps `total`, `passed`, `pass_rate`, `threshold`, and `meets_threshold`
over the whole experiment, not just the failures.

## Usage

Sample input row (one row from `fixtures/experiment.json`):

```json
{"id": "a1c0e003-0b36-4f1a-9c36-000000000003", "span_id": "span-0003", "input": {"message": "I was billed for a seat I removed last week.", "channel": "email"}, "expected": "billing", "output": "account_management", "scores": {"exact_match": 0.0, "calibrated_confidence": 0.74}, "metadata": {"model": "gpt-4o-mini", "prompt_version": "v3", "tags": ["prod-traffic"]}, "created": "2026-05-14T09:03:00.000Z"}
```

Convert:

```bash
python -m pluma.integrations.braintrust.cli \
    --input  src/pluma/integrations/braintrust/fixtures/experiment.json \
    --output src/pluma/integrations/braintrust/fixtures/failing_evals.json \
    [--score-threshold 1.0] [--scorer exact_match]
```

Sample output (the corresponding record in `results` in
`fixtures/failing_evals.json`):

```json
{
  "id": "a1c0e003-0b36-4f1a-9c36-000000000003",
  "span_id": "span-0003",
  "input": {"message": "I was billed for a seat I removed last week.", "channel": "email"},
  "expected": "billing",
  "output": "account_management",
  "scores": {"exact_match": 0.0, "calibrated_confidence": 0.74},
  "metadata": {"model": "gpt-4o-mini", "prompt_version": "v3", "tags": ["prod-traffic"], "experiment_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479", "experiment_name": "routing_classifier_eval_v3", "project_name": "support-router", "row_id": "a1c0e003-0b36-4f1a-9c36-000000000003"},
  "created": "2026-05-14T09:03:00.000Z",
  "scenario_id": "a1c0e003-0b36-4f1a-9c36-000000000003",
  "predicted": "account_management",
  "predicted_confidence": 0.0,
  "passed": false,
  "score": 0.0,
  "scorer": "exact_match",
  "notes": "Braintrust scorer 'exact_match' scored 0.0 (threshold 1.0). expected='billing' output='account_management'. experiment 'routing_classifier_eval_v3' (f47ac10b-58cc-4372-a567-0e02b2c3d479), row a1c0e003-0b36-4f1a-9c36-000000000003."
}
```

Point agent-researcher at the converted output (directly or via Pluma):

```bash
pluma diagnose-agent \
    --target-agent your_agent_dir \
    --eval-result  src/pluma/integrations/braintrust/fixtures/failing_evals.json \
    --output-file   hypotheses.md
```

## Filtering behavior

A row passes when its primary scorer's score is present and `>=` the
threshold (default `1.0` — anything not perfect is a failure). The primary
scorer defaults to the first scorer in each row's `scores`; pass `--scorer
NAME` to pin one. Rows missing the primary scorer are emitted as failures,
not silently dropped — a row that can't be confirmed passing is worth a
look. Passing scenarios are dropped entirely, not carried with a flag: this
converter feeds diagnosis, not analysis. The container's summary counts
preserve the audit trail for everything the filter removed.

## Notes on the fixture

`fixtures/experiment.json` is hand-authored to match the documented
Braintrust experiment shape, not captured from a live instance. It models a
generic support-routing intent classifier: 36 scored rows, 25 passing and 11
misrouted across billing / technical-support / account-management /
cancellation / sales / general-inquiry, authored newest-first (the converter
sorts output by `created` ascending). `fixtures/failing_evals.json` is the
committed golden output — a diff against a fresh run is the regression test.
