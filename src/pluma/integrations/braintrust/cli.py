"""CLI: Braintrust experiment JSON → agent-researcher failing-eval JSON.

    python -m pluma.integrations.braintrust.cli \\
        --input experiment.json --output failing_evals.json \\
        [--score-threshold 1.0] [--scorer exact_match]

Reads a captured Braintrust experiment export (one JSON object with a
``results`` array), keeps the rows that did not clear the score threshold,
and writes one JSON object in the shape ``agent_researcher.eval_analyzer.
load_eval_result`` parses. No network, no Braintrust SDK.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .experiment_to_failing_evals import experiment_to_failing_evals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pluma.integrations.braintrust.cli",
        description="Convert a Braintrust experiment into agent-researcher failing evals.",
    )
    parser.add_argument("--input", required=True, type=Path,
                        help="Braintrust experiment export JSON (object with a results array).")
    parser.add_argument("--output", required=True, type=Path,
                        help="Destination failing-eval JSON file (single JSON object).")
    parser.add_argument("--score-threshold", type=float, default=1.0,
                        help="A row passes when its primary scorer is >= this (default: 1.0).")
    parser.add_argument("--scorer", type=str, default=None,
                        help="Primary scorer name (default: the first scorer in each row).")
    args = parser.parse_args(argv)

    experiment = json.loads(args.input.read_text())
    if not isinstance(experiment, dict):
        print("Input must be a JSON object with a 'results' array.", file=sys.stderr)
        return 2

    result = experiment_to_failing_evals(
        experiment,
        score_threshold=args.score_threshold,
        primary_scorer=args.scorer,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    )
    print(f"[{len(result['results'])} failing of {result['total']} → {args.output}]",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
