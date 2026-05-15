"""PostHog event export → integration-watcher trace JSONL.

PostHog's events API (``GET /api/projects/:id/events``) returns events in a
documented shape: each event has an ``id``, an ``event`` name, an ISO-8601
``timestamp``, a ``distinct_id``, and a ``properties`` object holding
arbitrary keys. For API-call events the request/response detail lives in
``properties`` — ``method``, ``path``, ``request_body``, ``status_code``,
``error_code``, ``latency_ms``.

integration-watcher consumes JSONL traces with this contract (see
``integration_watcher.loaders.Trace``): ``timestamp``, ``developer_id``,
``endpoint``, ``request_summary``, ``response_status``, ``error_code``
(nullable), ``latency_ms``.

``events_to_traces`` maps one shape onto the other. The field mapping:

    integration-watcher        PostHog source
    -------------------        -----------------------------------------
    timestamp              <-  timestamp
    developer_id           <-  distinct_id
    endpoint               <-  "{properties.method} {properties.path}"
    request_summary        <-  compact repr of properties.request_body
    response_status        <-  properties.status_code
    error_code             <-  properties.error_code (null when absent)
    latency_ms             <-  properties.latency_ms (0 when absent)

The conversion is deliberately defensive. A raw PostHog export is
heterogeneous — ``$pageview`` and ``$identify`` events carry no
method/path — so every field falls back to a sensible default rather than
raising. Output is sorted by ``timestamp`` ascending so the trace stream
reads chronologically regardless of export order (PostHog returns events
newest-first).
"""

from __future__ import annotations

import json
from typing import Any

_DEFAULT_DEVELOPER_ID = "unknown"


def _endpoint(props: dict[str, Any]) -> str:
    """Format ``METHOD /path`` from PostHog properties.

    Events without method/path (page views, identifies) collapse to an
    empty string rather than a bogus endpoint.
    """
    method = str(props.get("method", "")).strip().upper()
    path = str(props.get("path", "")).strip()
    return f"{method} {path}".strip()


def _request_summary(request_body: Any) -> str:
    """Compact, deterministic one-line repr of a request body.

    Dicts become space-joined ``key=value`` pairs with values JSON-encoded
    (strings quoted, booleans/numbers unambiguous). Anything else is
    JSON-encoded whole. An absent body yields ``""``, which is also
    integration-watcher's own default for the field.
    """
    if request_body is None:
        return ""
    if isinstance(request_body, dict):
        return " ".join(
            f"{k}={json.dumps(v, separators=(',', ':'))}"
            for k, v in request_body.items()
        )
    return json.dumps(request_body, separators=(",", ":"))


def _int_field(props: dict[str, Any], key: str) -> int:
    """Coerce a numeric PostHog property to int; 0 when absent/unparseable."""
    try:
        return int(props.get(key, 0))
    except (TypeError, ValueError):
        return 0


def event_to_trace(event: dict[str, Any]) -> dict[str, Any]:
    """Map a single PostHog event dict to an integration-watcher trace dict."""
    props = event.get("properties") or {}
    if not isinstance(props, dict):
        props = {}
    return {
        "timestamp": str(event.get("timestamp", "")),
        "developer_id": str(event.get("distinct_id") or _DEFAULT_DEVELOPER_ID),
        "endpoint": _endpoint(props),
        "request_summary": _request_summary(props.get("request_body")),
        "response_status": _int_field(props, "status_code"),
        "error_code": props.get("error_code"),
        "latency_ms": _int_field(props, "latency_ms"),
    }


def events_to_traces(events: list[dict]) -> list[dict]:
    """Convert a list of PostHog events into integration-watcher traces.

    Every event is converted — no filtering. A raw export mixes API calls
    with page views; the caller (or downstream cohort scope) decides what
    to keep. Traces are returned sorted by ``timestamp`` ascending. The
    sort is stable, so events sharing a timestamp keep their input order,
    and events with an empty/unparseable timestamp sort first.
    """
    traces = [event_to_trace(e) for e in events]
    return sorted(traces, key=lambda t: t["timestamp"])
