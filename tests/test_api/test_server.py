"""End-to-end API behavior via FastAPI TestClient.

Auth, full job lifecycle, idempotency status codes, cancellation, 404,
409-before-complete, validation errors, and the PostHog → 501 stub.
Sister-tool fetches are monkeypatched — no network, no spend.
"""

from __future__ import annotations

import re
import threading
import time

import pytest
from fastapi.testclient import TestClient

from pluma.api import auth, server, worker
from pluma.api.job_store import JobStore

JOB_RE = re.compile(r"^job_[0-9A-HJKMNP-TV-Z]{24}$")
REQ_RE = re.compile(r"^req_[0-9A-HJKMNP-TV-Z]{24}$")
API_KEY = "plm_TEST00000000000000000000AB"

_INSTANT_CONTAINER = {
    "experiment_id": "exp_abc",
    "agent_revision": "sha-test",
    "total": 2,
    "passed": 1,
    "pass_rate": 0.5,
    "score_band": {"min": 1.0, "max": 1.0},
    "threshold": 1.0,
    "results": [
        {
            "scenario_id": "row_1",
            "scorer": "factuality",
            "score": 0.1,
            "metadata": {"row_id": "row_1"},
            "spans": None,
        }
    ],
}


@pytest.fixture
def gate():
    """A latch a fetch fake can block on, to hold a job 'running'."""
    return threading.Event()


@pytest.fixture
def client(monkeypatch, gate):
    monkeypatch.setenv("PLUMA_API_KEY", API_KEY)
    # Reset the announce/load singleton so the fixture's key is picked up.
    monkeypatch.setattr(auth, "_api_key", None, raising=False)
    monkeypatch.setattr(auth, "_announced", False, raising=False)
    # Fresh store per test.
    monkeypatch.setattr(server, "store", JobStore())

    def instant_bt(**kw):
        return dict(_INSTANT_CONTAINER)

    def instant_ls(**kw):
        return dict(_INSTANT_CONTAINER)

    monkeypatch.setattr(worker, "fetch_experiment_as_failing_evals", instant_bt)
    monkeypatch.setattr(worker, "fetch_runs_as_failing_evals", instant_ls)

    with TestClient(server.app) as c:
        c._gate = gate  # tests that want a blocking fake set it up themselves
        yield c


def _auth():
    return {"X-Pluma-Key": API_KEY}


def _poll(client, job_id, want, timeout=5.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = client.get(f"/v1/jobs/{job_id}", headers=_auth())
        last = r.json()
        if last["status"] == want:
            return last
        time.sleep(0.02)
    raise AssertionError(f"job never reached {want!r}; last={last}")


# ---- auth -----------------------------------------------------------------


def test_healthz_is_unauthenticated_and_has_request_id(client):
    r = client.get("/v1/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": "0.1.0"}
    assert REQ_RE.match(r.headers["X-Request-Id"])


def test_missing_key_is_401_unauthorized(client):
    r = client.post("/v1/jobs", json={"sources": [{"type": "braintrust", "experiment_id": "e"}]})
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "unauthorized"
    assert REQ_RE.match(body["request_id"])
    assert r.headers["X-Request-Id"] == body["request_id"]


def test_wrong_key_is_401(client):
    r = client.post(
        "/v1/jobs",
        headers={"X-Pluma-Key": "plm_WRONG0000000000000000000X"},
        json={"sources": [{"type": "braintrust", "experiment_id": "e"}]},
    )
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


def test_valid_key_creates_job(client):
    r = client.post(
        "/v1/jobs",
        headers=_auth(),
        json={"sources": [{"type": "braintrust", "experiment_id": "exp_abc"}]},
    )
    assert r.status_code == 202
    body = r.json()
    assert JOB_RE.match(body["job_id"])
    assert body["status"] == "pending"
    assert body["terminated_at"] is None
    assert body["error"] is None


# ---- lifecycle ------------------------------------------------------------


def test_full_lifecycle_create_poll_findings(client):
    r = client.post(
        "/v1/jobs",
        headers=_auth(),
        json={"sources": [{"type": "braintrust", "experiment_id": "exp_abc"}]},
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    done = _poll(client, job_id, "completed")
    assert done["terminated_at"] is not None
    assert done["error"] is None

    f = client.get(f"/v1/jobs/{job_id}/findings", headers=_auth())
    assert f.status_code == 200
    fb = f.json()
    assert fb["job_id"] == job_id
    assert fb["status"] == "completed"
    assert fb["findings"]["version"] == "0.2"
    assert fb["findings"]["evals"][0]["eval_id"] == "braintrust:exp_abc:row_1"
    assert fb["findings"]["evals"][0]["category"] == "measurement_instrument"
    assert fb["findings"]["evals"][0]["applyable"] is False


# ---- idempotency ----------------------------------------------------------


def test_idempotency_replay_returns_200_not_202(client):
    payload = {"sources": [{"type": "braintrust", "experiment_id": "exp_abc"}]}
    h = {**_auth(), "Idempotency-Key": "retry-abc"}
    r1 = client.post("/v1/jobs", headers=h, json=payload)
    assert r1.status_code == 202
    jid = r1.json()["job_id"]
    r2 = client.post("/v1/jobs", headers=h, json=payload)
    assert r2.status_code == 200
    assert r2.json()["job_id"] == jid


def test_bad_idempotency_key_is_422(client):
    r = client.post(
        "/v1/jobs",
        headers={**_auth(), "Idempotency-Key": "bad key!"},
        json={"sources": [{"type": "braintrust", "experiment_id": "e"}]},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "validation_failed"


# ---- cancellation ---------------------------------------------------------


def test_delete_marks_cancelled_and_is_idempotent(client, gate, monkeypatch):
    # Hold the job non-terminal (blocked in fetch) so DELETE exercises the
    # real cancel path rather than racing a fast completion.
    def blocking(**kw):
        gate.wait(timeout=5)
        return dict(_INSTANT_CONTAINER)

    monkeypatch.setattr(worker, "fetch_experiment_as_failing_evals", blocking)

    r = client.post(
        "/v1/jobs",
        headers=_auth(),
        json={"sources": [{"type": "braintrust", "experiment_id": "exp_abc"}]},
    )
    job_id = r.json()["job_id"]
    d = client.delete(f"/v1/jobs/{job_id}", headers=_auth())
    assert d.status_code == 200
    assert d.json()["status"] == "cancelled"
    assert d.json()["terminated_at"] is not None
    # Repeat DELETE is safe and still reports cancelled.
    d2 = client.delete(f"/v1/jobs/{job_id}", headers=_auth())
    assert d2.status_code == 200 and d2.json()["status"] == "cancelled"

    # Release the fetch; soft-cancel means the worker observes the
    # cancellation and does NOT flip the job to completed.
    gate.set()
    g = None
    for _ in range(100):
        g = client.get(f"/v1/jobs/{job_id}", headers=_auth()).json()
        time.sleep(0.02)
        if g["status"] != "cancelled":
            break
    assert g["status"] == "cancelled"
    # Findings on a cancelled job is 409, not 200.
    f = client.get(f"/v1/jobs/{job_id}/findings", headers=_auth())
    assert f.status_code == 409


# ---- not found ------------------------------------------------------------


def test_unknown_job_is_404_everywhere(client):
    jid = "job_00000000000000000000000Z"
    for r in (
        client.get(f"/v1/jobs/{jid}", headers=_auth()),
        client.delete(f"/v1/jobs/{jid}", headers=_auth()),
        client.get(f"/v1/jobs/{jid}/findings", headers=_auth()),
    ):
        assert r.status_code == 404
        assert r.json()["code"] == "not_found"
        assert r.json()["details"]["job_id"] == jid


# ---- findings before complete --------------------------------------------


def test_findings_before_complete_is_409(client, gate, monkeypatch):
    # A fetch fake that blocks until the test releases it keeps the job
    # in 'running' so we can probe the findings endpoint.
    def blocking(**kw):
        gate.wait(timeout=5)
        return dict(_INSTANT_CONTAINER)

    monkeypatch.setattr(worker, "fetch_experiment_as_failing_evals", blocking)

    r = client.post(
        "/v1/jobs",
        headers=_auth(),
        json={"sources": [{"type": "braintrust", "experiment_id": "exp_abc"}]},
    )
    job_id = r.json()["job_id"]

    f = client.get(f"/v1/jobs/{job_id}/findings", headers=_auth())
    assert f.status_code == 409
    body = f.json()
    assert body["code"] == "job_not_complete"
    assert body["details"]["job_id"] == job_id
    assert body["details"]["current_status"] in {"pending", "running"}

    gate.set()
    _poll(client, job_id, "completed")


# ---- validation -----------------------------------------------------------


def test_empty_sources_is_422_validation_failed(client):
    r = client.post("/v1/jobs", headers=_auth(), json={"sources": []})
    assert r.status_code == 422
    b = r.json()
    assert b["code"] == "validation_failed"
    assert "sources" in b["details"]["field"]


def test_missing_required_source_field_is_422(client):
    r = client.post(
        "/v1/jobs", headers=_auth(), json={"sources": [{"type": "braintrust"}]}
    )
    assert r.status_code == 422
    assert r.json()["code"] == "validation_failed"
    assert "experiment_id" in r.json()["details"]["field"]


def test_unknown_source_type_is_422(client):
    r = client.post(
        "/v1/jobs", headers=_auth(), json={"sources": [{"type": "nope"}]}
    )
    assert r.status_code == 422
    assert r.json()["code"] == "validation_failed"


def test_invalid_json_body_is_400_bad_request(client):
    r = client.post(
        "/v1/jobs",
        headers={**_auth(), "Content-Type": "application/json"},
        content="{not valid json",
    )
    assert r.status_code == 400
    assert r.json()["code"] == "bad_request"


# ---- PostHog → 501 stub ---------------------------------------------------


def test_posthog_job_fails_not_implemented_and_findings_is_501(client):
    r = client.post(
        "/v1/jobs",
        headers=_auth(),
        json={"sources": [{"type": "posthog", "cohort_id": "cohort_456"}]},
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    failed = _poll(client, job_id, "failed")
    # GET /v1/jobs/{id} stays spec-faithful: 200 with the failed job.
    assert failed["error"]["code"] == "not_implemented"

    f = client.get(f"/v1/jobs/{job_id}/findings", headers=_auth())
    assert f.status_code == 501
    assert f.json()["code"] == "not_implemented"
    assert f.json()["details"]["source_type"] == "posthog"
