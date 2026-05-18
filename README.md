# pluma

One CLI over three failure-diagnosis tools for developer-API products:
[funnel-researcher](https://github.com/ivaylogb/funnel-researcher) (why developers drop off a funnel step), 
[agent-researcher](https://github.com/ivaylogb/agent-researcher) (why an agent fails an eval), 
[integration-watcher](https://github.com/ivaylogb/integration-watcher) (what patterns show up in a cohort's integration traces). 

Pluma routes a single command to the right tool, caches runs so iteration is free, and runs two or more tools against the *same* product surface and reports where their findings overlap.

## What it does

You have a developer-API product that's leaking activation. You have funnel/dropoff data, you have integration traces from a cohort, maybe you have an agent eval. 
Each sister tool reads one of those plus the product's artifacts (docs, SDK source, error catalog) and produces evidence-grounded, `file:line`-cited findings. 

```bash
pluma cross \
    --product fixtures/pluma_api \
    --funnel  examples/cross_pluma/inputs/funnel.yaml \
    --dropoff examples/cross_pluma/inputs/dropoff_data.json \
    --traces  examples/cross_pluma/inputs/traces.jsonl \
    --cohort  examples/cross_pluma/inputs/integration_cohort.yaml \
    --output-file outputs/pluma_cross_example.md
```

That runs funnel-researcher and integration-watcher against the same fixture, normalizes both reports, and emits one report with a correlation matrix, the findings that show up in *both* tools, and the findings unique to each.

## Worked examples

- **[examples/cross_pluma/](examples/cross_pluma/)** — fictional fixture demonstrating the cross-tool report. Use this to see how Pluma's machinery composes; the example's README walks the 4 cross-tool findings and how to reproduce them from cache.

- **[examples/stripe/](examples/stripe/)** — Stripe Connect onboarding diagnosed against the real product surface (real docs, real SDK source) with public-signal-grounded synthetic cohort data. Two diagnostic lenses converging on the silent-200 gate. The credibility test of the methodology on a real production system.

## Subcommands

| Subcommand | Routes to | Purpose |
|---|---|---|
| `diagnose-funnel` | funnel-researcher `diagnose` | funnel-step dropoff → hypotheses |
| `diagnose-agent` | agent-researcher `diagnose` | failing agent eval → hypotheses |
| `watch` | integration-watcher `watch` | cohort traces → findings |
| `diagnose` | funnel- or agent-researcher only (traces use `watch`) | picked from the flags |
| `apply` | the report's origin tool | apply one finding's structured edits |
| `iterate` | the report's origin tool | apply every applyable finding, side-by-side |
| `cross` | ≥2 tools | the cross-tool report |

`apply`/`iterate` read the `Origin:` tag out of a Pluma report and dispatch to the tool that produced it — you don't restate which tool. 
They are mechanical (no model tokens); only `diagnose*`/`watch`/`cross` spend.

## Intent routing

**Explicit** — `diagnose-funnel`, `diagnose-agent`, `watch` map 1:1 to a tool.

**Inferred** — `pluma diagnose` sniffs the flags:

- `--funnel --dropoff --product` → funnel-researcher
- `--eval-result --target-agent` → agent-researcher

`diagnose` and `watch` are kept distinct: `watch` (integration-watcher's verb) is never folded into inferred `diagnose`. If you pass watch-shaped flags to `pluma diagnose`, it exits 2 and names `pluma watch` instead of guessing. Ambiguous flag-sets (matching two tools) also exit 2 and name the explicit subcommands rather than picking one.

## Cross-tool report

 `pluma cross` needs inputs for at least two tools, all pointing at the same `--product`. It runs each applicable tool (through the cache), normalizes every output into a unified **Finding** shape, and detects overlap two ways:

- **Mechanical** — two findings cite the same `file:line` (ranges overlap).
- **Categorical** — two findings share a Layer *and* a product surface (a cited file), without a line-level hit.

The report leads with a correlation matrix (tool × Layer → finding count), then a *Cross-tool findings* section (every overlap, both findings' full bodies, the match reason), then *Findings unique to <tool>* — one section per tool. Mechanical matches win over categorical when both apply.

## How it works

Pluma imports the three sister tools as libraries and calls their Python API directly. agent-researcher still spawns its own eval subprocess internally, each tool is installed from its GitHub repo (`pyproject.toml` pins them via `git+https`).
Every generating run goes through an input-hash cache at `~/.pluma/cache/<tool>_<hash>.md`. The key covers file *contents* (not paths) and flag values: rename an input or move the working directory and the cache still hits; edit one byte of any input and it misses. `--force` re-runs on a hit; `--no-cache` bypasses entirely. This is what makes iterating on a `cross` report or re-running after a normalizer change cost $0.

Each tool emits a slightly different report (funnel-/agent-researcher call them "Hypotheses", integration-watcher "Findings"; section names and metadata differ). `normalize.py` parses each into one shape: Pluma uses **Finding** everywhere, preserves the source term in an `Original entity term:` metadata line, lifts the `(Layer N)` annotation into a structured field, and extracts `file:line` citations for the cross-tool matcher.

Pluma normalizes per-tool outputs into the agent-diagnosis-spec v0.1 Finding shape (see normalize.py for the parser; see [github.com/ivaylogb/agent-diagnosis-spec](https://github.com/ivaylogb/agent-diagnosis-spec) for the spec).

Exit codes mirror the tools: `0` success, `2` missing input / routing ambiguity, `3` parse or upstream-API failure, `4` not applyable, `5` empty/all-errored iterate. agent-researcher's `apply` adds `6` (edit application failed), `7` (re-eval failed, edits left on disk), `8` (catastrophic): Pluma propagates these unchanged.

## Integrations

Connect Pluma to existing analytics platforms and data sources.

- **[PostHog](src/pluma/integrations/posthog/)** — convert PostHog event exports into integration-watcher trace input. Field-mapping documented, deterministic converter, golden fixture for diff testing. Roadmap covers a live API client, funnel converter, and writing Pluma findings back as PostHog annotations.

- **[OpenTelemetry](src/pluma/integrations/otel/)** — convert OpenTelemetry trace exports (OTLP/JSON, Jaeger, bare span arrays) into integration-watcher trace input. Format auto-detected; pre-1.21 and post-1.21 HTTP semantic-convention attribute names both handled. One adapter covers anything that exports OTel — Datadog, Honeycomb, Tempo, Jaeger, Grafana Cloud, X-Ray, Lightstep, Splunk. Field-mapping documented, deterministic converter, golden fixture for diff testing.

- **[Braintrust](src/pluma/integrations/braintrust/)** — convert Braintrust experiment exports into agent-researcher failing-eval input. Field-mapping documented, deterministic converter, golden fixture for diff testing. Filters by primary scorer threshold; preserves the full Braintrust row for diagnostic context. A Braintrust experiment can also be diagnosed directly: `pluma diagnose-agent --target-agent <dir> --braintrust-experiment-id <id> --output-file <md>` (or `--braintrust-project <name> --latest`) pulls it live via the API, converts it, and runs agent-researcher in one command.

- **[LangSmith](src/pluma/integrations/langsmith/)** — convert LangSmith runs into agent-researcher failing-eval input, across both LangSmith workflows: Dataset-Experiment (`--langsmith-experiment-id`, reference outputs from the dataset Example) and project-traced production (`--langsmith-project [--filter]`, no dataset). Feedback is fetched as a separate batched resource and pass/fail decided client-side against a caller-supplied `--primary-feedback-key` (LangSmith does not standardize key names); the run tree is walked per level with a global span-node budget that preserves root→error paths. `agent_revision` is never auto-resolved (LangSmith has no SHA convention — deliberate difference from Braintrust). Field-mapping documented, deterministic converter, golden fixtures for both workflows validated against agent-diagnosis-spec v0.2. Ships as a structural sketch — network shapes match the published SDK/docs but are untested against a live instance; smoke-test before relying on it.

- **[GitHub Action template](templates/github-action/)** — drop-in workflow for running Pluma diagnosis on PRs or via webhook. Triggers on Braintrust experiment completion (`repository_dispatch`), manual `workflow_dispatch`, or `workflow_call` from a CI job; posts findings to the PR as a comment or opens an issue. Ships untested against real CI infrastructure — smoke test on a sandbox repo before relying on it.

## Install

```bash
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e .          # pulls the three sister tools via git+https
export ANTHROPIC_API_KEY=sk-ant-...
pluma --help
```

For local development against working copies of the sister tools, install them editable after `pip install --no-deps -e .`:

```bash
pip install -e ../agent_researcher -e ../funnel-researcher -e ../integration-watcher
```

## Usage

```bash
# explicit
pluma diagnose-funnel --funnel f.yaml --dropoff d.json --product DIR --output-file out.md

# inferred — same effect, tool picked from the flags
pluma diagnose --funnel f.yaml --dropoff d.json --product DIR --output-file out.md

# integration traces
pluma watch --traces t.jsonl --cohort c.yaml --product DIR --output-file out.md

# apply one finding from any Pluma report (origin auto-detected)
pluma apply --report out.md --hypothesis-id H1 --product DIR --output-file delta.md

# cross-tool — the point of the whole thing
pluma cross --product DIR --funnel f.yaml --dropoff d.json \
            --traces t.jsonl --cohort c.yaml --output-file cross.md
```

Add `--no-cache` to force a live run, `--force` to re-run despite a cache hit.

## Tests

```bash
python -m pytest
```

114 tests, no API calls — every sister-tool entrypoint is monkey-patched, so the suite runs in <1s and costs nothing. Coverage: runners (each tool, incl. upstream `anthropic.APIError` handling), the input-hash cache (hit/miss/force/invalidation), the normalizer (per-tool parsing, trailing-section boundaries, citation extraction), the router (explicit/inferred/ambiguous/origin-tag), cross-tool match detection (mechanical/categorical/unique/correlation), and the CLI surface for every subcommand.

## License

MIT.
