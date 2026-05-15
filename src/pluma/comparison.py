"""Cross-tool report rendering — turns a CrossReport into Pluma's unified
markdown.

Section order:
    1. Header (tools run, cache status, timestamp)
    2. Correlation matrix (tool × layer → finding count)
    3. Cross-tool findings (each match's pair of findings, full bodies)
    4. Findings unique to each tool (one section per tool, in input order)
"""

from __future__ import annotations

from datetime import datetime, timezone

from .cross import CrossMatch, CrossReport
from .normalize import Finding


def render_cross_report(report: CrossReport) -> str:
    lines: list[str] = []

    lines.extend(_render_header(report))
    lines.append("")
    lines.append("## Correlation matrix")
    lines.append("")
    lines.append(_render_correlation(report.correlation))
    lines.append("")

    lines.append(f"## Cross-tool findings ({len(report.cross_matches)})")
    lines.append("")
    if not report.cross_matches:
        lines.append(
            "_No cross-tool findings detected. Each tool's findings stand alone "
            "below._"
        )
        lines.append("")
    else:
        for idx, m in enumerate(report.cross_matches, 1):
            lines.extend(_render_match(idx, m))
            lines.append("")

    matched = _matched_finding_keys(report)
    for origin, pluma_report in report.per_tool.items():
        unique = [f for f in pluma_report.findings if (origin, f.id) not in matched]
        lines.append(f"## Findings unique to {origin} ({len(unique)})")
        lines.append("")
        if not unique:
            lines.append("_All of this tool's findings appear in the cross-tool section above._")
            lines.append("")
            continue
        for f in unique:
            lines.extend(_render_finding_block(origin, f))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# =========================================================================
# Sections
# =========================================================================


def _render_header(report: CrossReport) -> list[str]:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# Pluma cross-tool report",
        "",
        f"Generated: {ts}",
        "",
        "Tools run:",
    ]
    for origin in report.per_tool:
        hit = report.inputs is not None and origin
        # `cache_hits` lives on the CrossRunResult, not the CrossReport — the
        # renderer doesn't have access to it. Caller can prepend a status line
        # if they want to show cache state; we surface tool list only here.
        lines.append(f"  - {origin}")
    return lines


def _render_correlation(corr: dict[str, dict[int, int]]) -> str:
    layers = sorted({l for tc in corr.values() for l in tc})
    if not layers:
        return "_No Layer annotations parsed from any tool's report._"
    header = "| Tool | " + " | ".join(f"Layer {l}" for l in layers) + " | Total |"
    sep = "|" + "---|" * (len(layers) + 2)
    rows = [header, sep]
    for tool, counts in corr.items():
        cells = [tool]
        total = 0
        for l in layers:
            n = counts.get(l, 0)
            cells.append(str(n))
            total += n
        cells.append(str(total))
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def _render_match(idx: int, m: CrossMatch) -> list[str]:
    origins = ", ".join(o for o, _ in m.findings)
    out = [
        f"### Cross-match {idx} — {m.kind.title()} match",
        "",
        f"**Reason:** {m.reason}",
        "",
        f"**Tools:** {origins}",
        "",
    ]
    for origin, f in m.findings:
        out.extend(_render_finding_block(origin, f, header_prefix="**"))
    return out


def _render_finding_block(
    origin: str, f: Finding, *, header_prefix: str = "###"
) -> list[str]:
    layer = f" [Layer {f.layer}]" if f.layer is not None else ""
    if header_prefix == "**":
        head = f"**{origin} — {f.id}: {f.title}{layer}**"
    else:
        head = f"{header_prefix} Finding {f.id} — {f.title}{layer} _(from {origin})_"
    return [head, "", f.body, ""]


def _matched_finding_keys(report: CrossReport) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for m in report.cross_matches:
        for origin, f in m.findings:
            out.add((origin, f.id))
    return out
