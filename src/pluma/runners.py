"""Direct Python-API runners for the three sister tools.

One function per (tool, subcommand) pair. Every runner returns a `RunResult`
with the output path and the exit code, mirroring each tool's native exit
convention so the CLI can propagate them.

Design choice (resolved during discovery):
    All runners use direct Python API calls. No subprocess fallback. Sister-
    tool entrypoints are imported at module level so tests can monkey-patch
    them without touching the upstream packages.

agent-researcher's apply/iterate still spawn an eval subprocess internally —
that's the upstream tool's choice; Pluma doesn't add a second subprocess hop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import anthropic

# --- funnel-researcher ---------------------------------------------------
from funnel_researcher.applier import (
    ApplyError as FrApplyError,
    apply_edits as fr_apply_edits,
    parse_hypothesis_edits as fr_parse_edits,
)
from funnel_researcher.comparison import render_comparison as fr_render_comparison
from funnel_researcher.delta import render_delta as fr_render_delta
from funnel_researcher.hypothesis_agent import (
    generate_hypotheses as fr_generate_hypotheses,
)
from funnel_researcher.iterator import iterate_report as fr_iterate_report
from funnel_researcher.loaders import (
    load_dropoff as fr_load_dropoff,
    load_funnel as fr_load_funnel,
)
from funnel_researcher.product_reader import read_product as fr_read_product

# --- integration-watcher -------------------------------------------------
from integration_watcher.applier import (
    ApplyError as IwApplyError,
    apply_edits as iw_apply_edits,
    parse_finding_edits as iw_parse_edits,
)
from integration_watcher.comparison import render_comparison as iw_render_comparison
from integration_watcher.delta import render_delta as iw_render_delta
from integration_watcher.findings_agent import (
    generate_findings as iw_generate_findings,
)
from integration_watcher.iterator import iterate_report as iw_iterate_report
from integration_watcher.loaders import (
    load_cohort as iw_load_cohort,
    load_traces as iw_load_traces,
)
from integration_watcher.product_reader import read_product as iw_read_product
from integration_watcher.trace_analyzer import analyze_cohort as iw_analyze_cohort

# --- agent-researcher ----------------------------------------------------
from agent_researcher.applier import (
    apply_edits as ar_apply_edits,
    parse_hypothesis_report as ar_parse_report,
)
from agent_researcher.code_reader import load_target_agent as ar_load_target
from agent_researcher.comparison import (
    render_iteration_report as ar_render_iteration,
)
from agent_researcher.delta import (
    compute_delta as ar_compute_delta,
    render_delta_markdown as ar_render_delta,
)
from agent_researcher.eval_analyzer import (
    load_eval_result as ar_load_eval,
    select_failure as ar_select_failure,
)
from agent_researcher.eval_runner import (
    EvalRunError as ArEvalRunError,
    run_eval as ar_run_eval,
)
from agent_researcher.hypothesis_agent import (
    generate_hypotheses as ar_generate_hypotheses,
)
from agent_researcher.orchestrator import iterate as ar_iterate


@dataclass
class RunResult:
    """What a runner returns.

    On success, `output_path` is the written markdown and `error` is None.
    On an upstream API failure (network, rate limit, API status) `output_path`
    is None, `exit_code` is 3, and `error` carries a descriptive message so
    the CLI surfaces a clean line instead of a raw stack trace.
    """

    output_path: Optional[Path]
    exit_code: int
    error: Optional[str] = None


# =========================================================================
# funnel-researcher runners
# =========================================================================


def funnel_diagnose(
    *,
    funnel: Path,
    dropoff: Path,
    product: Path,
    output_file: Path,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    extra_files: Optional[list[Path]] = None,
) -> RunResult:
    """Run `funnel-researcher diagnose` via direct API call."""
    if not funnel.is_file():
        return RunResult(output_file, 2)
    if not dropoff.is_file():
        return RunResult(output_file, 2)
    if not product.is_dir():
        return RunResult(output_file, 2)

    try:
        funnel_def = fr_load_funnel(funnel)
        dropoff_data = fr_load_dropoff(dropoff)
        artifacts = fr_read_product(product, extra_files=extra_files or [])
    except (ValueError, FileNotFoundError, KeyError):
        return RunResult(output_file, 3)

    kw: dict = {"funnel": funnel_def, "dropoff": dropoff_data, "artifacts": artifacts}
    if model is not None:
        kw["model"] = model
    if max_tokens is not None:
        kw["max_tokens"] = max_tokens

    try:
        report = fr_generate_hypotheses(**kw)
    except anthropic.APIError as e:
        # Network / rate-limit / API-status failures from the anthropic SDK.
        # (APIConnectionError, APITimeoutError, RateLimitError, APIStatusError
        # all derive from anthropic.APIError — not from RuntimeError.)
        return RunResult(output_path=None, exit_code=3, error=f"upstream API error: {e}")
    except RuntimeError as e:
        return RunResult(output_path=None, exit_code=3, error=str(e))

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(report.markdown)
    return RunResult(output_file, 0)


def funnel_apply(
    *,
    hypothesis_report: Path,
    hypothesis_id: str,
    product: Path,
    output_file: Path,
    dry_run: bool = False,
) -> RunResult:
    """Run `funnel-researcher apply` via direct API call."""
    if not hypothesis_report.is_file():
        return RunResult(output_file, 2)
    if not product.is_dir():
        return RunResult(output_file, 2)

    try:
        spec = fr_parse_edits(hypothesis_report, hypothesis_id)
    except (ValueError, FileNotFoundError):
        return RunResult(output_file, 3)

    if not spec.applyable:
        return RunResult(output_file, 4)

    try:
        applied = fr_apply_edits(spec, product, dry_run=dry_run)
    except (FrApplyError, FileNotFoundError, ValueError):
        return RunResult(output_file, 3)

    summary = _summary_from_report(
        hypothesis_report, hypothesis_id, label="Hypothesis"
    )
    delta_md = fr_render_delta(applied, summary, product_dir=product, dry_run=dry_run)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(delta_md)
    return RunResult(output_file, 0)


def funnel_iterate(
    *,
    hypothesis_report: Path,
    product: Path,
    output_file: Path,
    dry_run: bool = False,
) -> RunResult:
    """Run `funnel-researcher iterate` via direct API call."""
    if not hypothesis_report.is_file():
        return RunResult(output_file, 2)
    if not product.is_dir():
        return RunResult(output_file, 2)

    try:
        results = fr_iterate_report(hypothesis_report, product, dry_run=dry_run)
    except (ValueError, FileNotFoundError):
        return RunResult(output_file, 3)

    n_applied = sum(
        1 for r in results if r.applyable and r.applied_edits and not r.error
    )
    n_skipped = sum(1 for r in results if not r.applyable and not r.error)

    md = fr_render_comparison(
        results, report_path=hypothesis_report, product_dir=product, dry_run=dry_run
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(md)

    if not results or (n_applied == 0 and n_skipped == 0):
        return RunResult(output_file, 5)
    return RunResult(output_file, 0)


# =========================================================================
# integration-watcher runners
# =========================================================================


def integration_watch(
    *,
    traces: Path,
    cohort: Path,
    product: Path,
    output_file: Path,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    extra_files: Optional[list[Path]] = None,
) -> RunResult:
    """Run `integration-watcher watch` via direct API call."""
    if not traces.is_file():
        return RunResult(output_file, 2)
    if not cohort.is_file():
        return RunResult(output_file, 2)
    if not product.is_dir():
        return RunResult(output_file, 2)

    try:
        cohort_def = iw_load_cohort(cohort)
        trace_list = iw_load_traces(traces)
    except (ValueError, KeyError, FileNotFoundError):
        return RunResult(output_file, 3)

    analysis = iw_analyze_cohort(trace_list)
    try:
        artifacts = iw_read_product(product, extra_files=extra_files or [])
    except (ValueError, FileNotFoundError):
        return RunResult(output_file, 3)

    kw: dict = {
        "cohort": cohort_def,
        "traces": trace_list,
        "analysis": analysis,
        "artifacts": artifacts,
    }
    if model is not None:
        kw["model"] = model
    if max_tokens is not None:
        kw["max_tokens"] = max_tokens

    try:
        report = iw_generate_findings(**kw)
    except anthropic.APIError as e:
        return RunResult(output_path=None, exit_code=3, error=f"upstream API error: {e}")
    except RuntimeError as e:
        return RunResult(output_path=None, exit_code=3, error=str(e))

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(report.markdown)
    return RunResult(output_file, 0)


def integration_apply(
    *,
    hypothesis_report: Path,
    hypothesis_id: str,
    product: Path,
    output_file: Path,
    dry_run: bool = False,
) -> RunResult:
    """Run `integration-watcher apply` via direct API call.

    Note: integration-watcher's CLI keeps the `--hypothesis-report` /
    `--hypothesis-id` flag names even though the entity is a Finding. Pluma
    keeps the runner parameter names matching the upstream CLI.
    """
    if not hypothesis_report.is_file():
        return RunResult(output_file, 2)
    if not product.is_dir():
        return RunResult(output_file, 2)

    try:
        spec = iw_parse_edits(hypothesis_report, hypothesis_id)
    except (ValueError, FileNotFoundError):
        return RunResult(output_file, 3)

    if not spec.applyable:
        return RunResult(output_file, 4)

    try:
        applied = iw_apply_edits(spec, product, dry_run=dry_run)
    except (IwApplyError, FileNotFoundError, ValueError):
        return RunResult(output_file, 3)

    summary = _summary_from_report(
        hypothesis_report, hypothesis_id, label="Finding"
    )
    delta_md = iw_render_delta(applied, summary, product_dir=product, dry_run=dry_run)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(delta_md)
    return RunResult(output_file, 0)


def integration_iterate(
    *,
    hypothesis_report: Path,
    product: Path,
    output_file: Path,
    dry_run: bool = False,
) -> RunResult:
    """Run `integration-watcher iterate` via direct API call."""
    if not hypothesis_report.is_file():
        return RunResult(output_file, 2)
    if not product.is_dir():
        return RunResult(output_file, 2)

    try:
        results = iw_iterate_report(hypothesis_report, product, dry_run=dry_run)
    except (ValueError, FileNotFoundError):
        return RunResult(output_file, 3)

    n_applied = sum(
        1 for r in results if r.applyable and r.applied_edits and not r.error
    )
    n_skipped = sum(1 for r in results if not r.applyable and not r.error)

    md = iw_render_comparison(
        results, report_path=hypothesis_report, product_dir=product, dry_run=dry_run
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(md)

    if not results or (n_applied == 0 and n_skipped == 0):
        return RunResult(output_file, 5)
    return RunResult(output_file, 0)


# =========================================================================
# agent-researcher runners
# =========================================================================


def agent_diagnose(
    *,
    target_agent: Path,
    eval_result: Path,
    output_file: Path,
    scenario_id: Optional[str] = None,
    scenario_input: Optional[str] = None,
    scenario_input_file: Optional[Path] = None,
    model: Optional[str] = None,
) -> RunResult:
    """Run `agent-researcher diagnose` via direct API call.

    Unlike the upstream CLI (where `--output-file` is optional), Pluma always
    writes the markdown to `output_file` for consistency with the other two
    tools' canonical-file convention.
    """
    if not target_agent.is_dir():
        return RunResult(output_file, 2)
    if not eval_result.is_file():
        return RunResult(output_file, 2)

    try:
        target = ar_load_target(target_agent)
        eval_summary = ar_load_eval(eval_result)
        failure = ar_select_failure(eval_summary, scenario_id=scenario_id)
    except (FileNotFoundError, ValueError):
        return RunResult(output_file, 2)

    if scenario_input is None and scenario_input_file is not None:
        scenario_input = scenario_input_file.read_text().strip()

    kw: dict = {"target": target, "failure": failure, "scenario_input": scenario_input}
    if model is not None:
        kw["model"] = model

    try:
        report = ar_generate_hypotheses(**kw)
    except anthropic.APIError as e:
        return RunResult(output_path=None, exit_code=3, error=f"upstream API error: {e}")
    except RuntimeError as e:
        return RunResult(output_path=None, exit_code=3, error=str(e))

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(report.markdown + "\n")
    return RunResult(output_file, 0)


def agent_apply(
    *,
    hypothesis_report: Path,
    hypothesis_id: int,
    target_agent: Path,
    eval_command: str,
    output_file: Path,
    scenario_id: Optional[str] = None,
    eval_cwd: Optional[Path] = None,
    eval_result_path: Optional[Path] = None,
    eval_timeout: int = 300,
    dry_run: bool = False,
) -> RunResult:
    """Run `agent-researcher apply` via direct API calls.

    Preserves the upstream tool's exit-code map (incl. 6/7 for application /
    re-eval failure) by mirroring the same step sequence: parse → baseline
    eval → apply → re-eval → delta.
    """
    if not hypothesis_report.is_file():
        return RunResult(output_file, 2)
    if not target_agent.is_dir():
        return RunResult(output_file, 2)

    try:
        spec = ar_parse_report(hypothesis_report, hypothesis_id)
    except (FileNotFoundError, ValueError):
        return RunResult(output_file, 2)

    if not spec.applyable:
        return RunResult(output_file, 4)

    if dry_run:
        try:
            ar_apply_edits(target_agent, spec, dry_run=True)
        except (FileNotFoundError, ValueError):
            return RunResult(output_file, 5)
        return RunResult(output_file, 0)

    try:
        before = ar_run_eval(
            target_agent,
            eval_command,
            timeout=eval_timeout,
            cwd=eval_cwd,
            result_path=eval_result_path,
        )
    except (FileNotFoundError, ArEvalRunError):
        return RunResult(output_file, 5)

    try:
        changes = ar_apply_edits(target_agent, spec, dry_run=False)
    except (FileNotFoundError, ValueError):
        return RunResult(output_file, 6)

    files_modified = [str(c.path) for c in changes if c.changed]

    try:
        after = ar_run_eval(
            target_agent,
            eval_command,
            timeout=eval_timeout,
            cwd=eval_cwd,
            result_path=eval_result_path,
        )
    except (FileNotFoundError, ArEvalRunError):
        return RunResult(output_file, 7)

    target_id = scenario_id or _infer_agent_scenario(hypothesis_report, before.summary)
    delta = ar_compute_delta(before.summary, after.summary, target_id)
    summary = _summary_from_report(hypothesis_report, hypothesis_id, label="Hypothesis")
    md = ar_render_delta(delta, hypothesis_summary=summary, files_modified=files_modified)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(md)
    return RunResult(output_file, 0)


def agent_iterate(
    *,
    hypothesis_report: Path,
    target_agent: Path,
    eval_command: str,
    output_file: Path,
    eval_cwd: Optional[Path] = None,
    eval_result_path: Optional[Path] = None,
    eval_timeout: int = 300,
) -> RunResult:
    """Run `agent-researcher iterate` via direct API call."""
    if not hypothesis_report.is_file():
        return RunResult(output_file, 2)
    if not target_agent.is_dir():
        return RunResult(output_file, 2)

    try:
        report = ar_iterate(
            hypothesis_report,
            target_agent,
            eval_command,
            eval_cwd=eval_cwd,
            eval_result_path=eval_result_path,
            eval_timeout=eval_timeout,
        )
    except (FileNotFoundError, ValueError):
        return RunResult(output_file, 2)
    except ArEvalRunError:
        return RunResult(output_file, 5)
    except BaseException:  # noqa: BLE001 — match upstream catastrophic catch
        return RunResult(output_file, 8)

    md = ar_render_iteration(report)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(md)
    return RunResult(output_file, 0)


# =========================================================================
# helpers
# =========================================================================

_SUMMARY_RE = re.compile(
    r"^###\s+(Hypothesis|Finding)\s+(\d+)\s*:?\s*(.*)$",
    re.MULTILINE | re.IGNORECASE,
)


def _summary_from_report(
    report_path: Path, item_id: str | int, *, label: str
) -> str:
    """Pluck the `### {Hypothesis|Finding} N: …` title for the delta header.

    Mirrors the small helper each tool uses in its own `__main__.py`. Falls
    back to a minimal placeholder if the header isn't found.
    """
    try:
        wanted = int(str(item_id).lstrip("HhFf"))
    except (ValueError, AttributeError):
        wanted = None

    text = report_path.read_text()
    for m in _SUMMARY_RE.finditer(text):
        if wanted is None or int(m.group(2)) == wanted:
            return f"{m.group(1).title()} {m.group(2)}: {m.group(3).strip()}"
    return f"{label} {item_id} from {report_path}"


def _infer_agent_scenario(report_path: Path, summary) -> str:
    """Match `agent_researcher.__main__._infer_target_scenario_id` behavior."""
    try:
        text = report_path.read_text()
        m = re.search(r"Scenario:\s*(?:issue\s+)?([\w.-]+)", text)
        if m:
            return m.group(1)
    except OSError:
        pass
    if summary.failures:
        return summary.failures[0].scenario_id
    return "unknown"
