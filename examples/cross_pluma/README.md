# Worked example: cross-tool report on the Pluma API fixture

This runs funnel-researcher and integration-watcher against the *same* product surface — the fictional agentic-API product in `fixtures/pluma_api/` (a symlink into funnel-researcher's read-only fixture) — and reports where their findings overlap. The funnel inputs come from funnel-researcher's `api_activation` example; the trace inputs from integration-watcher's `agent_platform` example. Both target the same product, which is the whole point: two independent diagnostic lenses, one surface.

## Running cross

```bash
pluma cross \
    --product fixtures/pluma_api \
    --funnel  ../funnel-researcher/examples/api_activation/funnel.yaml \
    --dropoff ../funnel-researcher/examples/api_activation/dropoff_data.json \
    --traces  ../integration-watcher/examples/agent_platform/traces.jsonl \
    --cohort  ../integration-watcher/examples/agent_platform/integration_cohort.yaml \
    --output-file outputs/pluma_cross_example.md
```

Cost: the sum of the two source tools — one funnel-researcher `diagnose` + one integration-watcher `watch`, ≈$1.50 against Opus 4.7, one time. Every subsequent run is **$0**: both legs hit `~/.pluma/cache/` and only the normalize + cross-match + render steps re-execute.

## The produced report

`report.md` in this directory is the actual run output. Correlation matrix:

| Tool | Layer 1 | Layer 2 | Layer 3 | Total |
|---|---|---|---|---|
| funnel-researcher | 0 | 1 | 2 | 3 |
| integration-watcher | 1 | 1 | 1 | 3 |

**4 cross-tool findings, 1 unique.**

- **Cross-match 1 — Mechanical (`docs/quickstart.md:23-30`):** funnel `H1` (quickstart shows `agents.run()` before establishing `agent_id` must be created — copy-paste-the-placeholder → 400) ↔ integration `F3` (dev_a8f3's `MISSING_AGENT_ID` cluster at session start, produced by the same `agt_xxxxxxxx` literal). This is the overlap the fixture was built to expose: the placeholder shows up as a *dropoff hypothesis* and a *trace pattern*, and both cite the same lines.
- **Cross-match 2 — Categorical (Layer 2, `sdk/agents.py`):** funnel `H2` (`MISSING_AGENT_ID` / `INVALID_AGENT_SCOPE` messages don't carry the next action) ↔ integration `F2` (dev_b2k7 dead-ended by `INVALID_TOOL_PARAMS` with no catalog entry). Same Layer, same surface, no shared line — caught categorically, not mechanically.
- **Cross-match 3 — Mechanical (`sdk/agents.py:28-65`):** funnel `H3` (`run.start` without `run.complete` — async/streaming confusion) ↔ integration `F2`.
- **Cross-match 4 — Categorical (Layer 3, `docs/quickstart.md`):** funnel `H3` ↔ integration `F3`.

Unique:

- **Findings unique to funnel-researcher: 0** — every funnel hypothesis matched something on the trace side.
- **Findings unique to integration-watcher: 1** — `F1` (Layer 1): the "stall after 5 runs" framing is itself a trace-framing artifact; the cohort actually contains three distinct failure shapes. Funnel data has no equivalent because it never saw the framing — this is the kind of finding only the trace lens produces, and the cross report keeps it instead of dropping it.

## Reproducing from cache (free)

After the one-time live run, the source outputs are cached at `~/.pluma/cache/funnel-researcher_<hash>.md` and `~/.pluma/cache/integration-watcher_<hash>.md`. Re-running the exact command above re-emits the report with both legs marked `cache hit` and zero API spend. `report.md` here was regenerated this way after a normalizer fix — same 4+1, no model tokens.

## What this report does NOT prove

- The match detector is **pairwise, not a clustering.** A finding can appear in more than one cross-match (here, funnel `H3` matches both integration `F2` mechanically and `F3` categorically; `F2` and `F3` each appear twice). The report surfaces every overlapping pair — it does not deduplicate them into themes. That's the operator's read.
- A categorical match (same Layer + shared file, no shared line) is a weaker signal than a mechanical one. It means "both tools are looking at the same surface for the same kind of reason," not "both tools found the same line." Treat the two kinds differently.
- Single-run diagnose/watch outputs are subject to model variance (see each sister tool's own example README). The cross report inherits that variance — it correlates whatever the two underlying runs produced; it does not stabilize them.
- Cross-tool overlap is evidence that two independent lenses agree on *where* to look. It is not a verified fix. Applying a finding's structured edit and re-measuring both the funnel and the trace cohort is the other half of the loop, and is out of scope here.
