"""OpenTelemetry spans → integration-watcher trace JSONL.

The de-facto standard for distributed tracing in 2026 is OpenTelemetry.
Anything that exports OTel — DataDog APM, Honeycomb, Tempo, Jaeger,
Grafana Cloud, AWS X-Ray (via the OTel collector), Splunk, Lightstep
— produces spans in the same shape. One adapter, dozens of downstream
platforms covered.

integration-watcher consumes a JSONL stream of API call records:

    timestamp        ISO 8601
    developer_id     string
    endpoint         "METHOD /path"
    request_summary  compact string repr
    response_status  HTTP status code
    error_code       string or null
    latency_ms       integer

OTel HTTP client spans carry the same primitives, just under different
attribute names. This module reads either the OTLP/JSON wire format
(what an OTel collector emits to stdout / file / object storage) or
the Jaeger-style flat JSON some platforms export, and writes the
JSONL integration-watcher reads.

Input format detection is automatic: we look for ``resourceSpans``
(OTLP/JSON) first, then ``data[].spans`` (Jaeger), then a bare span
array. Each detected format has its own walker; the trace conversion
itself is shared.

What this module is **not**: a full OTel SDK. It is a one-way reader
from exported span batches to integration-watcher's input. For live
ingestion, point an OTel collector at a file exporter and feed the
file here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator


# OTel semantic conventions for HTTP — both old (pre-1.21) and new
# (post-1.21 stable) attribute names. We accept either; OTel renamed
# several of these in 2024 and instrumenters are still on both.
HTTP_METHOD_KEYS = ("http.request.method", "http.method")
HTTP_PATH_KEYS = ("url.path", "http.target", "http.route")
HTTP_STATUS_KEYS = ("http.response.status_code", "http.status_code")
HTTP_ERROR_KEYS = ("error.type", "exception.type", "rpc.grpc.status_code")
DEV_ID_KEYS = (
    "enduser.id",
    "user.id",
    "developer.id",
    "client.id",
    "service.namespace",  # last-resort fallback
)


@dataclass
class TraceRecord:
    """integration-watcher's per-call record shape."""

    timestamp: str
    developer_id: str
    endpoint: str
    request_summary: str
    response_status: int
    error_code: str | None
    latency_ms: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "developer_id": self.developer_id,
            "endpoint": self.endpoint,
            "request_summary": self.request_summary,
            "response_status": self.response_status,
            "error_code": self.error_code,
            "latency_ms": self.latency_ms,
        }


# --------------------------------------------------------------------------
# Attribute extraction (shared between OTLP and Jaeger walkers)
# --------------------------------------------------------------------------


def _attr_lookup(attrs: dict[str, Any], keys: Iterable[str]) -> Any:
    """First non-None value in ``attrs`` for any of ``keys``.

    Some span sources nest attribute values inside ``{"stringValue":
    ...}`` etc. — we unwrap the common cases.
    """
    for k in keys:
        if k in attrs:
            val = attrs[k]
            if isinstance(val, dict):
                # OTLP/JSON wraps primitives in typed objects.
                for inner in (
                    "stringValue",
                    "intValue",
                    "doubleValue",
                    "boolValue",
                ):
                    if inner in val:
                        return val[inner]
            return val
    return None


def _flatten_otlp_attributes(raw: Iterable[dict]) -> dict[str, Any]:
    """OTLP/JSON attributes are ``[{key, value: {type: ...}}]``.

    Flatten to ``{key: primitive}`` for shared extraction.
    """
    out: dict[str, Any] = {}
    for entry in raw or ():
        key = entry.get("key")
        value = entry.get("value") or {}
        for vt in (
            "stringValue",
            "intValue",
            "doubleValue",
            "boolValue",
        ):
            if vt in value:
                out[key] = value[vt]
                break
        else:
            # Array / KVList values: pass through as-is.
            if "arrayValue" in value:
                out[key] = value["arrayValue"].get("values")
            elif key is not None:
                out[key] = value
    return out


def _nanos_to_iso(nanos: Any) -> str:
    """OTLP timestamps are Unix nanos as a string or int.

    Convert to ISO 8601 UTC, rounded to seconds (integration-watcher
    doesn't use sub-second precision).
    """
    try:
        n = int(nanos)
    except (TypeError, ValueError):
        return ""
    return (
        datetime.fromtimestamp(n / 1_000_000_000, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _latency_ms_from_otlp(start: Any, end: Any) -> int:
    try:
        return max(0, (int(end) - int(start)) // 1_000_000)
    except (TypeError, ValueError):
        return 0


def _compact_request_summary(attrs: dict[str, Any]) -> str:
    """Best-effort compact representation of the request body / params.

    OTel rarely carries the request body (deliberately — PII risk), so
    we synthesize from query params + content-type. If the
    instrumenter happened to capture ``http.request.body`` (or
    similar), use that; otherwise emit the query string and content
    type.
    """
    body = (
        attrs.get("http.request.body")
        or attrs.get("messaging.message.payload")
    )
    if body:
        return str(body)[:500]
    parts: list[str] = []
    query = attrs.get("url.query") or attrs.get("http.query")
    if query:
        parts.append(str(query))
    ctype = attrs.get("http.request.header.content-type") or attrs.get(
        "http.request.mime_type"
    )
    if ctype:
        parts.append(f"content-type={ctype}")
    return " ".join(parts)


# --------------------------------------------------------------------------
# Format walkers
# --------------------------------------------------------------------------


def _walk_otlp(doc: Any) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """Yield (resource_attrs, span) pairs from an OTLP/JSON document.

    Shape: ``{resourceSpans: [{resource: {attributes: [...]},
    scopeSpans: [{spans: [...]}]}]}``.
    """
    for rs in doc.get("resourceSpans") or ():
        res_attrs = _flatten_otlp_attributes(
            (rs.get("resource") or {}).get("attributes") or ()
        )
        for ss in rs.get("scopeSpans") or rs.get("instrumentationLibrarySpans") or ():
            for span in ss.get("spans") or ():
                yield res_attrs, span


def _walk_jaeger(doc: Any) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """Yield (process_tags, span) pairs from a Jaeger-style export.

    Jaeger's exported shape is ``{data: [{spans: [...], processes:
    {pK: {tags: [...]}}}]}``. We synthesize a per-trace process-tag
    bag once per trace.
    """
    for trace in doc.get("data") or ():
        processes = trace.get("processes") or {}
        # Build a process-id → flat-tag-dict lookup.
        proc_tags: dict[str, dict[str, Any]] = {}
        for pid, p in processes.items():
            proc_tags[pid] = {
                t.get("key"): t.get("value")
                for t in (p.get("tags") or ())
            }
        for span in trace.get("spans") or ():
            tags = proc_tags.get(span.get("processID"), {})
            yield tags, span


def _walk_bare(doc: Any) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """Some exporters emit a flat array of spans with attributes
    already flattened.
    """
    if isinstance(doc, list):
        for span in doc:
            yield {}, span


def _detect_walker(doc: Any):
    if isinstance(doc, dict) and "resourceSpans" in doc:
        return _walk_otlp
    if isinstance(doc, dict) and "data" in doc:
        return _walk_jaeger
    return _walk_bare


# --------------------------------------------------------------------------
# Span → trace record
# --------------------------------------------------------------------------


def _span_to_record(
    span: dict[str, Any],
    res_or_proc_attrs: dict[str, Any],
) -> TraceRecord | None:
    """Convert one span to an integration-watcher record.

    Returns ``None`` for spans that don't look like HTTP / API calls
    (server spans without an HTTP method, internal compute spans,
    etc.). integration-watcher's cohort scope downstream decides what
    to retain; this filter is just to avoid emitting structural noise
    with no method/path.
    """
    raw_attrs = span.get("attributes") or []
    if isinstance(raw_attrs, list):
        attrs = _flatten_otlp_attributes(raw_attrs)
    elif isinstance(raw_attrs, dict):
        attrs = dict(raw_attrs)
    else:
        attrs = {}

    # Jaeger represents tags as a list of {key, value, type}.
    if not attrs and isinstance(span.get("tags"), list):
        attrs = {
            t.get("key"): t.get("value")
            for t in span.get("tags") or ()
        }

    method = _attr_lookup(attrs, HTTP_METHOD_KEYS)
    path = _attr_lookup(attrs, HTTP_PATH_KEYS)
    status = _attr_lookup(attrs, HTTP_STATUS_KEYS)
    error_code = _attr_lookup(attrs, HTTP_ERROR_KEYS)

    # Developer / end-user identifier: span attrs first, then resource
    # / process attrs as a fallback.
    dev_id = _attr_lookup(attrs, DEV_ID_KEYS) or _attr_lookup(
        res_or_proc_attrs, DEV_ID_KEYS
    )
    if not method and not path:
        return None

    endpoint = f"{str(method or '').upper()} {path or ''}".strip()

    # Timing: OTLP gives nanos; Jaeger gives ``startTime`` micros and
    # ``duration`` micros.
    if "startTimeUnixNano" in span:
        ts = _nanos_to_iso(span["startTimeUnixNano"])
        latency_ms = _latency_ms_from_otlp(
            span.get("startTimeUnixNano"),
            span.get("endTimeUnixNano"),
        )
    else:
        start_micros = span.get("startTime")
        try:
            ts = (
                datetime.fromtimestamp(
                    int(start_micros) / 1_000_000,
                    tz=timezone.utc,
                )
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
        except (TypeError, ValueError):
            ts = ""
        try:
            latency_ms = max(0, int(span.get("duration") or 0) // 1000)
        except (TypeError, ValueError):
            latency_ms = 0

    return TraceRecord(
        timestamp=ts,
        developer_id=str(dev_id) if dev_id is not None else "",
        endpoint=endpoint,
        request_summary=_compact_request_summary(attrs),
        response_status=int(status) if isinstance(status, (int, float)) else 0,
        error_code=str(error_code) if error_code else None,
        latency_ms=latency_ms,
    )


def otel_to_traces(doc: Any) -> list[TraceRecord]:
    """Convert an OTel-shaped document to a list of trace records.

    Accepts OTLP/JSON, Jaeger-style, or a bare span array. Sorted by
    timestamp ascending; integration-watcher's cohort analyzer assumes
    chronological order within a developer.
    """
    walker = _detect_walker(doc)
    records: list[TraceRecord] = []
    for env, span in walker(doc):
        rec = _span_to_record(span, env)
        if rec is not None:
            records.append(rec)
    records.sort(key=lambda r: (r.developer_id, r.timestamp))
    return records


__all__ = ["TraceRecord", "otel_to_traces"]
