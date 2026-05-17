# integration-watcher

`integration-watcher` finds patterns across a cohort's integration traces.
Given the trace stream, the cohort definition (including the watch question),
and the product's artifacts, it produces a markdown findings report of 2–3
structurally distinct findings about how that cohort's integrations get stuck.
Each finding is assigned to one layer (Trace definition, API/SDK surface,
Docs/Context, Integration sequence), grounded in both trace evidence
(`developer_id` + call sequence) and product evidence (`file:line`), and ships
an applyable structured edit. The analysis logic lives in the CLI; you invoke
the CLI through your shell and relay what it produced.

## When to invoke

Invoke when the user has API call traces (JSONL), a cohort definition (YAML)
with a watch question, and a directory of product artifacts (docs, SDK source,
error catalog), and wants the patterns in how that cohort's integrations get
stuck. The user typically says something like *"the traces from our beta
cohort are in `traces.jsonl` — tell me why so many integrations stall after
the first call."* This is the trigger: a trace cohort, a watch question, and a
product surface to ground the patterns in.

Do not invoke without a trace stream, without a cohort definition, or as a
substitute for analytics, telemetry, or session replay — this surfaces
structural patterns and traces them to product artifacts, not usage metrics.

## Prerequisites

- The `integration-watcher` CLI on PATH. Install from a clone of
  <https://github.com/ivaylogb/integration-watcher>:
  ```bash
  pip install -e .
  export ANTHROPIC_API_KEY=sk-ant-...
  ```
- `ANTHROPIC_API_KEY` set — `watch` spends model tokens.

## Inputs

| Input | Flag | Required | Notes |
|---|---|---|---|
| Trace stream | `--traces` | yes | JSONL of API-call traces across the cohort. |
| Cohort definition | `--cohort` | yes | YAML; includes the watch question. |
| Product artifact directory | `--product` | yes | Docs, SDK source, error catalog. |
| Output path | `--output-file` | yes | Where to write the report (markdown). |
| Extra artifact file | `--extra-file` | no | Repeatable; pulls in a file outside the product dir. |
| Model | `--model` | no | Claude model override. |
| Max tokens | `--max-tokens` | no | Output token cap. |

## Outputs

A markdown findings report written to `--output-file`. `--output-file` is
required by the CLI; use `./integration-findings.md` as the default name.
After it completes, read that file back and present each finding with its
layer, the trace evidence (`developer_id` + call sequence), the `file:line`
citation, and the proposed edit.

## Invocation

Run the installed CLI directly through your shell:

```bash
integration-watcher watch \
    --traces ./traces.jsonl \
    --cohort ./cohort.yaml \
    --product ./product_artifacts \
    --output-file ./integration-findings.md
```

Then read `./integration-findings.md` and present each finding with its layer,
the trace evidence (`developer_id` + call sequence), the `file:line`
citation, and the proposed edit.

## What this tool does not do

- It does not apply edits or run `iterate`. Those are separate CLI
  subcommands; do not invoke them as part of analysis.
- It does not find patterns itself — relay what the CLI produced.
- It is not analytics, telemetry, or session replay. It surfaces structural
  patterns and traces them to product artifacts.
