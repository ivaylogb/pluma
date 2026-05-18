"""CLI wrapper for the LangSmith integration.

Two modes, one per workflow:

  - **Workflow A — Dataset-Experiment**: ``--experiment-id ID`` pulls
    the experiment's root runs (each aligned to a dataset Example) via
    the LangSmith API and writes the converted failing-eval JSON.

  - **Workflow B — Project-traced production**: ``--project NAME``
    walks the project's root runs, optionally narrowed by ``--filter``
    (a LangSmith filter-DSL string passed through verbatim).

``--experiment-id`` and ``--project`` are mutually exclusive; exactly
one is required. The CLI is intentionally thin — all real logic lives
in ``runs_to_failing_evals.py`` and ``langsmith_client.py`` so the same
calls work from the Pluma router and from ad-hoc scripts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .langsmith_client import (
    DEFAULT_BASE_URL,
    LangSmithAPIError,
    fetch_runs_as_failing_evals,
)
from .runs_to_failing_evals import (
    DEFAULT_MAX_TOTAL_NODES,
    DEFAULT_MAX_TREE_DEPTH,
    DEFAULT_THRESHOLD,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m pluma.integrations.langsmith.cli",
        description=(
            "Convert LangSmith runs into agent-researcher's failing-"
            "eval input. Workflow A: --experiment-id. Workflow B: "
            "--project [--filter]."
        ),
    )

    src = p.add_argument_group("source (pick exactly one)")
    src.add_argument(
        "--experiment-id",
        help="Workflow A: a LangSmith Dataset-Experiment (tracing "
        "session) id. Reference outputs come from each run's dataset "
        "Example.",
    )
    src.add_argument(
        "--project",
        help="Workflow B: a LangSmith project name. Production traces; "
        "no dataset reference outputs.",
    )
    src.add_argument(
        "--filter",
        default=None,
        help="Workflow B only: a LangSmith filter-DSL expression passed "
        'through verbatim, e.g. \'and(gt(start_time, '
        '"2026-05-01T00:00:00Z"), eq(feedback_key, "correctness"))\'.',
    )

    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Where to write the converted JSON.",
    )

    p.add_argument(
        "--primary-feedback-key",
        default=None,
        help="Feedback key that decides pass/fail (LangSmith does not "
        "standardize key names). If omitted, a run fails when any "
        "feedback key scores below --threshold.",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Minimum passing score (default: {DEFAULT_THRESHOLD}).",
    )
    p.add_argument(
        "--reference-feedback-key",
        default=None,
        help="Workflow B only: a feedback key whose value is the "
        "reference output, used to populate `expected` when there is "
        "no dataset Example. Default: expected is the 'unknown' "
        "sentinel.",
    )
    p.add_argument(
        "--agent-revision",
        default=None,
        help="Git SHA (or similar) for the agent source that produced "
        "these runs. LangSmith has no SHA convention, so this is the "
        "ONLY way to set it — it is never auto-resolved (deliberate "
        "difference from the Braintrust adapter).",
    )
    p.add_argument(
        "--max-tree-depth",
        type=int,
        default=DEFAULT_MAX_TREE_DEPTH,
        help=f"Run-tree BFS depth bound, root = 0 (default: "
        f"{DEFAULT_MAX_TREE_DEPTH}).",
    )
    p.add_argument(
        "--max-total-nodes",
        type=int,
        default=DEFAULT_MAX_TOTAL_NODES,
        help=f"Global cap on span nodes per run across the whole "
        f"subtree (default: {DEFAULT_MAX_TOTAL_NODES}). Root→error "
        f"paths are kept; sibling leaves dropped first.",
    )
    p.add_argument(
        "--langsmith-api-key",
        default=None,
        help="LangSmith API key. Falls back to the LANGSMITH_API_KEY "
        "env var.",
    )
    p.add_argument(
        "--langsmith-base-url",
        default=DEFAULT_BASE_URL,
        help=f"LangSmith API base URL (default: {DEFAULT_BASE_URL}).",
    )

    return p


def _validate(args: argparse.Namespace) -> None:
    """Exactly one of --experiment-id / --project; --filter is
    workflow B only."""
    if bool(args.experiment_id) == bool(args.project):
        raise SystemExit(
            "Specify exactly one of --experiment-id (workflow A) or "
            "--project (workflow B)."
        )
    if args.filter and not args.project:
        raise SystemExit("--filter applies to --project (workflow B) only.")
    if args.reference_feedback_key and not args.project:
        raise SystemExit(
            "--reference-feedback-key applies to --project (workflow B) "
            "only."
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _validate(args)

    try:
        container = fetch_runs_as_failing_evals(
            experiment_id=args.experiment_id,
            project=args.project,
            filter_expression=args.filter,
            primary_feedback_key=args.primary_feedback_key,
            threshold=args.threshold,
            reference_feedback_key=args.reference_feedback_key,
            max_tree_depth=args.max_tree_depth,
            max_total_nodes=args.max_total_nodes,
            agent_revision=args.agent_revision,
            api_key=args.langsmith_api_key,
            base_url=args.langsmith_base_url,
        )
    except LangSmithAPIError as e:
        print(f"LangSmith API error: {e}", file=sys.stderr)
        if e.status:
            print(f"  status: {e.status}", file=sys.stderr)
        if e.body:
            print(f"  body: {e.body[:500]}", file=sys.stderr)
        return 3

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(container, indent=2, sort_keys=False) + "\n"
    )

    n_results = len(container.get("results") or [])
    print(
        f"Wrote {n_results} failing record(s) to {args.output} "
        f"(pass_rate={container.get('pass_rate')}, "
        f"total={container.get('total')}).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
