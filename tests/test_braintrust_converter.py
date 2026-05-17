"""Braintrust converter contract tests.

Covers the v2 additions to ``experiment_to_failing_evals``: the
``ScoreBand`` pass condition, per-scorer ``scorer_signature``, span
preservation/trimming, ``agent_revision`` resolution, the optional
``cluster_failing_rows`` pre-pass, and a round-trip of the converter's
output through ``agent_researcher.eval_analyzer.load_eval_result``.

Mirrors the existing ``tests/`` pattern: pytest, plain ``assert``,
``tmp_path``, module-under-test imported directly. The golden-fixture
regression (``fixtures/experiment.json`` -> ``fixtures/failing_evals.json``)
is exercised here via the live agent-researcher loader rather than a
byte-diff so the test asserts the consumed contract, not formatting.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pluma.integrations.braintrust.experiment_to_failing_evals import (
    DEFAULT_MAX_SPANS,
    ScoreBand,
    cluster_failing_rows,
    experiment_to_failing_evals,
)

# fixtures live next to the converter module, not under tests/
_BT_DIR = (
    Path(__file__).resolve().parent.parent
    / "src" / "pluma" / "integrations" / "braintrust"
)
FIXTURE = _BT_DIR / "fixtures" / "experiment.json"


def _exp(rows: list[dict], **top) -> dict:
    """A minimal Braintrust experiment export around the given rows."""
    base = {
        "experiment_id": "exp-1",
        "experiment_name": "unit",
        "project_name": "proj",
        "results": rows,
    }
    base.update(top)
    return base


def _row(rid: str, *, scores: dict, expected="a", output="b",
         created="2026-01-01T00:00:00Z", **extra) -> dict:
    r = {
        "id": rid,
        "input": {"message": rid},
        "expected": expected,
        "output": output,
        "scores": scores,
        "created": created,
    }
    r.update(extra)
    return r


def _only(container: dict) -> dict:
    """The single emitted record (asserts there is exactly one)."""
    assert len(container["results"]) == 1, container["results"]
    return container["results"][0]


# =========================================================================
# ScoreBand
# =========================================================================


def test_scoreband_default_is_strict_threshold():
    band = ScoreBand()
    assert (band.min_score, band.max_score) == (1.0, 1.0)
    assert band.contains(1.0) is True
    assert band.contains(0.99) is False
    assert band.contains(None) is False


def test_scoreband_custom_band():
    band = ScoreBand(0.4, 0.8)
    assert band.contains(0.5) is True
    assert band.contains(0.3) is False
    assert band.contains(0.9) is False


# =========================================================================
# scorer_signature
# =========================================================================


def test_scorer_signature_single_scorer():
    c = experiment_to_failing_evals(
        _exp([_row("r1", scores={"exact_match": 0.0})])
    )
    sig = _only(c)["scorer_signature"]
    assert list(sig) == ["exact_match"]
    assert sig["exact_match"]["is_primary"] is True
    assert sig["exact_match"]["passed"] is False
    assert sig["exact_match"]["score"] == 0.0


def test_scorer_signature_multi_scorer():
    # Insertion order fixes the primary (first) scorer.
    row = _row(
        "r1",
        scores={
            "exact_match": 0.0,          # primary -> judged vs band
            "calibrated_confidence": 0.9,  # non-primary -> >= band.min?
            "factuality": 1.0,           # non-primary -> >= band.min?
        },
    )
    sig = _only(experiment_to_failing_evals(_exp([row])))["scorer_signature"]

    assert list(sig) == ["exact_match", "calibrated_confidence", "factuality"]
    assert [e["is_primary"] for e in sig.values()] == [True, False, False]
    # primary judged against the (default 1.0) band
    assert sig["exact_match"]["passed"] is False
    # non-primary use the softer floor: passed iff score >= band.min (1.0)
    assert sig["calibrated_confidence"]["passed"] is False  # 0.9 < 1.0
    assert sig["factuality"]["passed"] is True               # 1.0 >= 1.0


# =========================================================================
# spans
# =========================================================================


def _spans(n: int) -> list[dict]:
    return [
        {
            "span_id": f"s{i}",
            "parent_span_id": None if i == 0 else "s0",
            "name": "classify_intent" if i == 0 else "agent.step",
            "input": {"i": i},
            "output": {"i": i},
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-01T00:00:01Z",
        }
        for i in range(n)
    ]


def test_spans_preserved():
    spans = _spans(5)
    rec = _only(
        experiment_to_failing_evals(
            _exp([_row("r1", scores={"exact_match": 0.0}, spans=spans)])
        )
    )
    assert rec["spans"] == spans  # untouched below the cap


def test_spans_trimmed_at_default_cap():
    rec = _only(
        experiment_to_failing_evals(
            _exp([_row("r1", scores={"exact_match": 0.0}, spans=_spans(75))])
        )
    )
    assert len(rec["spans"]) == DEFAULT_MAX_SPANS + 1 == 51
    assert rec["spans"][:DEFAULT_MAX_SPANS] == _spans(75)[:DEFAULT_MAX_SPANS]
    assert rec["spans"][-1] == {"_truncated": True, "_dropped": 25}


def test_spans_disabled_with_max_spans_none():
    rec = _only(
        experiment_to_failing_evals(
            _exp([_row("r1", scores={"exact_match": 0.0}, spans=_spans(75))]),
            max_spans=None,
        )
    )
    assert len(rec["spans"]) == 75
    assert all("_truncated" not in s for s in rec["spans"])


def test_spans_absent_handled():
    # Row with no spans key -> record carries spans = None (present, null).
    rec = _only(
        experiment_to_failing_evals(
            _exp([_row("r1", scores={"exact_match": 0.0})])
        )
    )
    assert "spans" in rec
    assert rec["spans"] is None


# =========================================================================
# agent_revision
# =========================================================================


def test_agent_revision_auto_resolved_from_experiment_metadata():
    c = experiment_to_failing_evals(
        _exp(
            [_row("r1", scores={"exact_match": 0.0})],
            metadata={"agent_revision": "sha123"},
        )
    )
    assert c["agent_revision"] == "sha123"
    assert _only(c)["metadata"]["agent_revision"] == "sha123"


def test_agent_revision_explicit_override():
    c = experiment_to_failing_evals(
        _exp(
            [_row("r1", scores={"exact_match": 0.0})],
            metadata={"agent_revision": "sha123"},
        ),
        agent_revision="explicit",
    )
    assert c["agent_revision"] == "explicit"
    assert _only(c)["metadata"]["agent_revision"] == "explicit"


# =========================================================================
# cluster_failing_rows
# =========================================================================


def test_cluster_failing_rows_collapses_equivalent_failures():
    # Same scorer signature + same (expected, predicted) -> one cluster.
    rows = [
        _row("r1", scores={"exact_match": 0.0}, expected="x", output="y",
             created="2026-01-01T00:00:01Z"),
        _row("r2", scores={"exact_match": 0.0}, expected="x", output="y",
             created="2026-01-01T00:00:02Z"),
    ]
    clustered = cluster_failing_rows(experiment_to_failing_evals(_exp(rows)))
    assert clustered["clustered"] is True
    assert clustered["cluster_count"] == 1
    rep = _only(clustered)
    assert rep["cluster_size"] == 2
    assert sorted(rep["cluster_member_ids"]) == ["r1", "r2"]


def test_cluster_failing_rows_preserves_unique_failures():
    # Different scorer signatures -> two separate clusters.
    rows = [
        _row("r1", scores={"exact_match": 0.0}, expected="x", output="y"),
        _row("r2", scores={"factuality": 0.0}, expected="x", output="y"),
    ]
    clustered = cluster_failing_rows(experiment_to_failing_evals(_exp(rows)))
    assert clustered["cluster_count"] == 2
    assert all(r["cluster_size"] == 1 for r in clustered["results"])


# =========================================================================
# round-trip through agent-researcher's loader
# =========================================================================


def test_round_trip_through_agent_researcher_loader(tmp_path):
    loader = pytest.importorskip("agent_researcher.eval_analyzer")

    experiment = json.loads(FIXTURE.read_text())
    container = experiment_to_failing_evals(experiment)

    out = tmp_path / "failing_evals.json"
    out.write_text(json.dumps(container, indent=2) + "\n")

    summary = loader.load_eval_result(out)  # must not raise

    assert summary.total == container["total"]
    assert summary.passed == container["passed"]
    assert summary.pass_rate == container["pass_rate"]
    assert len(summary.failures) == len(container["results"])
    assert summary.passed + len(summary.failures) == summary.total

    # The v2 diagnostic context must survive into raw (the prompt input).
    first = summary.failures[0]
    assert "scorer_signature" in first.raw
    assert "spans" in first.raw
    assert first.raw["metadata"]["agent_revision"] == (
        "a1b2c3d4e5f67890abcdef1234567890abcdef12"
    )
