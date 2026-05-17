"""CLI wrapper for the Braintrust integration.

Two modes:

  - **File mode** (the original): ``--input FILE`` reads a Braintrust
    experiment export saved to disk and writes the converter output.
    Kept verbatim for backward compatibility.

  - **Live mode** (new): ``--braintrust-experiment-id ID`` or
    ``--braintrust-project NAME [--latest | --braintrust-experiment-name
    NAME]`` pulls the experiment from the Braintrust API directly,
    enriches rows with spans, and writes the converter output.

Both modes share the same downstream flags (``--scorer``,
``--score-threshold``, ``--score-band-max``, ``--agent-revision``,
``--cluster``).

The CLI is intentionally thin — all real logic lives in
``experiment_to_failing_evals.py`` and ``braintrust_client.py`` so the
same calls work from the Pluma router and from ad-hoc scripts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .braintrust_client import BraintrustAPIError, BraintrustClient
from .experiment_to_failing_evals import (
    DEFAULT_MAX_SPANS,
    ScoreBand,
    cluster_failing_rows,
    experiment_to_failing_evals,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m pluma.integrations.braintrust.cli",
        description=(
            "Convert a Braintrust experiment into agent-researcher's "
            "failing-eval input. Reads either a saved export or the "
            "live Braintrust API."
        ),
    )

    # Input source. Exactly one of these branches.
    src = p.add_argument_group("source (pick one)")
    src.add_argument(
        "--input",
        type=Path,
        help="Saved experiment JSON export (file-mode).",
    )
    src.add_argument(
        "--braintrust-experiment-id",
        help="Pull this experiment directly via the Braintrust API.",
    )
    src.add_argument(
        "--braintrust-project",
        help=(
            "Pull from this project, paired with --latest or "
            "--braintrust-experiment-name."
        ),
    )
    src.add_argument(
        "--braintrust-experiment-name",
        help="Name of the experiment under --braintrust-project.",
    )
    src.add_argument(
        "--latest",
        action="store_true",
        help=(
            "With --braintrust-project, pull the most recent "
            "experiment in the project."
        ),
    )
    src.add_argument(
        "--no-spans",
        action="store_true",
        help=(
            "Skip fetching span data in live mode. Faster, less "
            "diagnostic context."
        ),
    )

    # Output.
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Where to write the converted JSON.",
    )

    # Filter / shaping.
    p.add_argument(
        "--scorer",
        default=None,
        help=(
            "Primary scorer name. Defaults to the first scorer in "
            "each row."
        ),
    )
    p.add_argument(
        "--score-threshold",
        type=float,
        default=1.0,
        help=(
            "Minimum passing score for the primary scorer "
            "(default: 1.0)."
        ),
    )
    p.add_argument(
        "--score-band-max",
        type=float,
        default=None,
        help=(
            "Maximum passing score for the primary scorer. With "
            "--score-threshold, defines a band; useful for "
            "calibration-style scorers where over-confidence is also "
            "a failure."
        ),
    )
    p.add_argument(
        "--agent-revision",
        default=None,
        help=(
            "Git SHA (or similar) for the agent source that produced "
            "this experiment. Pinned to metadata so the downstream "
            "diagnoser knows which source to read. If absent, the "
            "adapter looks for agent_revision/git_sha in the "
            "experiment's own metadata."
        ),
    )
    p.add_argument(
        "--max-spans",
        type=int,
        default=DEFAULT_MAX_SPANS,
        help=(
            f"Trim each row's spans to at most this many entries "
            f"(default: {DEFAULT_MAX_SPANS}). Pass -1 to disable."
        ),
    )
    p.add_argument(
        "--cluster",
        choices=("none", "first", "worst"),
        default="none",
        help=(
            "Pre-cluster failing rows by scorer signature + "
            "(expected, predicted). 'first' picks the earliest row "
            "as cluster representative; 'worst' picks the lowest "
            "primary-scorer score. Default: none."
        ),
    )

    return p


def _load_experiment(args: argparse.Namespace) -> dict:
    """Resolve the input source and return an experiment dict.

    Exactly one of (--input, --braintrust-experiment-id,
    --braintrust-project) must be set.
    """
    sources = [
        bool(args.input),
        bool(args.braintrust_experiment_id),
        bool(args.braintrust_project),
    ]
    if sum(sources) != 1:
        raise SystemExit(
            "Specify exactly one of: --input, "
            "--braintrust-experiment-id, --braintrust-project."
        )

    if args.input:
        return json.loads(Path(args.input).read_text())

    client = BraintrustClient()
    experiment_id = client.resolve_experiment_id(
        experiment_id=args.braintrust_experiment_id,
        project=args.braintrust_project,
        experiment_name=args.braintrust_experiment_name,
        latest=args.latest,
    )
    return client.fetch_experiment_export(
        experiment_id,
        with_spans=not args.no_spans,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        experiment = _load_experiment(args)
    except BraintrustAPIError as e:
        print(
            f"Braintrust API error: {e}",
            file=sys.stderr,
        )
        if e.status:
            print(f"  status: {e.status}", file=sys.stderr)
        if e.body:
            print(f"  body: {e.body[:500]}", file=sys.stderr)
        return 3

    band = ScoreBand(
        min_score=args.score_threshold,
        max_score=(
            args.score_band_max
            if args.score_band_max is not None
            else max(args.score_threshold, 1.0)
        ),
    )

    max_spans = None if args.max_spans == -1 else args.max_spans

    container = experiment_to_failing_evals(
        experiment,
        primary_scorer=args.scorer,
        score_band=band,
        agent_revision=args.agent_revision,
        max_spans=max_spans,
    )

    if args.cluster != "none":
        container = cluster_failing_rows(
            container, representative=args.cluster
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(container, indent=2, sort_keys=False) + "\n"
    )

    n_results = len(container.get("results") or [])
    suffix = " (clustered)" if args.cluster != "none" else ""
    print(
        f"Wrote {n_results} failing record(s){suffix} to {args.output} "
        f"(pass_rate={container.get('pass_rate')}, "
        f"total={container.get('total')}).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
