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
import sys
from pathlib import Path
from typing import Optional

from . import __version__
from . import cache as cache_mod
from . import router as router_mod
from . import runners

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
    _add_agent_diagnose_flags(p)

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
    p: argparse.ArgumentParser, *, required: bool = True, skip_output: bool = False
) -> None:
    p.add_argument("--target-agent", type=Path, required=required)
    p.add_argument("--eval-result", type=Path, required=required)
    p.add_argument("--scenario-id", type=str, default=None)
    p.add_argument("--scenario-input", type=str, default=None)
    p.add_argument("--scenario-input-file", type=Path, default=None)
    p.add_argument("--model", type=str, default=None) if not p._has_action("--model") else None
    if required and not skip_output:
        p.add_argument("--output-file", type=Path, required=True)
    if not p._has_action("--no-cache"):
        p.add_argument("--no-cache", action="store_true")
        p.add_argument("--force", action="store_true")


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
