"""Pydantic v2 models for the Pluma HTTP API.

Every model here is a direct, hand-checked transcription of a schema in
``openapi.yaml`` (this directory) — the spec is authoritative; these
models exist so FastAPI can validate and serialize against it, not to
re-derive it. ``tests/test_schema_internal_consistency.py`` asserts the
two stay in step (required fields, patterns, reachable refs).

Datetime policy: every timestamp is timezone-aware UTC and serializes as
RFC 3339 with a trailing ``Z`` (e.g. ``2026-05-18T12:00:00Z``), matching
the spec examples.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field, PlainSerializer, field_validator

# --------------------------------------------------------------------------
# Scalars
# --------------------------------------------------------------------------

# Crockford base32, no I/L/O/U — must match the spec patterns exactly.
JOB_ID_PATTERN = r"^job_[0-9A-HJKMNP-TV-Z]{24}$"
REQUEST_ID_PATTERN = r"^req_[0-9A-HJKMNP-TV-Z]{24}$"

JobId = Annotated[str, Field(pattern=JOB_ID_PATTERN)]
RequestId = Annotated[str, Field(pattern=REQUEST_ID_PATTERN)]


def _to_rfc3339(value: datetime) -> str:
    """Serialize a tz-aware datetime as RFC 3339 with a ``Z`` suffix."""
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


UtcDateTime = Annotated[
    datetime,
    PlainSerializer(_to_rfc3339, return_type=str, when_used="json"),
]


class JobStatus(str, Enum):
    """Job lifecycle state. See the spec's JobStatus schema."""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (
            JobStatus.completed,
            JobStatus.failed,
            JobStatus.cancelled,
        )


# --------------------------------------------------------------------------
# Sources (discriminated union on `type`)
# --------------------------------------------------------------------------


class BraintrustSource(BaseModel):
    type: Literal["braintrust"]
    experiment_id: str = Field(max_length=128)
    primary_scorer: Optional[str] = Field(default=None, max_length=64)


class LangSmithSource(BaseModel):
    type: Literal["langsmith"]
    project_name: str = Field(max_length=128)
    filter: Optional[str] = Field(default=None, max_length=512)
    workflow: Literal["dataset_experiment", "project_traced"] = "project_traced"


class PostHogSource(BaseModel):
    type: Literal["posthog"]
    cohort_id: str = Field(max_length=128)


Source = Annotated[
    Union[BraintrustSource, LangSmithSource, PostHogSource],
    Field(discriminator="type"),
]


class CreateJobRequest(BaseModel):
    sources: list[Source] = Field(min_length=1, max_length=10)
    agent_revision: Optional[str] = Field(default=None, max_length=64)


# --------------------------------------------------------------------------
# Findings (agent-diagnosis-spec v0.2 shape; v0.1 capability subset)
# --------------------------------------------------------------------------


class Citation(BaseModel):
    file: str
    line: int = Field(ge=1)


class Edit(BaseModel):
    path: str
    before: str
    after: str


class FailingEval(BaseModel):
    """One failing eval surfaced by the API.

    v0.1 populates ``eval_id``/``claim``/``category`` honestly and leaves
    ``citation``/``edit`` null unless source metadata supplies a citation;
    ``applyable`` is always false. See the spec's ``x-version-capability``.
    """

    eval_id: str
    category: Literal[
        "measurement_instrument",
        "interface",
        "context_at_decision",
        "call_sequence",
    ]
    claim: str
    citation: Optional[Citation] = None
    applyable: bool = False
    edit: Optional[Edit] = None


class FailingEvalContainer(BaseModel):
    version: Literal["0.2"] = "0.2"
    evals: list[FailingEval] = Field(default_factory=list)
    agent_revision: Optional[str] = None


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class Error(BaseModel):
    code: str
    message: str
    request_id: RequestId
    details: Optional[dict[str, Any]] = None


# --------------------------------------------------------------------------
# Job resource + sub-resources
# --------------------------------------------------------------------------


class Job(BaseModel):
    job_id: JobId
    status: JobStatus
    created_at: UtcDateTime
    terminated_at: Optional[UtcDateTime] = None
    error: Optional[Error] = None

    @field_validator("created_at", "terminated_at")
    @classmethod
    def _require_tz_aware(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return v
        if v.tzinfo is None:
            # Defensive: never store a naive timestamp. Treat as UTC.
            return v.replace(tzinfo=timezone.utc)
        return v


class JobFindings(BaseModel):
    job_id: JobId
    status: JobStatus
    findings: FailingEvalContainer


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


__all__ = [
    "JOB_ID_PATTERN",
    "REQUEST_ID_PATTERN",
    "JobId",
    "RequestId",
    "UtcDateTime",
    "JobStatus",
    "BraintrustSource",
    "LangSmithSource",
    "PostHogSource",
    "Source",
    "CreateJobRequest",
    "Citation",
    "Edit",
    "FailingEval",
    "FailingEvalContainer",
    "Error",
    "Job",
    "JobFindings",
    "HealthResponse",
]
