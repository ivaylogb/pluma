"""LangSmith converter contract tests.

Covers both workflows (Dataset-Experiment / project-traced production),
the global-node-cap run-tree walker, primary-feedback-key resolution
(explicit + any-failing fallback), the deliberate no-auto-resolution of
agent_revision, reference-output handling per workflow, v0.2 schema
conformance of the committed goldens, and the `pluma diagnose-agent`
live dispatch for both workflows.

Mirrors the existing tests/ pattern: pytest, plain assert, fixtures
next to the converter module, transport faked (no network, no spend).
The committed goldens are regression-tested by `*_workflow_basic`.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import pluma.integrations.langsmith.langsmith_client as lsc
from pluma import __main__ as cli
from pluma import runners
from pluma.integrations.langsmith.runs_to_failing_evals import (
    _walk_run_tree,
    runs_from_experiment,
    runs_from_project,
)

_LS_DIR = (
    Path(__file__).resolve().parent.parent
    / "src" / "pluma" / "integrations" / "langsmith"
)
FIX = _LS_DIR / "fixtures"
EXPERIMENT_FIXTURE = FIX / "experiment.json"
PROJECT_FIXTURE = FIX / "project_runs.json"
GOLDEN_EXPERIMENT = FIX / "failing_evals_experiment.json"
GOLDEN_PROJECT = FIX / "failing_evals_project.json"


class FakeClient:
    """In-memory stand-in for LangSmithClient driven by a fixture dict.

    Models the verified API semantics: list_runs(parent_run_id=X)
    returns *direct children only* (the walker recurses per level);
    is_root excludes runs with a parent; list_feedback is the separate
    batched resource; read_example raises when the id is unknown (the
    converter degrades to no reference, never blocks).
    """

    def __init__(self, fixture: dict):
        self.runs = fixture.get("runs", [])
        self.children = fixture.get("children", {})
        self.feedback = fixture.get("feedback", [])
        self.examples = fixture.get("examples", {})
        self.feedback_calls: list[list[str]] = []
        self.run_queries: list[dict] = []

    def list_runs(
        self,
        *,
        project_id=None,
        project_name=None,
        is_root=None,
        parent_run_id=None,
        trace_id=None,
        filter=None,
        limit=None,
    ):
        self.run_queries.append(
            {"parent_run_id": parent_run_id, "is_root": is_root}
        )
        if parent_run_id is not None:
            return list(self.children.get(parent_run_id, []))
        runs = self.runs
        if is_root:
            runs = [r for r in runs if r.get("parent_run_id") is None]
        return list(runs)

    def list_feedback(self, *, run_ids):
        self.feedback_calls.append(list(run_ids))
        wanted = set(run_ids)
        return [
            fb for fb in self.feedback if str(fb.get("run_id")) in wanted
        ]

    def read_example(self, example_id):
        ex = self.examples.get(example_id)
        if ex is None:
            raise KeyError(example_id)
        return ex


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _experiment_client() -> FakeClient:
    return FakeClient(_load(EXPERIMENT_FIXTURE))


def _project_client() -> FakeClient:
    return FakeClient(_load(PROJECT_FIXTURE))


# =========================================================================
# workflow basics + committed-golden regression
# =========================================================================


def test_experiment_workflow_basic():
    container = runs_from_experiment(
        "exp-routing-classifier-v3",
        primary_feedback_key="correctness",
        threshold=1.0,
        client=_experiment_client(),
    )
    assert container["total"] == 10
    assert container["passed"] == 7
    assert container["pass_rate"] == 0.7
    ids = sorted(r["metadata"]["run_id"] for r in container["results"])
    assert ids == ["r03", "r07", "r09"]
    assert container == _load(GOLDEN_EXPERIMENT), (
        "experiment golden drifted — regenerate "
        "fixtures/failing_evals_experiment.json"
    )


def test_project_workflow_basic():
    container = runs_from_project(
        "support-agent-prod",
        primary_feedback_key=None,
        threshold=1.0,
        client=_project_client(),
    )
    # 15 roots; x01/x02 (non-root) excluded by the is_root filter.
    assert container["total"] == 15
    assert container["passed"] == 10
    assert container["pass_rate"] == 0.6667
    ids = sorted(r["metadata"]["run_id"] for r in container["results"])
    assert ids == ["r02", "r05", "r08", "r11", "r14"]
    assert container == _load(GOLDEN_PROJECT), (
        "project golden drifted — regenerate "
        "fixtures/failing_evals_project.json"
    )


# =========================================================================
# run-tree walker
# =========================================================================


def _chain(n: int) -> dict:
    """A fixture-shaped fake where run 0 is root and each run i has one
    child i+1 (a single deep chain of n nodes)."""
    runs = [{"id": "n0", "parent_run_id": None}]
    children: dict[str, list] = {}
    for i in range(1, n):
        children[f"n{i - 1}"] = [{"id": f"n{i}", "parent_run_id": f"n{i - 1}"}]
    return {"runs": runs, "children": children, "feedback": [], "examples": {}}


def test_run_tree_walker_respects_depth():
    client = FakeClient(_chain(10))
    root = client.runs[0]
    spans = _walk_run_tree(root, client, max_depth=3, max_total_nodes=50)
    real = [s for s in spans if "_truncated" not in s]
    # root (depth 0) + 3 levels => n0..n3
    assert [s["span_id"] for s in real] == ["n0", "n1", "n2", "n3"]


def test_run_tree_walker_respects_node_cap():
    # Wide tree: root with 40 children, plus one child carrying an
    # erroring grandchild. Cap at 10 → root + the error path survive,
    # sibling leaves are dropped, a truncation marker is appended.
    runs = [{"id": "root", "parent_run_id": None}]
    kids = [
        {"id": f"k{i}", "parent_run_id": "root", "error": None}
        for i in range(40)
    ]
    grandchild = {
        "id": "deep_err",
        "parent_run_id": "k39",
        "error": "boom: failure surfaced here",
    }
    fixture = {
        "runs": runs,
        "children": {"root": kids, "k39": [grandchild]},
        "feedback": [],
        "examples": {},
    }
    client = FakeClient(fixture)
    spans = _walk_run_tree(
        client.runs[0], client, max_depth=4, max_total_nodes=10
    )
    real = [s for s in spans if "_truncated" not in s]
    marker = [s for s in spans if "_truncated" in s]
    assert len(real) == 10
    kept = {s["span_id"] for s in real}
    # Root and the full root→error path are intact (sibling leaves
    # dropped first, ancestors of kept nodes force-included).
    assert "root" in kept
    assert "k39" in kept
    assert "deep_err" in kept
    # 42 collected (root + 40 kids + 1 erroring grandchild) − 10 kept.
    assert marker[0] == {"_truncated": True, "_dropped": 32, "_max_nodes": 10}


# =========================================================================
# primary feedback key
# =========================================================================


def test_primary_feedback_key_explicit():
    # With an explicit key, only runs failing THAT key are emitted.
    c = runs_from_experiment(
        "exp-routing-classifier-v3",
        primary_feedback_key="correctness",
        threshold=1.0,
        client=_experiment_client(),
    )
    for rec in c["results"]:
        assert rec["scorer"] == "correctness"
        assert rec["score"] == 0.0
        assert rec["scorer_signature"]["correctness"]["is_primary"] is True


def test_primary_feedback_key_fallback_to_any_failing():
    # No primary key: a run fails when ANY feedback key is below
    # threshold; a run with no feedback is not a failure.
    c = runs_from_project(
        "support-agent-prod",
        primary_feedback_key=None,
        threshold=1.0,
        client=_project_client(),
    )
    by_run = {r["metadata"]["run_id"]: r for r in c["results"]}
    assert set(by_run) == {"r02", "r05", "r08", "r11", "r14"}
    # r08's only failing key is groundedness=0.4 → that is the scorer.
    assert by_run["r08"]["scorer"] == "groundedness"
    assert by_run["r08"]["score"] == 0.4


# =========================================================================
# agent_revision — deliberately never auto-resolved
# =========================================================================


def test_agent_revision_not_auto_resolved():
    c = runs_from_experiment(
        "exp-routing-classifier-v3",
        primary_feedback_key="correctness",
        client=_experiment_client(),
    )
    assert c["agent_revision"] is None
    for rec in c["results"]:
        assert "agent_revision" not in rec["metadata"]

    c2 = runs_from_experiment(
        "exp-routing-classifier-v3",
        primary_feedback_key="correctness",
        agent_revision="deadbeef",
        client=_experiment_client(),
    )
    assert c2["agent_revision"] == "deadbeef"
    assert all(
        r["metadata"]["agent_revision"] == "deadbeef"
        for r in c2["results"]
    )


# =========================================================================
# reference outputs per workflow
# =========================================================================


def test_workflow_a_populates_expected_from_reference():
    c = runs_from_experiment(
        "exp-routing-classifier-v3",
        primary_feedback_key="correctness",
        client=_experiment_client(),
    )
    by_run = {r["metadata"]["run_id"]: r for r in c["results"]}
    # r03's dataset Example (ex03) outputs {"intent": "billing"}.
    assert by_run["r03"]["expected"] == '{"intent":"billing"}'
    assert by_run["r07"]["expected"] == '{"intent":"technical_support"}'


def test_workflow_b_expected_is_null_or_sourced_from_feedback():
    # Default: no dataset Example → expected is the 'unknown' sentinel.
    c = runs_from_project(
        "support-agent-prod",
        primary_feedback_key=None,
        client=_project_client(),
    )
    assert all(r["expected"] == "unknown" for r in c["results"])

    # With --reference-feedback-key, a feedback value supplies expected.
    c2 = runs_from_project(
        "support-agent-prod",
        primary_feedback_key=None,
        reference_feedback_key="reference_answer",
        client=_project_client(),
    )
    by_run = {r["metadata"]["run_id"]: r for r in c2["results"]}
    assert by_run["r05"]["expected"] == (
        "billing — confirm the duplicate charge and issue a refund"
    )
    # Runs without that feedback key still fall back to the sentinel.
    assert by_run["r08"]["expected"] == "unknown"


# =========================================================================
# v0.2 schema conformance (canonical Draft7 validator)
# =========================================================================


def test_round_trip_validates_against_v0_2_schema():
    jsonschema = pytest.importorskip("jsonschema")
    referencing = pytest.importorskip("referencing")

    spec_v02 = (
        Path(__file__).resolve().parents[2]
        / "agent-diagnosis-spec" / "spec" / "v0.2"
    )
    if not spec_v02.is_dir():
        pytest.skip("agent-diagnosis-spec sibling repo not present")

    resources = []
    for name in (
        "failing-eval.schema.json",
        "failing-eval-container.schema.json",
    ):
        schema = json.loads((spec_v02 / name).read_text())
        resources.append(
            (schema["$id"], referencing.Resource.from_contents(schema))
        )
    registry = referencing.Registry().with_resources(resources)
    container_schema = json.loads(
        (spec_v02 / "failing-eval-container.schema.json").read_text()
    )
    validator = jsonschema.Draft7Validator(
        container_schema, registry=registry
    )

    for golden in (GOLDEN_EXPERIMENT, GOLDEN_PROJECT):
        errors = sorted(
            validator.iter_errors(_load(golden)),
            key=lambda e: list(e.absolute_path),
        )
        assert not errors, f"{golden.name}: {[e.message for e in errors]}"


def test_goldens_round_trip_through_agent_researcher_loader(tmp_path):
    loader = pytest.importorskip("agent_researcher.eval_analyzer")
    for golden in (GOLDEN_EXPERIMENT, GOLDEN_PROJECT):
        container = _load(golden)
        out = tmp_path / golden.name
        out.write_text(json.dumps(container, indent=2) + "\n")
        summary = loader.load_eval_result(out)  # must not raise
        assert summary.total == container["total"]
        assert len(summary.failures) == len(container["results"])
        assert summary.passed + len(summary.failures) == summary.total


# =========================================================================
# pluma diagnose-agent live dispatch (no network, no spend)
# =========================================================================


_CONTAINER = {
    "experiment_id": "exp-x",
    "experiment_name": "exp-x",
    "project_name": "exp-x",
    "total": 2,
    "passed": 1,
    "pass_rate": 0.5,
    "results": [
        {
            "scenario_id": "ex03",
            "expected": "billing",
            "predicted": "account_management",
            "passed": False,
        }
    ],
}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path_factory):
    root = tmp_path_factory.mktemp("pluma_cache")
    monkeypatch.setenv("PLUMA_CACHE_ROOT", str(root))
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)


def _target(tmp_path: Path) -> Path:
    d = tmp_path / "agent"
    d.mkdir()
    return d


def _spy_fetch(record: dict):
    def _fake(**kwargs):
        record.update(kwargs)
        return _CONTAINER

    return _fake


def _capture_agent_diagnose(seen: dict):
    def _fake(*, target_agent, eval_result, output_file, **kw):
        seen["existed_at_call"] = Path(eval_result).is_file()
        seen["container"] = json.loads(Path(eval_result).read_text())
        seen["path"] = Path(eval_result)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("# diagnosed\n")
        return runners.RunResult(output_file, 0)

    return _fake


def test_dispatch_via_pluma_cli_experiment(monkeypatch, tmp_path):
    target = _target(tmp_path)
    out = tmp_path / "out.md"
    sent: dict = {}
    seen: dict = {}
    monkeypatch.setattr(cli, "fetch_runs_as_failing_evals", _spy_fetch(sent))
    monkeypatch.setattr(runners, "agent_diagnose", _capture_agent_diagnose(seen))

    rc = cli.main([
        "diagnose-agent",
        "--target-agent", str(target),
        "--langsmith-experiment-id", "exp-routing-classifier-v3",
        "--primary-feedback-key", "correctness",
        "--output-file", str(out),
    ])

    assert rc == 0
    assert sent["experiment_id"] == "exp-routing-classifier-v3"
    assert sent["project"] is None
    assert sent["primary_feedback_key"] == "correctness"
    assert seen["existed_at_call"] is True
    assert seen["container"] == _CONTAINER
    assert not seen["path"].exists()  # temp file cleaned up
    assert out.read_text() == "# diagnosed\n"


def test_dispatch_via_pluma_cli_project(monkeypatch, tmp_path):
    target = _target(tmp_path)
    out = tmp_path / "out.md"
    sent: dict = {}
    monkeypatch.setattr(cli, "fetch_runs_as_failing_evals", _spy_fetch(sent))
    monkeypatch.setattr(runners, "agent_diagnose", _capture_agent_diagnose({}))

    rc = cli.main([
        "diagnose-agent",
        "--target-agent", str(target),
        "--langsmith-project", "support-agent-prod",
        "--filter", 'eq(feedback_key, "correctness")',
        "--output-file", str(out),
    ])

    assert rc == 0
    assert sent["project"] == "support-agent-prod"
    assert sent["experiment_id"] is None
    assert sent["filter_expression"] == 'eq(feedback_key, "correctness")'


def test_dispatch_langsmith_mutually_exclusive_with_braintrust(
    tmp_path, capsys
):
    target = _target(tmp_path)
    rc = cli.main([
        "diagnose-agent",
        "--target-agent", str(target),
        "--langsmith-experiment-id", "exp-1",
        "--braintrust-experiment-id", "bt-1",
        "--output-file", str(tmp_path / "o.md"),
    ])
    assert rc == 2
    assert "mutually exclusive" in capsys.readouterr().err
