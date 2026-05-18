"""FastAPI app implementing ``openapi.yaml``.

Five endpoints, all under a ``/v1`` prefix:

    POST   /v1/jobs                  createJob
    GET    /v1/jobs/{job_id}         retrieveJob
    DELETE /v1/jobs/{job_id}         cancelJob
    GET    /v1/jobs/{job_id}/findings retrieveJobFindings
    GET    /v1/healthz               healthCheck   (unauthenticated)

Every response — success or error — carries an ``X-Request-Id`` header
(Crockford-ULID, ``req_`` prefix) attached by middleware before the route
runs. Error bodies echo the same id as ``request_id``.

Spec-adjacent note: a PostHog job fails with ``error.code ==
"not_implemented"`` (see ``worker.py``). The findings endpoint surfaces
that as HTTP 501; ``GET /v1/jobs/{job_id}`` still returns the failed job
(200) per the spec's Job schema.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import APIRouter, Depends, FastAPI, Path, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .. import __version__
from .auth import AuthError, init_api_key, verify_api_key
from .job_store import JobStore, new_request_id
from .models import (
    CreateJobRequest,
    Error,
    HealthResponse,
    Job,
    JobFindings,
    JobStatus,
)
from .worker import run_job

_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Strong refs to in-flight worker tasks so the loop doesn't GC them.
_background: set[asyncio.Task] = set()


class ApiError(Exception):
    """A spec-shaped error to return at a chosen HTTP status."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Generate/load the API key and announce it on stderr exactly once.
    init_api_key()
    yield


app = FastAPI(
    title="Pluma Diagnostic API",
    version=__version__,
    lifespan=lifespan,
)

# One store for the process lifetime. In-memory only (v0.1).
store = JobStore()


# --------------------------------------------------------------------------
# Request-id middleware + error helpers
# --------------------------------------------------------------------------


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = new_request_id()
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


def _request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    return rid or new_request_id()


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Optional[dict[str, Any]] = None,
) -> JSONResponse:
    rid = _request_id(request)
    body = Error(
        code=code, message=message, request_id=rid, details=details
    ).model_dump(mode="json", exclude_none=True)
    return JSONResponse(
        status_code=status_code,
        content=body,
        headers={"X-Request-Id": rid},
    )


@app.exception_handler(AuthError)
async def _handle_auth(request: Request, exc: AuthError) -> JSONResponse:
    return _error_response(request, 401, "unauthorized", str(exc))


@app.exception_handler(ApiError)
async def _handle_api_error(
    request: Request, exc: ApiError
) -> JSONResponse:
    return _error_response(
        request, exc.status_code, exc.code, exc.message, exc.details
    )


@app.exception_handler(RequestValidationError)
async def _handle_validation(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    first = errors[0] if errors else {}
    # A malformed JSON body is a 400 bad_request; a well-formed body that
    # fails the schema is a 422 validation_failed.
    if first.get("type") in {"json_invalid", "value_error.jsondecode"}:
        return _error_response(
            request, 400, "bad_request", "Request body is not valid JSON"
        )
    loc = [str(p) for p in first.get("loc", []) if p != "body"]
    field = ""
    for part in loc:
        field += f"[{part}]" if part.isdigit() else (
            f".{part}" if field else part
        )
    return _error_response(
        request,
        422,
        "validation_failed",
        "Request body failed schema validation",
        details={
            "field": field or "(body)",
            "error": first.get("msg", "validation failed"),
        },
    )


@app.exception_handler(Exception)
async def _handle_unexpected(
    request: Request, exc: Exception
) -> JSONResponse:
    rid = _request_id(request)
    return _error_response(
        request,
        500,
        "internal_error",
        f"An unexpected error occurred. Please report request_id {rid}.",
    )


# --------------------------------------------------------------------------
# Routers
# --------------------------------------------------------------------------

system = APIRouter(prefix="/v1", tags=["system"])
jobs = APIRouter(
    prefix="/v1", tags=["jobs"], dependencies=[Depends(verify_api_key)]
)


@system.get("/healthz", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


def _schedule(job_id: str) -> None:
    task = asyncio.create_task(run_job(job_id, store))
    _background.add(task)
    task.add_done_callback(_background.discard)


@jobs.post("/jobs")
async def create_job(request: Request, body: CreateJobRequest) -> Response:
    idem = request.headers.get("Idempotency-Key")
    if idem is not None and not _IDEMPOTENCY_KEY_RE.match(idem):
        raise ApiError(
            422,
            "validation_failed",
            "Invalid Idempotency-Key header",
            details={
                "field": "Idempotency-Key",
                "error": "must match ^[A-Za-z0-9_-]{1,64}$",
            },
        )

    if idem is not None:
        job, is_replay = store.create_with_idempotency_key(idem, body)
        if is_replay:
            return JSONResponse(
                status_code=200, content=job.model_dump(mode="json")
            )
        _schedule(job.job_id)
        return JSONResponse(
            status_code=202, content=job.model_dump(mode="json")
        )

    job = store.create(body)
    _schedule(job.job_id)
    return JSONResponse(
        status_code=202, content=job.model_dump(mode="json")
    )


@jobs.get("/jobs/{job_id}", response_model=Job)
async def retrieve_job(request: Request, job_id: str = Path(...)) -> Job:
    job = store.get(job_id)
    if job is None:
        raise ApiError(
            404,
            "not_found",
            f"No job with id {job_id}",
            details={"job_id": job_id},
        )
    return job


@jobs.delete("/jobs/{job_id}", response_model=Job)
async def cancel_job(request: Request, job_id: str = Path(...)) -> Job:
    job = store.cancel(job_id)
    if job is None:
        raise ApiError(
            404,
            "not_found",
            f"No job with id {job_id}",
            details={"job_id": job_id},
        )
    return job


@jobs.get("/jobs/{job_id}/findings", response_model=JobFindings)
async def retrieve_job_findings(
    request: Request, job_id: str = Path(...)
) -> JobFindings:
    job = store.get(job_id)
    if job is None:
        raise ApiError(
            404,
            "not_found",
            f"No job with id {job_id}",
            details={"job_id": job_id},
        )

    # PostHog stub: the worker failed the job with `not_implemented`.
    # Surface it as 501 here (the spec's Job schema still lets
    # GET /v1/jobs/{job_id} return this failed job at 200).
    if (
        job.status is JobStatus.failed
        and job.error is not None
        and job.error.code == "not_implemented"
    ):
        raise ApiError(
            501,
            "not_implemented",
            job.error.message,
            details=job.error.details,
        )

    if job.status is not JobStatus.completed:
        raise ApiError(
            409,
            "job_not_complete",
            f"Job is in status '{job.status.value}'. Wait for status "
            "'completed' before fetching findings.",
            details={
                "job_id": job_id,
                "current_status": job.status.value,
            },
        )

    if store.findings_expired(job_id):
        raise ApiError(
            410,
            "findings_expired",
            "Findings have expired and are no longer retrievable.",
            details={"job_id": job_id},
        )

    findings = store.get_findings(job_id)
    if findings is None:  # completed but no container — defensive
        raise ApiError(
            410,
            "findings_expired",
            "Findings are no longer retrievable.",
            details={"job_id": job_id},
        )
    return JobFindings(
        job_id=job_id, status=JobStatus.completed, findings=findings
    )


app.include_router(system)
app.include_router(jobs)
