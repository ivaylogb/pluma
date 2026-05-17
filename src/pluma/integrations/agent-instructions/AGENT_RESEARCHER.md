# agent-researcher

`agent-researcher` diagnoses one failing eval scenario. Given the target
agent's directory and the harness output containing the failure, it reads the
agent's source and the failing scenario, then produces a markdown report of
2–3 structurally distinct hypotheses about why the failure happened. Each
hypothesis is assigned to one agent-engineering layer (Evaluation, Tools,
Context, Workflow), cites specific `file:line` evidence in the target agent,
ships an applyable structured edit, and names a verification step. The
diagnostic logic lives in the CLI; you invoke the CLI through your shell and
relay what it produced.

## When to invoke

Invoke when a scenario in an eval suite is failing, the user wants to
understand why, and the eval output is available as a JSON file — for example
an export from Braintrust, LangSmith, or a custom harness. The user typically
says something like *"the routing eval is failing on scenario 107, figure out
why."* This is the trigger: a known failing scenario, an agent under
diagnosis, and a request for structured hypotheses rather than a guess.

Do not invoke for green eval suites, for "make the agent better" with no
specific failure, or when no eval-result JSON exists.

## Prerequisites

- The `agent-researcher` CLI on PATH. Install from a clone of
  <https://github.com/ivaylogb/agent-researcher>:
  ```bash
  pip install -e .
  export ANTHROPIC_API_KEY=sk-ant-...
  ```
- `ANTHROPIC_API_KEY` set — `diagnose` spends model tokens.

## Inputs

| Input | Flag | Required | Notes |
|---|---|---|---|
| Target agent directory | `--target-agent` | yes | The agent under diagnosis (manifest, prompts, tools). |
| Eval result JSON | `--eval-result` | yes | The harness output containing the failure. |
| Scenario id | `--scenario-id` | no | Which failure to investigate; defaults to the first. |
| Scenario input | `--scenario-input` / `--scenario-input-file` | no | The user message for the failing scenario. Strongly improves the report. |
| Model | `--model` | no | Claude model override. |
| Output path | `--output-file` | no | Where to write the report. See Outputs. |

## Outputs

A markdown hypotheses report. Pass `--output-file ./hypotheses.md` (or a
scenario-specific name) so the report is captured to a file; without
`--output-file` the CLI writes the report to stdout. After it completes, read
that file back and surface the hypotheses to the user — each with its layer,
`file:line` citation, proposed edit, and verification step.

## Invocation

Run the installed CLI directly through your shell:

```bash
agent-researcher diagnose \
    --target-agent ./reference_agent \
    --eval-result ./reference_agent/evals/routing/last_run.json \
    --scenario-id 107 \
    --scenario-input-file ./scenario_107.txt \
    --output-file ./hypotheses_107.md
```

Then read `./hypotheses_107.md` and present the hypotheses, each with its
layer, `file:line` citation, proposed edit, and verification step.

## What this tool does not do

- It does not apply edits or re-run the eval. That is the CLI's `apply` /
  `iterate`; do not invoke those as part of diagnosis.
- It does not invent hypotheses itself — relay what the CLI produced.
- It does not choose which hypothesis is correct. A human decides what to
  apply.
