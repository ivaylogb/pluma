"""diagnose-agent Braintrust dispatch tests.

Day 2 wires the live Braintrust path into `pluma diagnose-agent`. These
tests exercise the new dispatch and its source-validation rules without a
network or a real BRAINTRUST_API_KEY.

Two mocking boundaries are used deliberately:

  - Dispatch / forwarding tests patch `__main__.fetch_experiment_as_failing_evals`
    (the symbol the router calls) so we assert exactly what the router
    forwards and that the converted container reaches agent-researcher via
    the temp file — no transport involved.

  - The API-key tests patch `BraintrustClient.resolve_experiment_id` /
    `fetch_experiment_export` instead, so the *real* helper and the *real*
    `BraintrustClient.__post_init__` run and we can assert the env-var
    fallback / flag-override actually resolves on the client.

The regression test routes `--eval-result` through the unchanged file
path and asserts the live helper is never called.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import pluma.integrations.braintrust.braintrust_client as btc
from pluma import __main__ as cli
from pluma import runners
from pluma.integrations.braintrust.experiment_to_failing_evals import ScoreBand


_CONTAINER = {
    "experiment_id": "abc123",
    "experiment_name": "routing_v3",
    "project_name": "support-router",
    "total": 3,
    "passed": 1,
    "pass_rate": 0.3333,
    "results": [
        {"scenario_id": "r1", "expected": "billing", "predicted": "sales",
         "passed": False, "raw": {"scorer_signature": {}}},
    ],
}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path_factory):
    """Per-test cache dir + guaranteed-absent API key (no creds, no spend)."""
    root = tmp_path_factory.mktemp("pluma_cache")
    monkeypatch.setenv("PLUMA_CACHE_ROOT", str(root))
    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)


def _target(tmp_path: Path) -> Path:
    d = tmp_path / "agent"
    d.mkdir()
    return d


def _spy_fetch(record: dict):
    """A fake `fetch_experiment_as_failing_evals` recording its kwargs."""

    def _fake(**kwargs):
        record.update(kwargs)
        return _CONTAINER

    return _fake


def _capture_agent_diagnose(seen: dict):
    """A fake `runners.agent_diagnose` that records the eval_result path,
    its parsed content, and that the file existed when handed over."""

    def _fake(*, target_agent, eval_result, output_file, **kw):
        seen["eval_result_path"] = Path(eval_result)
        seen["existed_at_call"] = Path(eval_result).is_file()
        seen["container"] = json.loads(Path(eval_result).read_text())
        seen["kw"] = kw
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("# diagnosed\n")
        return runners.RunResult(output_file, 0)

    return _fake


# =========================================================================
# regression: --eval-result file path unchanged
# =========================================================================


def test_eval_result_path_still_works_unchanged(monkeypatch, tmp_path):
    target = _target(tmp_path)
    eval_result = tmp_path / "e.json"
    eval_result.write_text("{}")
    out = tmp_path / "out.md"

    def _boom(**kw):
        raise AssertionError("live helper must not run for the file path")

    monkeypatch.setattr(cli, "fetch_experiment_as_failing_evals", _boom)
    monkeypatch.setattr(runners, "ar_load_target", lambda p: SimpleNamespace())
    monkeypatch.setattr(
        runners, "ar_load_eval", lambda p: SimpleNamespace(failures=[])
    )
    monkeypatch.setattr(
        runners,
        "ar_select_failure",
        lambda s, scenario_id=None: SimpleNamespace(scenario_id="s"),
    )
    monkeypatch.setattr(
        runners,
        "ar_generate_hypotheses",
        lambda **kw: SimpleNamespace(markdown="# agent-out"),
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
# live dispatch: experiment id / project+latest
# =========================================================================


def test_braintrust_experiment_id_dispatch(monkeypatch, tmp_path):
    target = _target(tmp_path)
    out = tmp_path / "out.md"
    sent: dict = {}
    seen: dict = {}
    monkeypatch.setattr(cli, "fetch_experiment_as_failing_evals", _spy_fetch(sent))
    monkeypatch.setattr(runners, "agent_diagnose", _capture_agent_diagnose(seen))

    rc = cli.main([
        "diagnose-agent",
        "--target-agent", str(target),
        "--braintrust-experiment-id", "abc123",
        "--output-file", str(out),
    ])

    assert rc == 0
    assert sent["experiment_id"] == "abc123"
    assert sent["project"] is None
    assert sent["latest"] is False
    # The converted container reached agent-researcher via the temp file...
    assert seen["existed_at_call"] is True
    assert seen["container"] == _CONTAINER
    # ...and the temp file was cleaned up afterward.
    assert not seen["eval_result_path"].exists()
    assert out.read_text() == "# diagnosed\n"


def test_braintrust_project_latest_dispatch(monkeypatch, tmp_path):
    target = _target(tmp_path)
    out = tmp_path / "out.md"
    sent: dict = {}
    monkeypatch.setattr(cli, "fetch_experiment_as_failing_evals", _spy_fetch(sent))
    monkeypatch.setattr(
        runners, "agent_diagnose", _capture_agent_diagnose({})
    )

    rc = cli.main([
        "diagnose-agent",
        "--target-agent", str(target),
        "--braintrust-project", "support-router",
        "--latest",
        "--output-file", str(out),
    ])

    assert rc == 0
    assert sent["project"] == "support-router"
    assert sent["latest"] is True
    assert sent["experiment_id"] is None


# =========================================================================
# source validation / mutual exclusion
# =========================================================================


def test_mutually_exclusive_eval_result_vs_braintrust(tmp_path, capsys):
    target = _target(tmp_path)
    eval_result = tmp_path / "e.json"
    eval_result.write_text("{}")
    rc = cli.main([
        "diagnose-agent",
        "--target-agent", str(target),
        "--eval-result", str(eval_result),
        "--braintrust-experiment-id", "abc123",
        "--output-file", str(tmp_path / "o.md"),
    ])
    assert rc == 2
    assert "mutually exclusive" in capsys.readouterr().err


def test_braintrust_experiment_id_and_project_mutually_exclusive(tmp_path, capsys):
    target = _target(tmp_path)
    rc = cli.main([
        "diagnose-agent",
        "--target-agent", str(target),
        "--braintrust-experiment-id", "abc123",
        "--braintrust-project", "support-router",
        "--latest",
        "--output-file", str(tmp_path / "o.md"),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--braintrust-experiment-id and --braintrust-project" in err


def test_braintrust_project_requires_latest(tmp_path, capsys):
    target = _target(tmp_path)
    rc = cli.main([
        "diagnose-agent",
        "--target-agent", str(target),
        "--braintrust-project", "support-router",
        "--output-file", str(tmp_path / "o.md"),
    ])
    assert rc == 2
    assert "--braintrust-project requires --latest" in capsys.readouterr().err


def test_latest_requires_project(tmp_path, capsys):
    target = _target(tmp_path)
    rc = cli.main([
        "diagnose-agent",
        "--target-agent", str(target),
        "--latest",
        "--output-file", str(tmp_path / "o.md"),
    ])
    assert rc == 2
    assert "--latest requires --braintrust-project" in capsys.readouterr().err


def test_no_source_reports_clear_error(tmp_path, capsys):
    target = _target(tmp_path)
    rc = cli.main([
        "diagnose-agent",
        "--target-agent", str(target),
        "--output-file", str(tmp_path / "o.md"),
    ])
    assert rc == 2
    assert "requires a source" in capsys.readouterr().err


# =========================================================================
# pass-through flag forwarding
# =========================================================================


def test_pass_through_flags_forwarded(monkeypatch, tmp_path):
    target = _target(tmp_path)
    out = tmp_path / "out.md"
    sent: dict = {}
    monkeypatch.setattr(cli, "fetch_experiment_as_failing_evals", _spy_fetch(sent))
    monkeypatch.setattr(runners, "agent_diagnose", _capture_agent_diagnose({}))

    rc = cli.main([
        "diagnose-agent",
        "--target-agent", str(target),
        "--braintrust-experiment-id", "abc123",
        "--scorer", "exact_match",
        "--score-band-min", "0.4",
        "--score-band-max", "0.8",
        "--max-spans", "5",
        "--cluster", "worst",
        "--output-file", str(out),
    ])

    assert rc == 0
    assert sent["scorer"] == "exact_match"
    assert sent["score_band"] == ScoreBand(0.4, 0.8)
    assert sent["max_spans"] == 5
    assert sent["cluster"] == "worst"


def test_max_spans_minus_one_disables_trimming(monkeypatch, tmp_path):
    target = _target(tmp_path)
    sent: dict = {}
    monkeypatch.setattr(cli, "fetch_experiment_as_failing_evals", _spy_fetch(sent))
    monkeypatch.setattr(runners, "agent_diagnose", _capture_agent_diagnose({}))

    rc = cli.main([
        "diagnose-agent",
        "--target-agent", str(target),
        "--braintrust-experiment-id", "abc123",
        "--max-spans", "-1",
        "--output-file", str(tmp_path / "o.md"),
    ])
    assert rc == 0
    assert sent["max_spans"] is None


def test_no_cluster_overrides_cluster(monkeypatch, tmp_path):
    target = _target(tmp_path)
    sent: dict = {}
    monkeypatch.setattr(cli, "fetch_experiment_as_failing_evals", _spy_fetch(sent))
    monkeypatch.setattr(runners, "agent_diagnose", _capture_agent_diagnose({}))

    rc = cli.main([
        "diagnose-agent",
        "--target-agent", str(target),
        "--braintrust-experiment-id", "abc123",
        "--cluster", "worst",
        "--no-cluster",
        "--output-file", str(tmp_path / "o.md"),
    ])
    assert rc == 0
    assert sent["cluster"] == "none"


def test_score_band_max_defaults_to_min(monkeypatch, tmp_path):
    target = _target(tmp_path)
    sent: dict = {}
    monkeypatch.setattr(cli, "fetch_experiment_as_failing_evals", _spy_fetch(sent))
    monkeypatch.setattr(runners, "agent_diagnose", _capture_agent_diagnose({}))

    rc = cli.main([
        "diagnose-agent",
        "--target-agent", str(target),
        "--braintrust-experiment-id", "abc123",
        "--score-band-min", "0.5",
        "--output-file", str(tmp_path / "o.md"),
    ])
    assert rc == 0
    # max defaults to max(min, 1.0) → 1.0, mirroring the standalone CLI.
    assert sent["score_band"] == ScoreBand(0.5, 1.0)


# =========================================================================
# API-key resolution (real helper + real client, mocked transport)
# =========================================================================


def _stub_transport(monkeypatch, captured: list):
    def _resolve(self, **kw):
        captured.append(self.api_key)
        return "exp-x"

    def _fetch(self, experiment_id, with_spans=True):
        return {"experiment_id": experiment_id, "results": []}

    monkeypatch.setattr(btc.BraintrustClient, "resolve_experiment_id", _resolve)
    monkeypatch.setattr(btc.BraintrustClient, "fetch_experiment_export", _fetch)


def test_api_key_from_env_var(monkeypatch, tmp_path):
    target = _target(tmp_path)
    captured: list = []
    _stub_transport(monkeypatch, captured)
    monkeypatch.setattr(runners, "agent_diagnose", _capture_agent_diagnose({}))
    monkeypatch.setenv("BRAINTRUST_API_KEY", "env-key")

    rc = cli.main([
        "diagnose-agent",
        "--target-agent", str(target),
        "--braintrust-experiment-id", "abc123",
        "--output-file", str(tmp_path / "o.md"),
    ])
    assert rc == 0
    assert captured == ["env-key"]


def test_api_key_flag_overrides_env_var(monkeypatch, tmp_path):
    target = _target(tmp_path)
    captured: list = []
    _stub_transport(monkeypatch, captured)
    monkeypatch.setattr(runners, "agent_diagnose", _capture_agent_diagnose({}))
    monkeypatch.setenv("BRAINTRUST_API_KEY", "env-key")

    rc = cli.main([
        "diagnose-agent",
        "--target-agent", str(target),
        "--braintrust-experiment-id", "abc123",
        "--braintrust-api-key", "flag-key",
        "--output-file", str(tmp_path / "o.md"),
    ])
    assert rc == 0
    assert captured == ["flag-key"]
