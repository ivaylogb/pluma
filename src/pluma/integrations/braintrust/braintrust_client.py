"""Live Braintrust API client.

The original adapter reads a pre-exported experiment JSON file. That
makes the workflow four steps long: run eval in Braintrust → export
from UI → save locally → run adapter. This module collapses it to one:
``pluma diagnose-agent --braintrust-experiment-id <id>`` (or
``--braintrust-latest <project>``) hits the API, pulls the experiment
with its spans, runs the converter inline, and feeds agent-researcher.

Authentication: a Braintrust API key is read from ``BRAINTRUST_API_KEY``
(matching Braintrust's own SDK convention). Pass ``api_key`` directly
to ``BraintrustClient`` for tests.

Scope: this client wraps just the endpoints the adapter actually needs
(``experiment``, ``experiment/{id}/fetch`` for rows, optional
``experiment/{id}/spans`` for trace data). It is not a general-purpose
Braintrust SDK — for that, use Braintrust's official one. The point of
keeping it tiny is to avoid pinning the whole sister project on a
moving SDK surface.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator

DEFAULT_BASE_URL = "https://api.braintrust.dev/v1"
DEFAULT_TIMEOUT_S = 30
DEFAULT_PAGE_LIMIT = 100


class BraintrustAPIError(RuntimeError):
    """Raised on non-2xx responses or transport failure.

    Carries ``status`` (None for transport errors), ``url``, and
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
class BraintrustClient:
    """Minimal client for the endpoints the adapter needs.

    Use ``fetch_experiment_export`` to get an experiment in the shape
    ``experiment_to_failing_evals`` already consumes; the client
    handles pagination and (optionally) span enrichment.
    """

    api_key: str | None = None
    base_url: str = DEFAULT_BASE_URL
    timeout_s: int = DEFAULT_TIMEOUT_S

    def __post_init__(self) -> None:
        key = self.api_key or os.environ.get("BRAINTRUST_API_KEY")
        if not key:
            raise BraintrustAPIError(
                "BRAINTRUST_API_KEY not set and api_key not provided."
            )
        self.api_key = key

    # ---- transport ------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        qs = ""
        if params:
            qs = "?" + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}
            )
        url = f"{self.base_url}{path}{qs}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:2000]
            except Exception:
                pass
            raise BraintrustAPIError(
                f"Braintrust API returned {e.code} for {path}",
                status=e.code,
                url=url,
                body=body,
            ) from e
        except urllib.error.URLError as e:
            raise BraintrustAPIError(
                f"Braintrust API transport error: {e.reason!r}",
                url=url,
            ) from e

    # ---- resolution -----------------------------------------------------

    def resolve_experiment_id(
        self,
        *,
        experiment_id: str | None = None,
        project: str | None = None,
        experiment_name: str | None = None,
        latest: bool = False,
    ) -> str:
        """Resolve user-supplied flags to a concrete experiment ID.

        Resolution rules, in priority order:

        1. ``experiment_id`` given → use it verbatim.
        2. ``project`` + ``experiment_name`` → look up by name.
        3. ``project`` + ``latest=True`` → most recent experiment in
           the project.

        Anything else raises.
        """
        if experiment_id:
            return experiment_id
        if not project:
            raise BraintrustAPIError(
                "Need either --braintrust-experiment-id or "
                "--braintrust-project (plus --latest or "
                "--braintrust-experiment-name)."
            )
        # We list experiments under the project and pick by name or by
        # recency. Braintrust's listing endpoint is paginated; we only
        # need the first page for resolution.
        listing = self._get(
            "/experiment",
            params={"project_name": project, "limit": DEFAULT_PAGE_LIMIT},
        )
        experiments = listing.get("objects") or listing.get("experiments") or []
        if experiment_name:
            for exp in experiments:
                if exp.get("name") == experiment_name:
                    return exp["id"]
            raise BraintrustAPIError(
                f"No experiment named {experiment_name!r} in project "
                f"{project!r}."
            )
        if latest:
            if not experiments:
                raise BraintrustAPIError(
                    f"No experiments found in project {project!r}."
                )
            # Listing endpoint returns most-recent-first; first item
            # is the latest.
            return experiments[0]["id"]
        raise BraintrustAPIError(
            "Specify --braintrust-experiment-name or --latest alongside "
            "--braintrust-project."
        )

    # ---- rows + spans ---------------------------------------------------

    def _iter_rows(self, experiment_id: str) -> Iterator[dict]:
        """Yield every row in an experiment, paginating over cursors.

        Braintrust paginates fetches; we follow the ``cursor`` until
        the API returns none.
        """
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": DEFAULT_PAGE_LIMIT}
            if cursor:
                params["cursor"] = cursor
            page = self._get(
                f"/experiment/{experiment_id}/fetch",
                params=params,
            )
            rows = page.get("events") or page.get("rows") or []
            for row in rows:
                yield row
            cursor = page.get("cursor")
            if not cursor or not rows:
                return

    def fetch_experiment_export(
        self,
        experiment_id: str,
        *,
        with_spans: bool = True,
    ) -> dict:
        """Pull a full experiment in the shape the adapter consumes.

        Output is a single JSON object with the summary fields
        (``experiment_id``, ``experiment_name``, ``project_name``,
        ``metadata``) and a ``results`` array of rows. Each row has the
        Braintrust shape — ``id``, ``input``, ``expected``, ``output``,
        ``scores``, ``metadata``, ``created`` — plus a ``spans`` field
        when ``with_spans=True`` and the row has trace data.

        Spans are pulled per-row, not per-experiment, because the
        Braintrust trace endpoint is keyed by ``span_id`` / row, and
        bulk-pulling the full trace stream for an experiment costs
        more than it returns for the diagnostic case (only failing
        rows need spans, and the adapter doesn't know which rows
        failed until after conversion). Operators who want spans on
        passing rows too can fetch them separately.
        """
        # Header / metadata fetch.
        meta = self._get(f"/experiment/{experiment_id}")
        rows: list[dict] = list(self._iter_rows(experiment_id))

        if with_spans:
            # We attach spans only to rows that already have a span_id
            # or root_span_id — rows without one weren't instrumented.
            for row in rows:
                root_id = row.get("root_span_id") or row.get("span_id")
                if not root_id:
                    continue
                try:
                    spans = self._get(
                        f"/experiment/{experiment_id}/spans",
                        params={"root_span_id": root_id},
                    )
                except BraintrustAPIError:
                    # Spans are nice-to-have; a failed fetch should not
                    # block diagnosis. The conversion proceeds without
                    # spans for that row.
                    continue
                row["spans"] = (
                    spans.get("spans")
                    or spans.get("objects")
                    or spans
                )

        return {
            "experiment_id": meta.get("id") or experiment_id,
            "experiment_name": meta.get("name"),
            "project_name": meta.get("project_name"),
            "metadata": meta.get("metadata") or {},
            "results": rows,
        }


__all__ = [
    "BraintrustAPIError",
    "BraintrustClient",
    "DEFAULT_BASE_URL",
]
