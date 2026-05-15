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

## Worked example

[`examples/cross_pluma/`](examples/cross_pluma/) is the canonical run: funnel-researcher + integration-watcher against the agentic-API fixture bundled at `fixtures/pluma_api/`. It surfaces 4 cross-tool findings — including the `agt_xxxxxxxx` quickstart placeholder, which appears as a dropoff hypothesis in funnel-researcher *and* a trace-pattern finding in integration-watcher, matched mechanically on `docs/quickstart.md:23-30` — plus 1 finding unique to integration-watcher. See [the example's README](examples/cross_pluma/README.md) for the breakdown and how to reproduce it for free from cache.

The fixture and inputs are bundled here as a snapshot for self-contained reproducibility. The canonical fixture lives in [funnel-researcher](https://github.com/ivaylogb/funnel-researcher); the trace inputs in [integration-watcher](https://github.com/ivaylogb/integration-watcher).

## How it works

Pluma imports the three sister tools as libraries and calls their Python API directly. agent-researcher still spawns its own eval subprocess internally, each tool is installed from its GitHub repo (`pyproject.toml` pins them via `git+https`).
Every generating run goes through an input-hash cache at `~/.pluma/cache/<tool>_<hash>.md`. The key covers file *contents* (not paths) and flag values: rename an input or move the working directory and the cache still hits; edit one byte of any input and it misses. `--force` re-runs on a hit; `--no-cache` bypasses entirely. This is what makes iterating on a `cross` report or re-running after a normalizer change cost $0.

Each tool emits a slightly different report (funnel-/agent-researcher call them "Hypotheses", integration-watcher "Findings"; section names and metadata differ). `normalize.py` parses each into one shape: Pluma uses **Finding** everywhere, preserves the source term in an `Original entity term:` metadata line, lifts the `(Layer N)` annotation into a structured field, and extracts `file:line` citations for the cross-tool matcher.

Pluma normalizes per-tool outputs into the agent-diagnosis-spec v0.1 Finding shape (see normalize.py for the parser; see [github.com/ivaylogb/agent-diagnosis-spec](https://github.com/ivaylogb/agent-diagnosis-spec) for the spec).

Exit codes mirror the tools: `0` success, `2` missing input / routing ambiguity, `3` parse or upstream-API failure, `4` not applyable, `5` empty/all-errored iterate. agent-researcher's `apply` adds `6` (edit application failed), `7` (re-eval failed, edits left on disk), `8` (catastrophic): Pluma propagates these unchanged.

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
