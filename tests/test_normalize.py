"""Normalizer contract tests. Uses synthetic markdown plus a sample from the
real example reports in the sister repos."""

from __future__ import annotations

from pathlib import Path

import pytest

from pluma import normalize
from pluma.normalize import (
    Citation,
    Finding,
    PlumaReport,
    extract_citations,
    normalize_citation,
    parse,
    parse_agent,
    parse_funnel,
    parse_integration,
)


SISTER_ROOT = Path(__file__).resolve().parent.parent.parent
FUNNEL_EXAMPLE = SISTER_ROOT / "funnel-researcher" / "examples" / "api_activation" / "diagnosis.md"
INTEGRATION_EXAMPLE = (
    SISTER_ROOT / "integration-watcher" / "examples" / "agent_platform" / "findings.md"
)
AGENT_EXAMPLE = SISTER_ROOT / "agent_researcher" / "examples" / "issue_107" / "report.md"


# =========================================================================
# normalize_citation / extract_citations
# =========================================================================


def test_normalize_citation_simple():
    c = normalize_citation("docs/quickstart.md:21")
    assert c == Citation("docs/quickstart.md", 21, 21, "docs/quickstart.md:21")


def test_normalize_citation_range():
    c = normalize_citation("docs/quickstart.md:21-30")
    assert c.line_start == 21
    assert c.line_end == 30
    assert c.file == "docs/quickstart.md"


def test_normalize_citation_en_dash():
    c = normalize_citation("docs/quickstart.md:21–30")
    assert c.line_start == 21
    assert c.line_end == 30


def test_normalize_citation_inside_sentence():
    c = normalize_citation("see `docs/quickstart.md:21-30` for details")
    assert c is not None
    assert c.file == "docs/quickstart.md"


def test_normalize_citation_non_citation_returns_none():
    assert normalize_citation("just some prose with no file ref") is None


def test_extract_citations_dedups_and_orders():
    body = """
    First evidence: `docs/quickstart.md:21-30`.
    Second evidence: `README.md:13`.
    Repeat first: `docs/quickstart.md:21-30`.
    """
    cites = extract_citations(body)
    assert len(cites) == 2
    assert cites[0].file == "docs/quickstart.md"
    assert cites[1].file == "README.md"


def test_citation_overlap_same_range():
    a = normalize_citation("docs/x.md:10-20")
    b = normalize_citation("docs/x.md:15-25")
    assert a.overlaps(b) and b.overlaps(a)


def test_citation_overlap_disjoint():
    a = normalize_citation("docs/x.md:10-20")
    b = normalize_citation("docs/x.md:25-30")
    assert not a.overlaps(b)


def test_citation_overlap_different_files():
    a = normalize_citation("docs/x.md:10")
    b = normalize_citation("docs/y.md:10")
    assert not a.overlaps(b)


# =========================================================================
# per-tool parsers — synthetic
# =========================================================================


def test_parse_funnel_synthetic():
    md = """# Funnel diagnosis: foo

## Hypotheses

### Hypothesis 1: Placeholder agent_id in docs (Layer 3)

**Claim:** see `docs/quickstart.md:21-30`.

```json
{"applyable": true, "edits": []}
```

### Hypothesis 2: Error message unclear (Layer 2)

**Claim:** see `errors.yaml:18`.

```json
{"applyable": false, "reason": "needs more context"}
```
"""
    r = parse_funnel(md)
    assert r.origin == "funnel-researcher"
    assert r.original_term == "Hypothesis"
    assert r.title == "Funnel diagnosis: foo"
    assert len(r.findings) == 2

    f1 = r.findings[0]
    assert f1.index == 1
    assert "Placeholder agent_id in docs" in f1.title
    assert f1.layer == 3
    assert f1.applyable is True
    assert any(c.file == "docs/quickstart.md" for c in f1.citations)

    f2 = r.findings[1]
    assert f2.layer == 2
    assert f2.applyable is False


def test_parse_integration_synthetic():
    md = """# Integration findings: bar

## Findings

### Finding 1: trace gap at startup (Layer 1)

evidence in `traces.jsonl:5-8`

```json
{"applyable": true, "edits": []}
```
"""
    r = parse_integration(md)
    assert r.origin == "integration-watcher"
    assert r.original_term == "Finding"
    assert len(r.findings) == 1
    assert r.findings[0].layer == 1
    assert r.findings[0].applyable is True


def test_parse_agent_synthetic():
    md = """# Hypothesis report: agent X

## Hypotheses

### Hypothesis 1: Buried tie-break rule (Layer 3)

evidence at `classification.j2:44`
"""
    r = parse_agent(md)
    assert r.origin == "agent-researcher"
    assert r.original_term == "Hypothesis"
    assert r.findings[0].layer == 3
    assert any(c.file == "classification.j2" for c in r.findings[0].citations)


def test_parse_dispatcher_routes_correctly():
    md = "# t\n\n### Hypothesis 1: x\n"
    r = parse(md, origin="funnel-researcher")
    assert r.original_term == "Hypothesis"
    r2 = parse(md, origin="integration-watcher")
    # integration-watcher uses Finding; "Hypothesis" header won't match
    assert r2.findings == []


def test_parse_unknown_origin_raises():
    with pytest.raises(ValueError):
        parse("# t\n", origin="bogus")


# =========================================================================
# per-tool parsers — real example reports from the sister repos
# =========================================================================


@pytest.mark.skipif(not FUNNEL_EXAMPLE.is_file(), reason="example absent")
def test_parse_funnel_real_example():
    r = parse_funnel(FUNNEL_EXAMPLE.read_text())
    assert r.findings, "funnel example should yield ≥1 finding"
    # The first hypothesis is about quickstart.md
    titles = [f.title.lower() for f in r.findings]
    assert any("quickstart" in t or "agent_id" in t for t in titles)
    # Every finding should have at least one citation
    assert all(f.citations for f in r.findings)


@pytest.mark.skipif(not INTEGRATION_EXAMPLE.is_file(), reason="example absent")
def test_parse_integration_real_example():
    r = parse_integration(INTEGRATION_EXAMPLE.read_text())
    assert r.findings
    assert r.original_term == "Finding"


@pytest.mark.skipif(not AGENT_EXAMPLE.is_file(), reason="example absent")
def test_parse_agent_real_example():
    r = parse_agent(AGENT_EXAMPLE.read_text())
    assert r.findings
    # Should pick up the classification.j2 citations.
    assert any(
        any(c.file == "classification.j2" for c in f.citations) for f in r.findings
    )


# =========================================================================
# Pluma markdown rendering
# =========================================================================


def test_to_markdown_uses_finding_terminology_with_origin_tag():
    md = "# t\n\n### Hypothesis 1: foo (Layer 3)\nbody\n"
    r = parse_funnel(md)
    out = r.to_markdown()
    assert "# Pluma report" in out
    assert "Origin: funnel-researcher" in out
    assert "Original entity term: Hypothesis" in out
    assert "## Findings (1)" in out
    assert "### Finding 1 — foo [Layer 3]" in out


def test_to_markdown_omits_layer_when_absent():
    md = "# t\n\n### Hypothesis 1: foo\nbody\n"
    r = parse_funnel(md)
    assert "[Layer" not in r.to_markdown()


def test_to_markdown_preserves_body_verbatim():
    md = "# t\n\n### Hypothesis 1: foo (Layer 1)\n\n**Claim:** here.\n\n`docs/x.md:5`.\n"
    r = parse_funnel(md)
    out = r.to_markdown()
    assert "**Claim:** here." in out
    assert "`docs/x.md:5`" in out


# =========================================================================
# Trailing-meta-section boundary (the cross-report pollution fix)
# =========================================================================


def test_last_finding_body_stops_at_trailing_h2_section():
    """A `## What this report is NOT` trailer after the last hypothesis must
    NOT be absorbed into that hypothesis's body."""
    md = (
        "# Funnel diagnosis: x\n\n"
        "## Hypotheses\n\n"
        "### Hypothesis 1: first (Layer 3)\n\n"
        "**Claim:** body one.\n\n"
        "### Hypothesis 2: last (Layer 2)\n\n"
        "**Claim:** body two — the real end of the finding.\n\n"
        "## What this report is NOT\n\n"
        "This is a trailing meta section that must not leak into Hypothesis 2.\n"
    )
    r = parse_funnel(md)
    assert len(r.findings) == 2
    last = r.findings[1]
    assert "body two — the real end of the finding." in last.body
    assert "What this report is NOT" not in last.body
    assert "must not leak" not in last.body
    # And it must not surface in the re-emitted Pluma markdown either.
    assert "What this report is NOT" not in r.to_markdown()


def test_last_finding_body_runs_to_eof_when_no_trailing_h2():
    """Existing behavior preserved: with no trailing `## ` section, the last
    finding's body extends to EOF."""
    md = (
        "# Funnel diagnosis: x\n\n"
        "## Hypotheses\n\n"
        "### Hypothesis 1: only (Layer 1)\n\n"
        "**Claim:** body.\n\n"
        "**How to verify:** the very last line of the document.\n"
    )
    r = parse_funnel(md)
    assert len(r.findings) == 1
    assert "the very last line of the document." in r.findings[0].body
