"""Braintrust experiment results → agent-researcher failing-eval input.

A Braintrust experiment export is one JSON object whose ``results`` array
holds a scored row per scenario (``id``, ``input``, ``expected``,
``output``, a ``scores`` map, optional ``metadata``, a ``created``
timestamp). agent-researcher's ``load_eval_result`` reads a single JSON
object — a summary header plus a ``results`` array — and types against six
per-record fields (``scenario_id``, ``expected``, ``predicted``,
``predicted_confidence``, ``notes``, ``passed``), keeping the whole record
as ``raw`` for the diagnostic prompt.

This converter keeps only the rows that did not clear the score threshold
and overlays the six recognized fields onto a copy of the Braintrust row,
so every original field rides along untouched. The full field map lives in
this directory's README.
"""

from __future__ import annotations

import json
from typing import Any

_UNKNOWN = "unknown"


def _stringify(value: Any) -> str:
    """A string is returned as-is; anything else is compact-JSON encoded.

    Routing/classification labels are already strings, so the common case
    is loss-free; structured expected/output values stay faithful.
    """
    if isinstance(value, str):
        return value
    if value is None:
        return _UNKNOWN
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _select_scorer(scores: dict[str, Any], primary_scorer: str | None) -> str | None:
    """The explicit primary scorer if given, else the first scorer in the
    row's ``scores`` object (insertion order, as Braintrust emits it).
    """
    if primary_scorer is not None:
        return primary_scorer
    return next(iter(scores), None)


def _row_to_failing_eval(
    row: dict[str, Any],
    *,
    scorer: str | None,
    score: Any,
    threshold: float,
    experiment_id: str,
    experiment_name: str,
    project_name: str,
) -> dict[str, Any]:
    """Overlay agent-researcher's recognized fields onto a copy of the
    Braintrust row so nothing the platform supplied is dropped.
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
    record["notes"] = (
        f"Braintrust scorer {scorer!r} scored {score} (threshold {threshold}). "
        f"expected={expected!r} output={predicted!r}. "
        f"experiment {experiment_name!r} ({experiment_id}), row {row_id}."
    )
    record["metadata"] = {
        **(row.get("metadata") or {}),
        "experiment_id": experiment_id,
        "experiment_name": experiment_name,
        "project_name": project_name,
        "row_id": row_id,
    }
    return record


def experiment_to_failing_evals(
    experiment: dict,
    score_threshold: float = 1.0,
    primary_scorer: str | None = None,
) -> dict:
    """Extract failing scenarios from a Braintrust experiment.

    A row passes when its primary scorer's score is present and
    ``>= score_threshold``; everything else (including rows missing the
    primary scorer) is emitted as a failure, since this converter feeds
    diagnosis and a row that can't be confirmed passing is worth a look.

    Returns the single JSON object ``agent_researcher.eval_analyzer.
    load_eval_result`` expects: a summary header plus a ``results`` array
    of failing records, sorted by ``created`` ascending. The summary
    counts cover the whole experiment, not just the failures, so the
    audit trail (total / passed / pass_rate) survives the filter.
    """
    rows: list[dict] = list(experiment.get("results") or [])
    experiment_id = str(experiment.get("experiment_id") or _UNKNOWN)
    experiment_name = str(experiment.get("experiment_name") or _UNKNOWN)
    project_name = str(experiment.get("project_name") or _UNKNOWN)

    failing: list[dict] = []
    for row in rows:
        scores = row.get("scores") or {}
        scorer = _select_scorer(scores, primary_scorer)
        score = scores.get(scorer) if scorer is not None else None
        if score is not None and score >= score_threshold:
            continue
        failing.append(
            _row_to_failing_eval(
                row,
                scorer=scorer,
                score=score,
                threshold=score_threshold,
                experiment_id=experiment_id,
                experiment_name=experiment_name,
                project_name=project_name,
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
        "total": total,
        "passed": passed,
        "pass_rate": pass_rate,
        "threshold": score_threshold,
        "meets_threshold": len(failing) == 0,
        "results": failing,
    }
