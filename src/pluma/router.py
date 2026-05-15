"""Intent routing — explicit subcommands + inferred `diagnose` / `watch`.

Pluma exposes two routing paths:

1. **Explicit subcommands** map 1:1 to a (tool, verb) pair:

       pluma diagnose-funnel  → funnel-researcher diagnose
       pluma diagnose-agent   → agent-researcher  diagnose
       pluma watch            → integration-watcher watch
       pluma apply            → mechanical, reads Origin tag from the Pluma
                                report and routes to the matching tool
       pluma iterate          → ditto
       pluma cross            → see cross.py (Phase 3)

2. **Inferred subcommands** — Pluma's top-level `diagnose` and `watch` verbs
   sniff the flags passed and route to the tool that matches. Verbs are
   held distinct (refinement A): `diagnose` is for funnel- and
   agent-researcher only; `watch` is for integration-watcher only. Inferred
   routing never collapses the two.

   Ambiguous flag-sets exit 2 with a message naming the explicit alternatives.

This module is pure: it returns a `Route` object; calling the matching
runner is the CLI's job (Phase 2.5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional


Tool = Literal["funnel-researcher", "integration-watcher", "agent-researcher"]
Verb = Literal["diagnose", "watch", "apply", "iterate"]


@dataclass
class Route:
    """Where a CLI invocation should be dispatched.

    `error` is set when routing failed (ambiguous or no match); the CLI uses
    it to print the message and exit 2.
    """

    tool: Optional[Tool] = None
    verb: Optional[Verb] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.tool is not None and self.verb is not None


# =========================================================================
# Explicit subcommands
# =========================================================================


_EXPLICIT_SUBCOMMANDS: dict[str, tuple[Tool, Verb]] = {
    "diagnose-funnel": ("funnel-researcher", "diagnose"),
    "diagnose-agent": ("agent-researcher", "diagnose"),
    "watch": ("integration-watcher", "watch"),
}


def route_explicit(subcommand: str) -> Optional[Route]:
    """Resolve an explicit Pluma subcommand to a (tool, verb).

    Returns None for subcommands that need their own handling (`apply`,
    `iterate`, `cross`) — those are routed by the CLI, not by sniffing.
    """
    if subcommand in _EXPLICIT_SUBCOMMANDS:
        tool, verb = _EXPLICIT_SUBCOMMANDS[subcommand]
        return Route(tool=tool, verb=verb)
    return None


# =========================================================================
# Inferred routing for `diagnose` and `watch`
# =========================================================================


# Flag-set signatures. Each entry: tool, required flags, optional flags.
# A flag is "present" when its key appears in the parsed flag dict with a
# non-None value.
@dataclass(frozen=True)
class _Signature:
    tool: Tool
    verb: Verb
    required: frozenset[str]


_DIAGNOSE_SIGNATURES: tuple[_Signature, ...] = (
    _Signature(
        tool="funnel-researcher",
        verb="diagnose",
        required=frozenset({"funnel", "dropoff", "product"}),
    ),
    _Signature(
        tool="agent-researcher",
        verb="diagnose",
        required=frozenset({"eval_result", "target_agent"}),
    ),
)

_WATCH_SIGNATURES: tuple[_Signature, ...] = (
    _Signature(
        tool="integration-watcher",
        verb="watch",
        required=frozenset({"traces", "cohort", "product"}),
    ),
)


def route_inferred(verb: str, flags: dict[str, object]) -> Route:
    """Sniff `flags` to determine which tool to dispatch to.

    `verb` is the Pluma top-level verb (`"diagnose"` or `"watch"`). `flags`
    is a dict where keys are snake_case flag names (`funnel`, `dropoff`,
    `traces`, etc.) and values are non-None when the flag was passed.
    """
    if verb == "diagnose":
        sigs = _DIAGNOSE_SIGNATURES
        other_verb = "watch"
        other_sigs = _WATCH_SIGNATURES
    elif verb == "watch":
        sigs = _WATCH_SIGNATURES
        other_verb = "diagnose"
        other_sigs = _DIAGNOSE_SIGNATURES
    else:
        return Route(error=f"inferred routing not supported for verb {verb!r}")

    present = {k for k, v in flags.items() if v is not None}
    matches = [s for s in sigs if s.required.issubset(present)]

    if len(matches) == 1:
        return Route(tool=matches[0].tool, verb=matches[0].verb)

    if len(matches) > 1:
        names = ", ".join(_explicit_name_for(s) for s in matches)
        return Route(
            error=(
                f"`pluma {verb}` matched multiple tools ({names}). "
                "Disambiguate with an explicit subcommand."
            )
        )

    # Zero matches — list what each signature would have needed. If the
    # supplied flags actually fit the *other* top-level verb, surface that
    # as a redirect (refinement A: verbs stay distinct, but the help is
    # cross-aware).
    hints: list[str] = []
    for s in sigs:
        missing = sorted(s.required - present)
        hints.append(
            f"  {_explicit_name_for(s)}: needs {', '.join('--' + m.replace('_', '-') for m in sorted(s.required))} "
            f"(missing: {', '.join('--' + m.replace('_', '-') for m in missing)})"
        )

    cross_match = next((s for s in other_sigs if s.required.issubset(present)), None)
    redirect = ""
    if cross_match is not None:
        redirect = (
            f"\nThe flags you passed match `pluma {other_verb}` "
            f"(routes to {cross_match.tool}). Re-run as: "
            f"`pluma {other_verb} ...`."
        )

    return Route(
        error=(
            f"`pluma {verb}` could not infer a tool from the flags you passed.\n"
            "Either pass the full flag set for one of:\n"
            + "\n".join(hints)
            + "\nOr use an explicit subcommand: "
            + ", ".join(_explicit_names_for_verb(verb))
            + "."
            + redirect
        )
    )


def _explicit_name_for(sig: _Signature) -> str:
    for name, (tool, verb) in _EXPLICIT_SUBCOMMANDS.items():
        if tool == sig.tool and verb == sig.verb:
            return f"pluma {name}"
    return f"{sig.tool} {sig.verb}"


def _explicit_names_for_verb(verb: str) -> list[str]:
    return [
        f"`pluma {name}`"
        for name, (_t, v) in _EXPLICIT_SUBCOMMANDS.items()
        if v == verb
    ]


# =========================================================================
# `apply` / `iterate` — origin-tag routing from a Pluma report
# =========================================================================


_ORIGIN_RE = re.compile(r"^Origin:\s*([\w-]+)\s*$", re.MULTILINE)


def route_from_report(report_path: Path) -> Route:
    """Read the `Origin:` line out of a Pluma report and route `apply`/`iterate`
    to that tool's runner.

    Pluma's normalized reports tag the source tool in their metadata header.
    The CLI's `apply` / `iterate` subcommands use this so the user doesn't
    have to remember which tool produced a given report.
    """
    if not report_path.is_file():
        return Route(error=f"report not found: {report_path}")
    text = report_path.read_text()
    m = _ORIGIN_RE.search(text)
    if not m:
        return Route(
            error=(
                f"no `Origin:` tag found in {report_path}. Run a diagnose/watch "
                "via Pluma first so the report is normalized."
            )
        )
    origin = m.group(1)
    if origin not in ("funnel-researcher", "integration-watcher", "agent-researcher"):
        return Route(error=f"unrecognized Origin tag: {origin!r}")
    return Route(tool=origin, verb="apply")  # caller swaps in "iterate" if needed
