"""Runner contract tests. All sister-tool entrypoints are monkey-patched so
nothing in this file makes an LLM call or spawns a subprocess."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import anthropic
import pytest

from pluma import runners
from pluma.runners import RunResult


def _touch(p: Path, content: str = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def _fake_report(md: str = "# fake\n\n## Findings (0)\n") -> SimpleNamespace:
    return SimpleNamespace(markdown=md, input_tokens=0, output_tokens=0)


def _applyable_spec() -> SimpleNamespace:
    return SimpleNamespace(applyable=True, reason=None, edits=[])


def _not_applyable_spec() -> SimpleNamespace:
    return SimpleNamespace(applyable=False, reason="no structured edits", edits=[])


# =========================================================================
# funnel_diagnose
# =========================================================================


def test_funnel_diagnose_writes_markdown_and_returns_0(monkeypatch, tmp_path):
    funnel = _touch(tmp_path / "funnel.yaml", "name: test\n")
    dropoff = _touch(tmp_path / "dropoff.json", "{}")
    product = tmp_path / "product"
    product.mkdir()
    out = tmp_path / "out.md"

    monkeypatch.setattr(runners, "fr_load_funnel", lambda p: {"name": "test"})
    monkeypatch.setattr(runners, "fr_load_dropoff", lambda p: {})
    monkeypatch.setattr(runners, "fr_read_product", lambda d, extra_files=None: {})
    monkeypatch.setattr(
        runners, "fr_generate_hypotheses", lambda **kw: _fake_report("# funnel-md")
    )

    r = runners.funnel_diagnose(
        funnel=funnel, dropoff=dropoff, product=product, output_file=out
    )
    assert r == RunResult(out, 0)
    assert out.read_text() == "# funnel-md"


def test_funnel_diagnose_missing_funnel_returns_2(tmp_path):
    r = runners.funnel_diagnose(
        funnel=tmp_path / "nope.yaml",
        dropoff=_touch(tmp_path / "d.json"),
        product=tmp_path,
        output_file=tmp_path / "o.md",
    )
    assert r.exit_code == 2


def test_funnel_diagnose_runtime_error_returns_3(monkeypatch, tmp_path):
    funnel = _touch(tmp_path / "f.yaml")
    dropoff = _touch(tmp_path / "d.json")
    product = tmp_path / "p"
    product.mkdir()

    monkeypatch.setattr(runners, "fr_load_funnel", lambda p: None)
    monkeypatch.setattr(runners, "fr_load_dropoff", lambda p: None)
    monkeypatch.setattr(runners, "fr_read_product", lambda d, extra_files=None: None)

    def _boom(**kw):
        raise RuntimeError("LLM died")

    monkeypatch.setattr(runners, "fr_generate_hypotheses", _boom)

    r = runners.funnel_diagnose(
        funnel=funnel, dropoff=dropoff, product=product, output_file=tmp_path / "o.md"
    )
    assert r.exit_code == 3
    assert r.error == "LLM died"


def test_funnel_diagnose_api_connection_error_returns_3_with_message(
    monkeypatch, tmp_path
):
    """Regression: anthropic.APIConnectionError is NOT a RuntimeError. The
    runner must catch it (via anthropic.APIError) and return a clean exit 3
    with a descriptive message — never let a raw stack trace escape."""
    import httpx

    funnel = _touch(tmp_path / "f.yaml")
    dropoff = _touch(tmp_path / "d.json")
    product = tmp_path / "p"
    product.mkdir()

    monkeypatch.setattr(runners, "fr_load_funnel", lambda p: None)
    monkeypatch.setattr(runners, "fr_load_dropoff", lambda p: None)
    monkeypatch.setattr(runners, "fr_read_product", lambda d, extra_files=None: None)

    def _conn_err(**kw):
        raise anthropic.APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        )

    monkeypatch.setattr(runners, "fr_generate_hypotheses", _conn_err)

    r = runners.funnel_diagnose(
        funnel=funnel, dropoff=dropoff, product=product, output_file=tmp_path / "o.md"
    )
    assert r.exit_code == 3
    assert r.error is not None and r.error != ""
    assert "API error" in r.error  # descriptive, not a bare repr/stack trace


def test_agent_diagnose_api_error_returns_3_with_message(monkeypatch, tmp_path):
    """Same gap, agent-researcher path (RateLimitError this time)."""
    import httpx

    target = tmp_path / "a"
    target.mkdir()
    eval_result = _touch(tmp_path / "e.json", "{}")

    monkeypatch.setattr(runners, "ar_load_target", lambda p: SimpleNamespace())
    monkeypatch.setattr(
        runners, "ar_load_eval", lambda p: SimpleNamespace(failures=[])
    )
    monkeypatch.setattr(
        runners,
        "ar_select_failure",
        lambda s, scenario_id=None: SimpleNamespace(scenario_id="s"),
    )

    def _rate_limited(**kw):
        raise anthropic.RateLimitError(
            "rate limited",
            response=httpx.Response(
                429, request=httpx.Request("POST", "https://api.anthropic.com")
            ),
            body=None,
        )

    monkeypatch.setattr(runners, "ar_generate_hypotheses", _rate_limited)

    r = runners.agent_diagnose(
        target_agent=target, eval_result=eval_result, output_file=tmp_path / "o.md"
    )
    assert r.exit_code == 3
    assert r.error is not None and "API error" in r.error


# =========================================================================
# funnel_apply
# =========================================================================


def test_funnel_apply_happy_path_returns_0(monkeypatch, tmp_path):
    report = _touch(tmp_path / "r.md", "### Hypothesis 1: foo\n")
    product = tmp_path / "p"
    product.mkdir()
    out = tmp_path / "delta.md"

    monkeypatch.setattr(runners, "fr_parse_edits", lambda r, hid: _applyable_spec())
    monkeypatch.setattr(runners, "fr_apply_edits", lambda s, p, dry_run=False: [])
    monkeypatch.setattr(
        runners, "fr_render_delta", lambda *a, **kw: "# delta funnel"
    )

    r = runners.funnel_apply(
        hypothesis_report=report, hypothesis_id="1", product=product, output_file=out
    )
    assert r.exit_code == 0
    assert out.read_text() == "# delta funnel"


def test_funnel_apply_not_applyable_returns_4(monkeypatch, tmp_path):
    report = _touch(tmp_path / "r.md")
    product = tmp_path / "p"
    product.mkdir()
    monkeypatch.setattr(runners, "fr_parse_edits", lambda r, hid: _not_applyable_spec())
    r = runners.funnel_apply(
        hypothesis_report=report,
        hypothesis_id="1",
        product=product,
        output_file=tmp_path / "o.md",
    )
    assert r.exit_code == 4


# =========================================================================
# funnel_iterate
# =========================================================================


def test_funnel_iterate_writes_comparison_returns_0(monkeypatch, tmp_path):
    report = _touch(tmp_path / "r.md")
    product = tmp_path / "p"
    product.mkdir()
    out = tmp_path / "c.md"

    res = [SimpleNamespace(applyable=True, applied_edits=[1], error=None)]
    monkeypatch.setattr(runners, "fr_iterate_report", lambda r, p, dry_run=False: res)
    monkeypatch.setattr(
        runners, "fr_render_comparison", lambda *a, **kw: "# comparison funnel"
    )

    r = runners.funnel_iterate(
        hypothesis_report=report, product=product, output_file=out
    )
    assert r.exit_code == 0
    assert out.read_text() == "# comparison funnel"


def test_funnel_iterate_all_errored_returns_5(monkeypatch, tmp_path):
    report = _touch(tmp_path / "r.md")
    product = tmp_path / "p"
    product.mkdir()
    res = [SimpleNamespace(applyable=True, applied_edits=[], error="boom")]
    monkeypatch.setattr(runners, "fr_iterate_report", lambda r, p, dry_run=False: res)
    monkeypatch.setattr(runners, "fr_render_comparison", lambda *a, **kw: "x")
    r = runners.funnel_iterate(
        hypothesis_report=report, product=product, output_file=tmp_path / "o.md"
    )
    assert r.exit_code == 5


# =========================================================================
# integration_watch
# =========================================================================


def test_integration_watch_writes_markdown_returns_0(monkeypatch, tmp_path):
    traces = _touch(tmp_path / "t.jsonl", "{}\n")
    cohort = _touch(tmp_path / "c.yaml", "name: x\n")
    product = tmp_path / "p"
    product.mkdir()
    out = tmp_path / "o.md"

    monkeypatch.setattr(runners, "iw_load_cohort", lambda p: {})
    monkeypatch.setattr(runners, "iw_load_traces", lambda p: [])
    monkeypatch.setattr(runners, "iw_analyze_cohort", lambda t: {})
    monkeypatch.setattr(runners, "iw_read_product", lambda d, extra_files=None: {})
    monkeypatch.setattr(
        runners, "iw_generate_findings", lambda **kw: _fake_report("# iw-md")
    )

    r = runners.integration_watch(
        traces=traces, cohort=cohort, product=product, output_file=out
    )
    assert r.exit_code == 0
    assert out.read_text() == "# iw-md"


def test_integration_watch_missing_traces_returns_2(tmp_path):
    r = runners.integration_watch(
        traces=tmp_path / "nope.jsonl",
        cohort=_touch(tmp_path / "c.yaml"),
        product=tmp_path,
        output_file=tmp_path / "o.md",
    )
    assert r.exit_code == 2


# =========================================================================
# integration_apply / iterate
# =========================================================================


def test_integration_apply_happy_path(monkeypatch, tmp_path):
    report = _touch(tmp_path / "r.md", "### Finding 1: x\n")
    product = tmp_path / "p"
    product.mkdir()
    monkeypatch.setattr(runners, "iw_parse_edits", lambda r, hid: _applyable_spec())
    monkeypatch.setattr(runners, "iw_apply_edits", lambda s, p, dry_run=False: [])
    monkeypatch.setattr(runners, "iw_render_delta", lambda *a, **kw: "# iw delta")
    r = runners.integration_apply(
        hypothesis_report=report,
        hypothesis_id="F1",
        product=product,
        output_file=tmp_path / "o.md",
    )
    assert r.exit_code == 0


def test_integration_iterate_empty_returns_5(monkeypatch, tmp_path):
    report = _touch(tmp_path / "r.md")
    product = tmp_path / "p"
    product.mkdir()
    monkeypatch.setattr(runners, "iw_iterate_report", lambda r, p, dry_run=False: [])
    monkeypatch.setattr(runners, "iw_render_comparison", lambda *a, **kw: "x")
    r = runners.integration_iterate(
        hypothesis_report=report, product=product, output_file=tmp_path / "o.md"
    )
    assert r.exit_code == 5


# =========================================================================
# agent_diagnose
# =========================================================================


def test_agent_diagnose_writes_markdown_returns_0(monkeypatch, tmp_path):
    target = tmp_path / "agent"
    target.mkdir()
    eval_result = _touch(tmp_path / "eval.json", "{}")
    out = tmp_path / "o.md"

    monkeypatch.setattr(runners, "ar_load_target", lambda p: SimpleNamespace())
    monkeypatch.setattr(runners, "ar_load_eval", lambda p: SimpleNamespace(failures=[]))
    monkeypatch.setattr(
        runners,
        "ar_select_failure",
        lambda s, scenario_id=None: SimpleNamespace(scenario_id="s1"),
    )
    monkeypatch.setattr(
        runners, "ar_generate_hypotheses", lambda **kw: _fake_report("# agent-md")
    )

    r = runners.agent_diagnose(target_agent=target, eval_result=eval_result, output_file=out)
    assert r.exit_code == 0
    assert "# agent-md" in out.read_text()


def test_agent_diagnose_missing_target_returns_2(tmp_path):
    r = runners.agent_diagnose(
        target_agent=tmp_path / "nope",
        eval_result=_touch(tmp_path / "e.json"),
        output_file=tmp_path / "o.md",
    )
    assert r.exit_code == 2


# =========================================================================
# agent_apply
# =========================================================================


def test_agent_apply_dry_run_returns_0(monkeypatch, tmp_path):
    report = _touch(tmp_path / "r.md")
    target = tmp_path / "agent"
    target.mkdir()
    monkeypatch.setattr(runners, "ar_parse_report", lambda r, hid: _applyable_spec())
    monkeypatch.setattr(runners, "ar_apply_edits", lambda t, s, dry_run=False: [])
    r = runners.agent_apply(
        hypothesis_report=report,
        hypothesis_id=1,
        target_agent=target,
        eval_command="echo hi",
        output_file=tmp_path / "o.md",
        dry_run=True,
    )
    assert r.exit_code == 0


def test_agent_apply_baseline_eval_failure_returns_5(monkeypatch, tmp_path):
    report = _touch(tmp_path / "r.md")
    target = tmp_path / "agent"
    target.mkdir()
    monkeypatch.setattr(runners, "ar_parse_report", lambda r, hid: _applyable_spec())

    def _bad_eval(*a, **kw):
        from agent_researcher.eval_runner import EvalRunError
        raise EvalRunError("eval crashed")

    monkeypatch.setattr(runners, "ar_run_eval", _bad_eval)
    r = runners.agent_apply(
        hypothesis_report=report,
        hypothesis_id=1,
        target_agent=target,
        eval_command="x",
        output_file=tmp_path / "o.md",
    )
    assert r.exit_code == 5


def test_agent_apply_edit_failure_returns_6(monkeypatch, tmp_path):
    report = _touch(tmp_path / "r.md")
    target = tmp_path / "agent"
    target.mkdir()
    monkeypatch.setattr(runners, "ar_parse_report", lambda r, hid: _applyable_spec())
    monkeypatch.setattr(
        runners,
        "ar_run_eval",
        lambda *a, **kw: SimpleNamespace(summary=SimpleNamespace(failures=[])),
    )

    def _bad_apply(*a, **kw):
        raise ValueError("bad edit")

    monkeypatch.setattr(runners, "ar_apply_edits", _bad_apply)
    r = runners.agent_apply(
        hypothesis_report=report,
        hypothesis_id=1,
        target_agent=target,
        eval_command="x",
        output_file=tmp_path / "o.md",
    )
    assert r.exit_code == 6


# =========================================================================
# agent_iterate
# =========================================================================


def test_agent_iterate_writes_markdown_returns_0(monkeypatch, tmp_path):
    report = _touch(tmp_path / "r.md")
    target = tmp_path / "agent"
    target.mkdir()
    monkeypatch.setattr(
        runners, "ar_iterate", lambda *a, **kw: SimpleNamespace()
    )
    monkeypatch.setattr(runners, "ar_render_iteration", lambda r: "# agent iter")
    r = runners.agent_iterate(
        hypothesis_report=report,
        target_agent=target,
        eval_command="x",
        output_file=tmp_path / "o.md",
    )
    assert r.exit_code == 0


def test_agent_iterate_catastrophic_returns_8(monkeypatch, tmp_path):
    report = _touch(tmp_path / "r.md")
    target = tmp_path / "agent"
    target.mkdir()

    def _explode(*a, **kw):
        raise SystemError("disk gone")

    monkeypatch.setattr(runners, "ar_iterate", _explode)
    r = runners.agent_iterate(
        hypothesis_report=report,
        target_agent=target,
        eval_command="x",
        output_file=tmp_path / "o.md",
    )
    assert r.exit_code == 8


# =========================================================================
# helper: _summary_from_report
# =========================================================================


def test_summary_from_report_finds_hypothesis(tmp_path):
    p = _touch(tmp_path / "r.md", "### Hypothesis 2: dropoff at step 3\nbody\n")
    assert (
        runners._summary_from_report(p, 2, label="Hypothesis")
        == "Hypothesis 2: dropoff at step 3"
    )


def test_summary_from_report_finds_finding(tmp_path):
    p = _touch(tmp_path / "r.md", "### Finding 1: trace miss\nbody\n")
    assert (
        runners._summary_from_report(p, "F1", label="Finding")
        == "Finding 1: trace miss"
    )


def test_summary_from_report_fallback(tmp_path):
    p = _touch(tmp_path / "r.md", "no headers here\n")
    s = runners._summary_from_report(p, 99, label="Hypothesis")
    assert "Hypothesis 99" in s
