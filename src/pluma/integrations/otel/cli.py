"""CLI wrapper for the OTel integration.

Reads an OTLP/JSON or Jaeger-style span export and writes
integration-watcher's expected JSONL.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .otel_to_traces import otel_to_traces


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m pluma.integrations.otel.cli",
        description=(
            "Convert an OpenTelemetry span export into "
            "integration-watcher trace JSONL. Accepts OTLP/JSON, "
            "Jaeger-style, or a bare span array."
        ),
    )
    p.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to the OTel export JSON.",
    )
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the integration-watcher trace JSONL.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        doc = json.loads(Path(args.input).read_text())
    except json.JSONDecodeError as e:
        print(f"Could not parse {args.input}: {e}", file=sys.stderr)
        return 3

    records = otel_to_traces(doc)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as f:
        for r in records:
            f.write(json.dumps(r.as_dict(), separators=(",", ":")) + "\n")

    print(
        f"Wrote {len(records)} trace record(s) to {args.output}.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
