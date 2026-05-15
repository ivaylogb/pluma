"""Cross-tool orchestration + comparison-rendering tests. All sister-tool
entrypoints are monkey-patched — nothing here makes an LLM call."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pluma import comparison, cross, runners
from pluma.cross import (
    CrossInputs,
    CrossMatch,
    CrossReport,
    build_correlation,
    detect_cross_matches,
    determine_tools,
    run_cross,
)
from pluma.normalize import Citation, Finding, PlumaReport


# =========================================================================
# Isolate cache to tmp_path
# =========================================================================


@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("PLUMA_CACHE_ROOT", str(tmp_path_factory.mktemp("cache")))


def _touch(p: Path, content: str = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def _fake_report(md: str = "# fake\n\n## Findings (0)\n"):
    return SimpleNamespace(markdown=md, input_tokens=0, output_tokens=0)


# =========================================================================
# determine_tools
# =========================================================================


def test_determine_tools_two_provided(tmp_path):
    inputs = CrossInputs(
        product=tmp_path,
        funnel=tmp_path / "f.yaml",
        dropoff=tmp_path / "d.json",
        traces=tmp_path / "t.jsonl",
        cohort=tmp_path / "c.yaml",
    )
    assert determine_tools(inputs) == ["funnel-researcher", "integration-watcher"]


def test_determine_tools_one_provided(tmp_path):
    inputs = CrossInputs(
        product=tmp_path,
        funnel=tmp_path / "f.yaml",
        dropoff=tmp_path / "d.json",
    )
    assert determine_tools(inputs) == ["funnel-researcher"]


def test_determine_tools_three_provided(tmp_path):
    inputs = CrossInputs(
        product=tmp_path,
        funnel=tmp_path / "f.yaml",
        dropoff=tmp_path / "d.json",
        traces=tmp_path / "t.jsonl",
        cohort=tmp_path / "c.yaml",
        eval_result=tmp_path / "e.json",
        target_agent=tmp_path / "a",
    )
    assert determine_tools(inputs) == [
        "funnel-researcher", "integration-watcher", "agent-researcher",
    ]


def test_determine_tools_partial_inputs_dont_count(tmp_path):
    """Half a tool's inputs is not enough."""
    inputs = CrossInputs(product=tmp_path, funnel=tmp_path / "f.yaml")  # no dropoff
    assert determine_tools(inputs) == []


# =========================================================================
# detect_cross_matches — mechanical
# =========================================================================


def _finding(id: str, *, title: str, layer: int | None, citations: list[Citation]) -> Finding:
    return Finding(
        index=int(id[1:]),
        id=id,
        title=title,
        layer=layer,
        body=f"body for {id}",
        citations=citations,
    )


def _pluma(origin: str, findings: list[Finding]) -> PlumaReport:
    term = "Finding" if origin == "integration-watcher" else "Hypothesis"
    return PlumaReport(origin=origin, original_term=term, title="t", findings=findings)


def test_mechanical_match_same_file_overlapping_lines():
    c1 = Citation("docs/quickstart.md", 10, 20, "raw1")
    c2 = Citation("docs/quickstart.md", 15, 25, "raw2")
    per_tool = {
        "funnel-researcher": _pluma("funnel-researcher", [
            _finding("H1", title="placeholder agent_id", layer=3, citations=[c1])
        ]),
        "integration-watcher": _pluma("integration-watcher", [
            _finding("F1", title="agt_xxxxxxxx literal", layer=3, citations=[c2])
        ]),
    }
    matches = detect_cross_matches(per_tool)
    assert len(matches) == 1
    assert matches[0].kind == "mechanical"
    assert "docs/quickstart.md" in matches[0].reason


def test_mechanical_match_same_single_line():
    c = Citation("README.md", 13, 13, "README.md:13")
    per_tool = {
        "funnel-researcher": _pluma("funnel-researcher", [
            _finding("H1", title="X", layer=3, citations=[c])
        ]),
        "integration-watcher": _pluma("integration-watcher", [
            _finding("F1", title="Y", layer=3,
                     citations=[Citation("README.md", 13, 13, "raw")])
        ]),
    }
    matches = detect_cross_matches(per_tool)
    assert len(matches) == 1
    assert matches[0].kind == "mechanical"


def test_no_match_different_files_same_layer():
    per_tool = {
        "funnel-researcher": _pluma("funnel-researcher", [
            _finding("H1", title="X", layer=2,
                     citations=[Citation("a.md", 1, 1, "a.md:1")])
        ]),
        "integration-watcher": _pluma("integration-watcher", [
            _finding("F1", title="Y", layer=2,
                     citations=[Citation("b.md", 1, 1, "b.md:1")])
        ]),
    }
    assert detect_cross_matches(per_tool) == []


def test_no_match_same_file_disjoint_lines():
    per_tool = {
        "funnel-researcher": _pluma("funnel-researcher", [
            _finding("H1", title="X", layer=2,
                     citations=[Citation("a.md", 1, 5, "a.md:1-5")])
        ]),
        "integration-watcher": _pluma("integration-watcher", [
            _finding("F1", title="Y", layer=2,
                     citations=[Citation("a.md", 20, 30, "a.md:20-30")])
        ]),
    }
    # Different layers would prevent categorical too — they share Layer 2 + file
    # "a.md", so this WILL trigger a categorical match. Specifically test that
    # mechanical doesn't fire.
    matches = detect_cross_matches(per_tool)
    assert len(matches) == 1
    assert matches[0].kind == "categorical"


# =========================================================================
# detect_cross_matches — categorical
# =========================================================================


def test_categorical_match_same_layer_shared_surface():
    per_tool = {
        "funnel-researcher": _pluma("funnel-researcher", [
            _finding("H1", title="X", layer=3,
                     citations=[Citation("docs/quickstart.md", 1, 10, "raw")])
        ]),
        "integration-watcher": _pluma("integration-watcher", [
            _finding("F1", title="Y", layer=3,
                     citations=[Citation("docs/quickstart.md", 100, 105, "raw")])
        ]),
    }
    matches = detect_cross_matches(per_tool)
    assert len(matches) == 1
    assert matches[0].kind == "categorical"
    assert "Layer 3" in matches[0].reason


def test_categorical_no_match_different_layer():
    per_tool = {
        "funnel-researcher": _pluma("funnel-researcher", [
            _finding("H1", title="X", layer=3,
                     citations=[Citation("a.md", 1, 10, "raw")])
        ]),
        "integration-watcher": _pluma("integration-watcher", [
            _finding("F1", title="Y", layer=4,
                     citations=[Citation("a.md", 100, 105, "raw")])
        ]),
    }
    assert detect_cross_matches(per_tool) == []


def test_findings_unique_to_each_tool():
    per_tool = {
        "funnel-researcher": _pluma("funnel-researcher", [
            _finding("H1", title="shared", layer=3,
                     citations=[Citation("a.md", 1, 1, "a.md:1")]),
            _finding("H2", title="unique-to-funnel", layer=2, citations=[]),
        ]),
        "integration-watcher": _pluma("integration-watcher", [
            _finding("F1", title="shared", layer=3,
                     citations=[Citation("a.md", 1, 1, "a.md:1")]),
            _finding("F2", title="unique-to-integration", layer=4, citations=[]),
        ]),
    }
    matches = detect_cross_matches(per_tool)
    assert len(matches) == 1
    # H2 and F2 should not be in any match
    matched = {(o, f.id) for m in matches for o, f in m.findings}
    assert ("funnel-researcher", "H2") not in matched
    assert ("integration-watcher", "F2") not in matched


# =========================================================================
# build_correlation
# =========================================================================


def test_build_correlation_counts_layers():
    per_tool = {
        "funnel-researcher": _pluma("funnel-researcher", [
            _finding("H1", title="a", layer=3, citations=[]),
            _finding("H2", title="b", layer=3, citations=[]),
            _finding("H3", title="c", layer=2, citations=[]),
        ]),
        "integration-watcher": _pluma("integration-watcher", [
            _finding("F1", title="a", layer=1, citations=[]),
        ]),
    }
    corr = build_correlation(per_tool)
    assert corr["funnel-researcher"] == {2: 1, 3: 2}
    assert corr["integration-watcher"] == {1: 1}


def test_build_correlation_ignores_findings_without_layer():
    per_tool = {
        "funnel-researcher": _pluma("funnel-researcher", [
            _finding("H1", title="a", layer=None, citations=[]),
            _finding("H2", title="b", layer=3, citations=[]),
        ]),
    }
    assert build_correlation(per_tool) == {"funnel-researcher": {3: 1}}


# =========================================================================
# run_cross — orchestration with mocked runners
# =========================================================================


def test_run_cross_insufficient_inputs_returns_2(tmp_path):
    inputs = CrossInputs(product=tmp_path)
    result = run_cross(inputs)
    assert result.exit_code == 2
    assert "at least 2" in result.error


def test_run_cross_two_tools_happy_path(monkeypatch, tmp_path):
    product = tmp_path / "p"
    product.mkdir()
    funnel = _touch(tmp_path / "f.yaml")
    dropoff = _touch(tmp_path / "d.json")
    traces = _touch(tmp_path / "t.jsonl")
    cohort = _touch(tmp_path / "c.yaml")

    funnel_md = (
        "# F\n\n### Hypothesis 1: agent_id placeholder (Layer 3)\n"
        "evidence at `README.md:13`\n"
    )
    integration_md = (
        "# I\n\n### Finding 1: agt_xxxxxxxx literal (Layer 3)\n"
        "evidence at `README.md:13`\n"
    )

    # Funnel pipeline
    monkeypatch.setattr(runners, "fr_load_funnel", lambda p: {})
    monkeypatch.setattr(runners, "fr_load_dropoff", lambda p: {})
    monkeypatch.setattr(runners, "fr_read_product", lambda d, extra_files=None: {})
    monkeypatch.setattr(runners, "fr_generate_hypotheses", lambda **kw: _fake_report(funnel_md))

    # Integration pipeline
    monkeypatch.setattr(runners, "iw_load_cohort", lambda p: {})
    monkeypatch.setattr(runners, "iw_load_traces", lambda p: [])
    monkeypatch.setattr(runners, "iw_analyze_cohort", lambda t: {})
    monkeypatch.setattr(runners, "iw_read_product", lambda d, extra_files=None: {})
    monkeypatch.setattr(runners, "iw_generate_findings", lambda **kw: _fake_report(integration_md))

    inputs = CrossInputs(
        product=product, funnel=funnel, dropoff=dropoff, traces=traces, cohort=cohort,
    )
    result = run_cross(inputs)
    assert result.exit_code == 0
    assert result.report is not None
    assert len(result.report.cross_matches) == 1
    assert result.report.cross_matches[0].kind == "mechanical"
    assert "funnel-researcher" in result.cache_hits
    assert result.cache_hits["funnel-researcher"] is False  # first run


def test_run_cross_cache_hits_on_second_call(monkeypatch, tmp_path):
    product = tmp_path / "p"
    product.mkdir()
    funnel = _touch(tmp_path / "f.yaml", "x")
    dropoff = _touch(tmp_path / "d.json", "{}")
    traces = _touch(tmp_path / "t.jsonl", "{}\n")
    cohort = _touch(tmp_path / "c.yaml", "x")

    monkeypatch.setattr(runners, "fr_load_funnel", lambda p: {})
    monkeypatch.setattr(runners, "fr_load_dropoff", lambda p: {})
    monkeypatch.setattr(runners, "fr_read_product", lambda d, extra_files=None: {})
    monkeypatch.setattr(runners, "fr_generate_hypotheses", lambda **kw: _fake_report("# F\n"))
    monkeypatch.setattr(runners, "iw_load_cohort", lambda p: {})
    monkeypatch.setattr(runners, "iw_load_traces", lambda p: [])
    monkeypatch.setattr(runners, "iw_analyze_cohort", lambda t: {})
    monkeypatch.setattr(runners, "iw_read_product", lambda d, extra_files=None: {})
    monkeypatch.setattr(runners, "iw_generate_findings", lambda **kw: _fake_report("# I\n"))

    inputs = CrossInputs(
        product=product, funnel=funnel, dropoff=dropoff, traces=traces, cohort=cohort,
    )
    r1 = run_cross(inputs)
    r2 = run_cross(inputs)
    assert r1.exit_code == r2.exit_code == 0
    assert all(v is False for v in r1.cache_hits.values())
    assert all(v is True for v in r2.cache_hits.values())


# =========================================================================
# render_cross_report
# =========================================================================


def test_render_correlation_matrix_appears():
    per_tool = {
        "funnel-researcher": _pluma("funnel-researcher", [
            _finding("H1", title="x", layer=3,
                     citations=[Citation("a.md", 1, 1, "raw")]),
        ]),
        "integration-watcher": _pluma("integration-watcher", [
            _finding("F1", title="y", layer=3,
                     citations=[Citation("a.md", 1, 1, "raw")]),
        ]),
    }
    report = CrossReport(
        per_tool=per_tool,
        cross_matches=detect_cross_matches(per_tool),
        correlation=build_correlation(per_tool),
        inputs=CrossInputs(product=Path("/x")),
    )
    md = comparison.render_cross_report(report)
    assert "## Correlation matrix" in md
    assert "| Layer 3 |" in md
    assert "funnel-researcher" in md
    assert "integration-watcher" in md


def test_render_empty_cross_section_has_placeholder():
    per_tool = {
        "funnel-researcher": _pluma("funnel-researcher", [
            _finding("H1", title="x", layer=3, citations=[]),
        ]),
        "integration-watcher": _pluma("integration-watcher", [
            _finding("F1", title="y", layer=4, citations=[]),
        ]),
    }
    report = CrossReport(
        per_tool=per_tool,
        cross_matches=[],
        correlation=build_correlation(per_tool),
        inputs=CrossInputs(product=Path("/x")),
    )
    md = comparison.render_cross_report(report)
    assert "Cross-tool findings (0)" in md
    assert "No cross-tool findings detected" in md


def test_render_unique_section_lists_per_tool_findings():
    per_tool = {
        "funnel-researcher": _pluma("funnel-researcher", [
            _finding("H1", title="shared", layer=3,
                     citations=[Citation("a.md", 1, 1, "raw")]),
            _finding("H2", title="funnel-only", layer=2, citations=[]),
        ]),
        "integration-watcher": _pluma("integration-watcher", [
            _finding("F1", title="shared", layer=3,
                     citations=[Citation("a.md", 1, 1, "raw")]),
        ]),
    }
    report = CrossReport(
        per_tool=per_tool,
        cross_matches=detect_cross_matches(per_tool),
        correlation=build_correlation(per_tool),
        inputs=CrossInputs(product=Path("/x")),
    )
    md = comparison.render_cross_report(report)
    assert "Findings unique to funnel-researcher (1)" in md
    assert "funnel-only" in md
    assert "Findings unique to integration-watcher (0)" in md


# =========================================================================
# CLI integration — pluma cross
# =========================================================================


def test_cli_cross_two_tools(monkeypatch, tmp_path):
    from pluma import __main__ as cli

    product = tmp_path / "p"
    product.mkdir()
    funnel = _touch(tmp_path / "f.yaml")
    dropoff = _touch(tmp_path / "d.json")
    traces = _touch(tmp_path / "t.jsonl")
    cohort = _touch(tmp_path / "c.yaml")
    out = tmp_path / "cross.md"

    monkeypatch.setattr(runners, "fr_load_funnel", lambda p: {})
    monkeypatch.setattr(runners, "fr_load_dropoff", lambda p: {})
    monkeypatch.setattr(runners, "fr_read_product", lambda d, extra_files=None: {})
    monkeypatch.setattr(
        runners, "fr_generate_hypotheses",
        lambda **kw: _fake_report(
            "# F\n\n### Hypothesis 1: x (Layer 3)\n`README.md:13`\n"
        ),
    )
    monkeypatch.setattr(runners, "iw_load_cohort", lambda p: {})
    monkeypatch.setattr(runners, "iw_load_traces", lambda p: [])
    monkeypatch.setattr(runners, "iw_analyze_cohort", lambda t: {})
    monkeypatch.setattr(runners, "iw_read_product", lambda d, extra_files=None: {})
    monkeypatch.setattr(
        runners, "iw_generate_findings",
        lambda **kw: _fake_report(
            "# I\n\n### Finding 1: y (Layer 3)\n`README.md:13`\n"
        ),
    )

    rc = cli.main([
        "cross",
        "--product", str(product),
        "--funnel", str(funnel),
        "--dropoff", str(dropoff),
        "--traces", str(traces),
        "--cohort", str(cohort),
        "--output-file", str(out),
    ])
    assert rc == 0
    md = out.read_text()
    assert "Cross-tool findings (1)" in md


def test_cli_cross_insufficient_inputs(tmp_path, capsys):
    from pluma import __main__ as cli

    product = tmp_path / "p"
    product.mkdir()
    out = tmp_path / "cross.md"
    rc = cli.main([
        "cross",
        "--product", str(product),
        "--funnel", str(_touch(tmp_path / "f.yaml")),
        "--dropoff", str(_touch(tmp_path / "d.json")),
        "--output-file", str(out),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "at least 2" in err
