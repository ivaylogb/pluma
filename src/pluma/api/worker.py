"""The diagnostic worker — a source-type dispatcher.

This module owns *all* source-type-to-sister-tool routing. Nothing
outside ``worker.py`` decides which integration handles a source.

Dispatch table (v0.1):

    BraintrustSource → braintrust integration  (fetch_experiment_as_failing_evals)
    LangSmithSource  → langsmith integration   (fetch_runs_as_failing_evals)
    PostHogSource    → not implemented in v0.1  → structured `not_implemented`
                       error; the findings endpoint surfaces it as HTTP 501.
                       PostHog → integration-watcher is v0.2 work (there is no
                       live PostHog fetch in the codebase yet — only an
                       offline events→traces converter).

Findings synthesis (the "E4" pattern — rich schema, honest v0.1
population). The braintrust/langsmith integrations return the
agent-diagnosis-spec v0.2 *input* container (a `results` array of failing
rows); v0.1 does not run the LLM diagnosis loop, so each emitted
``FailingEval`` is populated only with what is truthfully known from
source data:

    eval_id   "braintrust:<exp_id>:<row_id>" / "langsmith:<project>:<run_id>"
    claim     short source-data summary (failing-row count, score band, scorer)
    category  always "measurement_instrument" (accurate per the spec's
              capability table — we observed a failing eval, nothing deeper)
    citation  lifted from source span/row metadata if it carries file:line,
              else null
    applyable always false
    edit      always null

Concurrency: sister-tool fetches are synchronous, so they run via
``asyncio.to_thread`` to keep FastAPI's event loop unblocked.

Cancellation is *soft* in v0.1: an in-flight sister-tool call is allowed
to finish. The job's status is checked between source dispatches and
before the terminal transition. Hard cancellation (interrupting an
in-flight sister-tool call mid-fetch) is a v0.2 concern.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from ..integrations.braintrust.braintrust_client import (
    BraintrustAPIError,
    fetch_experiment_as_failing_evals,
)
from ..integrations.langsmith.langsmith_client import (
    LangSmithAPIError,
    fetch_runs_as_failing_evals,
)
from .job_store import JobStore, new_request_id
from .models import (
    BraintrustSource,
    Citation,
    CreateJobRequest,
    Error,
    FailingEval,
    FailingEvalContainer,
    JobStatus,
    LangSmithSource,
    PostHogSource,
)


# --------------------------------------------------------------------------
# Citation extraction (best-effort, v0.1)
# --------------------------------------------------------------------------


def _coerce_line(value: Any) -> Optional[int]:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 1 else None


def _citation_from_obj(obj: Any) -> Optional[Citation]:
    """A Citation if ``obj`` is a dict carrying both a file and a line."""
    if not isinstance(obj, dict):
        return None
    file = obj.get("file") or obj.get("filename") or obj.get("path")
    line = obj.get("line")
    if line is None:
        line = obj.get("lineno")
    if not isinstance(file, str) or not file:
        return None
    n = _coerce_line(line)
    if n is None:
        return None
    return Citation(file=file, line=n)


def _extract_citation(row: dict) -> Optional[Citation]:
    """Look for a ``file:line`` in a failing row's metadata or spans.

    v0.1 only surfaces a citation the source already provides; it never
    infers one (that is structural diagnosis — v0.2 work).
    """
    cite = _citation_from_obj(row.get("metadata"))
    if cite is not None:
        return cite
    spans = row.get("spans")
    if isinstance(spans, list):
        for span in spans:
            cite = _citation_from_obj(span)
            if cite is not None:
                return cite
            if isinstance(span, dict):
                cite = _citation_from_obj(span.get("metadata"))
                if cite is not None:
                    return cite
    return None


# --------------------------------------------------------------------------
# Container → FailingEval synthesis
# --------------------------------------------------------------------------


def _row_id(row: dict) -> str:
    meta = row.get("metadata") or {}
    return str(
        meta.get("row_id")
        or row.get("scenario_id")
        or row.get("id")
        or "unknown"
    )


def _band_str(container: dict) -> str:
    band = container.get("score_band")
    if isinstance(band, dict) and "min" in band and "max" in band:
        return f"[{band['min']}, {band['max']}]"
    thr = container.get("threshold")
    return f"[{thr}, 1.0]" if thr is not None else "[unspecified]"


def _synthesize_evals(
    *, source_prefix: str, container_scope: str, container: dict
) -> list[FailingEval]:
    """Turn a failing-evals container into honest v0.1 ``FailingEval``s.

    ``source_prefix`` is ``braintrust:<exp_id>`` or
    ``langsmith:<project>``; ``container_scope`` is a human label used in
    the claim text (the experiment id or project name).
    """
    rows = container.get("results") or []
    n = len(rows)
    band = _band_str(container)
    evals: list[FailingEval] = []
    for row in rows:
        rid = _row_id(row)
        scorer = row.get("scorer")
        score = row.get("score")
        claim = (
            f"{n} failing row(s) in {container_scope}; this row "
            f"({rid}) failed scorer {scorer!r} with score {score} "
            f"outside the pass band {band}."
        )
        evals.append(
            FailingEval(
                eval_id=f"{source_prefix}:{rid}",
                category="measurement_instrument",
                claim=claim,
                citation=_extract_citation(row),
                applyable=False,
                edit=None,
            )
        )
    return evals


# --------------------------------------------------------------------------
# Per-source dispatch
# --------------------------------------------------------------------------


async def _dispatch_braintrust(
    source: BraintrustSource, agent_revision: Optional[str]
) -> tuple[list[FailingEval], Optional[str]]:
    container = await asyncio.to_thread(
        fetch_experiment_as_failing_evals,
        experiment_id=source.experiment_id,
        scorer=source.primary_scorer,
        agent_revision=agent_revision,
    )
    evals = _synthesize_evals(
        source_prefix=f"braintrust:{source.experiment_id}",
        container_scope=f"Braintrust experiment {source.experiment_id}",
        container=container,
    )
    return evals, container.get("agent_revision")


async def _dispatch_langsmith(
    source: LangSmithSource, agent_revision: Optional[str]
) -> tuple[list[FailingEval], Optional[str]]:
    # The spec's LangSmithSource carries only a project name; map the
    # workflow onto the integration's two modes. `dataset_experiment`
    # treats the project name as a Dataset-Experiment id (workflow A);
    # `project_traced` walks production traces with the optional filter
    # (workflow B).
    if source.workflow == "dataset_experiment":
        kwargs: dict[str, Any] = {"experiment_id": source.project_name}
    else:
        kwargs = {
            "project": source.project_name,
            "filter_expression": source.filter,
        }
    container = await asyncio.to_thread(
        fetch_runs_as_failing_evals,
        agent_revision=agent_revision,
        **kwargs,
    )
    evals = _synthesize_evals(
        source_prefix=f"langsmith:{source.project_name}",
        container_scope=f"LangSmith project {source.project_name}",
        container=container,
    )
    return evals, container.get("agent_revision")


# --------------------------------------------------------------------------
# Worker entrypoint
# --------------------------------------------------------------------------


def _is_cancelled(store: JobStore, job_id: str) -> bool:
    job = store.get(job_id)
    return job is not None and job.status is JobStatus.cancelled


async def run_job(job_id: str, store: JobStore) -> None:
    """Run a job to a terminal state. Never raises — every failure path
    is translated into a structured ``Error`` on the job."""
    request: Optional[CreateJobRequest] = store.get_request(job_id)
    if request is None:  # job evicted or unknown — nothing to do
        return

    # If the job was cancelled while still pending, don't start work.
    if _is_cancelled(store, job_id):
        return
    store.update_status(job_id, JobStatus.running)

    all_evals: list[FailingEval] = []
    resolved_revision: Optional[str] = request.agent_revision

    for idx, source in enumerate(request.sources):
        # Soft cancellation: observed between source dispatches.
        if _is_cancelled(store, job_id):
            return

        try:
            if isinstance(source, PostHogSource):
                # PostHog → integration-watcher is v0.2 work. There is no
                # live PostHog fetch in the codebase (only an offline
                # events→traces converter), so v0.1 fails the job with a
                # structured `not_implemented`; the findings endpoint
                # surfaces this as HTTP 501.
                store.set_error(
                    job_id,
                    Error(
                        code="not_implemented",
                        message="PostHog source support is not implemented in v0.1.",
                        request_id=new_request_id(),
                        details={
                            "source_type": "posthog",
                            "cohort_id": source.cohort_id,
                        },
                    ),
                )
                return

            if isinstance(source, BraintrustSource):
                evals, rev = await _dispatch_braintrust(
                    source, request.agent_revision
                )
            elif isinstance(source, LangSmithSource):
                evals, rev = await _dispatch_langsmith(
                    source, request.agent_revision
                )
            else:  # unreachable: Source is a closed union
                raise RuntimeError(
                    f"unhandled source type: {type(source).__name__}"
                )

        except BraintrustAPIError as e:
            store.set_error(
                job_id,
                Error(
                    code="source_fetch_failed",
                    message=str(e),
                    request_id=new_request_id(),
                    details={
                        "source_type": "braintrust",
                        "experiment_id": getattr(
                            source, "experiment_id", None
                        ),
                    },
                ),
            )
            return
        except LangSmithAPIError as e:
            store.set_error(
                job_id,
                Error(
                    code="source_fetch_failed",
                    message=str(e),
                    request_id=new_request_id(),
                    details={
                        "source_type": "langsmith",
                        "project_name": getattr(
                            source, "project_name", None
                        ),
                    },
                ),
            )
            return
        except Exception as e:  # noqa: BLE001 — every Exception → Error
            store.set_error(
                job_id,
                Error(
                    code="internal_error",
                    message=f"{type(e).__name__}: {e}",
                    request_id=new_request_id(),
                    details={
                        "source_type": getattr(source, "type", "unknown"),
                        "source_index": idx,
                    },
                ),
            )
            return

        all_evals.extend(evals)
        # Preserve the request override; otherwise take the first source's
        # resolved revision.
        if request.agent_revision is None and resolved_revision is None:
            resolved_revision = rev

    # Final cancellation check before the terminal transition.
    if _is_cancelled(store, job_id):
        return

    container = FailingEvalContainer(
        version="0.2",
        evals=all_evals,
        agent_revision=resolved_revision,
    )
    store.set_findings(job_id, container)
    store.mark_terminated(job_id, JobStatus.completed)
