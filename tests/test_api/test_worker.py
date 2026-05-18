"""Worker dispatcher: routing, E4 synthesis, exception translation,
soft cancellation. Sister-tool integrations are mocked — no network."""

from __future__ import annotations

import asyncio

import pytest

from pluma.api import worker
from pluma.api.job_store import JobStore
from pluma.api.models import (
    BraintrustSource,
    CreateJobRequest,
    JobStatus,
    LangSmithSource,
    PostHogSource,
)
from pluma.integrations.braintrust.braintrust_client import BraintrustAPIError
from pluma.integrations.langsmith.langsmith_client import LangSmithAPIError


def _container(results, *, agent_revision=None):
    return {
        "experiment_id": "exp_abc",
        "agent_revision": agent_revision,
        "total": len(results) + 1,
        "passed": 1,
        "pass_rate": 0.5,
        "score_band": {"min": 1.0, "max": 1.0},
        "threshold": 1.0,
        "results": results,
    }


def _row(rid, *, scorer="factuality", score=0.2, metadata=None, spans=None):
    return {
        "scenario_id": rid,
        "scorer": scorer,
        "score": score,
        "metadata": metadata or {"row_id": rid},
        "spans": spans,
    }


def _run(req: CreateJobRequest, store: JobStore) -> str:
    job = store.create(req)
    asyncio.run(worker.run_job(job.job_id, store))
    return job.job_id


def test_braintrust_routes_to_braintrust_and_synthesizes_v01(monkeypatch):
    calls = {}

    def fake_bt(**kw):
        calls["bt"] = kw
        return _container([_row("row_1"), _row("row_2")], agent_revision="sha-x")

    def fake_ls(**kw):  # must NOT be called
        calls["ls"] = kw
        return _container([])

    monkeypatch.setattr(worker, "fetch_experiment_as_failing_evals", fake_bt)
    monkeypatch.setattr(worker, "fetch_runs_as_failing_evals", fake_ls)

    store = JobStore()
    req = CreateJobRequest(
        sources=[
            BraintrustSource(
                type="braintrust", experiment_id="exp_abc",
                primary_scorer="factuality",
            )
        ]
    )
    jid = _run(req, store)

    assert "bt" in calls and "ls" not in calls
    assert calls["bt"]["experiment_id"] == "exp_abc"
    assert calls["bt"]["scorer"] == "factuality"

    job = store.get(jid)
    assert job.status is JobStatus.completed
    fc = store.get_findings(jid)
    assert fc.version == "0.2"
    assert fc.agent_revision == "sha-x"
    assert [e.eval_id for e in fc.evals] == [
        "braintrust:exp_abc:row_1",
        "braintrust:exp_abc:row_2",
    ]
    for e in fc.evals:
        assert e.category == "measurement_instrument"
        assert e.applyable is False
        assert e.edit is None
        assert "factuality" in e.claim


def test_langsmith_routes_and_workflow_maps_to_kwargs(monkeypatch):
    seen = {}

    def fake_ls(**kw):
        seen.update(kw)
        return _container([_row("run_9")], agent_revision="ls-sha")

    monkeypatch.setattr(worker, "fetch_runs_as_failing_evals", fake_ls)

    store = JobStore()
    # project_traced (default) → project + filter_expression kwargs
    req = CreateJobRequest(
        sources=[
            LangSmithSource(
                type="langsmith", project_name="prod",
                filter='eq(feedback_key, "thumbs_down")',
            )
        ]
    )
    jid = _run(req, store)
    assert seen["project"] == "prod"
    assert seen["filter_expression"] == 'eq(feedback_key, "thumbs_down")'
    assert "experiment_id" not in seen
    fc = store.get_findings(jid)
    assert fc.evals[0].eval_id == "langsmith:prod:run_9"

    # dataset_experiment → experiment_id kwarg
    seen.clear()
    store2 = JobStore()
    req2 = CreateJobRequest(
        sources=[
            LangSmithSource(
                type="langsmith", project_name="ds-exp-1",
                workflow="dataset_experiment",
            )
        ]
    )
    _run(req2, store2)
    assert seen["experiment_id"] == "ds-exp-1"
    assert "project" not in seen


def test_braintrust_fetch_error_maps_to_source_fetch_failed(monkeypatch):
    def boom(**kw):
        raise BraintrustAPIError("Braintrust API returned 404", status=404)

    monkeypatch.setattr(worker, "fetch_experiment_as_failing_evals", boom)
    store = JobStore()
    req = CreateJobRequest(
        sources=[BraintrustSource(type="braintrust", experiment_id="exp_404")]
    )
    jid = _run(req, store)
    job = store.get(jid)
    assert job.status is JobStatus.failed
    assert job.error.code == "source_fetch_failed"
    assert job.error.details["source_type"] == "braintrust"
    assert job.error.details["experiment_id"] == "exp_404"
    assert job.error.request_id.startswith("req_")


def test_langsmith_fetch_error_maps_to_source_fetch_failed(monkeypatch):
    def boom(**kw):
        raise LangSmithAPIError("LangSmith API returned 500", status=500)

    monkeypatch.setattr(worker, "fetch_runs_as_failing_evals", boom)
    store = JobStore()
    req = CreateJobRequest(
        sources=[LangSmithSource(type="langsmith", project_name="p")]
    )
    jid = _run(req, store)
    job = store.get(jid)
    assert job.status is JobStatus.failed
    assert job.error.code == "source_fetch_failed"
    assert job.error.details["source_type"] == "langsmith"
    assert job.error.details["project_name"] == "p"


def test_unexpected_exception_maps_to_internal_error(monkeypatch):
    def boom(**kw):
        raise ValueError("kaboom")

    monkeypatch.setattr(worker, "fetch_experiment_as_failing_evals", boom)
    store = JobStore()
    req = CreateJobRequest(
        sources=[BraintrustSource(type="braintrust", experiment_id="e")]
    )
    jid = _run(req, store)
    job = store.get(jid)
    assert job.status is JobStatus.failed
    assert job.error.code == "internal_error"
    assert "kaboom" in job.error.message


def test_posthog_returns_not_implemented_and_skips_fetch(monkeypatch):
    called = {"bt": False, "ls": False}
    monkeypatch.setattr(
        worker,
        "fetch_experiment_as_failing_evals",
        lambda **k: called.__setitem__("bt", True),
    )
    monkeypatch.setattr(
        worker,
        "fetch_runs_as_failing_evals",
        lambda **k: called.__setitem__("ls", True),
    )
    store = JobStore()
    req = CreateJobRequest(
        sources=[PostHogSource(type="posthog", cohort_id="cohort_456")]
    )
    jid = _run(req, store)
    job = store.get(jid)
    assert job.status is JobStatus.failed
    assert job.error.code == "not_implemented"
    assert job.error.message == "PostHog source support is not implemented in v0.1."
    assert job.error.details["source_type"] == "posthog"
    assert job.error.details["cohort_id"] == "cohort_456"
    assert called == {"bt": False, "ls": False}


def test_citation_extracted_from_span_metadata(monkeypatch):
    rows = [
        _row("r_cite", spans=[{"metadata": {"file": "src/a.py", "line": 42}}]),
        _row("r_nocite"),
    ]
    monkeypatch.setattr(
        worker, "fetch_experiment_as_failing_evals", lambda **k: _container(rows)
    )
    store = JobStore()
    req = CreateJobRequest(
        sources=[BraintrustSource(type="braintrust", experiment_id="exp_abc")]
    )
    jid = _run(req, store)
    fc = store.get_findings(jid)
    by_id = {e.eval_id: e for e in fc.evals}
    cited = by_id["braintrust:exp_abc:r_cite"]
    assert cited.citation is not None
    assert cited.citation.file == "src/a.py"
    assert cited.citation.line == 42
    assert by_id["braintrust:exp_abc:r_nocite"].citation is None


def test_multi_source_merge_and_agent_revision_override(monkeypatch):
    monkeypatch.setattr(
        worker,
        "fetch_experiment_as_failing_evals",
        lambda **k: _container([_row("b1")], agent_revision="from-bt"),
    )
    monkeypatch.setattr(
        worker,
        "fetch_runs_as_failing_evals",
        lambda **k: _container([_row("l1")], agent_revision="from-ls"),
    )
    store = JobStore()
    req = CreateJobRequest(
        sources=[
            BraintrustSource(type="braintrust", experiment_id="exp_abc"),
            LangSmithSource(type="langsmith", project_name="prod"),
        ],
        agent_revision="override-sha",
    )
    jid = _run(req, store)
    fc = store.get_findings(jid)
    assert {e.eval_id for e in fc.evals} == {
        "braintrust:exp_abc:b1",
        "langsmith:prod:l1",
    }
    assert fc.agent_revision == "override-sha"  # request override wins


def test_agent_revision_falls_back_to_first_source(monkeypatch):
    monkeypatch.setattr(
        worker,
        "fetch_experiment_as_failing_evals",
        lambda **k: _container([_row("b1")], agent_revision="first-src-sha"),
    )
    store = JobStore()
    req = CreateJobRequest(
        sources=[BraintrustSource(type="braintrust", experiment_id="exp_abc")]
    )
    jid = _run(req, store)
    assert store.get_findings(jid).agent_revision == "first-src-sha"


def test_soft_cancel_before_start_does_not_run(monkeypatch):
    ran = {"v": False}
    monkeypatch.setattr(
        worker,
        "fetch_experiment_as_failing_evals",
        lambda **k: ran.__setitem__("v", True) or _container([]),
    )
    store = JobStore()
    req = CreateJobRequest(
        sources=[BraintrustSource(type="braintrust", experiment_id="e")]
    )
    job = store.create(req)
    store.cancel(job.job_id)  # cancelled while pending
    asyncio.run(worker.run_job(job.job_id, store))
    assert store.get(job.job_id).status is JobStatus.cancelled
    assert ran["v"] is False


def test_soft_cancel_between_sources_stops_before_completion(monkeypatch):
    store = JobStore()

    def cancel_then_return(**kw):
        # First source: cancel the job mid-flight, then return normally
        # (soft cancel — the in-flight call is allowed to finish).
        store.cancel(cancel_then_return.job_id)
        return _container([_row("b1")])

    monkeypatch.setattr(
        worker, "fetch_experiment_as_failing_evals", cancel_then_return
    )
    second_called = {"v": False}
    monkeypatch.setattr(
        worker,
        "fetch_runs_as_failing_evals",
        lambda **k: second_called.__setitem__("v", True) or _container([]),
    )

    req = CreateJobRequest(
        sources=[
            BraintrustSource(type="braintrust", experiment_id="e"),
            LangSmithSource(type="langsmith", project_name="p"),
        ]
    )
    job = store.create(req)
    cancel_then_return.job_id = job.job_id
    asyncio.run(worker.run_job(job.job_id, store))

    assert store.get(job.job_id).status is JobStatus.cancelled
    assert second_called["v"] is False  # cancellation observed between sources
    assert store.get_findings(job.job_id) is None  # never completed
