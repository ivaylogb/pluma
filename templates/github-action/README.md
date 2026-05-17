# pluma-diagnose GitHub Action template

Runs Pluma diagnosis when an eval fails and posts findings to your PR or as
an issue.

This is a **template**, not a published composite action: you copy
`pluma-diagnose.yml` into your own repo's `.github/workflows/` and configure
secrets. It lives here, next to the CLI it invokes, so it stays in step with
Pluma's flags. Fork or customize it freely.

## What this does

When a Braintrust experiment completes (or you manually trigger via the
GitHub UI), this workflow:

1. Installs Pluma + the diagnostic tools it orchestrates
2. Pulls the failing experiment from Braintrust (live mode) or reads a
   pre-computed `failing_evals.json` (CI mode)
3. Skips early if the eval pass rate is at or above the threshold
4. Otherwise runs `pluma diagnose-agent` against the failing scenarios
5. Posts structured findings (with `file:line` citations and applyable
   edits) to the PR as a comment, or opens an Issue if no PR is associated,
   and uploads the diagnosis as a workflow artifact

## Installation

Copy `pluma-diagnose.yml` to your repo:

    mkdir -p .github/workflows
    curl -O https://raw.githubusercontent.com/ivaylogb/pluma/main/templates/github-action/pluma-diagnose.yml
    mv pluma-diagnose.yml .github/workflows/

Or download the file via the GitHub UI and place it in `.github/workflows/`.

The template installs Pluma from `main` (`pip install "pluma @
git+https://github.com/ivaylogb/pluma@main"`). For production use, pin that
line to a tag instead of `main` so a diagnosis run is reproducible.

## Required secrets

Configure in your repo's **Settings → Secrets and variables → Actions →
Secrets**:

- `ANTHROPIC_API_KEY` — always required; Pluma's diagnostic agent calls
  Claude.
- `BRAINTRUST_API_KEY` — required only for the live-experiment path
  (`repository_dispatch`, or `workflow_dispatch` with an experiment ID).
  Not needed when a pre-computed `failing_evals.json` is supplied via
  `workflow_call`.

## Triggers

The workflow supports three trigger modes:

- `repository_dispatch` (type `braintrust-experiment-completed`) — fired by
  an external webhook (e.g., a Braintrust experiment-completion webhook
  posting to the GitHub `repository_dispatch` endpoint). Useful for
  automatic diagnosis on every failing eval.
- `workflow_dispatch` — manual trigger via the GitHub UI Actions tab.
  Useful for ad-hoc diagnosis.
- `workflow_call` — reusable from other workflows in your repo (e.g., a CI
  workflow can call this after running evals and writing
  `failing_evals.json`).

## Configuration

### Trigger inputs

- `repository_dispatch` reads `client_payload.experiment_id` and
  `client_payload.pr_number`.
- `workflow_dispatch` accepts `experiment_id` (optional; overrides the
  dispatch payload) and `pr_number` (optional).
- `workflow_call` accepts `failing_evals_path` (required — path, relative
  to the repo, to a pre-computed `failing_evals.json`) and `pr_number`
  (optional).

Source resolution precedence: a `workflow_dispatch` input wins, then the
`repository_dispatch` payload, then a `workflow_call` `failing_evals_path`.
If no experiment ID and no `failing_evals_path` resolve, the run fails
fast with an error.

### Repository variables

Configure in **Settings → Secrets and variables → Actions → Variables**:

- `PLUMA_TARGET_AGENT_PATH` — path under the repo to the agent source that
  Pluma diagnoses. Default `./agent`.
- `PLUMA_PASS_RATE_THRESHOLD` — minimum acceptable eval pass rate. At or
  above this value, diagnosis is skipped (nothing to investigate); below
  it, diagnosis runs. Default `0.95`.

### Build failure on regression

When the pass rate is below the threshold, the final step exits non-zero
so the regression is a red CI signal the PR author actually sees. To run
in non-blocking advisory mode (post the diagnosis but keep the check
green), comment out the `exit 1` line in the last step of the workflow.

## What this does not do

- It does not apply edits silently. Findings are posted; a human decides
  which to apply.
- It does not re-run the failing eval. Pluma produces diagnoses; running
  the eval again is the user's decision.
- It does not modify the target agent's code. Edits are proposed as
  structured diffs in the posted comments; actually applying them is a
  separate human action.

## Smoke testing

This template ships untested against real GitHub infrastructure. Before
relying on it for production CI, smoke-test it on a sandbox repo with
`workflow_dispatch` + a test experiment ID.
