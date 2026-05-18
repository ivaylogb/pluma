# NOTE: This file diverges from the upstream bundle at
# _bundle_day1/runs_to_failing_evals.py.
#
# The bundle draft made six LangSmith API-shape assumptions. All six
# were checked against the published langsmith SDK / docs (May 2026)
# and all six were wrong. This file uses the verified real shapes:
#
#   1. Filter DSL — no `has_feedback()`; filters are `and(...)`-wrapped
#      `eq/neq/gt/.../has/search` expressions, and `is_root` is a
#      first-class list_runs parameter. The bundle's
#      "eq(is_root, true), has_feedback()" is not valid. We decide
#      pass/fail client-side after fetching feedback; a caller-supplied
#      filter string is passed through verbatim.
#   2. Descendants — there is no /runs/{id}/descendants endpoint. Child
#      runs are queried per level via list_runs(parent_run_id=...).
#      _walk_run_tree does a depth- and node-budget-bounded BFS.
#   3. Feedback — runs do not carry inline `feedback`. It is fetched
#      separately and in batches via list_feedback(run_ids=[...]).
#   4. Reference outputs — not on the run. They live on the Example the
#      run was evaluated against (run.reference_example_id ->
#      read_example -> example.outputs). Present in workflow A, absent
#      in workflow B.
#   5. Feedback keys — LangSmith does not standardize feedback key
#      names. No hardcoded ("correctness","overall","score") list;
#      the primary key is caller-supplied, with an any-failing-key
#      fallback.
#   6. agent_revision — LangSmith has no git-SHA convention. Auto-
#      resolution is removed; --agent-revision is the only way to set
#      it. Deliberate adapter difference from Braintrust.
#
# If re-syncing from the bundle, preserve these divergences. The
# committed tests in tests/test_langsmith_converter.py fail if any are
# reverted.

"""LangSmith runs → agent-researcher failing-eval input.

LangSmith's primary entity is a **run**: one agent execution captured
as a trace tree of parent + nested child runs (one per LLM/tool call).
Evaluations attach to runs as *feedback*, not as a scored row. The run
tree is the highest-leverage diagnostic input: it lets agent-researcher
localize a defect to a step of the agent's reasoning instead of reading
source alone.

Two workflows produce failing evals, exposed as two entry points that
share ~70% of their internals:

  - **Workflow A — Dataset-Experiment.** ``client.evaluate(...)`` ran a
    dataset of reference cases, producing an experiment (a tracing
    session) with a fixed scenario set. Reference outputs live on the
    dataset Example each run points at. ``runs_from_experiment``.

  - **Workflow B — Project-traced production.** Agent runs flow into a
    project as they happen; there is no experiment boundary. Feedback
    comes from online evaluators / human review. No reference outputs.
    ``runs_from_project``.

Both emit the FailingEvalContainer shape (agent-diagnosis-spec v0.2),
identical to the Braintrust adapter's output, so the downstream loader
and ``pluma diagnose-agent`` consume them unchanged.

Status: a structural sketch. The network shapes match the published
SDK/docs but have not been exercised against a live LangSmith
instance; the converter logic and the run-tree walker are covered by
synthetic fixtures and unit tests. Treat as v0.1 of this adapter.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Protocol

_UNKNOWN = "unknown"

DEFAULT_THRESHOLD = 1.0
DEFAULT_MAX_TREE_DEPTH = 4
DEFAULT_MAX_TOTAL_NODES = 50

# list_feedback(run_ids=[...]) is batched; this caps ids per request so
# a large failing set does not build one unbounded query string.
_FEEDBACK_BATCH = 100


class _Client(Protocol):
    """The slice of a LangSmith client this converter needs.

    ``langsmith_client.LangSmithClient`` implements it; tests pass a
    fake. Methods return plain dicts in the LangSmith REST shape.
    """

    def list_runs(
        self,
        *,
        project_id: str | None = ...,
        project_name: str | None = ...,
        is_root: bool | None = ...,
        parent_run_id: str | None = ...,
        trace_id: str | None = ...,
        filter: str | None = ...,
        limit: int | None = ...,
    ) -> Iterable[dict]: ...

    def list_feedback(self, *, run_ids: list[str]) -> Iterable[dict]: ...

    def read_example(self, example_id: str) -> dict: ...


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def _stringify(value: Any) -> str:
    """String passes through; anything else is compact-JSON encoded;
    None becomes the ``unknown`` sentinel (the schema requires a
    string, never null, for expected/predicted)."""
    if isinstance(value, str):
        return value
    if value is None:
        return _UNKNOWN
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _numeric(score: Any) -> float | None:
    """A real number (not bool) becomes float; everything else None."""
    if isinstance(score, bool):
        return None
    if isinstance(score, (int, float)):
        return float(score)
    return None


# --------------------------------------------------------------------------
# Feedback
# --------------------------------------------------------------------------


def _fetch_feedback_for_runs(
    run_ids: list[str], client: _Client
) -> dict[str, list[dict]]:
    """Batched feedback fetch, grouped by run_id.

    LangSmith feedback is not inline on the run; it is a separate
    resource. ``list_feedback`` accepts a sequence of run ids, so we
    issue one request per ``_FEEDBACK_BATCH`` ids rather than one per
    run.
    """
    grouped: dict[str, list[dict]] = {rid: [] for rid in run_ids}
    for start in range(0, len(run_ids), _FEEDBACK_BATCH):
        batch = run_ids[start : start + _FEEDBACK_BATCH]
        for fb in client.list_feedback(run_ids=batch):
            rid = str(fb.get("run_id"))
            grouped.setdefault(rid, []).append(fb)
    return grouped


def _select_primary_feedback(
    feedbacks: list[dict],
    primary_key: str | None,
    threshold: float,
) -> tuple[str | None, float | None]:
    """Resolve ``(scorer_name, numeric_score)`` for the record.

    With an explicit ``primary_key`` the matching feedback wins (its
    score may be None for a non-numeric evaluator). Without one, the
    primary is the first feedback whose numeric score is below
    ``threshold`` — the signal that made the run failing — falling back
    to the first feedback entry.
    """
    if primary_key is not None:
        for fb in feedbacks:
            if fb.get("key") == primary_key:
                return primary_key, _numeric(fb.get("score"))
        return primary_key, None
    for fb in feedbacks:
        s = _numeric(fb.get("score"))
        if s is not None and s < threshold:
            return fb.get("key"), s
    if feedbacks:
        first = feedbacks[0]
        return first.get("key"), _numeric(first.get("score"))
    return None, None


def _scorer_signature(
    feedbacks: list[dict],
    primary: str | None,
    threshold: float,
) -> dict[str, dict[str, Any]]:
    """Per-feedback-key ``{score, passed, is_primary}``.

    ``passed`` is ``score >= threshold`` for numeric feedback; a
    non-numeric or absent score is never "passed" (we cannot confirm
    it). The pattern across keys is itself diagnostic — the diagnostic
    agent reads which evaluators failed, not just the primary verdict.
    """
    sig: dict[str, dict[str, Any]] = {}
    for fb in feedbacks:
        key = fb.get("key") or "unnamed"
        score = _numeric(fb.get("score"))
        sig[key] = {
            "score": score,
            "passed": score is not None and score >= threshold,
            "is_primary": key == primary,
        }
    return sig


def _is_failing(
    feedbacks: list[dict],
    primary_key: str | None,
    threshold: float,
) -> bool:
    """Decide pass/fail client-side (LangSmith has no server-side
    "has failing feedback" filter).

    With ``primary_key``: the run fails if that key is absent (a run
    that cannot be confirmed passing is worth a look — mirrors the
    Braintrust adapter's missing-primary-scorer rule) or its numeric
    score is below ``threshold``. Without ``primary_key``: the run
    fails if *any* feedback key has a numeric score below ``threshold``;
    a run with no feedback at all is not a failure (no signal).
    """
    if primary_key is not None:
        for fb in feedbacks:
            if fb.get("key") == primary_key:
                s = _numeric(fb.get("score"))
                return s is not None and s < threshold
        return True  # primary key absent → cannot confirm passing
    return any(
        (s := _numeric(fb.get("score"))) is not None and s < threshold
        for fb in feedbacks
    )


# --------------------------------------------------------------------------
# Run-tree walker
# --------------------------------------------------------------------------


def _run_to_span(run: dict, parent_id: str | None) -> dict:
    """One run node as an opaque-to-the-spec span dict. Keys mirror the
    Braintrust adapter's span shape so downstream rendering is uniform,
    plus ``run_type``/``error`` which LangSmith carries natively."""
    return {
        "span_id": str(run.get("id")),
        "parent_span_id": parent_id,
        "name": run.get("name"),
        "run_type": run.get("run_type"),
        "input": run.get("inputs"),
        "output": run.get("outputs"),
        "error": run.get("error"),
        "start": run.get("start_time"),
        "end": run.get("end_time"),
    }


def _select_within_budget(
    order: list[str],
    nodes_by_id: dict[str, dict],
    depth_by_id: dict[str, int],
    parent_by_id: dict[str, str | None],
    budget: int,
) -> set[str]:
    """Pick which collected nodes to keep when over budget.

    Priority: error-bearing nodes first, and among those the *deepest*
    first (closest to where the failure surfaced); then non-error nodes
    shallow-first; ties broken by discovery order. Each accepted node
    drags in its not-yet-kept ancestors so every kept node's
    root→node path stays intact — sibling leaves are dropped before
    ancestor paths. The root is always kept.
    """
    root_id = order[0]
    kept: set[str] = {root_id}

    def has_error(i: str) -> bool:
        return bool(nodes_by_id[i].get("error"))

    pos = {i: n for n, i in enumerate(order)}
    ranked = sorted(
        (i for i in order if i != root_id),
        key=lambda i: (
            0 if has_error(i) else 1,
            -depth_by_id[i] if has_error(i) else depth_by_id[i],
            pos[i],
        ),
    )
    for i in ranked:
        if len(kept) >= budget:
            break
        path: list[str] = []
        j: str | None = i
        while j is not None and j not in kept:
            path.append(j)
            j = parent_by_id.get(j)
        if path and len(kept) + len(path) <= budget:
            kept.update(path)
    return kept


def _walk_run_tree(
    root_run: dict,
    client: _Client,
    max_depth: int = DEFAULT_MAX_TREE_DEPTH,
    max_total_nodes: int = DEFAULT_MAX_TOTAL_NODES,
) -> list[dict]:
    """Walk a run's descendant tree breadth-first, capped at
    ``max_total_nodes`` total across the whole subtree (root = depth 0,
    bounded by ``max_depth``).

    There is no single descendants endpoint; children are queried per
    level via ``list_runs(parent_run_id=...)`` — O(tree-size) calls,
    bounded by ``max_depth`` (the per-level fan-out is unbounded; see
    the README's API-rate note). All nodes within ``max_depth`` are
    collected, then — only if over budget — ``_select_within_budget``
    keeps root→error-leaf paths intact and drops sibling leaves first;
    a truncation marker records the count dropped.
    """
    root_id = str(root_run.get("id"))
    nodes_by_id: dict[str, dict] = {root_id: root_run}
    depth_by_id: dict[str, int] = {root_id: 0}
    parent_by_id: dict[str, str | None] = {root_id: None}
    order: list[str] = [root_id]

    frontier = [root_run]
    depth = 0
    while frontier and depth < max_depth:
        next_frontier: list[dict] = []
        for run in frontier:
            rid = str(run.get("id"))
            for child in client.list_runs(parent_run_id=rid):
                cid = str(child.get("id"))
                if cid in nodes_by_id:
                    continue
                nodes_by_id[cid] = child
                depth_by_id[cid] = depth + 1
                parent_by_id[cid] = rid
                order.append(cid)
                next_frontier.append(child)
        depth += 1
        frontier = next_frontier

    if len(nodes_by_id) <= max_total_nodes:
        kept_ids = order
    else:
        kept = _select_within_budget(
            order, nodes_by_id, depth_by_id, parent_by_id, max_total_nodes
        )
        kept_ids = [i for i in order if i in kept]  # keep BFS order

    spans = [_run_to_span(nodes_by_id[i], parent_by_id[i]) for i in kept_ids]
    dropped = len(nodes_by_id) - len(kept_ids)
    if dropped > 0:
        spans.append(
            {
                "_truncated": True,
                "_dropped": dropped,
                "_max_nodes": max_total_nodes,
            }
        )
    return spans


# --------------------------------------------------------------------------
# Run → FailingEval record
# --------------------------------------------------------------------------


def _reference_outputs(
    run: dict, client: _Client, cache: dict[str, dict | None]
) -> Any:
    """Workflow A: reference outputs live on the dataset Example the
    run was evaluated against, reached through
    ``run.reference_example_id``. Cached because reruns of the same
    dataset reuse example ids. A failed example fetch degrades to no
    reference, never blocks diagnosis."""
    ex_id = run.get("reference_example_id")
    if not ex_id:
        return None
    ex_id = str(ex_id)
    if ex_id not in cache:
        try:
            cache[ex_id] = client.read_example(ex_id)
        except Exception:
            cache[ex_id] = None
    example = cache[ex_id]
    if not example:
        return None
    return example.get("outputs")


def _run_to_failing_eval(
    run: dict,
    *,
    scorer: str | None,
    score: float | None,
    signature: dict[str, dict[str, Any]],
    spans: list[dict] | None,
    expected_value: Any,
    workflow: str,
    experiment_id: str,
    experiment_name: str,
    project_name: str,
    agent_revision: str | None,
    threshold: float,
) -> dict:
    """Build one FailingEval record (agent-diagnosis-spec v0.2). The
    primary scorer/score and the per-key signature are resolved by the
    caller (which holds the real primary_feedback_key)."""
    run_id = str(run.get("id") or _UNKNOWN)
    expected = _stringify(expected_value)
    predicted = _stringify(run.get("outputs"))
    # Workflow A keys the scenario on the dataset example (stable across
    # experiment reruns); workflow B has no example, so the run id is
    # the only stable handle.
    scenario_id = str(
        run.get("reference_example_id") or run_id
        if workflow == "experiment"
        else run_id
    )

    metadata: dict[str, Any] = {
        "run_id": run_id,
        "trace_id": run.get("trace_id"),
        "project_name": project_name,
        "experiment_id": experiment_id,
        "experiment_name": experiment_name,
        "workflow": workflow,
    }
    if agent_revision is not None:
        # Schema types metadata.agent_revision as a string — only set it
        # when we actually have one (never write null here).
        metadata["agent_revision"] = agent_revision

    record: dict[str, Any] = {
        "scenario_id": scenario_id,
        "expected": expected,
        "predicted": predicted,
        "predicted_confidence": score,
        "passed": False,
        "score": score,
        "scorer": scorer,
        "scorer_signature": signature,
        "spans": spans,
        "input": run.get("inputs"),
        "output": run.get("outputs"),
        "notes": (
            f"LangSmith {workflow} run {run_id} in project "
            f"{project_name!r}: scorer {scorer!r} scored {score} "
            f"(threshold {threshold}). expected={expected!r} "
            f"predicted={predicted!r}."
        ),
        "metadata": metadata,
    }
    created = run.get("start_time")
    if created:
        record["created"] = created
    return record


def _container(
    *,
    workflow: str,
    experiment_id: str,
    experiment_name: str,
    project_name: str,
    agent_revision: str | None,
    threshold: float,
    total_seen: int,
    failing: list[dict],
) -> dict:
    """The FailingEvalContainer envelope.

    LangSmith has no cheap experiment-wide pass count; ``total`` is the
    runs the filter walked (a lower bound, like the Braintrust live
    path reports). ``passed`` / ``pass_rate`` follow from it so the
    audit trail survives the filter.
    """
    failing.sort(key=lambda r: str(r.get("created") or ""))
    passed = max(0, total_seen - len(failing))
    return {
        "experiment_id": str(experiment_id),
        "experiment_name": str(experiment_name),
        "project_name": str(project_name),
        "agent_revision": agent_revision,
        "total": total_seen,
        "passed": passed,
        "pass_rate": round(passed / total_seen, 4) if total_seen else 0.0,
        "threshold": threshold,
        "meets_threshold": len(failing) == 0,
        "results": failing,
    }


# --------------------------------------------------------------------------
# Shared core
# --------------------------------------------------------------------------


def _convert_runs(
    runs: list[dict],
    *,
    client: _Client,
    workflow: str,
    experiment_id: str,
    experiment_name: str,
    project_name: str,
    primary_feedback_key: str | None,
    threshold: float,
    reference_feedback_key: str | None,
    max_tree_depth: int,
    max_total_nodes: int,
    agent_revision: str | None,
) -> dict:
    """Shared by both entry points: feedback fetch → failing filter →
    tree walk → record build → container."""
    runs = list(runs)
    total_seen = len(runs)
    if not runs:
        return _container(
            workflow=workflow,
            experiment_id=experiment_id,
            experiment_name=experiment_name,
            project_name=project_name,
            agent_revision=agent_revision,
            threshold=threshold,
            total_seen=0,
            failing=[],
        )

    run_ids = [str(r.get("id")) for r in runs]
    feedback_by_run = _fetch_feedback_for_runs(run_ids, client)

    example_cache: dict[str, dict | None] = {}
    failing: list[dict] = []
    for run in runs:
        rid = str(run.get("id"))
        fbs = feedback_by_run.get(rid, [])
        if not _is_failing(fbs, primary_feedback_key, threshold):
            continue

        if workflow == "experiment":
            expected_value = _reference_outputs(run, client, example_cache)
        else:
            # Workflow B has no Example. expected is the sentinel unless
            # a caller-named reference feedback key carries a value.
            expected_value = None
            if reference_feedback_key is not None:
                for fb in fbs:
                    if fb.get("key") == reference_feedback_key:
                        expected_value = fb.get("value")
                        break

        try:
            spans: list[dict] | None = _walk_run_tree(
                run, client, max_tree_depth, max_total_nodes
            )
        except Exception:
            # Trees are nice-to-have; a failed walk must not block
            # diagnosis. Conversion proceeds without spans.
            spans = None

        scorer, score = _select_primary_feedback(
            fbs, primary_feedback_key, threshold
        )
        rec = _run_to_failing_eval(
            run,
            scorer=scorer,
            score=score,
            signature=_scorer_signature(fbs, scorer, threshold),
            spans=spans,
            expected_value=expected_value,
            workflow=workflow,
            experiment_id=experiment_id,
            experiment_name=experiment_name,
            project_name=project_name,
            agent_revision=agent_revision,
            threshold=threshold,
        )
        failing.append(rec)

    return _container(
        workflow=workflow,
        experiment_id=experiment_id,
        experiment_name=experiment_name,
        project_name=project_name,
        agent_revision=agent_revision,
        threshold=threshold,
        total_seen=total_seen,
        failing=failing,
    )


# --------------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------------


def runs_from_experiment(
    experiment_id: str,
    *,
    primary_feedback_key: str | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    max_tree_depth: int = DEFAULT_MAX_TREE_DEPTH,
    max_total_nodes: int = DEFAULT_MAX_TOTAL_NODES,
    agent_revision: str | None = None,
    client: _Client | None = None,
) -> dict:
    """Workflow A — Dataset-Experiment.

    ``experiment_id`` is the LangSmith tracing-session id created by
    ``client.evaluate(...)``. Its root runs each point at a dataset
    Example carrying the reference outputs. Returns the
    FailingEvalContainer the agent-researcher loader consumes.
    """
    if client is None:  # pragma: no cover - import kept lazy / no network in tests
        from .langsmith_client import LangSmithClient

        client = LangSmithClient()

    runs = list(
        client.list_runs(project_id=experiment_id, is_root=True)
    )
    return _convert_runs(
        runs,
        client=client,
        workflow="experiment",
        experiment_id=experiment_id,
        experiment_name=experiment_id,
        project_name=experiment_id,
        primary_feedback_key=primary_feedback_key,
        threshold=threshold,
        reference_feedback_key=None,
        max_tree_depth=max_tree_depth,
        max_total_nodes=max_total_nodes,
        agent_revision=agent_revision,
    )


def runs_from_project(
    project_name: str,
    *,
    filter_expression: str | None = None,
    primary_feedback_key: str | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    reference_feedback_key: str | None = None,
    max_tree_depth: int = DEFAULT_MAX_TREE_DEPTH,
    max_total_nodes: int = DEFAULT_MAX_TOTAL_NODES,
    agent_revision: str | None = None,
    client: _Client | None = None,
) -> dict:
    """Workflow B — Project-traced production.

    Walks root runs in ``project_name`` (optionally narrowed by a
    LangSmith ``filter_expression``, passed through verbatim — e.g.
    ``and(gt(start_time, "2026-05-01T00:00:00Z"), eq(feedback_key,
    "correctness"))``). No dataset Example, so ``expected`` is the
    ``unknown`` sentinel unless ``reference_feedback_key`` names a
    feedback entry whose value is the reference.
    """
    if client is None:  # pragma: no cover - import kept lazy / no network in tests
        from .langsmith_client import LangSmithClient

        client = LangSmithClient()

    runs = list(
        client.list_runs(
            project_name=project_name,
            is_root=True,
            filter=filter_expression,
        )
    )
    return _convert_runs(
        runs,
        client=client,
        workflow="project",
        experiment_id=project_name,
        experiment_name=project_name,
        project_name=project_name,
        primary_feedback_key=primary_feedback_key,
        threshold=threshold,
        reference_feedback_key=reference_feedback_key,
        max_tree_depth=max_tree_depth,
        max_total_nodes=max_total_nodes,
        agent_revision=agent_revision,
    )


__all__ = [
    "DEFAULT_THRESHOLD",
    "DEFAULT_MAX_TREE_DEPTH",
    "DEFAULT_MAX_TOTAL_NODES",
    "runs_from_experiment",
    "runs_from_project",
]
