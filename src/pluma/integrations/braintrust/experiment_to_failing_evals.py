"""Braintrust experiment results → agent-researcher failing-eval input.

A Braintrust experiment export is one JSON object whose ``results`` array
holds a scored row per scenario (``id``, ``input``, ``expected``,
``output``, a ``scores`` map, optional ``metadata``, a ``created``
timestamp, and — when the eval was instrumented — a ``spans`` tree
capturing the agent's actual execution). agent-researcher's
``load_eval_result`` reads a single JSON object — a summary header plus
a ``results`` array — and types against six per-record fields
(``scenario_id``, ``expected``, ``predicted``, ``predicted_confidence``,
``notes``, ``passed``), keeping the whole record as ``raw`` for the
diagnostic prompt.

This converter:

  - keeps rows whose primary scorer is below ``score_threshold`` (or
    missing entirely — a row that can't be confirmed passing is worth
    a look);
  - overlays the six recognized fields onto a copy of the row, so every
    original field rides along untouched;
  - attaches a ``scorer_signature`` showing per-scorer pass/fail, so the
    diagnostic agent sees *which* scorers failed rather than only that
    the primary one did — the scorer pattern is itself diagnostic
    signal (factuality-but-not-exact-match ≠ exact-match-but-not-
    factuality);
  - preserves the ``spans`` tree on each emitted record — the agent's
    actual execution trace is the single highest-leverage diagnostic
    input Braintrust supplies. Without it, agent-researcher diagnoses
    by reading source alone; with it, it can localize a defect to the
    specific step of the agent's reasoning;
  - threads through an optional ``agent_revision`` (e.g. a git SHA) so
    a downstream diagnoser can pin the target-agent source to the
    revision that actually produced the experiment, instead of
    diagnosing against drifted code;
  - supports continuous scorers via an optional ``score_band`` (min,
    max) — useful for calibration-style scorers where both
    under-confidence and over-confidence are failures.

The full field map lives in this directory's README.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

_UNKNOWN = "unknown"

# Maximum number of spans we serialize per row by default. A
# multi-agent run can produce hundreds of nested spans; sending all of
# them blows the diagnostic prompt budget for no marginal benefit. The
# default keeps the top 50 in trace-tree order, which empirically
# covers the failure-producing call for the cases we've seen. Override
# with ``max_spans=None`` to disable the cap.
DEFAULT_MAX_SPANS = 50


@dataclass(frozen=True)
class ScoreBand:
    """A continuous-scorer pass condition.

    A row passes when ``min_score <= score <= max_score``. The common
    case (anything not perfect is failing) is the default
    ``ScoreBand(1.0, 1.0)`` — equivalent to a strict threshold of 1.0.
    For calibration scorers, ``ScoreBand(0.4, 0.8)`` rejects both
    under- and over-confident rows.
    """

    min_score: float = 1.0
    max_score: float = 1.0

    def contains(self, score: Any) -> bool:
        if score is None or not isinstance(score, (int, float)):
            return False
        return self.min_score <= float(score) <= self.max_score


def _stringify(value: Any) -> str:
    """A string is returned as-is; anything else is compact-JSON encoded.

    Routing/classification labels are already strings, so the common
    case is loss-free; structured expected/output values stay faithful.
    """
    if isinstance(value, str):
        return value
    if value is None:
        return _UNKNOWN
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _select_scorer(scores: dict[str, Any], primary_scorer: str | None) -> str | None:
    """The explicit primary scorer if given, else the first scorer in
    the row's ``scores`` object (insertion order, as Braintrust emits
    it).
    """
    if primary_scorer is not None:
        return primary_scorer
    return next(iter(scores), None)


def _scorer_signature(
    scores: dict[str, Any],
    band: ScoreBand,
    primary_scorer: str | None,
) -> dict[str, dict[str, Any]]:
    """Per-scorer pass/fail signature for the row.

    For each scorer present in the row's ``scores`` object, emit
    ``{score: float|None, passed: bool, is_primary: bool}``. ``passed``
    is judged against the band only for the primary scorer; for
    non-primary scorers, ``passed`` is ``True`` iff score is present
    and ``>= band.min_score`` (a softer floor — we don't want a
    calibration scorer to mark a row "passed" because it under-scored
    in band).

    The diagnostic agent reads this to understand the scorer pattern:
    "fails factuality, passes exact_match" is a different bug than
    "fails exact_match, passes factuality".
    """
    sig: dict[str, dict[str, Any]] = {}
    primary = primary_scorer or _select_scorer(scores, None)
    for name, score in scores.items():
        if name == primary:
            passed = band.contains(score)
        else:
            passed = (
                isinstance(score, (int, float))
                and float(score) >= band.min_score
            )
        sig[name] = {
            "score": score,
            "passed": passed,
            "is_primary": name == primary,
        }
    return sig


def _trim_spans(
    spans: Any,
    max_spans: int | None,
) -> Any:
    """Trim a spans tree to at most ``max_spans`` entries in
    depth-first order, preserving structure.

    Braintrust spans are typically a list of nested dicts with
    ``span_id``, ``parent_span_id``, ``name``, ``input``, ``output``,
    ``start``, ``end``, and arbitrary metadata. We walk depth-first
    and stop after ``max_spans`` entries. The cap exists to keep the
    diagnostic prompt bounded; ``max_spans=None`` disables it.

    Non-list ``spans`` (e.g. a tree-shaped dict) is returned as-is —
    we only know how to bound flat lists.
    """
    if spans is None or max_spans is None or not isinstance(spans, list):
        return spans
    if len(spans) <= max_spans:
        return spans
    return spans[:max_spans] + [
        {"_truncated": True, "_dropped": len(spans) - max_spans}
    ]


def _row_to_failing_eval(
    row: dict[str, Any],
    *,
    scorer: str | None,
    score: Any,
    band: ScoreBand,
    experiment_id: str,
    experiment_name: str,
    project_name: str,
    agent_revision: str | None,
    max_spans: int | None,
    scorer_signature: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Overlay agent-researcher's recognized fields onto a copy of the
    Braintrust row so nothing the platform supplied is dropped.

    Adds ``scorer_signature`` and ``spans`` (trimmed) onto the record,
    plus the experiment/revision lineage in ``metadata``.
    """
    record: dict[str, Any] = dict(row)
    row_id = str(row.get("id") or _UNKNOWN)
    expected = _stringify(row.get("expected"))
    predicted = _stringify(row.get("output"))

    record["scenario_id"] = row_id
    record["expected"] = expected
    record["predicted"] = predicted
    record["predicted_confidence"] = score
    record["passed"] = False
    record["score"] = score
    record["scorer"] = scorer
    record["scorer_signature"] = scorer_signature
    record["spans"] = _trim_spans(row.get("spans"), max_spans)
    record["notes"] = (
        f"Braintrust scorer {scorer!r} scored {score} (band "
        f"[{band.min_score}, {band.max_score}]). "
        f"expected={expected!r} output={predicted!r}. "
        f"experiment {experiment_name!r} ({experiment_id}), "
        f"row {row_id}."
    )

    metadata = {
        **(row.get("metadata") or {}),
        "experiment_id": experiment_id,
        "experiment_name": experiment_name,
        "project_name": project_name,
        "row_id": row_id,
    }
    if agent_revision is not None:
        metadata["agent_revision"] = agent_revision
    record["metadata"] = metadata
    return record


def experiment_to_failing_evals(
    experiment: dict,
    score_threshold: float = 1.0,
    primary_scorer: str | None = None,
    *,
    score_band: ScoreBand | None = None,
    agent_revision: str | None = None,
    max_spans: int | None = DEFAULT_MAX_SPANS,
) -> dict:
    """Extract failing scenarios from a Braintrust experiment.

    A row passes when its primary scorer's score is present and falls
    inside ``score_band`` (default: ``[1.0, 1.0]``, equivalent to the
    historical "anything not perfect is failing" threshold). Rows
    missing the primary scorer are emitted as failures, not silently
    dropped — a row that can't be confirmed passing is worth a look.

    ``score_threshold`` is kept as a positional argument for backward
    compatibility; when ``score_band`` is not given, it is interpreted
    as ``ScoreBand(score_threshold, max=1.0 or higher)``. Pass
    ``score_band`` explicitly when you need a non-strict upper bound
    or a continuous lower bound below 1.0.

    Returns the single JSON object ``agent_researcher.eval_analyzer.
    load_eval_result`` expects. The summary counts cover the whole
    experiment, not just the failures, so the audit trail
    (total / passed / pass_rate) survives the filter.
    """
    if score_band is None:
        # Backward-compat: score_threshold becomes the band floor;
        # the ceiling stays at 1.0 (or threshold, if > 1, for unusual
        # scorers that exceed 1).
        score_band = ScoreBand(
            min_score=score_threshold,
            max_score=max(score_threshold, 1.0),
        )

    rows: list[dict] = list(experiment.get("results") or [])
    experiment_id = str(experiment.get("experiment_id") or _UNKNOWN)
    experiment_name = str(experiment.get("experiment_name") or _UNKNOWN)
    project_name = str(experiment.get("project_name") or _UNKNOWN)

    # If the experiment ships an agent_revision in its metadata, use it
    # unless the caller overrode it. This lets a CI run tag the
    # experiment with the commit SHA and have the downstream diagnoser
    # automatically pin to that revision.
    resolved_revision = agent_revision
    if resolved_revision is None:
        exp_meta = experiment.get("metadata") or {}
        resolved_revision = exp_meta.get("agent_revision") or exp_meta.get(
            "git_sha"
        )

    failing: list[dict] = []
    for row in rows:
        scores = row.get("scores") or {}
        scorer = _select_scorer(scores, primary_scorer)
        score = scores.get(scorer) if scorer is not None else None
        if score_band.contains(score):
            continue
        sig = _scorer_signature(scores, score_band, primary_scorer)
        failing.append(
            _row_to_failing_eval(
                row,
                scorer=scorer,
                score=score,
                band=score_band,
                experiment_id=experiment_id,
                experiment_name=experiment_name,
                project_name=project_name,
                agent_revision=resolved_revision,
                max_spans=max_spans,
                scorer_signature=sig,
            )
        )

    failing.sort(key=lambda r: str(r.get("created") or ""))

    total = len(rows)
    passed = total - len(failing)
    pass_rate = round(passed / total, 4) if total else 0.0
    return {
        "experiment_id": experiment_id,
        "experiment_name": experiment_name,
        "project_name": project_name,
        "agent_revision": resolved_revision,
        "total": total,
        "passed": passed,
        "pass_rate": pass_rate,
        "score_band": {
            "min": score_band.min_score,
            "max": score_band.max_score,
        },
        # Kept for back-compat with the v0.1 schema; equal to band.min.
        "threshold": score_band.min_score,
        "meets_threshold": len(failing) == 0,
        "results": failing,
    }


# --------------------------------------------------------------------------
# Cluster pre-pass (optional)
# --------------------------------------------------------------------------
#
# Most experiments have either one systemic failure (one mechanism,
# many rows manifesting it) or scattershot noise. Diagnosing 30
# independent rows when there is one root cause wastes 29 model calls.
# This pre-pass groups failing rows by their scorer signature and
# expected/predicted shape, then emits one representative per cluster
# with ``cluster_size`` attached. The diagnostic agent then sees
# "this is 18 of 23 failures" as load-bearing context.
#
# Kept as a separate function rather than wired into
# ``experiment_to_failing_evals`` because clustering is a *diagnostic*
# decision, not a *conversion* decision — operators may want all rows
# for some workflows.

def cluster_failing_rows(
    container: dict,
    representative: str = "first",
) -> dict:
    """Cluster a converted failing-evals container by failure shape.

    Two rows are in the same cluster when their scorer signature
    (which scorers passed/failed) and their (expected, predicted) pair
    match. The cluster representative is either the first row in the
    cluster by ``created`` order (``representative="first"``) or the
    row with the lowest primary-scorer score (``"worst"``).

    Emits the same container shape with ``results`` replaced by one
    record per cluster, each carrying ``cluster_size`` and
    ``cluster_member_ids`` so the audit trail is preserved.
    """
    results = list(container.get("results") or [])
    clusters: dict[tuple, list[dict]] = {}
    for row in results:
        sig = row.get("scorer_signature") or {}
        # Build a stable, hashable signature key.
        sig_key = tuple(
            sorted(
                (name, bool(entry.get("passed")))
                for name, entry in sig.items()
            )
        )
        ep_key = (row.get("expected"), row.get("predicted"))
        key = (sig_key, ep_key)
        clusters.setdefault(key, []).append(row)

    out_rows: list[dict] = []
    for members in clusters.values():
        if representative == "worst":
            rep = min(
                members,
                key=lambda r: (
                    r.get("score") if isinstance(r.get("score"), (int, float))
                    else float("inf")
                ),
            )
        else:
            rep = min(members, key=lambda r: str(r.get("created") or ""))
        rep = dict(rep)
        rep["cluster_size"] = len(members)
        rep["cluster_member_ids"] = [
            m.get("scenario_id") or m.get("id") for m in members
        ]
        out_rows.append(rep)

    out_rows.sort(
        key=lambda r: r.get("cluster_size", 0),
        reverse=True,
    )
    out = dict(container)
    out["results"] = out_rows
    out["clustered"] = True
    out["cluster_count"] = len(out_rows)
    return out


__all__ = [
    "ScoreBand",
    "experiment_to_failing_evals",
    "cluster_failing_rows",
    "DEFAULT_MAX_SPANS",
]
