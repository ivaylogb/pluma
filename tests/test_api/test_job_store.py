"""JobStore: ULID format, idempotency window, concurrency races."""

from __future__ import annotations

import re
import threading
from datetime import timedelta

import pytest

from pluma.api.job_store import (
    IDEMPOTENCY_WINDOW,
    JobStore,
    new_job_id,
    new_request_id,
    now_utc,
)
from pluma.api.models import (
    BraintrustSource,
    CreateJobRequest,
    Error,
    FailingEvalContainer,
    JobStatus,
)

JOB_RE = re.compile(r"^job_[0-9A-HJKMNP-TV-Z]{24}$")
REQ_RE = re.compile(r"^req_[0-9A-HJKMNP-TV-Z]{24}$")
_FORBIDDEN = set("ILOU")


def _req() -> CreateJobRequest:
    return CreateJobRequest(
        sources=[BraintrustSource(type="braintrust", experiment_id="exp_1")]
    )


def test_generated_ids_match_crockford_ulid_pattern():
    for _ in range(2000):
        jid = new_job_id()
        rid = new_request_id()
        assert JOB_RE.match(jid), jid
        assert REQ_RE.match(rid), rid
        # Crockford excludes I, L, O, U entirely.
        assert not (_FORBIDDEN & set(jid[4:]))
        assert not (_FORBIDDEN & set(rid[4:]))


def test_create_get_roundtrip_and_unknown():
    store = JobStore()
    job = store.create(_req())
    assert job.status is JobStatus.pending
    assert store.get(job.job_id).job_id == job.job_id
    assert store.get("job_000000000000000000000000") is None


def test_idempotency_replay_within_window():
    store = JobStore()
    j1, replay1 = store.create_with_idempotency_key("k-1", _req())
    assert replay1 is False
    j2, replay2 = store.create_with_idempotency_key("k-1", _req())
    assert replay2 is True
    assert j1.job_id == j2.job_id
    # A different key is a different job.
    j3, replay3 = store.create_with_idempotency_key("k-2", _req())
    assert replay3 is False and j3.job_id != j1.job_id


def test_idempotency_window_expiry_not_honored():
    store = JobStore()
    j1, _ = store.create_with_idempotency_key("stale", _req())
    # Age the recorded entry past the 24h window.
    store._idem["stale"].created_at = now_utc() - IDEMPOTENCY_WINDOW - timedelta(
        minutes=1
    )
    j2, replay = store.create_with_idempotency_key("stale", _req())
    assert replay is False
    assert j2.job_id != j1.job_id


def test_terminal_states_are_sticky():
    store = JobStore()
    job = store.create(_req())
    store.cancel(job.job_id)
    assert store.get(job.job_id).status is JobStatus.cancelled
    # A late completion attempt must not resurrect a cancelled job.
    store.set_findings(job.job_id, FailingEvalContainer(version="0.2", evals=[]))
    store.mark_terminated(job.job_id, JobStatus.completed)
    assert store.get(job.job_id).status is JobStatus.cancelled
    # set_error on a terminal job is a no-op too.
    store.set_error(
        job.job_id,
        Error(code="internal_error", message="x", request_id=new_request_id()),
    )
    assert store.get(job.job_id).status is JobStatus.cancelled


def test_update_status_does_not_clobber_cancelled_job():
    """Regression for bug W1.

    Simulates the worker race: a DELETE (cancel) lands between the
    worker's pending→running check and its update_status(running) call.
    update_status must be a no-op on a terminal job — the cancellation
    must survive and terminated_at must be preserved (not left non-null
    against a 'running' status).
    """
    store = JobStore()
    job = store.create(_req())
    cancelled = store.cancel(job.job_id)
    assert cancelled.status is JobStatus.cancelled
    terminated_at = cancelled.terminated_at
    assert terminated_at is not None

    after = store.update_status(job.job_id, JobStatus.running)
    assert after.status is JobStatus.cancelled  # not resurrected
    assert after.terminated_at == terminated_at  # preserved, not stale
    assert store.get(job.job_id).status is JobStatus.cancelled


def test_cancel_unknown_returns_none_and_is_idempotent():
    store = JobStore()
    assert store.cancel("job_000000000000000000000000") is None
    job = store.create(_req())
    assert store.cancel(job.job_id).status is JobStatus.cancelled
    assert store.cancel(job.job_id).status is JobStatus.cancelled  # repeat OK


def test_concurrent_create_and_update_races():
    store = JobStore()
    ids: list[str] = []
    ids_lock = threading.Lock()
    errors: list[BaseException] = []

    def worker():
        try:
            for _ in range(50):
                j = store.create(_req())
                with ids_lock:
                    ids.append(j.job_id)
                store.update_status(j.job_id, JobStatus.running)
                store.mark_terminated(j.job_id, JobStatus.completed)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(ids) == 8 * 50
    assert len(set(ids)) == len(ids)  # all unique
    for jid in ids:
        assert store.get(jid).status is JobStatus.completed


def test_findings_expiry_flag():
    store = JobStore()
    job = store.create(_req())
    store.set_findings(job.job_id, FailingEvalContainer(version="0.2", evals=[]))
    store.mark_terminated(job.job_id, JobStatus.completed)
    assert store.findings_expired(job.job_id) is False
    # Backdate termination beyond retention.
    rec = store._jobs[job.job_id]
    rec.job = rec.job.model_copy(
        update={"terminated_at": now_utc() - timedelta(hours=25)}
    )
    assert store.findings_expired(job.job_id) is True
