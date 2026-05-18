"""Thread-safe, in-memory job store.

State lives only in this process — persistence is explicitly out of scope
for v0.1. A single :class:`threading.Lock` guards every mutation; jobs are
replaced (never mutated in place) so a concurrent reader always sees a
consistent snapshot.

ULID-shaped IDs are minted from :mod:`secrets` using the Crockford base32
alphabet (no I/L/O/U), matching the spec patterns
``^job_[0-9A-HJKMNP-TV-Z]{24}$`` and ``^req_[0-9A-HJKMNP-TV-Z]{24}$``.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from .models import (
    CreateJobRequest,
    Error,
    FailingEvalContainer,
    Job,
    JobStatus,
)

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ID_BODY_LEN = 24

# How long an Idempotency-Key replay is honored, and how long findings
# remain retrievable after a job terminates. Both 24h per the spec.
IDEMPOTENCY_WINDOW = timedelta(hours=24)
FINDINGS_RETENTION = timedelta(hours=24)


def now_utc() -> datetime:
    """Timezone-aware current time in UTC."""
    return datetime.now(timezone.utc)


def _crockford_token(n: int = _ID_BODY_LEN) -> str:
    return "".join(secrets.choice(_CROCKFORD) for _ in range(n))


def new_job_id() -> str:
    return "job_" + _crockford_token()


def new_request_id() -> str:
    return "req_" + _crockford_token()


@dataclass
class _Record:
    job: Job
    request: CreateJobRequest
    findings: Optional[FailingEvalContainer] = None
    idempotency_key: Optional[str] = None


@dataclass
class _IdemEntry:
    job_id: str
    created_at: datetime = field(default_factory=now_utc)


class JobStore:
    """In-memory job registry. All public methods are thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, _Record] = {}
        self._idem: dict[str, _IdemEntry] = {}

    # ---- creation ------------------------------------------------------

    def create(self, request: CreateJobRequest) -> Job:
        """Create a fresh ``pending`` job and return it."""
        with self._lock:
            return self._create_locked(request, idempotency_key=None)

    def create_with_idempotency_key(
        self, key: str, request: CreateJobRequest
    ) -> tuple[Job, bool]:
        """Create or replay by ``Idempotency-Key``.

        Returns ``(job, is_replay)``. ``is_replay`` is True when a job for
        this key exists and is within the 24h window — the caller responds
        ``200``. A first submission, or a replay of a key whose original
        job is older than 24h, creates a new job and returns
        ``is_replay=False`` (caller responds ``202``).
        """
        with self._lock:
            entry = self._idem.get(key)
            if entry is not None:
                fresh = now_utc() - entry.created_at < IDEMPOTENCY_WINDOW
                rec = self._jobs.get(entry.job_id)
                if fresh and rec is not None:
                    return rec.job, True
                # Stale key (or its job was evicted): drop and re-create.
                self._idem.pop(key, None)
            job = self._create_locked(request, idempotency_key=key)
            self._idem[key] = _IdemEntry(job_id=job.job_id)
            return job, False

    def _create_locked(
        self, request: CreateJobRequest, *, idempotency_key: Optional[str]
    ) -> Job:
        job_id = new_job_id()
        while job_id in self._jobs:  # astronomically unlikely; still correct
            job_id = new_job_id()
        job = Job(
            job_id=job_id,
            status=JobStatus.pending,
            created_at=now_utc(),
            terminated_at=None,
            error=None,
        )
        self._jobs[job_id] = _Record(
            job=job, request=request, idempotency_key=idempotency_key
        )
        return job

    # ---- reads ---------------------------------------------------------

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            rec = self._jobs.get(job_id)
            return rec.job if rec is not None else None

    def get_request(self, job_id: str) -> Optional[CreateJobRequest]:
        with self._lock:
            rec = self._jobs.get(job_id)
            return rec.request if rec is not None else None

    def get_findings(self, job_id: str) -> Optional[FailingEvalContainer]:
        with self._lock:
            rec = self._jobs.get(job_id)
            return rec.findings if rec is not None else None

    def findings_expired(self, job_id: str) -> bool:
        """True iff the job completed but is past the retention window."""
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None or rec.job.terminated_at is None:
                return False
            if rec.job.status is not JobStatus.completed:
                return False
            return now_utc() - rec.job.terminated_at >= FINDINGS_RETENTION

    # ---- mutations -----------------------------------------------------

    def _replace(self, job_id: str, **updates) -> Optional[Job]:
        rec = self._jobs.get(job_id)
        if rec is None:
            return None
        rec.job = rec.job.model_copy(update=updates)
        return rec.job

    def update_status(
        self, job_id: str, status: JobStatus
    ) -> Optional[Job]:
        """Set status only (e.g. ``pending`` → ``running``).

        No-op if the job is already terminal. Without this guard a
        ``DELETE`` that lands in the worker's pending→running window
        would be clobbered (cancelled job resurrected to ``running``
        with a stale ``terminated_at``). Matches the sticky-terminal
        invariant enforced by :meth:`mark_terminated`, :meth:`set_error`,
        and :meth:`cancel`.
        """
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                return None
            if rec.job.status.is_terminal:
                return rec.job
            return self._replace(job_id, status=status)

    def set_findings(
        self, job_id: str, findings: FailingEvalContainer
    ) -> Optional[Job]:
        """Attach findings. Does not change status — pair with
        :meth:`mark_terminated` to flip the job to ``completed``."""
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                return None
            rec.findings = findings
            return rec.job

    def mark_terminated(
        self, job_id: str, status: JobStatus
    ) -> Optional[Job]:
        """Set a terminal status and stamp ``terminated_at``.

        No-op if the job is already terminal (terminal states are sticky;
        a soft-cancelled job that the worker later tries to complete stays
        cancelled).
        """
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                return None
            if rec.job.status.is_terminal:
                return rec.job
            return self._replace(
                job_id, status=status, terminated_at=now_utc()
            )

    def set_error(self, job_id: str, error: Error) -> Optional[Job]:
        """Record an error and move the job to terminal ``failed``.

        No-op if the job is already terminal (e.g. cancelled before the
        worker observed the failure).
        """
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                return None
            if rec.job.status.is_terminal:
                return rec.job
            return self._replace(
                job_id,
                status=JobStatus.failed,
                error=error,
                terminated_at=now_utc(),
            )

    def cancel(self, job_id: str) -> Optional[Job]:
        """Soft-cancel. Idempotent: cancelling a terminal job is a no-op
        and returns its existing state (spec: DELETE is safe to repeat).

        v0.1 cancellation is *soft* — see ``worker.py``: an in-flight
        sister-tool call is allowed to finish; cancellation is observed
        between source dispatches.
        """
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                return None
            if rec.job.status.is_terminal:
                return rec.job
            return self._replace(
                job_id,
                status=JobStatus.cancelled,
                terminated_at=now_utc(),
            )
