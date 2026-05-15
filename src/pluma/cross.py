"""Cross-tool report — runs ≥2 sister tools against the same product surface
and unifies their findings into one report.

Process:
    1. Determine which tools' inputs were provided (need ≥2).
    2. For each, run via cache + runner. Hits short-circuit; misses spend.
    3. Normalize each tool's markdown into a `PlumaReport`.
    4. Detect cross-tool findings:
         - mechanical: two findings share a file:line citation (range overlap)
         - categorical: two findings share a Layer AND a product surface (file)
    5. Build a correlation matrix (tool × layer → finding count).
    6. Hand the assembled `CrossReport` to `comparison.render_cross_report()`.

Match-detection design (resolved during normalize.py design, refinement C):
    `Citation.overlaps()` handles the mechanical case as a one-liner.
    Categorical matching uses the file set from each finding's citations
    plus the Layer annotation. That's why citations carry a structured
    `file` field — both matchers consume it.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Optional

from . import cache as cache_mod
from . import normalize, runners
from .runners import RunResult


# =========================================================================
# Data classes
# =========================================================================


Tool = Literal["funnel-researcher", "integration-watcher", "agent-researcher"]


@dataclass
class CrossInputs:
    """Which tool inputs the CLI received. Provided inputs determine which
    tools Pluma actually runs."""

    product: Path
    output_file: Optional[Path] = None
    funnel: Optional[Path] = None
    dropoff: Optional[Path] = None
    traces: Optional[Path] = None
    cohort: Optional[Path] = None
    eval_result: Optional[Path] = None
    target_agent: Optional[Path] = None
    model: Optional[str] = None
    max_tokens: Optional[int] = None
    extra_files: list[Path] = field(default_factory=list)
    no_cache: bool = False
    force: bool = False


@dataclass
class CrossMatch:
    """Two findings that match across tools.

    `kind` is "mechanical" (shared file:line citation) or "categorical"
    (shared Layer + shared surface file). `reason` is human-readable.
    """

    findings: list[tuple[str, normalize.Finding]]  # [(origin, finding), …]
    kind: Literal["mechanical", "categorical"]
    reason: str


@dataclass
class CrossReport:
    """Result of a cross-tool run. Consumed by comparison.render_cross_report()."""

    per_tool: dict[str, normalize.PlumaReport]
    cross_matches: list[CrossMatch]
    correlation: dict[str, dict[int, int]]  # origin → {layer: count}
    inputs: CrossInputs


# =========================================================================
# Input → tool resolution
# =========================================================================


def determine_tools(inputs: CrossInputs) -> list[Tool]:
    """List of tools whose required inputs are all present."""
    tools: list[Tool] = []
    if inputs.funnel and inputs.dropoff:
        tools.append("funnel-researcher")
    if inputs.traces and inputs.cohort:
        tools.append("integration-watcher")
    if inputs.eval_result and inputs.target_agent:
        tools.append("agent-researcher")
    return tools


# =========================================================================
# Per-tool execution (via cache + runner)
# =========================================================================


def _run_one(tool: Tool, inputs: CrossInputs) -> tuple[Path, int, bool]:
    """Run one tool. Returns (markdown_path, exit_code, from_cache)."""
    runner, cache_inputs = _build_runner(tool, inputs)

    if inputs.no_cache:
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tmp:
            dest = Path(tmp.name)
        r = runner(dest)
        return r.output_path, r.exit_code, False

    cached = cache_mod.run_with_cache(
        tool=tool, inputs=cache_inputs, runner=runner, force=inputs.force,
    )
    return cached.output_path, cached.exit_code, cached.from_cache


def _build_runner(
    tool: Tool, inputs: CrossInputs
) -> tuple[Callable[[Path], RunResult], list[tuple[str, object]]]:
    """Build the (runner, cache_inputs) pair for a given tool."""
    if tool == "funnel-researcher":
        cache_inputs = [
            ("funnel", inputs.funnel),
            ("dropoff", inputs.dropoff),
            ("product", inputs.product),
            ("model", inputs.model),
            ("max_tokens", inputs.max_tokens),
            ("extra_files", tuple(inputs.extra_files or [])),
        ]

        def _runner(dest: Path) -> RunResult:
            return runners.funnel_diagnose(
                funnel=inputs.funnel,
                dropoff=inputs.dropoff,
                product=inputs.product,
                output_file=dest,
                model=inputs.model,
                max_tokens=inputs.max_tokens,
                extra_files=inputs.extra_files,
            )

        return _runner, cache_inputs

    if tool == "integration-watcher":
        cache_inputs = [
            ("traces", inputs.traces),
            ("cohort", inputs.cohort),
            ("product", inputs.product),
            ("model", inputs.model),
            ("max_tokens", inputs.max_tokens),
            ("extra_files", tuple(inputs.extra_files or [])),
        ]

        def _runner(dest: Path) -> RunResult:
            return runners.integration_watch(
                traces=inputs.traces,
                cohort=inputs.cohort,
                product=inputs.product,
                output_file=dest,
                model=inputs.model,
                max_tokens=inputs.max_tokens,
                extra_files=inputs.extra_files,
            )

        return _runner, cache_inputs

    if tool == "agent-researcher":
        cache_inputs = [
            ("target_agent", inputs.target_agent),
            ("eval_result", inputs.eval_result),
            ("model", inputs.model),
        ]

        def _runner(dest: Path) -> RunResult:
            return runners.agent_diagnose(
                target_agent=inputs.target_agent,
                eval_result=inputs.eval_result,
                output_file=dest,
                model=inputs.model,
            )

        return _runner, cache_inputs

    raise ValueError(f"unknown tool: {tool}")


# =========================================================================
# Match detection
# =========================================================================


def detect_cross_matches(
    per_tool: dict[str, normalize.PlumaReport]
) -> list[CrossMatch]:
    """All pairwise cross-tool matches.

    A finding from tool A pairs with a finding from tool B if either:
        - any of their citations overlap (mechanical), OR
        - they share a Layer AND at least one citation file (categorical).

    Mechanical matches take precedence — if both kinds apply, the pair is
    reported as mechanical.
    """
    matches: list[CrossMatch] = []
    origins = list(per_tool.keys())
    for i, o1 in enumerate(origins):
        for o2 in origins[i + 1:]:
            for f1 in per_tool[o1].findings:
                for f2 in per_tool[o2].findings:
                    m = _match_pair(o1, f1, o2, f2)
                    if m is not None:
                        matches.append(m)
    return matches


def _match_pair(
    o1: str,
    f1: normalize.Finding,
    o2: str,
    f2: normalize.Finding,
) -> Optional[CrossMatch]:
    # Mechanical first.
    for c1 in f1.citations:
        for c2 in f2.citations:
            if c1.overlaps(c2):
                span_l = c1.line_start if c1.line_start is not None else "?"
                span_r = c1.line_end if c1.line_end is not None else span_l
                return CrossMatch(
                    findings=[(o1, f1), (o2, f2)],
                    kind="mechanical",
                    reason=f"both cite `{c1.file}:{span_l}-{span_r}`",
                )

    # Categorical: same Layer + at least one shared citation file.
    if f1.layer is not None and f1.layer == f2.layer:
        files_1 = {c.file for c in f1.citations}
        files_2 = {c.file for c in f2.citations}
        shared = files_1 & files_2
        if shared:
            surface = sorted(shared)[0]
            return CrossMatch(
                findings=[(o1, f1), (o2, f2)],
                kind="categorical",
                reason=f"same Layer {f1.layer}, shared surface `{surface}`",
            )

    return None


# =========================================================================
# Correlation matrix
# =========================================================================


def build_correlation(
    per_tool: dict[str, normalize.PlumaReport]
) -> dict[str, dict[int, int]]:
    """For each tool, count of findings per Layer."""
    out: dict[str, dict[int, int]] = {}
    for origin, report in per_tool.items():
        counts: dict[int, int] = {}
        for f in report.findings:
            if f.layer is not None:
                counts[f.layer] = counts.get(f.layer, 0) + 1
        out[origin] = dict(sorted(counts.items()))
    return out


# =========================================================================
# Top-level orchestration
# =========================================================================


@dataclass
class CrossRunResult:
    """What ``run_cross`` returns: either a complete CrossReport or an error."""

    report: Optional[CrossReport]
    exit_code: int
    error: Optional[str] = None
    cache_hits: dict[str, bool] = field(default_factory=dict)


def run_cross(inputs: CrossInputs) -> CrossRunResult:
    """Run every applicable tool, normalize each output, detect cross-matches,
    return a fully-assembled CrossReport.

    Returns a `CrossRunResult` with `exit_code` 0 on success or:
        2 — fewer than 2 tools' inputs provided
        anything else — the per-tool runner's own exit code (propagated)
    """
    tools = determine_tools(inputs)
    if len(tools) < 2:
        return CrossRunResult(
            report=None,
            exit_code=2,
            error=(
                "`pluma cross` needs inputs for at least 2 tools. Provided "
                f"inputs match: {tools or 'none'}. Pass at least two of: "
                "(--funnel + --dropoff), (--traces + --cohort), "
                "(--eval-result + --target-agent)."
            ),
        )

    per_tool: dict[str, normalize.PlumaReport] = {}
    cache_hits: dict[str, bool] = {}
    for tool in tools:
        path, exit_code, from_cache = _run_one(tool, inputs)
        cache_hits[tool] = from_cache
        if exit_code != 0:
            return CrossRunResult(
                report=None,
                exit_code=exit_code,
                error=f"{tool} run failed with exit code {exit_code}",
                cache_hits=cache_hits,
            )
        per_tool[tool] = normalize.normalize_report(path, origin=tool)

    matches = detect_cross_matches(per_tool)
    correlation = build_correlation(per_tool)
    return CrossRunResult(
        report=CrossReport(
            per_tool=per_tool,
            cross_matches=matches,
            correlation=correlation,
            inputs=inputs,
        ),
        exit_code=0,
        cache_hits=cache_hits,
    )
