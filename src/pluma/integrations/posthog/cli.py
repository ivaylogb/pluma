"""CLI: PostHog event export JSON → integration-watcher trace JSONL.

    python -m pluma.integrations.posthog.cli \\
        --input events.json --output traces.jsonl

Reads a captured PostHog event export (a JSON array of events, or the
``{"results": [...]}`` envelope the events API returns), converts each event
to an integration-watcher trace, and writes the result as JSONL — one trace
per line. No network, no PostHog SDK; the input is a file on disk.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .events_to_traces import events_to_traces


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pluma.integrations.posthog.cli",
        description="Convert a PostHog event export into integration-watcher traces.",
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="PostHog event export JSON (array of events, or {results: [...]}).",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Destination JSONL trace file.",
    )
    args = parser.parse_args(argv)

    raw = json.loads(args.input.read_text())
    events = raw.get("results", raw) if isinstance(raw, dict) else raw
    if not isinstance(events, list):
        print(
            'Input must be a JSON array of events (or a PostHog '
            '{"results": [...]} envelope).',
            file=sys.stderr,
        )
        return 2

    traces = events_to_traces(events)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as f:
        for trace in traces:
            f.write(json.dumps(trace) + "\n")

    print(f"[{len(traces)} trace(s) → {args.output}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
