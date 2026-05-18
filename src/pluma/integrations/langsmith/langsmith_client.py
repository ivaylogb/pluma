"""Live LangSmith API client.

A tiny urllib wrapper over the handful of LangSmith REST endpoints the
adapter needs — runs query, feedback, example read, project resolve. It
is deliberately *not* the official ``langsmith`` SDK: the Braintrust
client made the same choice for the same reason — keeping a sister
project off a large, moving SDK surface, and pluma installs no extra
dependency. The method surface mirrors the SDK's verified semantics
(``list_runs`` with ``parent_run_id``/``trace_id``/``is_root``/
``filter``; batched ``list_feedback(run_ids=...)``; ``read_example``).

Authentication: ``LANGSMITH_API_KEY`` (LangSmith's own convention),
sent as the ``x-api-key`` header. ``LANGSMITH_ENDPOINT`` overrides the
base URL for self-hosted instances; ``api_key``/``base_url`` args win
over the environment.

Scope: the network shapes match the published REST/SDK docs (May 2026)
but have not been exercised against a live instance — same status as
the converter. Transport is mocked in tests; no network, no spend.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator

from .runs_to_failing_evals import (
    DEFAULT_MAX_TOTAL_NODES,
    DEFAULT_MAX_TREE_DEPTH,
    DEFAULT_THRESHOLD,
    runs_from_experiment,
    runs_from_project,
)

DEFAULT_BASE_URL = "https://api.smith.langchain.com"
DEFAULT_TIMEOUT_S = 30
DEFAULT_PAGE_LIMIT = 100


class LangSmithAPIError(RuntimeError):
    """Raised on non-2xx responses or transport failure.

    Carries ``status`` (None for transport errors), ``url`` and
    ``body`` so the CLI can render a helpful message without leaking
    the API key.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        url: str = "",
        body: str = "",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.url = url
        self.body = body


@dataclass
class LangSmithClient:
    """Minimal client for the endpoints the adapter needs."""

    api_key: str | None = None
    base_url: str = DEFAULT_BASE_URL
    timeout_s: int = DEFAULT_TIMEOUT_S

    def __post_init__(self) -> None:
        key = self.api_key or os.environ.get("LANGSMITH_API_KEY")
        if not key:
            raise LangSmithAPIError(
                "LANGSMITH_API_KEY not set and api_key not provided."
            )
        self.api_key = key
        env_endpoint = os.environ.get("LANGSMITH_ENDPOINT")
        if env_endpoint and self.base_url == DEFAULT_BASE_URL:
            self.base_url = env_endpoint

    # ---- transport ------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        qs = ""
        if params:
            qs = "?" + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None},
                doseq=True,
            )
        url = f"{self.base_url}{path}{qs}"
        data = None
        headers = {
            "x-api-key": self.api_key,
            "Accept": "application/json",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            url, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:2000]
            except Exception:
                pass
            raise LangSmithAPIError(
                f"LangSmith API returned {e.code} for {path}",
                status=e.code,
                url=url,
                body=err_body,
            ) from e
        except urllib.error.URLError as e:
            raise LangSmithAPIError(
                f"LangSmith API transport error: {e.reason!r}",
                url=url,
            ) from e

    # ---- resolution -----------------------------------------------------

    def resolve_project_id(self, project_name: str) -> str:
        """Resolve a project name to its tracing-session id.

        ``/runs/query`` is keyed by session id; LangSmith's own SDK
        resolves the name the same way before querying.
        """
        listing = self._request(
            "GET", "/api/v1/sessions", params={"name": project_name}
        )
        sessions = (
            listing
            if isinstance(listing, list)
            else listing.get("sessions") or listing.get("objects") or []
        )
        for s in sessions:
            if s.get("name") == project_name or s.get("id"):
                return str(s["id"])
        raise LangSmithAPIError(
            f"No LangSmith project named {project_name!r}."
        )

    # ---- runs -----------------------------------------------------------

    def list_runs(
        self,
        *,
        project_id: str | None = None,
        project_name: str | None = None,
        is_root: bool | None = None,
        parent_run_id: str | None = None,
        trace_id: str | None = None,
        filter: str | None = None,
        limit: int | None = None,
    ) -> Iterator[dict]:
        """POST /runs/query, following the cursor.

        Mirrors the SDK's ``list_runs``: ``parent_run_id`` returns the
        run's *direct* children only (the walker recurses per level);
        ``trace_id`` returns every run in a trace; ``is_root`` limits
        to roots; ``filter`` is the LangSmith filter DSL passed through
        verbatim.
        """
        if project_id is None and project_name is not None:
            project_id = self.resolve_project_id(project_name)

        cursor: str | None = None
        sent = 0
        while True:
            payload: dict[str, Any] = {
                "limit": DEFAULT_PAGE_LIMIT
                if limit is None
                else min(limit - sent, DEFAULT_PAGE_LIMIT),
            }
            if project_id is not None:
                payload["session"] = [project_id]
            if is_root is not None:
                payload["is_root"] = is_root
            if parent_run_id is not None:
                payload["parent_run"] = [parent_run_id]
            if trace_id is not None:
                payload["trace"] = trace_id
            if filter:
                payload["filter"] = filter
            if cursor:
                payload["cursor"] = cursor

            page = self._request("POST", "/api/v1/runs/query", body=payload)
            runs = page.get("runs") or []
            for run in runs:
                yield run
                sent += 1
                if limit is not None and sent >= limit:
                    return
            cursor = page.get("cursor") or (
                (page.get("cursors") or {}).get("next")
            )
            if not cursor or not runs:
                return

    # ---- feedback -------------------------------------------------------

    def list_feedback(self, *, run_ids: list[str]) -> Iterator[dict]:
        """GET /feedback for a batch of run ids (repeated ``run`` query
        param), following the cursor."""
        if not run_ids:
            return
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {
                "run": list(run_ids),
                "limit": DEFAULT_PAGE_LIMIT,
            }
            if cursor:
                params["cursor"] = cursor
            page = self._request("GET", "/api/v1/feedback", params=params)
            items = (
                page
                if isinstance(page, list)
                else page.get("feedback") or page.get("objects") or []
            )
            for fb in items:
                yield fb
            cursor = (
                None
                if isinstance(page, list)
                else page.get("cursor")
                or (page.get("cursors") or {}).get("next")
            )
            if not cursor or not items:
                return

    # ---- examples -------------------------------------------------------

    def read_example(self, example_id: str) -> dict:
        """GET /examples/{id} — the dataset reference case a workflow-A
        run was evaluated against."""
        return self._request("GET", f"/api/v1/examples/{example_id}")


# --------------------------------------------------------------------------
# Live fetch → failing-evals container (shared dispatch)
# --------------------------------------------------------------------------
#
# The standalone CLI's two modes and Pluma's diagnose-agent router all
# need the same thing: pick the workflow, build a client, run the
# converter, hand back the container the agent-researcher loader
# consumes. Factored here — like braintrust_client.fetch_experiment_
# as_failing_evals — so no caller reimplements the dispatch. Pure data
# in, container dict out; LangSmithAPIError propagates for the caller
# to render.


def fetch_runs_as_failing_evals(
    *,
    experiment_id: str | None = None,
    project: str | None = None,
    filter_expression: str | None = None,
    primary_feedback_key: str | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    reference_feedback_key: str | None = None,
    max_tree_depth: int = DEFAULT_MAX_TREE_DEPTH,
    max_total_nodes: int = DEFAULT_MAX_TOTAL_NODES,
    agent_revision: str | None = None,
    api_key: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
) -> dict:
    """Resolve the workflow and convert.

    Exactly one of ``experiment_id`` (workflow A) or ``project``
    (workflow B) must be set; the caller (CLI / router) enforces mutual
    exclusion and reports it in its own UX, but this re-checks so the
    helper is safe to call directly.
    """
    if bool(experiment_id) == bool(project):
        raise LangSmithAPIError(
            "Specify exactly one of experiment_id or project."
        )
    client = LangSmithClient(api_key=api_key, base_url=base_url)

    if experiment_id:
        return runs_from_experiment(
            experiment_id,
            primary_feedback_key=primary_feedback_key,
            threshold=threshold,
            max_tree_depth=max_tree_depth,
            max_total_nodes=max_total_nodes,
            agent_revision=agent_revision,
            client=client,
        )
    return runs_from_project(
        project,
        filter_expression=filter_expression,
        primary_feedback_key=primary_feedback_key,
        threshold=threshold,
        reference_feedback_key=reference_feedback_key,
        max_tree_depth=max_tree_depth,
        max_total_nodes=max_total_nodes,
        agent_revision=agent_revision,
        client=client,
    )


__all__ = [
    "LangSmithAPIError",
    "LangSmithClient",
    "DEFAULT_BASE_URL",
    "fetch_runs_as_failing_evals",
]
