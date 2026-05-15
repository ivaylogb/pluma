"""Router contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from pluma import router
from pluma.router import Route, route_explicit, route_from_report, route_inferred


# =========================================================================
# route_explicit
# =========================================================================


def test_route_explicit_diagnose_funnel():
    r = route_explicit("diagnose-funnel")
    assert r == Route(tool="funnel-researcher", verb="diagnose")


def test_route_explicit_diagnose_agent():
    r = route_explicit("diagnose-agent")
    assert r == Route(tool="agent-researcher", verb="diagnose")


def test_route_explicit_watch():
    r = route_explicit("watch")
    assert r == Route(tool="integration-watcher", verb="watch")


def test_route_explicit_unknown_returns_none():
    """`apply`, `iterate`, and `cross` are not in the explicit map — they have
    their own handling. Caller distinguishes by checking the return."""
    assert route_explicit("apply") is None
    assert route_explicit("iterate") is None
    assert route_explicit("cross") is None
    assert route_explicit("nope") is None


# =========================================================================
# route_inferred — diagnose (refinement A: NOT collapsed with watch)
# =========================================================================


def test_inferred_diagnose_routes_funnel_on_funnel_flags():
    r = route_inferred(
        "diagnose",
        {"funnel": "/p/funnel.yaml", "dropoff": "/p/drop.json", "product": "/p/prod"},
    )
    assert r.ok
    assert r.tool == "funnel-researcher"
    assert r.verb == "diagnose"


def test_inferred_diagnose_routes_agent_on_agent_flags():
    r = route_inferred(
        "diagnose", {"eval_result": "/p/eval.json", "target_agent": "/p/agent"}
    )
    assert r.ok
    assert r.tool == "agent-researcher"


def test_inferred_diagnose_does_NOT_match_watch_flags():
    """Refinement A: `diagnose` and `watch` are separate verbs; traces+cohort
    must NOT route through diagnose."""
    r = route_inferred(
        "diagnose",
        {"traces": "/p/t.jsonl", "cohort": "/p/c.yaml", "product": "/p/prod"},
    )
    assert not r.ok
    assert "could not infer" in r.error
    assert "watch" in r.error  # the error should redirect to the watch alternative


def test_inferred_diagnose_ambiguous_returns_error():
    """If a caller passes flags that match both funnel and agent signatures,
    we exit with a disambiguation error rather than picking one."""
    r = route_inferred(
        "diagnose",
        {
            "funnel": "/p/f.yaml",
            "dropoff": "/p/d.json",
            "product": "/p/prod",
            "eval_result": "/p/eval.json",
            "target_agent": "/p/agent",
        },
    )
    assert not r.ok
    assert "matched multiple" in r.error
    assert "diagnose-funnel" in r.error
    assert "diagnose-agent" in r.error


def test_inferred_diagnose_no_match_lists_hints():
    r = route_inferred("diagnose", {"funnel": "/p/f.yaml"})  # missing dropoff/product
    assert not r.ok
    assert "missing" in r.error
    assert "--dropoff" in r.error
    assert "--product" in r.error


def test_inferred_diagnose_empty_flags():
    r = route_inferred("diagnose", {})
    assert not r.ok
    assert "could not infer" in r.error


# =========================================================================
# route_inferred — watch (NOT diagnose)
# =========================================================================


def test_inferred_watch_routes_integration():
    r = route_inferred(
        "watch", {"traces": "/p/t.jsonl", "cohort": "/p/c.yaml", "product": "/p/prod"}
    )
    assert r.ok
    assert r.tool == "integration-watcher"
    assert r.verb == "watch"


def test_inferred_watch_does_NOT_match_diagnose_flags():
    """Refinement A enforcement from the other direction: passing diagnose
    flags to `pluma watch` must not silently fall through."""
    r = route_inferred(
        "watch",
        {"funnel": "/p/f.yaml", "dropoff": "/p/d.json", "product": "/p/prod"},
    )
    assert not r.ok
    assert "--traces" in r.error
    assert "--cohort" in r.error


def test_inferred_unsupported_verb_errors():
    r = route_inferred("apply", {"foo": "bar"})
    assert not r.ok
    assert "inferred routing not supported" in r.error


# =========================================================================
# route_from_report — origin-tag routing for apply/iterate
# =========================================================================


def test_route_from_report_reads_origin(tmp_path):
    p = tmp_path / "r.md"
    p.write_text("# Pluma report\n\nOrigin: funnel-researcher\n\n## Findings (1)\n")
    r = route_from_report(p)
    assert r.ok
    assert r.tool == "funnel-researcher"


def test_route_from_report_integration(tmp_path):
    p = tmp_path / "r.md"
    p.write_text("# Pluma report\n\nOrigin: integration-watcher\n")
    r = route_from_report(p)
    assert r.tool == "integration-watcher"


def test_route_from_report_agent(tmp_path):
    p = tmp_path / "r.md"
    p.write_text("# Pluma report\n\nOrigin: agent-researcher\n")
    r = route_from_report(p)
    assert r.tool == "agent-researcher"


def test_route_from_report_missing_file():
    r = route_from_report(Path("/no/such/file.md"))
    assert not r.ok
    assert "not found" in r.error


def test_route_from_report_no_origin_tag(tmp_path):
    p = tmp_path / "r.md"
    p.write_text("# Some other report\n\nno origin here\n")
    r = route_from_report(p)
    assert not r.ok
    assert "Origin:" in r.error


def test_route_from_report_unknown_origin(tmp_path):
    p = tmp_path / "r.md"
    p.write_text("# Pluma report\n\nOrigin: bogus-tool\n")
    r = route_from_report(p)
    assert not r.ok
    assert "unrecognized" in r.error
