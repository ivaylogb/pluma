# pluma-cross

`pluma cross` reports where two or more diagnostic tools independently
converge on the same defect. Given the raw inputs for two or more sister tools
— all pointing at the same `--product` — it runs each applicable tool through
its input-hash cache, normalizes every report into a unified Finding shape,
and emits one report: a correlation matrix (tool × layer), the findings that
show up in **more than one** tool (mechanical match on overlapping
`file:line`, or categorical match on shared layer + product file), then the
findings unique to each tool. The cross-match logic lives in the CLI; you
invoke the CLI through your shell and relay what it produced.

`pluma cross` takes raw tool inputs and re-runs the tools; it does not consume
pre-generated finding markdown. The cache is what makes re-runs cheap: if a
tool was already run with the exact same inputs, that tool's run is a cache
hit and spends no model tokens — only the tools whose inputs were not
previously cached spend.

## When to invoke

Invoke when the user wants to run two or more diagnostic tools against the
same product surface and find where they independently agree. The user
typically says something like *"I have funnel/dropoff data and a trace cohort
for the same API — run both diagnostics and show me where they agree."* If the
individual tools were already run with identical inputs, `pluma cross` hits
the cache and only runs the cross-match step at near-zero cost.

Do not invoke with inputs for only one tool, or with tools pointed at
different product surfaces — convergence is only meaningful across tools
diagnosing the same `--product`.

## Prerequisites

- The `pluma` CLI on PATH, plus the sister tools it routes to
  (agent-researcher, funnel-researcher, integration-watcher). Install from a
  clone of <https://github.com/ivaylogb/pluma> (and the tool repos it
  orchestrates):
  ```bash
  pip install -e .
  export ANTHROPIC_API_KEY=sk-ant-...
  ```
- `ANTHROPIC_API_KEY` set — any tool that is **not** a cache hit spends model
  tokens.

## Inputs

`--product` and `--output-file` are required. Provide the input flags for **at
least two** tools, all describing the same product:

| Tool | Flags (both required for that tool) |
|---|---|
| funnel-researcher | `--funnel` + `--dropoff` |
| integration-watcher | `--traces` + `--cohort` |
| agent-researcher | `--eval-result` + `--target-agent` |

Optional passthrough: `--model`, `--max-tokens`, `--extra-file` (repeatable),
`--no-cache`, `--force`. Do not invoke unless at least two complete tool input
sets are present.

## Outputs

A markdown cross-tool report written to `--output-file`. `--output-file` is
required by the CLI; use `./pluma-cross.md` as the default name. After it
completes, read that file back and surface the correlation matrix and the
cross-tool findings.

## Invocation

Run the installed CLI directly through your shell:

```bash
pluma cross \
    --product ./product_artifacts \
    --funnel ./funnel.yaml \
    --dropoff ./dropoff_data.json \
    --traces ./traces.jsonl \
    --cohort ./cohort.yaml \
    --output-file ./pluma-cross.md
```

If `funnel-researcher` and `integration-watcher` were already run on these
exact inputs, this run is mostly cache hits — the convergence report comes
back at near-zero cost. Pass `--force` to re-run anyway, or `--no-cache` to
bypass the cache entirely. Then read `./pluma-cross.md` and present the
correlation matrix, the cross-tool findings, and each tool's unique findings.

## What this tool does not do

- It does not consume pre-generated finding files. `pluma cross` takes raw
  inputs and runs the tools (cache-backed).
- It does not run `apply` / `iterate`. Those are separate `pluma`
  subcommands.
- It does not correlate findings itself — the CLI does the matching.
- It does not decide which converged finding to act on. A human decides.
