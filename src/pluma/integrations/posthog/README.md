## Pluma + PostHog integration

This directory bridges [PostHog](https://posthog.com/) (product analytics) with Pluma's diagnostic
methodology. PostHog produces the data layer: funnel
dropoffs, event streams, cohorts. Pluma runs as the diagnosis layer:
where in the product surface to look, what byte-exact edit would change it.
The shapes line up; the integration moves data between them.

## What's here today

`events_to_traces.py` is a converter that transforms PostHog event exports
(the shape returned by `GET /api/projects/:id/events`) into integration-watcher's trace JSONL format. Read a PostHog event export JSON,
write a Pluma-ready `traces.jsonl`, point integration-watcher at it.
`cli.py` is a thin argparse wrapper. The fixture and golden output live in
`fixtures/`.

### PostHog format

Each event carries `id`, `event`, `timestamp` (ISO 8601), `distinct_id`,
and a `properties` object. For API-call events the request/response detail
lives in `properties`. The field mapping:

| integration-watcher | PostHog source |
|---|---|
| `timestamp` | `timestamp` |
| `developer_id` | `distinct_id` |
| `endpoint` | `"{properties.method} {properties.path}"` |
| `request_summary` | compact repr of `properties.request_body` |
| `response_status` | `properties.status_code` |
| `error_code` | `properties.error_code` (`null` when absent) |
| `latency_ms` | `properties.latency_ms` (`0` when absent) |

The converter does not filter: a raw export mixes API calls with
`$pageview`/`$identify` events that have no method/path. Those convert to a
trace with an empty endpoint and zeroed status — downstream cohort scope
decides what to keep rather than the converter silently dropping rows.

## Usage

Sample input event (one event from `fixtures/events.json`):

```json
{"id": "0190e0c2-7f3a-91d2-0003-000000000099", "event": "API call", "timestamp": "2026-05-10T09:12:03Z", "distinct_id": "dev_7f3a91", "properties": {"method": "post", "path": "/v1/auth/token", "request_body": {"client_id": "cli_7f3a91", "grant_type": "client_credentials"}, "status_code": 200, "latency_ms": 240, "$lib": "posthog-python", "$lib_version": "3.6.0", "$ip": "203.0.113.41", "service": "api-gateway"}}
```

Convert:

```bash
python -m pluma.integrations.posthog.cli \
    --input  src/pluma/integrations/posthog/fixtures/events.json \
    --output src/pluma/integrations/posthog/fixtures/traces.jsonl
```

Sample output trace (the corresponding line in `fixtures/traces.jsonl`):

```json
{"timestamp": "2026-05-10T09:12:03Z", "developer_id": "dev_7f3a91", "endpoint": "POST /v1/auth/token", "request_summary": "client_id=\"cli_7f3a91\" grant_type=\"client_credentials\"", "response_status": 200, "error_code": null, "latency_ms": 240}
```

Point integration-watcher at the converted output (directly or via Pluma):

```bash
pluma watch \
    --traces  src/pluma/integrations/posthog/fixtures/traces.jsonl \
    --cohort  your_cohort.yaml \
    --product your_product_dir \
    --output-file findings.md
```

## Coming soon

1. **Live PostHog API client.** The current converter reads a captured
   JSON file. Next: pull events directly from the PostHog API given a
   project ID and a date range, with pagination over the `next` cursor.

2. **Funnel converter.** PostHog funnel definitions and dropoff data →
   funnel-researcher's `funnel.yaml` + `dropoff_data.json` input shapes.
   Same field-mapping pattern as the trace converter, different shapes.

3. **Cohort converter.** PostHog cohort definitions →
   integration-watcher's cohort YAML (cohort name, date range, scope).

4. **End-to-end pipeline.** A `posthog-to-pluma` CLI that authenticates,
   pulls events + funnels + cohorts, runs the converters, runs `pluma
   diagnose-funnel` / `pluma watch` / `pluma cross` in sequence, and
   writes the results.

5. **Findings → PostHog annotations.** The reverse direction: take a Pluma
   Finding and write it back to PostHog as an annotation attached to the
   relevant funnel or event series. Closes the loop — the diagnosis lands
   in the same dashboard where the dropoff was first observed.

## Notes on the fixture

`fixtures/events.json` currently models a generic REST API integration cohort for authenticating, 
listing and creating resources, and hitting auth, validation, rate-limit,
and server errors along the way. `fixtures/traces.jsonl` is the committed
golden output of running the converter against it; a diff against a fresh
run is the regression test for the converter. When the live API client
(item 1) ships here, the fixture will be replaced with real captured data, or
supplemented with both.
