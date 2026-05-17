# OpenTelemetry trace adapter

This directory bridges [OpenTelemetry](https://opentelemetry.io/) — the
de-facto standard for distributed tracing — with Pluma's diagnostic
methodology. The adapter reads OpenTelemetry trace exports (OTLP/JSON,
Jaeger, bare span arrays) and converts them into integration-watcher's
trace cohort format. Anyone exporting OTel from their observability stack
can diagnose developer integration friction without writing a custom
adapter per backend.

## What's here

`otel_to_traces.py` is a converter that transforms an OpenTelemetry span
export into integration-watcher's trace JSONL format. Read an OTel
export, write a Pluma-ready trace file, point integration-watcher at it.
`cli.py` is a thin argparse wrapper. The fixtures and golden output live
in `fixtures/`.

## Supported input formats

Format detection is automatic — the converter inspects the top-level
shape (`--format` is not needed):

- **OTLP/JSON** — the OTLP HTTP/JSON export spec, what an OTel collector
  emits via a JSON file exporter. Detected by a top-level `resourceSpans`
  key.
- **Jaeger** — the flat `{data: [{spans: [...], processes: {...}}]}`
  export Jaeger and Tempo (Jaeger-compat mode) produce. Detected by a
  top-level `data` key.
- **Bare OTel span arrays** — the minimal "trace data only" export: a
  plain JSON array of spans with attributes already flattened. The
  fallback when neither wrapper is present.

## Supported observability platforms (via OTel export)

- Datadog (via OTLP exporter)
- Honeycomb (native OTel)
- Tempo (native OTel)
- Jaeger (Jaeger format)
- Grafana Cloud (via OTel collector)
- AWS X-Ray (via OTel collector)
- Lightstep (native OTel)
- Splunk (via OTel collector)
- Anyone else emitting OTel

## Semantic convention compatibility

OpenTelemetry renamed several HTTP attributes in the 1.21 semantic
conventions (late 2024); instrumenters are still split across both. The
adapter accepts either name and maps them to the same output field, so
the convention shift is transparent to integration-watcher:

| Field | pre-1.21 | post-1.21 (stable) |
|---|---|---|
| method | `http.method` | `http.request.method` |
| status | `http.status_code` | `http.response.status_code` |
| path | `http.target` / `http.route` | `url.path` / `http.route` |

A single export may mix both — the per-attribute lookup tries the new
name first, then the old one, independently for each span.

## Field mapping

OTel HTTP client spans carry the primitives integration-watcher needs.
The mapping (see `integration_watcher.loaders.Trace` for the consumed
contract):

| integration-watcher field | OTel source |
|---|---|
| `timestamp` | `startTimeUnixNano` (OTLP) / `startTime` micros (Jaeger), converted to ISO 8601 UTC, second precision |
| `developer_id` | `enduser.id`, `user.id`, `developer.id`, `client.id` (span attrs), else `service.namespace` (resource/process attrs fallback) |
| `endpoint` | `"{http.request.method or http.method} {url.path or http.target or http.route}"` |
| `request_summary` | `http.request.body` if captured, else `url.query`/`http.query` + request content-type |
| `response_status` | `http.response.status_code` (new) or `http.status_code` (old) |
| `error_code` | `error.type` / `exception.type` / `rpc.grpc.status_code` (null when absent) |
| `latency_ms` | `(endTimeUnixNano - startTimeUnixNano) / 1e6` (OTLP) or `duration / 1000` (Jaeger micros → ms) |

Spans with neither a method nor a path (internal compute spans,
non-HTTP server spans) are skipped — they carry no signal for
integration-watcher. Records are sorted by `(developer_id, timestamp)`
ascending so each developer's call stream reads chronologically;
integration-watcher re-groups by `developer_id` downstream. trace/span
IDs and the parent-child span tree are not propagated: integration-watcher's
contract is a flat per-developer call stream, not a span tree. Spans
that share a trace (one developer's flow) converge on the same
`developer_id` and stay correlated by chronological order.

## Usage

Convert:

```bash
python -m pluma.integrations.otel.cli \
    --input  src/pluma/integrations/otel/fixtures/traces.json \
    --output src/pluma/integrations/otel/fixtures/traces_converted.jsonl
```

Then point integration-watcher at the converted output (directly or via
Pluma):

```bash
pluma watch \
    --traces  src/pluma/integrations/otel/fixtures/traces_converted.jsonl \
    --cohort  your_cohort.yaml \
    --product your_product_dir \
    --output-file findings.md
```

## Getting an OTel export

The simplest path from a live system: configure the OTel collector with
a [file exporter](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/exporter/fileexporter/README.md)
and feed its output here. Vendor exports also work — Datadog supports
OTLP/JSON export; Honeycomb has a query-then-download flow; Tempo can
dump traces in Jaeger format directly.

## What this adapter is not

A live OTel collector or a span ingester. It reads exported batches and
converts them. For continuous diagnosis, point an OTel collector at a
file destination and feed the file through this adapter on a schedule.

## Fixture

The fixtures are synthetic, authored from the OTel HTTP semantic
conventions (https://opentelemetry.io/docs/specs/semconv/http/), not
captured from a live instance. They model a developer-integration cohort
against a generic REST API: a healthy onboarding flow, a developer stuck
in a 401 auth-misconfiguration loop, a rate-limited client retrying
through 429s, an async caller polling a 202 job endpoint, a validation
flow correcting 400s, and an integration hitting intermittent 502/500s.

- `fixtures/traces.json` — the primary fixture, OTLP/JSON, 60 spans
  across 7 developers (46 HTTP client spans + a root session span and a
  db span per developer that the converter skips), deliberately mixing
  pre-1.21 and post-1.21 attribute names, with parent-child spans and
  trace-id correlation.
- `fixtures/traces_jaeger.json` — the Jaeger-format fixture (a 6-span
  rate-limit / retry scenario, pre-1.21 names, tags + processes shape).
- `fixtures/traces_bare.json` — the bare-span-array fixture (8 spans,
  two developers, post-1.21 names, flattened attributes).
- `fixtures/traces_converted.jsonl` — the committed golden output of
  running the converter against `traces.json` (JSONL — one trace record
  per line, what integration-watcher's loader consumes); a diff against
  a fresh run is the converter's regression test.

Regenerate the fixtures deterministically with:

```bash
.venv/bin/python src/pluma/integrations/otel/fixtures/_author_fixture.py
python -m pluma.integrations.otel.cli \
    --input  src/pluma/integrations/otel/fixtures/traces.json \
    --output src/pluma/integrations/otel/fixtures/traces_converted.jsonl
```

`_author_fixture.py` carries a module docstring naming the conventions
and the integration scenario each developer represents.

## Coming soon

1. **gRPC OTLP receiver mode.** Listen on OTLP/gRPC directly so the
   adapter can sit inline with the collector for low-latency diagnosis.

2. **Attribute mapping config.** A YAML file mapping non-standard
   attribute names (some platforms keep custom prefixes) to the
   integration-watcher fields, so users with bespoke instrumentation
   don't need to modify the adapter.

3. **Cohort extraction from baggage.** OTel baggage often carries the
   developer/tenant identifier; if the operator can name the baggage
   key, the adapter could synthesize an integration-watcher cohort YAML
   automatically.
```
