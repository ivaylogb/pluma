"""Pluma CLI.

Subcommands:
    diagnose-funnel       funnel-researcher diagnose
    diagnose-agent        agent-researcher diagnose
    watch                 integration-watcher watch
    diagnose              inferred routing → funnel- or agent-researcher
    apply                 origin-tag routing from a Pluma report
    iterate               ditto
    cross                 cross-tool report (Phase 3 — stub here)
    --version

Exit-code union (preserves agent-researcher's 6/7/8 for its apply flow):
    0 success
    2 missing input file/dir / parse error / routing ambiguity
    3 generation runtime error / parse failure
    4 hypothesis or finding not applyable
    5 empty / all-errored iterate or baseline-eval failure
    6 agent-researcher apply: edit application failed
    7 agent-researcher apply: re-eval failed (edits left on disk)
    8 agent-researcher iterate: catastrophic orchestration error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

from . import __version__
from . import cache as cache_mod
from . import router as router_mod
from . import runners
from .integrations.braintrust.braintrust_client import (
    DEFAULT_BASE_URL as BRAINTRUST_DEFAULT_BASE_URL,
    BraintrustAPIError,
    fetch_experiment_as_failing_evals,
)
from .integrations.braintrust.experiment_to_failing_evals import (
    DEFAULT_MAX_SPANS,
    ScoreBand,
)
from .integrations.langsmith.langsmith_client import (
    DEFAULT_BASE_URL as LANGSMITH_DEFAULT_BASE_URL,
    LangSmithAPIError,
    fetch_runs_as_failing_evals,
)
from .integrations.langsmith.runs_to_failing_evals import (
    DEFAULT_MAX_TOTAL_NODES as LANGSMITH_DEFAULT_MAX_TOTAL_NODES,
    DEFAULT_MAX_TREE_DEPTH as LANGSMITH_DEFAULT_MAX_TREE_DEPTH,
    DEFAULT_THRESHOLD as LANGSMITH_DEFAULT_THRESHOLD,
)

# Sister-tool dispatch table for `apply` / `iterate`.
_APPLY_RUNNERS = {
    "funnel-researcher": runners.funnel_apply,
    "integration-watcher": runners.integration_apply,
    "agent-researcher": runners.agent_apply,
}
_ITERATE_RUNNERS = {
    "funnel-researcher": runners.funnel_iterate,
    "integration-watcher": runners.integration_iterate,
    "agent-researcher": runners.agent_iterate,
}


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "version", False):
        print(f"pluma {__version__}")
        return 0

    sub = args.subcommand
    if sub is None:
        parser.print_help()
        return 0

    if sub in {"diagnose-funnel", "diagnose-agent", "watch"}:
        return _run_explicit(args, sub)
    if sub == "diagnose":
        return _run_inferred(args, verb="diagnose")
    if sub == "apply":
        return _run_apply_or_iterate(args, verb="apply")
    if sub == "iterate":
        return _run_apply_or_iterate(args, verb="iterate")
    if sub == "cross":
        return _run_cross(args)

    parser.error(f"unknown subcommand: {sub}")
    return 2


# =========================================================================
# Argument parser
# =========================================================================


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pluma",
        description=(
            "Orchestrator for agent-researcher, funnel-researcher, "
            "integration-watcher."
        ),
    )
    parser.add_argument("--version", action="store_true")
    subs = parser.add_subparsers(dest="subcommand")

    # diagnose-funnel
    p = subs.add_parser("diagnose-funnel", help="funnel-researcher diagnose")
    _add_funnel_diagnose_flags(p)

    # diagnose-agent
    p = subs.add_parser("diagnose-agent", help="agent-researcher diagnose")
    # --eval-result becomes one of several sources (the others being a
    # live Braintrust experiment or live LangSmith runs), so argparse no
    # longer hard-requires it; the handler validates that exactly one
    # source is present.
    _add_agent_diagnose_flags(p, eval_result_required=False)
    _add_braintrust_source_flags(p)
    _add_langsmith_source_flags(p)

    # watch
    p = subs.add_parser("watch", help="integration-watcher watch")
    _add_watch_flags(p)

    # diagnose (inferred)
    p = subs.add_parser(
        "diagnose",
        help="inferred: funnel- or agent-researcher based on flags",
    )
    _add_funnel_diagnose_flags(p, required=False)
    _add_agent_diagnose_flags(p, required=False, skip_output=True)
    p.add_argument("--output-file", type=Path, required=True)

    # apply / iterate
    for name in ("apply", "iterate"):
        p = subs.add_parser(name, help=f"{name} a Pluma-normalized report")
        p.add_argument("--report", type=Path, required=True,
                       help="Pluma report from a prior diagnose/watch.")
        p.add_argument("--product", type=Path, required=False,
                       help="Product directory (funnel/integration tools).")
        p.add_argument("--target-agent", type=Path, required=False,
                       help="Target agent directory (agent-researcher only).")
        p.add_argument("--eval-command", type=str, required=False,
                       help="Eval command (agent-researcher only).")
        p.add_argument("--output-file", type=Path, required=True)
        p.add_argument("--hypothesis-id", type=str, required=False,
                       help="Hypothesis/finding id (apply only).")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--no-cache", action="store_true",
                       help="Bypass the input-hash cache for this run.")
        p.add_argument("--force", action="store_true",
                       help="Re-run even on a cache hit.")

    # cross — run ≥2 tools against the same product surface
    p = subs.add_parser("cross", help="cross-tool report (≥2 tools, one product surface)")
    p.add_argument("--product", type=Path, required=True)
    p.add_argument("--funnel", type=Path)
    p.add_argument("--dropoff", type=Path)
    p.add_argument("--traces", type=Path)
    p.add_argument("--cohort", type=Path)
    p.add_argument("--eval-result", type=Path)
    p.add_argument("--target-agent", type=Path)
    p.add_argument("--model", type=str, default=None)
    p.add_argument("--max-tokens", type=int, default=None)
    p.add_argument("--extra-file", type=Path, action="append", default=[])
    p.add_argument("--output-file", type=Path, required=True)
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--force", action="store_true")

    return parser


def _add_funnel_diagnose_flags(p: argparse.ArgumentParser, *, required: bool = True) -> None:
    p.add_argument("--funnel", type=Path, required=required)
    p.add_argument("--dropoff", type=Path, required=required)
    p.add_argument("--product", type=Path, required=required)
    if required:
        p.add_argument("--output-file", type=Path, required=True)
    p.add_argument("--model", type=str, default=None)
    p.add_argument("--max-tokens", type=int, default=None)
    p.add_argument("--extra-file", type=Path, action="append", default=[])
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--force", action="store_true")


def _add_agent_diagnose_flags(
    p: argparse.ArgumentParser,
    *,
    required: bool = True,
    skip_output: bool = False,
    eval_result_required: bool = True,
) -> None:
    p.add_argument("--target-agent", type=Path, required=required)
    p.add_argument(
        "--eval-result",
        type=Path,
        required=required and eval_result_required,
        help="agent-researcher failing-eval JSON (file source).",
    )
    p.add_argument("--scenario-id", type=str, default=None)
    p.add_argument("--scenario-input", type=str, default=None)
    p.add_argument("--scenario-input-file", type=Path, default=None)
    p.add_argument("--model", type=str, default=None) if not p._has_action("--model") else None
    if required and not skip_output:
        p.add_argument("--output-file", type=Path, required=True)
    if not p._has_action("--no-cache"):
        p.add_argument("--no-cache", action="store_true")
        p.add_argument("--force", action="store_true")


def _add_braintrust_source_flags(p: argparse.ArgumentParser) -> None:
    """Live-Braintrust source for diagnose-agent.

    These substitute for --eval-result: instead of a saved failing-eval
    file, the experiment is pulled from the Braintrust API, converted, and
    fed to agent-researcher. The handler enforces that exactly one source
    (file or Braintrust) is given. The shaping flags mirror the standalone
    braintrust CLI so behavior is identical on either entry point.
    """
    g = p.add_argument_group("braintrust source (alternative to --eval-result)")
    g.add_argument(
        "--braintrust-experiment-id",
        type=str,
        default=None,
        help="Diagnose this Braintrust experiment, pulled live via the API.",
    )
    g.add_argument(
        "--braintrust-project",
        type=str,
        default=None,
        help="Braintrust project to pull from; pair with --latest.",
    )
    g.add_argument(
        "--latest",
        action="store_true",
        help="With --braintrust-project, use the project's most recent experiment.",
    )
    g.add_argument(
        "--braintrust-api-key",
        type=str,
        default=None,
        help="Braintrust API key. Falls back to the BRAINTRUST_API_KEY env var.",
    )
    g.add_argument(
        "--braintrust-base-url",
        type=str,
        default=BRAINTRUST_DEFAULT_BASE_URL,
        help=f"Braintrust API base URL (default: {BRAINTRUST_DEFAULT_BASE_URL}).",
    )
    g.add_argument(
        "--scorer",
        type=str,
        default=None,
        help="Primary scorer name. Defaults to each row's first scorer.",
    )
    g.add_argument(
        "--score-band-min",
        type=float,
        default=1.0,
        help="Minimum passing score for the primary scorer (default: 1.0).",
    )
    g.add_argument(
        "--score-band-max",
        type=float,
        default=None,
        help="Maximum passing score for the primary scorer (default: the min, "
        "or 1.0). A band rejects over-confident rows for calibration scorers.",
    )
    g.add_argument(
        "--max-spans",
        type=int,
        default=DEFAULT_MAX_SPANS,
        help=f"Trim each row's spans to at most this many (default: "
        f"{DEFAULT_MAX_SPANS}). Pass -1 to disable trimming.",
    )
    g.add_argument(
        "--cluster",
        choices=("none", "first", "worst"),
        default="none",
        help="Collapse failing rows that share a failure shape into one "
        "representative ('first' or 'worst' by score). Default: none.",
    )
    g.add_argument(
        "--no-cluster",
        action="store_true",
        help="Force clustering off (overrides --cluster).",
    )


def _add_langsmith_source_flags(p: argparse.ArgumentParser) -> None:
    """Live-LangSmith source for diagnose-agent.

    Two workflows, mutually exclusive with each other, with
    --eval-result, and with the --braintrust-* flags. Workflow A
    (--langsmith-experiment-id) reads dataset reference outputs;
    workflow B (--langsmith-project [--filter]) walks production
    traces. Unlike Braintrust, agent_revision is never auto-resolved —
    --agent-revision is the only way to set it (LangSmith has no
    git-SHA convention).
    """
    g = p.add_argument_group(
        "langsmith source (alternative to --eval-result / --braintrust-*)"
    )
    g.add_argument(
        "--langsmith-experiment-id",
        type=str,
        default=None,
        help="Workflow A: diagnose this LangSmith Dataset-Experiment "
        "(tracing session) id, pulled live via the API.",
    )
    g.add_argument(
        "--langsmith-project",
        type=str,
        default=None,
        help="Workflow B: diagnose root runs in this LangSmith project "
        "(production traces).",
    )
    g.add_argument(
        "--filter",
        type=str,
        default=None,
        help="Workflow B only: a LangSmith filter-DSL expression passed "
        "through verbatim.",
    )
    g.add_argument(
        "--primary-feedback-key",
        type=str,
        default=None,
        help="Feedback key that decides pass/fail. If omitted, a run "
        "fails when any feedback key scores below --threshold.",
    )
    g.add_argument(
        "--threshold",
        type=float,
        default=LANGSMITH_DEFAULT_THRESHOLD,
        help=f"Minimum passing score for LangSmith feedback (default: "
        f"{LANGSMITH_DEFAULT_THRESHOLD}).",
    )
    g.add_argument(
        "--reference-feedback-key",
        type=str,
        default=None,
        help="Workflow B only: feedback key whose value is the "
        "reference output (populates `expected` absent a dataset "
        "Example).",
    )
    g.add_argument(
        "--agent-revision",
        type=str,
        default=None,
        help="Git SHA (or similar) for the agent source. LangSmith has "
        "no SHA convention — never auto-resolved.",
    )
    g.add_argument(
        "--max-tree-depth",
        type=int,
        default=LANGSMITH_DEFAULT_MAX_TREE_DEPTH,
        help=f"Run-tree BFS depth bound, root = 0 (default: "
        f"{LANGSMITH_DEFAULT_MAX_TREE_DEPTH}).",
    )
    g.add_argument(
        "--max-total-nodes",
        type=int,
        default=LANGSMITH_DEFAULT_MAX_TOTAL_NODES,
        help=f"Global span-node cap per run (default: "
        f"{LANGSMITH_DEFAULT_MAX_TOTAL_NODES}).",
    )
    g.add_argument(
        "--langsmith-api-key",
        type=str,
        default=None,
        help="LangSmith API key. Falls back to LANGSMITH_API_KEY.",
    )
    g.add_argument(
        "--langsmith-base-url",
        type=str,
        default=LANGSMITH_DEFAULT_BASE_URL,
        help=f"LangSmith API base URL (default: "
        f"{LANGSMITH_DEFAULT_BASE_URL}).",
    )


def _add_watch_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--traces", type=Path, required=True)
    p.add_argument("--cohort", type=Path, required=True)
    p.add_argument("--product", type=Path, required=True)
    p.add_argument("--output-file", type=Path, required=True)
    p.add_argument("--model", type=str, default=None)
    p.add_argument("--max-tokens", type=int, default=None)
    p.add_argument("--extra-file", type=Path, action="append", default=[])
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--force", action="store_true")


# argparse doesn't expose `_has_action`; monkey-patch it for the multi-add cases.
def _has_action(self, flag: str) -> bool:
    return any(flag in a.option_strings for a in self._actions)


argparse.ArgumentParser._has_action = _has_action  # type: ignore[attr-defined]


# =========================================================================
# Subcommand handlers
# =========================================================================


def _run_explicit(args: argparse.Namespace, sub: str) -> int:
    route = router_mod.route_explicit(sub)
    assert route is not None and route.ok, f"explicit route missing for {sub}"

    if route.tool == "funnel-researcher":
        return _wrap_cache(
            tool="funnel-researcher",
            inputs=[
                ("funnel", args.funnel),
                ("dropoff", args.dropoff),
                ("product", args.product),
                ("model", args.model),
                ("max_tokens", args.max_tokens),
                ("extra_files", tuple(args.extra_file)),
            ],
            args=args,
            runner_fn=lambda dest: runners.funnel_diagnose(
                funnel=args.funnel,
                dropoff=args.dropoff,
                product=args.product,
                output_file=dest,
                model=args.model,
                max_tokens=args.max_tokens,
                extra_files=args.extra_file,
            ),
        )
    if route.tool == "agent-researcher":
        # `getattr` defaults keep the inferred-`diagnose` re-dispatch (which
        # reuses this branch with a parser that has no Braintrust flags)
        # working unchanged.
        bt_exp = getattr(args, "braintrust_experiment_id", None)
        bt_proj = getattr(args, "braintrust_project", None)
        bt_latest = getattr(args, "latest", False)
        ls_exp = getattr(args, "langsmith_experiment_id", None)
        ls_proj = getattr(args, "langsmith_project", None)
        eval_result = getattr(args, "eval_result", None)

        err = _validate_agent_source(
            eval_result=eval_result,
            bt_exp=bt_exp,
            bt_proj=bt_proj,
            bt_latest=bt_latest,
            ls_exp=ls_exp,
            ls_proj=ls_proj,
        )
        if err is not None:
            print(err, file=sys.stderr)
            return 2

        if bt_exp or bt_proj:
            return _run_agent_diagnose_live(args)
        if ls_exp or ls_proj:
            return _run_agent_diagnose_live_langsmith(args)

        return _wrap_cache(
            tool="agent-researcher",
            inputs=[
                ("target_agent", args.target_agent),
                ("eval_result", args.eval_result),
                ("scenario_id", args.scenario_id),
                ("scenario_input", args.scenario_input),
                ("model", args.model),
            ],
            args=args,
            runner_fn=lambda dest: runners.agent_diagnose(
                target_agent=args.target_agent,
                eval_result=args.eval_result,
                output_file=dest,
                scenario_id=args.scenario_id,
                scenario_input=args.scenario_input,
                scenario_input_file=args.scenario_input_file,
                model=args.model,
            ),
        )
    if route.tool == "integration-watcher":
        return _wrap_cache(
            tool="integration-watcher",
            inputs=[
                ("traces", args.traces),
                ("cohort", args.cohort),
                ("product", args.product),
                ("model", args.model),
                ("max_tokens", args.max_tokens),
                ("extra_files", tuple(args.extra_file)),
            ],
            args=args,
            runner_fn=lambda dest: runners.integration_watch(
                traces=args.traces,
                cohort=args.cohort,
                product=args.product,
                output_file=dest,
                model=args.model,
                max_tokens=args.max_tokens,
                extra_files=args.extra_file,
            ),
        )
    return 2  # unreachable


def _validate_agent_source(
    *,
    eval_result: Optional[Path],
    bt_exp: Optional[str],
    bt_proj: Optional[str],
    bt_latest: bool,
    ls_exp: Optional[str] = None,
    ls_proj: Optional[str] = None,
) -> Optional[str]:
    """Enforce the diagnose-agent source rules. Returns an error string to
    print (caller exits 2) or None when the flags are coherent.

    Three source families — file (--eval-result), Braintrust
    (--braintrust-*), LangSmith (--langsmith-*) — exactly one. Order
    matters: the most specific conflict wins, so a stray --latest or a
    project without --latest gets a precise message instead of the
    generic "no source" one.
    """
    bt_any = bool(bt_exp or bt_proj)
    ls_any = bool(ls_exp or ls_proj)

    if bt_any and eval_result is not None:
        return (
            "diagnose-agent: --eval-result and the --braintrust-* flags are "
            "mutually exclusive — pass a file source or a Braintrust source, "
            "not both."
        )
    if ls_any and eval_result is not None:
        return (
            "diagnose-agent: --eval-result and the --langsmith-* flags are "
            "mutually exclusive — pass a file source or a LangSmith source, "
            "not both."
        )
    if bt_any and ls_any:
        return (
            "diagnose-agent: the --braintrust-* and --langsmith-* flags are "
            "mutually exclusive — pick one platform."
        )
    if bt_exp and bt_proj:
        return (
            "diagnose-agent: --braintrust-experiment-id and "
            "--braintrust-project are mutually exclusive."
        )
    if bt_proj and not bt_latest:
        return (
            "diagnose-agent: --braintrust-project requires --latest "
            "(project + named-experiment mode is not exposed here yet)."
        )
    if bt_latest and not bt_proj:
        return "diagnose-agent: --latest requires --braintrust-project."
    if ls_exp and ls_proj:
        return (
            "diagnose-agent: --langsmith-experiment-id and "
            "--langsmith-project are mutually exclusive."
        )
    if not bt_any and not ls_any and eval_result is None:
        return (
            "diagnose-agent requires a source: --eval-result FILE, a "
            "--braintrust-* source (--braintrust-experiment-id ID, or "
            "--braintrust-project NAME --latest), or a --langsmith-* "
            "source (--langsmith-experiment-id ID, or --langsmith-project "
            "NAME)."
        )
    return None


def _run_agent_diagnose_live(args: argparse.Namespace) -> int:
    """Pull a Braintrust experiment, convert it, and run agent-researcher.

    The converted container is the same JSON shape agent-researcher's
    loader reads from --eval-result, so it is staged to a temp file and
    fed through the existing runner unchanged. The Braintrust path does
    not use the input-hash cache: a live pull is keyed on an experiment
    id, not file contents, and the temp path is per-run, so a cache entry
    could never hit. --no-cache/--force are therefore inert here.
    """
    band = ScoreBand(
        min_score=args.score_band_min,
        max_score=(
            args.score_band_max
            if args.score_band_max is not None
            else max(args.score_band_min, 1.0)
        ),
    )
    max_spans = None if args.max_spans == -1 else args.max_spans
    cluster = "none" if args.no_cluster else args.cluster

    try:
        container = fetch_experiment_as_failing_evals(
            experiment_id=args.braintrust_experiment_id,
            project=args.braintrust_project,
            latest=args.latest,
            api_key=args.braintrust_api_key,
            base_url=args.braintrust_base_url,
            scorer=args.scorer,
            score_band=band,
            max_spans=max_spans,
            cluster=cluster,
        )
    except BraintrustAPIError as e:
        print(f"Braintrust API error: {e}", file=sys.stderr)
        if e.status:
            print(f"  status: {e.status}", file=sys.stderr)
        if e.body:
            print(f"  body: {e.body[:500]}", file=sys.stderr)
        return 3

    return _stage_and_run_agent_diagnose(args, container)


def _stage_and_run_agent_diagnose(
    args: argparse.Namespace, container: dict
) -> int:
    """Stage a live-fetched container to a temp file and run
    agent-researcher on it.

    Shared by the Braintrust and LangSmith live paths: the converted
    container is the same JSON shape agent-researcher's loader reads
    from --eval-result, so it is written to a per-run temp file and fed
    through the existing runner unchanged. Neither live path uses the
    input-hash cache — a live pull is keyed on an experiment/project id,
    not file contents, and the temp path is per-run, so a cache entry
    could never hit; --no-cache/--force are inert here.
    """
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    )
    try:
        json.dump(container, tmp)
        tmp.flush()
        tmp.close()
        result = runners.agent_diagnose(
            target_agent=args.target_agent,
            eval_result=Path(tmp.name),
            output_file=args.output_file,
            scenario_id=args.scenario_id,
            scenario_input=args.scenario_input,
            scenario_input_file=args.scenario_input_file,
            model=args.model,
        )
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    return result.exit_code


def _run_agent_diagnose_live_langsmith(args: argparse.Namespace) -> int:
    """Pull live LangSmith runs (workflow A or B), convert, and run
    agent-researcher. Mirrors the Braintrust live path; the shared
    ``fetch_runs_as_failing_evals`` helper picks the workflow."""
    try:
        container = fetch_runs_as_failing_evals(
            experiment_id=args.langsmith_experiment_id,
            project=args.langsmith_project,
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

    return _stage_and_run_agent_diagnose(args, container)


def _run_inferred(args: argparse.Namespace, *, verb: str) -> int:
    flags: dict[str, object] = {
        "funnel": args.funnel,
        "dropoff": args.dropoff,
        "product": args.product,
        "eval_result": args.eval_result,
        "target_agent": args.target_agent,
    }
    route = router_mod.route_inferred(verb, flags)
    if not route.ok:
        print(route.error, file=sys.stderr)
        return 2

    # Re-dispatch by faking the corresponding explicit subcommand.
    if route.tool == "funnel-researcher":
        return _run_explicit(args, "diagnose-funnel")
    if route.tool == "agent-researcher":
        return _run_explicit(args, "diagnose-agent")
    return 2  # unreachable


def _run_apply_or_iterate(args: argparse.Namespace, *, verb: str) -> int:
    route = router_mod.route_from_report(args.report)
    if not route.ok:
        print(route.error, file=sys.stderr)
        return 2

    table = _APPLY_RUNNERS if verb == "apply" else _ITERATE_RUNNERS
    runner_fn = table[route.tool]

    if route.tool == "agent-researcher":
        if args.target_agent is None or args.eval_command is None:
            print(
                "agent-researcher apply/iterate require --target-agent and --eval-command.",
                file=sys.stderr,
            )
            return 2
        if verb == "apply":
            if args.hypothesis_id is None:
                print("`apply` requires --hypothesis-id.", file=sys.stderr)
                return 2
            try:
                hid: object = int(args.hypothesis_id.lstrip("HhFf"))
            except (ValueError, AttributeError):
                print(f"agent-researcher --hypothesis-id must be int: {args.hypothesis_id!r}",
                      file=sys.stderr)
                return 2
            result = runner_fn(
                hypothesis_report=args.report,
                hypothesis_id=hid,
                target_agent=args.target_agent,
                eval_command=args.eval_command,
                output_file=args.output_file,
                dry_run=args.dry_run,
            )
        else:
            result = runner_fn(
                hypothesis_report=args.report,
                target_agent=args.target_agent,
                eval_command=args.eval_command,
                output_file=args.output_file,
            )
        return result.exit_code

    # funnel / integration
    if args.product is None:
        print(
            f"{route.tool} apply/iterate require --product.",
            file=sys.stderr,
        )
        return 2
    if verb == "apply":
        if args.hypothesis_id is None:
            print("`apply` requires --hypothesis-id.", file=sys.stderr)
            return 2
        result = runner_fn(
            hypothesis_report=args.report,
            hypothesis_id=args.hypothesis_id,
            product=args.product,
            output_file=args.output_file,
            dry_run=args.dry_run,
        )
    else:
        result = runner_fn(
            hypothesis_report=args.report,
            product=args.product,
            output_file=args.output_file,
            dry_run=args.dry_run,
        )
    return result.exit_code


def _run_cross(args: argparse.Namespace) -> int:
    """Run ≥2 sister tools against the same product surface and emit a
    unified cross-tool report."""
    from . import comparison, cross as cross_mod

    inputs = cross_mod.CrossInputs(
        product=args.product,
        output_file=args.output_file,
        funnel=args.funnel,
        dropoff=args.dropoff,
        traces=args.traces,
        cohort=args.cohort,
        eval_result=args.eval_result,
        target_agent=args.target_agent,
        model=args.model,
        max_tokens=args.max_tokens,
        extra_files=list(args.extra_file or []),
        no_cache=args.no_cache,
        force=args.force,
    )

    result = cross_mod.run_cross(inputs)
    if result.error:
        print(result.error, file=sys.stderr)
    if result.report is None:
        return result.exit_code

    md = comparison.render_cross_report(result.report)

    # Prepend cache-hit status so the operator knows what was reused vs spent.
    if result.cache_hits:
        status_lines = ["Cache status:"]
        for origin, hit in result.cache_hits.items():
            status_lines.append(f"  - {origin}: {'cache hit' if hit else 'live run'}")
        print("\n".join(status_lines), file=sys.stderr)

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text(md)
    n_cross = len(result.report.cross_matches)
    unique_total = sum(
        1
        for origin, pluma_report in result.report.per_tool.items()
        for f in pluma_report.findings
        if (origin, f.id) not in {
            (o, f2.id) for m in result.report.cross_matches for o, f2 in m.findings
        }
    )
    print(
        f"[cross: {n_cross} cross-tool finding(s), {unique_total} unique → "
        f"{args.output_file}]",
        file=sys.stderr,
    )
    return 0


# =========================================================================
# Cache integration
# =========================================================================


def _wrap_cache(
    *,
    tool: str,
    inputs: list,
    args: argparse.Namespace,
    runner_fn,
) -> int:
    """Run the given diagnose/watch runner through the cache layer.

    `runner_fn` is a callable that accepts a destination path and returns a
    `RunResult`. The cache picks the destination (under ``~/.pluma/cache/``)
    and short-circuits on hits unless `--force` is set.

    After a successful run the cached file is copied to the user's
    `--output-file` so they get a stable, named artifact.
    """
    user_out: Path = args.output_file

    if args.no_cache:
        result = runner_fn(user_out)
        return result.exit_code

    cached = cache_mod.run_with_cache(
        tool=tool,
        inputs=inputs,
        runner=runner_fn,
        force=args.force,
    )
    if cached.exit_code != 0:
        return cached.exit_code

    user_out.parent.mkdir(parents=True, exist_ok=True)
    if cached.output_path != user_out:
        user_out.write_text(cached.output_path.read_text())
    if cached.from_cache:
        print(f"[cache hit] {cached.output_path} → {user_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
