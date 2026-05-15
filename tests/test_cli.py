"""CLI integration tests. The full main → router → runners → cache path is
exercised; only the upstream sister-tool entrypoints are monkey-patched (so
nothing makes an LLM call or spawns a subprocess)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pluma import __main__ as cli
from pluma import runners


def _touch(p: Path, content: str = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def _fake_report(md: str = "# fake md\n"):
    return SimpleNamespace(markdown=md, input_tokens=0, output_tokens=0)


def _applyable_spec():
    return SimpleNamespace(applyable=True, reason=None, edits=[])


# Force the cache into a per-test tmp dir so no global state leaks.
@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch, tmp_path_factory):
    root = tmp_path_factory.mktemp("pluma_cache")
    monkeypatch.setenv("PLUMA_CACHE_ROOT", str(root))


# =========================================================================
# --version / --help / no-arg
# =========================================================================


def test_version_flag(capsys):
    assert cli.main(["--version"]) == 0
    out = capsys.readouterr().out
    assert "pluma 0.1.0" in out


def test_no_args_prints_help(capsys):
    rc = cli.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "diagnose-funnel" in out
    assert "watch" in out


# =========================================================================
# diagnose-funnel (explicit)
# =========================================================================


def test_diagnose_funnel_explicit_writes_output(monkeypatch, tmp_path):
    funnel = _touch(tmp_path / "f.yaml", "name: t\n")
    dropoff = _touch(tmp_path / "d.json", "{}")
    product = tmp_path / "p"
    product.mkdir()
    out = tmp_path / "out.md"

    monkeypatch.setattr(runners, "fr_load_funnel", lambda p: {})
    monkeypatch.setattr(runners, "fr_load_dropoff", lambda p: {})
    monkeypatch.setattr(runners, "fr_read_product", lambda d, extra_files=None: {})
    monkeypatch.setattr(
        runners, "fr_generate_hypotheses", lambda **kw: _fake_report("# funnel-out")
    )

    rc = cli.main([
        "diagnose-funnel",
        "--funnel", str(funnel),
        "--dropoff", str(dropoff),
        "--product", str(product),
        "--output-file", str(out),
        "--no-cache",
    ])
    assert rc == 0
    assert out.read_text() == "# funnel-out"


def test_diagnose_funnel_missing_input_returns_2(tmp_path):
    out = tmp_path / "out.md"
    rc = cli.main([
        "diagnose-funnel",
        "--funnel", str(tmp_path / "nope.yaml"),
        "--dropoff", str(_touch(tmp_path / "d.json")),
        "--product", str(tmp_path),
        "--output-file", str(out),
        "--no-cache",
    ])
    assert rc == 2


# =========================================================================
# diagnose-agent (explicit)
# =========================================================================


def test_diagnose_agent_explicit(monkeypatch, tmp_path):
    target = tmp_path / "a"
    target.mkdir()
    eval_result = _touch(tmp_path / "e.json", "{}")
    out = tmp_path / "out.md"

    monkeypatch.setattr(runners, "ar_load_target", lambda p: SimpleNamespace())
    monkeypatch.setattr(runners, "ar_load_eval", lambda p: SimpleNamespace(failures=[]))
    monkeypatch.setattr(
        runners,
        "ar_select_failure",
        lambda s, scenario_id=None: SimpleNamespace(scenario_id="s"),
    )
    monkeypatch.setattr(
        runners, "ar_generate_hypotheses", lambda **kw: _fake_report("# agent-out")
    )

    rc = cli.main([
        "diagnose-agent",
        "--target-agent", str(target),
        "--eval-result", str(eval_result),
        "--output-file", str(out),
        "--no-cache",
    ])
    assert rc == 0
    assert "# agent-out" in out.read_text()


# =========================================================================
# watch (explicit)
# =========================================================================


def test_watch_explicit(monkeypatch, tmp_path):
    traces = _touch(tmp_path / "t.jsonl", "{}\n")
    cohort = _touch(tmp_path / "c.yaml", "name: x\n")
    product = tmp_path / "p"
    product.mkdir()
    out = tmp_path / "out.md"

    monkeypatch.setattr(runners, "iw_load_cohort", lambda p: {})
    monkeypatch.setattr(runners, "iw_load_traces", lambda p: [])
    monkeypatch.setattr(runners, "iw_analyze_cohort", lambda t: {})
    monkeypatch.setattr(runners, "iw_read_product", lambda d, extra_files=None: {})
    monkeypatch.setattr(
        runners, "iw_generate_findings", lambda **kw: _fake_report("# watch-out")
    )

    rc = cli.main([
        "watch",
        "--traces", str(traces),
        "--cohort", str(cohort),
        "--product", str(product),
        "--output-file", str(out),
        "--no-cache",
    ])
    assert rc == 0
    assert out.read_text() == "# watch-out"


# =========================================================================
# diagnose (inferred)
# =========================================================================


def test_diagnose_inferred_routes_funnel(monkeypatch, tmp_path):
    funnel = _touch(tmp_path / "f.yaml")
    dropoff = _touch(tmp_path / "d.json")
    product = tmp_path / "p"
    product.mkdir()
    out = tmp_path / "out.md"

    monkeypatch.setattr(runners, "fr_load_funnel", lambda p: {})
    monkeypatch.setattr(runners, "fr_load_dropoff", lambda p: {})
    monkeypatch.setattr(runners, "fr_read_product", lambda d, extra_files=None: {})
    monkeypatch.setattr(runners, "fr_generate_hypotheses", lambda **kw: _fake_report("# routed-funnel"))

    rc = cli.main([
        "diagnose",
        "--funnel", str(funnel),
        "--dropoff", str(dropoff),
        "--product", str(product),
        "--output-file", str(out),
        "--no-cache",
    ])
    assert rc == 0
    assert "routed-funnel" in out.read_text()


def test_diagnose_inferred_ambiguous_exits_2(tmp_path, capsys):
    # Pass BOTH funnel and agent signature flags — should be ambiguous.
    rc = cli.main([
        "diagnose",
        "--funnel", str(_touch(tmp_path / "f.yaml")),
        "--dropoff", str(_touch(tmp_path / "d.json")),
        "--product", str(tmp_path),
        "--target-agent", str(tmp_path),
        "--eval-result", str(_touch(tmp_path / "e.json")),
        "--output-file", str(tmp_path / "o.md"),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "matched multiple" in err


def test_diagnose_inferred_redirects_to_watch_on_watch_flags(tmp_path, capsys):
    # Caller passed watch flags to `diagnose`. Should exit 2 and name `pluma watch`.
    rc = cli.main([
        "diagnose",
        "--output-file", str(tmp_path / "o.md"),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "could not infer" in err


# =========================================================================
# apply (Pluma-normalized report → origin tag)
# =========================================================================


def test_apply_routes_funnel_from_origin_tag(monkeypatch, tmp_path):
    report = _touch(tmp_path / "r.md", "# Pluma report\n\nOrigin: funnel-researcher\n")
    product = tmp_path / "p"
    product.mkdir()
    out = tmp_path / "delta.md"

    monkeypatch.setattr(runners, "fr_parse_edits", lambda r, hid: _applyable_spec())
    monkeypatch.setattr(runners, "fr_apply_edits", lambda s, p, dry_run=False: [])
    monkeypatch.setattr(runners, "fr_render_delta", lambda *a, **kw: "# delta")

    rc = cli.main([
        "apply",
        "--report", str(report),
        "--product", str(product),
        "--hypothesis-id", "1",
        "--output-file", str(out),
    ])
    assert rc == 0
    assert out.read_text() == "# delta"


def test_apply_routes_integration_from_origin_tag(monkeypatch, tmp_path):
    report = _touch(tmp_path / "r.md", "# Pluma report\n\nOrigin: integration-watcher\n")
    product = tmp_path / "p"
    product.mkdir()

    monkeypatch.setattr(runners, "iw_parse_edits", lambda r, hid: _applyable_spec())
    monkeypatch.setattr(runners, "iw_apply_edits", lambda s, p, dry_run=False: [])
    monkeypatch.setattr(runners, "iw_render_delta", lambda *a, **kw: "# iw delta")

    rc = cli.main([
        "apply",
        "--report", str(report),
        "--product", str(product),
        "--hypothesis-id", "F1",
        "--output-file", str(tmp_path / "o.md"),
    ])
    assert rc == 0


def test_apply_missing_origin_tag_returns_2(tmp_path, capsys):
    report = _touch(tmp_path / "r.md", "# Some report\n\nno origin\n")
    rc = cli.main([
        "apply",
        "--report", str(report),
        "--product", str(tmp_path),
        "--hypothesis-id", "1",
        "--output-file", str(tmp_path / "o.md"),
    ])
    assert rc == 2


def test_apply_agent_requires_target_agent_and_eval_command(tmp_path, capsys):
    report = _touch(tmp_path / "r.md", "# Pluma report\n\nOrigin: agent-researcher\n")
    rc = cli.main([
        "apply",
        "--report", str(report),
        "--hypothesis-id", "1",
        "--output-file", str(tmp_path / "o.md"),
    ])
    assert rc == 2
    assert "--target-agent" in capsys.readouterr().err


# =========================================================================
# iterate
# =========================================================================


def test_iterate_routes_funnel(monkeypatch, tmp_path):
    report = _touch(tmp_path / "r.md", "# Pluma report\n\nOrigin: funnel-researcher\n")
    product = tmp_path / "p"
    product.mkdir()
    res = [SimpleNamespace(applyable=True, applied_edits=[1], error=None)]
    monkeypatch.setattr(runners, "fr_iterate_report", lambda r, p, dry_run=False: res)
    monkeypatch.setattr(runners, "fr_render_comparison", lambda *a, **kw: "# iter")

    rc = cli.main([
        "iterate",
        "--report", str(report),
        "--product", str(product),
        "--output-file", str(tmp_path / "c.md"),
    ])
    assert rc == 0


# =========================================================================
# cache integration
# =========================================================================


def test_cache_hit_skips_runner(monkeypatch, tmp_path):
    funnel = _touch(tmp_path / "f.yaml", "name: t\n")
    dropoff = _touch(tmp_path / "d.json", "{}")
    product = tmp_path / "p"
    product.mkdir()
    out = tmp_path / "out.md"

    calls = []

    def _gen(**kw):
        calls.append(1)
        return _fake_report("# generated")

    monkeypatch.setattr(runners, "fr_load_funnel", lambda p: {})
    monkeypatch.setattr(runners, "fr_load_dropoff", lambda p: {})
    monkeypatch.setattr(runners, "fr_read_product", lambda d, extra_files=None: {})
    monkeypatch.setattr(runners, "fr_generate_hypotheses", _gen)

    argv = [
        "diagnose-funnel",
        "--funnel", str(funnel),
        "--dropoff", str(dropoff),
        "--product", str(product),
        "--output-file", str(out),
    ]
    assert cli.main(argv) == 0
    assert cli.main(argv) == 0  # second time → cache hit
    assert len(calls) == 1, "second call should hit cache, not regenerate"


def test_cache_force_bypasses_hit(monkeypatch, tmp_path):
    funnel = _touch(tmp_path / "f.yaml")
    dropoff = _touch(tmp_path / "d.json")
    product = tmp_path / "p"
    product.mkdir()
    out = tmp_path / "out.md"

    calls = []
    monkeypatch.setattr(runners, "fr_load_funnel", lambda p: {})
    monkeypatch.setattr(runners, "fr_load_dropoff", lambda p: {})
    monkeypatch.setattr(runners, "fr_read_product", lambda d, extra_files=None: {})
    monkeypatch.setattr(
        runners, "fr_generate_hypotheses",
        lambda **kw: (calls.append(1), _fake_report())[1],
    )

    base = [
        "diagnose-funnel",
        "--funnel", str(funnel),
        "--dropoff", str(dropoff),
        "--product", str(product),
        "--output-file", str(out),
    ]
    assert cli.main(base) == 0
    assert cli.main([*base, "--force"]) == 0
    assert len(calls) == 2


# =========================================================================
# cross (Phase 3 stub)
# =========================================================================


def test_cross_with_no_tool_inputs_returns_2(tmp_path, capsys):
    """`pluma cross` needs ≥2 tools' inputs; nothing → exit 2 with help."""
    rc = cli.main([
        "cross",
        "--product", str(tmp_path),
        "--output-file", str(tmp_path / "o.md"),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "at least 2" in err
