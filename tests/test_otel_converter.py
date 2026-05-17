"""OpenTelemetry → integration-watcher converter contract tests.

Covers the three input formats (OTLP/JSON, Jaeger, bare span array),
the pre-1.21 / post-1.21 HTTP semantic-convention compatibility layer,
format auto-detection, trace correlation, determinism, empty input, the
CLI's clear-error path, and a round-trip of the converter's output
through ``integration_watcher.loaders.load_traces``.

Mirrors the existing ``tests/`` pattern: pytest, plain ``assert``,
``tmp_path``, module-under-test imported directly. The golden-fixture
regression (``fixtures/traces.json`` -> ``fixtures/traces_converted.jsonl``)
is exercised here via a fresh CLI run plus the live integration-watcher
loader, so the test asserts the consumed contract, not just bytes.

Note on correlation: integration-watcher's trace contract is a flat
per-developer call stream grouped by ``developer_id`` and ordered by
``timestamp`` (see ``integration_watcher.trace_analyzer``). The bundle
converter deliberately does not propagate trace/span IDs or the
parent-child tree — they are not part of that contract. "Correlation
preserved" therefore means: spans of one developer's flow converge on
one ``developer_id`` and stay in chronological order. The tests assert
that real property, not a trace_id field that the output shape does not
carry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pluma.integrations.otel import cli as otel_cli
from pluma.integrations.otel.otel_to_traces import (
    _detect_walker,
    _walk_bare,
    _walk_jaeger,
    _walk_otlp,
    otel_to_traces,
)

# Fixtures live next to the converter module, not under tests/.
_OTEL_DIR = (
    Path(__file__).resolve().parent.parent
    / "src" / "pluma" / "integrations" / "otel"
)
_FIX = _OTEL_DIR / "fixtures"


# =========================================================================
# Builders: the same logical HTTP call in each of the three formats.
# =========================================================================


def _otlp(spans: list[dict], resource_attrs: dict | None = None) -> dict:
    def _attrs(d: dict) -> list[dict]:
        out = []
        for k, v in d.items():
            val = {"intValue": v} if isinstance(v, int) else {"stringValue": v}
            out.append({"key": k, "value": val})
        return out

    return {
        "resourceSpans": [
            {
                "resource": {"attributes": _attrs(resource_attrs or {})},
                "scopeSpans": [{"spans": [
                    {**s, "attributes": _attrs(s.get("attributes", {}))}
                    for s in spans
                ]}],
            }
        ]
    }


def _otlp_span(attrs: dict, *, start_ns=1_747_299_600_000_000_000,
               dur_ms=125, trace="a" * 32, span="b" * 16,
               parent=None) -> dict:
    s = {
        "traceId": trace,
        "spanId": span,
        "name": "client call",
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(start_ns + dur_ms * 1_000_000),
        "attributes": attrs,
    }
    if parent:
        s["parentSpanId"] = parent
    return s


def _jaeger_span(attrs: dict, *, start_us=1_747_299_600_000_000,
                  dur_us=125_000, trace="a" * 32, span="b" * 16) -> dict:
    return {
        "traceID": trace,
        "spanID": span,
        "operationName": "client call",
        "startTime": start_us,
        "duration": dur_us,
        "tags": [{"key": k, "value": v} for k, v in attrs.items()],
        "processID": "p1",
    }


def _jaeger(spans: list[dict]) -> dict:
    return {"data": [{"traceID": "a" * 32, "spans": spans,
                      "processes": {"p1": {"serviceName": "svc",
                                           "tags": []}}}]}


_PRE = {
    "http.method": "GET",
    "http.target": "/v1/widgets",
    "http.status_code": 503,
    "exception.type": "503",
    "enduser.id": "dev_x",
}
_POST = {
    "http.request.method": "GET",
    "url.path": "/v1/widgets",
    "http.response.status_code": 503,
    "error.type": "503",
    "enduser.id": "dev_x",
}
_EXPECTED = {
    "timestamp": "2025-05-15T09:00:00Z",
    "developer_id": "dev_x",
    "endpoint": "GET /v1/widgets",
    "request_summary": "",
    "response_status": 503,
    "error_code": "503",
    "latency_ms": 125,
}


# =========================================================================
# format parsing
# =========================================================================


def test_otlp_json_format_parsed():
    recs = otel_to_traces(_otlp([_otlp_span(_POST)]))
    assert len(recs) == 1
    assert recs[0].as_dict() == _EXPECTED


def test_jaeger_format_parsed():
    recs = otel_to_traces(_jaeger([_jaeger_span(_PRE)]))
    assert len(recs) == 1
    assert recs[0].as_dict() == _EXPECTED


def test_bare_spans_format_parsed():
    # Bare = a plain array of spans, attributes already a flat dict.
    bare = [{
        "traceId": "a" * 32,
        "spanId": "b" * 16,
        "startTimeUnixNano": 1_747_299_600_000_000_000,
        "endTimeUnixNano": 1_747_299_600_125_000_000,
        "attributes": _POST,
    }]
    recs = otel_to_traces(bare)
    assert len(recs) == 1
    assert recs[0].as_dict() == _EXPECTED


# =========================================================================
# semantic-convention compatibility
# =========================================================================


def test_pre_1_21_attribute_names_recognized():
    rec = otel_to_traces(_otlp([_otlp_span(_PRE)]))[0].as_dict()
    assert rec["endpoint"] == "GET /v1/widgets"
    assert rec["response_status"] == 503
    assert rec["error_code"] == "503"


def test_post_1_21_attribute_names_recognized():
    pre = otel_to_traces(_otlp([_otlp_span(_PRE)]))[0].as_dict()
    post = otel_to_traces(_otlp([_otlp_span(_POST)]))[0].as_dict()
    # The only difference in input is the attribute names; output must
    # be byte-equivalent.
    assert pre == post == _EXPECTED


def test_otlp_proto3_strict_string_status_recognized():
    """Strict proto3-JSON OTLP encodes int64 as JSON strings (status
    codes; timestamps were already string-encoded in this fixture
    family). The converter must accept that shape and produce the same
    output as the numeric-encoded equivalent — not silently zero the
    status.

    This guards the divergence documented at the top of
    ``otel_to_traces.py``: reverting to the bundle's original
    ``isinstance(status, (int, float))`` gate would zero ``"200"``
    and fail this test. ``latency_ms`` is asserted too, proving the
    string ``*UnixNano`` fields parse end-to-end (they already did via
    ``int()`` in ``_nanos_to_iso`` / ``_latency_ms_from_otlp``; status
    was the only hard gate, but the assertion documents the contract).
    """
    attrs = {
        "enduser.id": "dev_kilo",
        "http.request.method": "GET",
        "url.path": "/v1/items",
        "http.response.status_code": 200,  # -> "200" in strict encoding
    }

    def _otlp_one(int_as_string: bool) -> dict:
        def _val(v):
            if isinstance(v, int):
                return {"intValue": str(v) if int_as_string else v}
            return {"stringValue": v}

        return {"resourceSpans": [{"resource": {"attributes": []},
                "scopeSpans": [{"spans": [{
                    "traceId": "a" * 32, "spanId": "b" * 16,
                    # proto3-strict int64 nanos: JSON strings.
                    "startTimeUnixNano": "1778835600000000000",
                    "endTimeUnixNano": "1778835600250000000",
                    "attributes": [
                        {"key": k, "value": _val(v)}
                        for k, v in attrs.items()
                    ],
                }]}]}]}

    strict = otel_to_traces(_otlp_one(int_as_string=True))[0].as_dict()
    numeric = otel_to_traces(_otlp_one(int_as_string=False))[0].as_dict()

    # The fix: a string-encoded status is no longer zeroed.
    assert strict["response_status"] == 200
    # String nanos parse end-to-end: 250ms, ISO-second timestamp.
    assert strict["latency_ms"] == 250
    assert strict["timestamp"] == "2026-05-15T09:00:00Z"
    # Strict and numeric encodings converge byte-for-byte.
    assert strict == numeric

    # The committed fixture carries a proto3-strict developer; its
    # statuses must survive the converter, not collapse to 0.
    kilo = [
        r for r in otel_to_traces(
            json.loads((_FIX / "traces.json").read_text())
        )
        if r.developer_id == "dev_kilo"
    ]
    assert [r.response_status for r in kilo] == [200, 200, 503, 503, 200]
    assert all(r.response_status != 0 for r in kilo)


# =========================================================================
# auto-detection
# =========================================================================


def test_format_auto_detection():
    otlp = json.loads((_FIX / "traces.json").read_text())
    jaeger = json.loads((_FIX / "traces_jaeger.json").read_text())
    bare = json.loads((_FIX / "traces_bare.json").read_text())

    assert _detect_walker(otlp) is _walk_otlp
    assert _detect_walker(jaeger) is _walk_jaeger
    assert _detect_walker(bare) is _walk_bare

    # And each fixture actually converts via its detected path.
    # (51 = 46 original HTTP records + 5 for the proto3-strict
    # dev_kilo added by the string-status follow-up patch.)
    assert len(otel_to_traces(otlp)) == 51
    assert len(otel_to_traces(jaeger)) == 6
    assert len(otel_to_traces(bare)) == 8


# =========================================================================
# correlation (developer_id + chronological order — the real contract)
# =========================================================================


def test_trace_id_correlation_preserved():
    # Three spans, one shared trace, one developer flow, authored out of
    # chronological order. Output must keep them under one developer and
    # in time order.
    t = "f" * 32
    doc = _otlp([
        _otlp_span({**_POST, "enduser.id": "dev_corr",
                    "http.response.status_code": 200, "error.type": None
                    if False else "200"},
                   start_ns=1_747_299_602_000_000_000, span="c" * 16,
                   trace=t),
        _otlp_span({"http.request.method": "GET", "url.path": "/v1/a",
                    "http.response.status_code": 200,
                    "enduser.id": "dev_corr"},
                   start_ns=1_747_299_600_000_000_000, span="d" * 16,
                   trace=t),
        _otlp_span({"http.request.method": "GET", "url.path": "/v1/b",
                    "http.response.status_code": 200,
                    "enduser.id": "dev_corr"},
                   start_ns=1_747_299_601_000_000_000, span="e" * 16,
                   trace=t),
    ])
    recs = otel_to_traces(doc)
    assert len(recs) == 3
    assert {r.developer_id for r in recs} == {"dev_corr"}
    ts = [r.timestamp for r in recs]
    assert ts == sorted(ts), "spans of one trace must stay chronological"


def test_parent_child_relationship_preserved():
    # A root (non-HTTP, no method/path) parent span plus two HTTP child
    # spans referencing it. The parent is skipped (no signal); both
    # children survive, attributed to the same developer in order.
    root = {
        "traceId": "1" * 32, "spanId": "9" * 16, "name": "session",
        "startTimeUnixNano": "1747299600000000000",
        "endTimeUnixNano": "1747299605000000000",
        "attributes": {"enduser.id": "dev_pc", "session.kind": "integ"},
    }
    child1 = _otlp_span(
        {"http.request.method": "POST", "url.path": "/v1/auth",
         "http.response.status_code": 200, "enduser.id": "dev_pc"},
        start_ns=1_747_299_600_500_000_000, span="a1" + "0" * 14,
        trace="1" * 32, parent="9" * 16,
    )
    child2 = _otlp_span(
        {"http.request.method": "GET", "url.path": "/v1/data",
         "http.response.status_code": 200, "enduser.id": "dev_pc"},
        start_ns=1_747_299_601_500_000_000, span="a2" + "0" * 14,
        trace="1" * 32, parent="9" * 16,
    )
    recs = otel_to_traces(_otlp([root, child1, child2]))
    # Parent (no method/path) dropped; both children present.
    assert len(recs) == 2
    assert [r.endpoint for r in recs] == ["POST /v1/auth", "GET /v1/data"]
    assert {r.developer_id for r in recs} == {"dev_pc"}


# =========================================================================
# round-trip through integration-watcher's loader
# =========================================================================


def test_round_trip_through_integration_watcher_loader(tmp_path):
    loaders = pytest.importorskip("integration_watcher.loaders")
    analyzer = pytest.importorskip("integration_watcher.trace_analyzer")

    out = tmp_path / "rt.json"
    rc = otel_cli.main([
        "--input", str(_FIX / "traces.json"),
        "--output", str(out),
    ])
    assert rc == 0

    traces = loaders.load_traces(out)  # must not raise
    src_records = otel_to_traces(json.loads((_FIX / "traces.json").read_text()))
    # 51 = 46 original + 5 for proto3-strict dev_kilo (additive patch);
    # 8 developers = original 7 + dev_kilo.
    assert len(traces) == len(src_records) == 51

    cohort = analyzer.analyze_cohort(traces)
    assert cohort.developer_count == 8
    assert cohort.total_calls == 51
    # The "stuck in a 401 loop" pattern must survive the conversion.
    bravo = next(i for i in cohort.integrations
                 if i.developer_id == "dev_bravo")
    assert bravo.longest_consecutive_same_error == ("401", 8)


# =========================================================================
# determinism + golden regression
# =========================================================================


def test_deterministic_output(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    assert otel_cli.main(["--input", str(_FIX / "traces.json"),
                          "--output", str(a)]) == 0
    assert otel_cli.main(["--input", str(_FIX / "traces.json"),
                          "--output", str(b)]) == 0
    assert a.read_bytes() == b.read_bytes()
    # Committed golden is byte-identical to a fresh run (regression).
    assert a.read_bytes() == (_FIX / "traces_converted.jsonl").read_bytes()


# =========================================================================
# empty + error handling
# =========================================================================


def test_empty_input_handled(tmp_path):
    assert otel_to_traces({"resourceSpans": []}) == []
    assert otel_to_traces([]) == []
    assert otel_to_traces({"data": []}) == []

    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"resourceSpans": []}))
    out = tmp_path / "out.json"
    assert otel_cli.main(["--input", str(empty), "--output", str(out)]) == 0
    assert out.read_text() == ""  # valid empty output, no crash


def test_unknown_format_raises_clear_error(tmp_path, capsys):
    """Malformed (non-JSON) input surfaces a clear, path-named message
    and a clean exit code — not an uncaught JSONDecodeError traceback.

    (Valid JSON whose shape matches no known wrapper degrades to an
    empty result by converter design; that is asserted separately.)
    """
    bad = tmp_path / "bad.json"
    bad.write_text("this is not json {{{")
    out = tmp_path / "out.json"
    rc = otel_cli.main(["--input", str(bad), "--output", str(out)])
    assert rc == 3
    err = capsys.readouterr().err
    assert "Could not parse" in err
    assert str(bad) in err

    # Valid-but-unknown JSON: no exception, no records.
    assert otel_to_traces({"unexpected": "shape"}) == []
