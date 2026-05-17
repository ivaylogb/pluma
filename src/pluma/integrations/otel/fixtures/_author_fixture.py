"""Deterministic authoring script for the OTel adapter fixtures.

The fixtures are synthetic, written from the OpenTelemetry HTTP semantic
conventions (https://opentelemetry.io/docs/specs/semconv/http/), not
captured from a live backend. They exercise every path the converter
has: the three input formats (OTLP/JSON, Jaeger, bare span array), the
pre-1.21 *and* post-1.21 HTTP attribute names, parent-child span trees,
trace-id correlation, and the non-HTTP spans the converter is meant to
skip.

Conventions used
----------------
pre-1.21 :  http.method, http.target, http.url, http.status_code,
            exception.type (error)
post-1.21:  http.request.method, url.path, url.full, url.query,
            http.response.status_code, error.type (error), http.route
both     :  enduser.id (developer identity), service.namespace
            (resource-level fallback)

Integration scenario (one trace per developer, root session span +
child HTTP client spans):

  dev_alpha   (post-1.21) healthy onboarding: token, list, create, get,
                          delete — clean 2xx.
  dev_bravo   (pre-1.21)  stuck in a 401 loop: same call misconfigured,
                          retried until the developer gives up.
  dev_charlie (post-1.21) rate-limited: 429s with growing backoff
                          latency, then a 200.
  dev_delta   (pre-1.21)  async polling: submit 202, poll the job
                          endpoint on 202 repeatedly, then 200.
  dev_echo    (post-1.21) validation: 400s on a bad create payload,
                          corrected to a 201.
  dev_foxtrot (pre-1.21)  flaky upstream: intermittent 502/500 mixed
                          with 200s.
  dev_golf    (post-1.21) paginated reads with query strings (exercises
                          request_summary).

Plus per-developer non-HTTP spans (the root session span and a db
query span) that carry no method/path — the converter skips them.

`traces.json` (OTLP/JSON) is the primary, golden-tested fixture.
`traces_jaeger.json` and `traces_bare.json` re-encode focused
sub-scenarios in the other two formats so the format-detection and
pre/post-1.21 paths are covered without a second golden.

Run with `.venv/bin/python src/pluma/integrations/otel/fixtures/_author_fixture.py`;
output is byte-deterministic.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

_FIX_DIR = Path(__file__).resolve().parent

# 2026-05-15T09:00:00Z, the cohort window start.
_BASE_NS = int(
    datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc).timestamp()
) * 1_000_000_000


def _hex(label: str, width: int) -> str:
    """Deterministic, realistic-looking hex id of exactly ``width``
    chars (trace id = 32, span id = 16, per the OTel spec)."""
    return hashlib.sha256(label.encode()).hexdigest()[:width]


def _otlp_attrs(pairs: dict) -> list[dict]:
    """Encode a flat dict as OTLP/JSON typed attributes. ints become
    JSON numbers under intValue (what file/JSON exporters emit and what
    the converter expects); strings under stringValue."""
    out: list[dict] = []
    for k, v in pairs.items():
        if isinstance(v, bool):
            out.append({"key": k, "value": {"boolValue": v}})
        elif isinstance(v, int):
            out.append({"key": k, "value": {"intValue": v}})
        else:
            out.append({"key": k, "value": {"stringValue": str(v)}})
    return out


# --- the scenario -------------------------------------------------------
#
# Each developer: (developer_id, convention, [calls]). A call is
# (method, path, status, latency_ms, error). error is the value the
# converter should surface as error_code (None for success).

_HOST = "https://api.acme-dev.example.com"

_SCENARIO: list[tuple[str, str, list[tuple]]] = [
    (
        "dev_alpha", "post",
        [
            ("POST", "/v1/auth/token", 200, 180, None),
            ("GET", "/v1/projects", 200, 95, None),
            ("POST", "/v1/projects/proj_4a/items", 201, 220, None),
            ("GET", "/v1/projects/proj_4a/items/itm_91", 200, 70, None),
            ("DELETE", "/v1/projects/proj_4a/items/itm_91", 204, 60, None),
        ],
    ),
    (
        "dev_bravo", "pre",
        [
            ("POST", "/v1/auth/token", 200, 160, None),
            ("GET", "/v1/projects", 401, 55, "401"),
            ("GET", "/v1/projects", 401, 52, "401"),
            ("GET", "/v1/projects", 401, 58, "401"),
            ("GET", "/v1/projects", 401, 51, "401"),
            ("GET", "/v1/projects", 401, 60, "401"),
            ("GET", "/v1/projects", 401, 49, "401"),
            ("GET", "/v1/projects", 401, 57, "401"),
            ("GET", "/v1/projects", 401, 53, "401"),
        ],
    ),
    (
        "dev_charlie", "post",
        [
            ("POST", "/v1/auth/token", 200, 175, None),
            ("POST", "/v1/exports", 429, 40, "429"),
            ("POST", "/v1/exports", 429, 90, "429"),
            ("POST", "/v1/exports", 429, 200, "429"),
            ("POST", "/v1/exports", 429, 440, "429"),
            ("POST", "/v1/exports", 200, 310, None),
        ],
    ),
    (
        "dev_delta", "pre",
        [
            ("POST", "/v1/auth/token", 200, 165, None),
            ("POST", "/v1/jobs", 202, 130, None),
            ("GET", "/v1/jobs/job_77", 202, 45, None),
            ("GET", "/v1/jobs/job_77", 202, 47, None),
            ("GET", "/v1/jobs/job_77", 202, 44, None),
            ("GET", "/v1/jobs/job_77", 202, 46, None),
            ("GET", "/v1/jobs/job_77", 202, 48, None),
            ("GET", "/v1/jobs/job_77", 202, 45, None),
            ("GET", "/v1/jobs/job_77", 200, 80, None),
        ],
    ),
    (
        "dev_echo", "post",
        [
            ("POST", "/v1/auth/token", 200, 170, None),
            ("POST", "/v1/projects/proj_7c/items", 400, 65, "400"),
            ("POST", "/v1/projects/proj_7c/items", 400, 63, "400"),
            ("POST", "/v1/projects/proj_7c/items", 400, 66, "400"),
            ("POST", "/v1/projects/proj_7c/items", 201, 210, None),
        ],
    ),
    (
        "dev_foxtrot", "pre",
        [
            ("POST", "/v1/auth/token", 200, 158, None),
            ("GET", "/v1/projects", 200, 88, None),
            ("GET", "/v1/projects/proj_2b/items", 502, 1200, "502"),
            ("GET", "/v1/projects/proj_2b/items", 200, 140, None),
            ("GET", "/v1/projects/proj_2b/items", 500, 900, "500"),
            ("GET", "/v1/projects/proj_2b/items", 500, 950, "500"),
            ("GET", "/v1/projects/proj_2b/items", 200, 150, None),
        ],
    ),
    (
        "dev_golf", "post",
        [
            ("POST", "/v1/auth/token", 200, 172, None),
            ("GET", "/v1/projects?page=1&limit=50", 200, 110, None),
            ("GET", "/v1/projects?page=2&limit=50", 200, 115, None),
            ("GET", "/v1/projects?page=3&limit=50", 200, 120, None),
            ("GET", "/v1/search?q=onboarding&type=doc", 200, 130, None),
        ],
    ),
]


def _split_path_query(path: str) -> tuple[str, str]:
    if "?" in path:
        p, q = path.split("?", 1)
        return p, q
    return path, ""


def _http_attrs(
    convention: str,
    dev_id: str,
    method: str,
    path: str,
    status: int,
    error: str | None,
) -> dict:
    """Build the flat attribute dict for one HTTP client span in the
    requested semantic convention."""
    bare_path, query = _split_path_query(path)
    attrs: dict = {"enduser.id": dev_id}
    if convention == "post":
        attrs["http.request.method"] = method
        attrs["url.path"] = bare_path
        attrs["url.full"] = f"{_HOST}{path}"
        attrs["http.route"] = bare_path
        attrs["http.response.status_code"] = status
        if query:
            attrs["url.query"] = query
        if method in ("POST", "PUT", "PATCH"):
            attrs["http.request.header.content-type"] = "application/json"
        if error:
            attrs["error.type"] = error
    else:  # pre-1.21
        attrs["http.method"] = method
        attrs["http.target"] = path
        attrs["http.url"] = f"{_HOST}{path}"
        attrs["http.status_code"] = status
        if query:
            attrs["http.query"] = query
        if method in ("POST", "PUT", "PATCH"):
            attrs["http.request.mime_type"] = "application/json"
        if error:
            attrs["exception.type"] = error
    return attrs


def _build_otlp() -> dict:
    """Primary fixture: full scenario as one OTLP/JSON document.

    One resourceSpans entry; one scopeSpans; one trace per developer
    with a root INTERNAL session span, a non-HTTP db span, and the HTTP
    client spans as children of the root.
    """
    spans: list[dict] = []
    clock = _BASE_NS
    gap_ns = 3_000_000_000  # 3s between calls, keeps timestamps distinct

    for dev_id, convention, calls in _SCENARIO:
        trace_id = _hex(f"trace::{dev_id}", 32)
        root_id = _hex(f"span::{dev_id}::root", 16)
        # Root session span — no HTTP attributes, converter skips it.
        spans.append({
            "traceId": trace_id,
            "spanId": root_id,
            "name": f"integration.session {dev_id}",
            "kind": 1,  # SPAN_KIND_INTERNAL
            "startTimeUnixNano": str(clock),
            "endTimeUnixNano": str(clock + 2_000_000_000),
            "attributes": _otlp_attrs({
                "enduser.id": dev_id,
                "session.kind": "developer-integration",
            }),
            "status": {"code": 0},
        })
        # A non-HTTP db span under the root — also skipped.
        spans.append({
            "traceId": trace_id,
            "spanId": _hex(f"span::{dev_id}::db", 16),
            "parentSpanId": root_id,
            "name": "SELECT api_key",
            "kind": 3,  # CLIENT
            "startTimeUnixNano": str(clock + 1_000_000),
            "endTimeUnixNano": str(clock + 4_000_000),
            "attributes": _otlp_attrs({
                "db.system": "postgresql",
                "db.statement": "SELECT id FROM api_key WHERE token=$1",
            }),
            "status": {"code": 0},
        })
        for idx, (method, path, status, latency_ms, error) in enumerate(calls):
            start = clock
            end = start + latency_ms * 1_000_000
            spans.append({
                "traceId": trace_id,
                "spanId": _hex(f"span::{dev_id}::{idx}", 16),
                "parentSpanId": root_id,
                "name": f"{method} {_split_path_query(path)[0]}",
                "kind": 3,  # SPAN_KIND_CLIENT
                "startTimeUnixNano": str(start),
                "endTimeUnixNano": str(end),
                "attributes": _otlp_attrs(
                    _http_attrs(convention, dev_id, method, path, status, error)
                ),
                "status": {
                    "code": 2 if status >= 400 else 0  # ERROR / UNSET
                },
            })
            clock = end + gap_ns
        clock += gap_ns  # spacing between developers

    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": _otlp_attrs({
                        "service.name": "acme-api-client",
                        "service.namespace": "acme-prod",
                        "telemetry.sdk.name": "opentelemetry",
                        "telemetry.sdk.language": "python",
                    })
                },
                "scopeSpans": [
                    {
                        "scope": {
                            "name": "opentelemetry.instrumentation.requests",
                            "version": "0.48b0",
                        },
                        "spans": spans,
                    }
                ],
            }
        ]
    }


def _build_jaeger() -> dict:
    """Jaeger-format fixture: a focused rate-limit scenario, pre-1.21
    attribute names, tags + processes shape, micros timing."""
    trace_id = _hex("jaeger::trace::dev_hotel", 32)
    proc_id = "p1"
    base_micros = _BASE_NS // 1000
    clock = base_micros
    spans: list[dict] = []
    calls = [
        ("POST", "/v1/auth/token", 200, 165, None),
        ("POST", "/v1/exports", 429, 45, "429"),
        ("POST", "/v1/exports", 429, 120, "429"),
        ("POST", "/v1/exports", 429, 260, "429"),
        ("POST", "/v1/exports", 429, 510, "429"),
        ("POST", "/v1/exports", 200, 300, None),
    ]
    for idx, (method, path, status, latency_ms, error) in enumerate(calls):
        attrs = _http_attrs("pre", "dev_hotel", method, path, status, error)
        tags = [
            {"key": k, "type": (
                "int64" if isinstance(v, int) and not isinstance(v, bool)
                else "string"
            ), "value": v}
            for k, v in attrs.items()
        ]
        spans.append({
            "traceID": trace_id,
            "spanID": _hex(f"jaeger::span::dev_hotel::{idx}", 16),
            "operationName": f"{method} {path}",
            "references": (
                []
                if idx == 0
                else [{
                    "refType": "CHILD_OF",
                    "traceID": trace_id,
                    "spanID": _hex("jaeger::span::dev_hotel::0", 16),
                }]
            ),
            "startTime": clock,
            "duration": latency_ms * 1000,
            "tags": tags,
            "processID": proc_id,
        })
        clock += latency_ms * 1000 + 3_000_000
    return {
        "data": [
            {
                "traceID": trace_id,
                "spans": spans,
                "processes": {
                    proc_id: {
                        "serviceName": "acme-api-client",
                        "tags": [
                            {"key": "service.namespace",
                             "type": "string", "value": "acme-prod"},
                        ],
                    }
                },
            }
        ]
    }


def _build_bare() -> list[dict]:
    """Bare span array fixture: post-1.21 names, attributes already
    flattened to a dict, span-level OTLP nano timing."""
    out: list[dict] = []
    clock = _BASE_NS
    calls = [
        ("dev_india", "POST", "/v1/auth/token", 200, 170, None),
        ("dev_india", "GET", "/v1/projects", 200, 90, None),
        ("dev_india", "GET", "/v1/projects/proj_9d/items", 403, 60, "403"),
        ("dev_india", "GET", "/v1/projects/proj_9d/items", 403, 58, "403"),
        ("dev_india", "GET", "/v1/projects/proj_9d/items", 403, 61, "403"),
        ("dev_juliet", "POST", "/v1/auth/token", 200, 168, None),
        ("dev_juliet", "PUT", "/v1/projects/proj_1f", 200, 240, None),
        ("dev_juliet", "GET", "/v1/projects/proj_1f", 200, 75, None),
    ]
    for idx, (dev_id, method, path, status, latency_ms, error) in enumerate(
        calls
    ):
        start = clock
        end = start + latency_ms * 1_000_000
        out.append({
            "traceId": _hex(f"bare::trace::{dev_id}", 32),
            "spanId": _hex(f"bare::span::{dev_id}::{idx}", 16),
            "name": f"{method} {path}",
            "kind": 3,
            "startTimeUnixNano": start,
            "endTimeUnixNano": end,
            "attributes": _http_attrs(
                "post", dev_id, method, path, status, error
            ),
        })
        clock = end + 3_000_000_000
    return out


def main() -> None:
    (_FIX_DIR / "traces.json").write_text(
        json.dumps(_build_otlp(), indent=2) + "\n"
    )
    (_FIX_DIR / "traces_jaeger.json").write_text(
        json.dumps(_build_jaeger(), indent=2) + "\n"
    )
    (_FIX_DIR / "traces_bare.json").write_text(
        json.dumps(_build_bare(), indent=2) + "\n"
    )
    print(f"Wrote traces.json, traces_jaeger.json, traces_bare.json to {_FIX_DIR}")


if __name__ == "__main__":
    main()
