# funnel-researcher

`funnel-researcher` diagnoses developer dropoff at a funnel step. Given the
funnel definition, the per-step dropoff data, and the product's artifacts, it
produces a markdown report of 2–3 structurally distinct hypotheses about why
developers stall at the target step. Each hypothesis is assigned to one layer
(Funnel definition, API/SDK surface, Docs/Context, Workflow/Sequence),
grounded in both a specific dropoff signal and a `file:line` citation into the
product surface, and ships an applyable structured edit. The diagnostic logic
lives in the CLI; you invoke the CLI through your shell and relay what it
produced.

## When to invoke

Invoke when the user has a developer-API onboarding funnel (defined as YAML),
dropoff data per step, and a directory of product artifacts (docs, SDK source,
error catalog), and wants to know why developers fall off at a target step.
The user typically says something like *"developers are dropping off at the
first-API-call step of the activation funnel — figure out why."* This is the
trigger: a defined funnel, measured dropoff at a specific step, and a product
surface to ground the explanation in.

Do not invoke without measured dropoff data, without a funnel definition, or
for a generic "improve onboarding" request with no specific stalling step.

## Prerequisites

- The `funnel-researcher` CLI on PATH. Install from a clone of
  <https://github.com/ivaylogb/funnel-researcher>:
  ```bash
  pip install -e .
  export ANTHROPIC_API_KEY=sk-ant-...
  ```
- `ANTHROPIC_API_KEY` set — `diagnose` spends model tokens.

## Inputs

| Input | Flag | Required | Notes |
|---|---|---|---|
| Funnel definition | `--funnel` | yes | YAML defining the funnel steps. |
| Dropoff data | `--dropoff` | yes | JSON with per-step dropoff numbers. |
| Product artifact directory | `--product` | yes | Docs, SDK source, error catalog. |
| Output path | `--output-file` | yes | Where to write the report (markdown). |
| Extra artifact file | `--extra-file` | no | Repeatable; pulls in a file outside the product dir. |
| Model | `--model` | no | Claude model override. |
| Max tokens | `--max-tokens` | no | Output token cap. |

## Outputs

A markdown hypotheses report written to `--output-file`. `--output-file` is
required by the CLI; use `./funnel-hypotheses.md` as the default name. After
it completes, read that file back and present each hypothesis with its layer,
the dropoff signal it explains, its `file:line` citation, and the proposed
edit.

## Invocation

Run the installed CLI directly through your shell:

```bash
funnel-researcher diagnose \
    --funnel ./funnel.yaml \
    --dropoff ./dropoff_data.json \
    --product ./product_artifacts \
    --output-file ./funnel-hypotheses.md
```

Then read `./funnel-hypotheses.md` and present each hypothesis with its layer,
the dropoff signal it explains, its `file:line` citation, and the proposed
edit.

## What this tool does not do

- It does not apply edits or run `iterate`. Those are separate CLI
  subcommands; do not invoke them as part of diagnosis.
- It does not invent hypotheses itself — relay what the CLI produced.
- It does not decide which hypothesis is correct. A human picks what to apply.
