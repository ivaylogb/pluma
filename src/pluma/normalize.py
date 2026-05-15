"""Per-tool markdown → unified Pluma "Finding" shape.

Each sister tool emits a slightly different report. Pluma unifies them:

- funnel-researcher's "Hypothesis N" and integration-watcher's "Finding N" and
  agent-researcher's "Hypothesis N" all become Pluma **Findings**.
- The original tool's term is preserved verbatim in `Original entity term:`
  metadata so the report stays self-describing.
- The `(Layer N)` annotation embedded in each entity title is lifted into a
  structured field.
- Citations of the form `file:line` or `file:line-line` are extracted from
  the Evidence section and normalized via `normalize_citation()`. Phase 3's
  cross-tool matcher consumes these.

Design choice (resolved during discovery, refinement B):
    Pluma's unified format uses **Finding** everywhere. The original term
    survives only in the report metadata header.

Per-tool parsers are explicit and small — no shared AST. Shared helpers live
at the bottom of the module.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# =========================================================================
# Data classes
# =========================================================================


@dataclass(frozen=True)
class Citation:
    """A reference of the form `file:line` extracted from a Finding's Evidence.

    `line_end` equals `line_start` for single-line citations; both may be None
    when the original citation was file-only (rare but possible).
    """

    file: str
    line_start: Optional[int]
    line_end: Optional[int]
    raw: str

    def overlaps(self, other: "Citation") -> bool:
        """Mechanical match: same file, line ranges intersect.

        File-only citations (line_start is None on either side) match on file
        equality alone.
        """
        if self.file != other.file:
            return False
        if self.line_start is None or other.line_start is None:
            return True
        a_end = self.line_end if self.line_end is not None else self.line_start
        b_end = other.line_end if other.line_end is not None else other.line_start
        return not (a_end < other.line_start or b_end < self.line_start)


@dataclass
class Finding:
    """A unified Pluma finding, parsed from any of the three tools.

    `id` is the human-facing identifier (``"F1"`` for integration-watcher
    findings, ``"H1"`` for funnel- and agent-researcher hypotheses) so it
    round-trips through the CLI flags that sister tools accept.
    """

    index: int
    id: str  # "F1" / "H1" — derived from origin term + index
    title: str  # entity title with the trailing "(Layer N)" stripped
    layer: Optional[int]  # parsed from "(Layer N)" suffix, if present
    body: str  # full markdown body of the entity, verbatim
    citations: list[Citation] = field(default_factory=list)
    applyable: Optional[bool] = None  # parsed from the embedded JSON edit block


@dataclass
class PlumaReport:
    """Pluma's unified report shape. ``to_markdown()`` re-emits it."""

    origin: str  # "agent-researcher" | "funnel-researcher" | "integration-watcher"
    original_term: str  # "Hypothesis" | "Finding"
    title: str  # parsed from the report's `# ...` header
    findings: list[Finding] = field(default_factory=list)

    @property
    def metadata(self) -> dict[str, str]:
        """Flat dict view of the report's header — convenient for callers
        that want to query by string key (e.g., the spot-check probes)."""
        return {
            "origin": self.origin,
            "original_entity_term": self.original_term,
            "title": self.title,
        }

    def to_markdown(self) -> str:
        return _render_pluma_markdown(self)


# =========================================================================
# Per-tool parsers
# =========================================================================


_TOOL_TO_TERM = {
    "agent-researcher": "Hypothesis",
    "funnel-researcher": "Hypothesis",
    "integration-watcher": "Finding",
}


def parse(md: str, *, origin: str) -> PlumaReport:
    """Dispatch to the per-tool parser for ``origin``.

    Origins are the canonical tool names (with hyphens):
        - "agent-researcher"
        - "funnel-researcher"
        - "integration-watcher"
    """
    if origin == "funnel-researcher":
        return parse_funnel(md)
    if origin == "integration-watcher":
        return parse_integration(md)
    if origin == "agent-researcher":
        return parse_agent(md)
    raise ValueError(f"unknown origin: {origin!r}")


def parse_funnel(md: str) -> PlumaReport:
    return _parse_with_term(md, origin="funnel-researcher", term="Hypothesis")


def parse_agent(md: str) -> PlumaReport:
    return _parse_with_term(md, origin="agent-researcher", term="Hypothesis")


def parse_integration(md: str) -> PlumaReport:
    return _parse_with_term(md, origin="integration-watcher", term="Finding")


# =========================================================================
# Citation normalization (also consumed by Phase 3 cross.py)
# =========================================================================


# Match either ASCII "-" or en-dash "–" in line ranges.
_CITATION_RE = re.compile(
    r"""
    (?<![\w/])                     # left boundary: not preceded by word/path char
    (?P<file>[\w./\-]+\.[A-Za-z0-9]+)   # filename with an extension
    :(?P<start>\d+)
    (?:\s*[-–]\s*(?P<end>\d+))?
    """,
    re.VERBOSE,
)


def normalize_citation(raw: str) -> Optional[Citation]:
    """Parse a single citation token like ``docs/quickstart.md:21-30``.

    Returns ``None`` if the input doesn't look like a structured citation.
    Phase 3 consumes this for mechanical match detection across tools.
    """
    raw = raw.strip().strip(",.;:")
    m = _CITATION_RE.search(raw)
    if not m:
        return None
    file = m.group("file")
    start = int(m.group("start"))
    end = int(m.group("end")) if m.group("end") else start
    if end < start:
        start, end = end, start
    return Citation(file=file, line_start=start, line_end=end, raw=m.group(0))


def extract_citations(body: str) -> list[Citation]:
    """All file:line citations found anywhere in ``body``, in document order,
    deduplicated by (file, line_start, line_end)."""
    seen: set[tuple[str, Optional[int], Optional[int]]] = set()
    out: list[Citation] = []
    for m in _CITATION_RE.finditer(body):
        file = m.group("file")
        start = int(m.group("start"))
        end = int(m.group("end")) if m.group("end") else start
        if end < start:
            start, end = end, start
        key = (file, start, end)
        if key in seen:
            continue
        seen.add(key)
        out.append(Citation(file=file, line_start=start, line_end=end, raw=m.group(0)))
    return out


# =========================================================================
# Internals
# =========================================================================


def _parse_with_term(md: str, *, origin: str, term: str) -> PlumaReport:
    title = _extract_top_title(md)
    findings = _extract_findings(md, term=term)
    return PlumaReport(
        origin=origin,
        original_term=term,
        title=title,
        findings=findings,
    )


_TOP_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def _extract_top_title(md: str) -> str:
    m = _TOP_TITLE_RE.search(md)
    return m.group(1).strip() if m else "(untitled)"


def _entity_header_re(term: str) -> re.Pattern[str]:
    # `### Hypothesis 1: …` or `### Finding 1: …` (case-insensitive).
    return re.compile(
        rf"^###\s+{term}\s+(\d+)\s*:?\s*(.*?)$",
        re.MULTILINE | re.IGNORECASE,
    )


_LAYER_RE = re.compile(r"\(Layer\s+(\d+)\)", re.IGNORECASE)
_APPLYABLE_RE = re.compile(
    r"```json\s*\n(\{.*?\})\s*\n```", re.DOTALL | re.IGNORECASE
)
# An h2 boundary: a line starting with exactly `## ` (not `###`). Sister-tool
# reports place trailing meta sections (e.g. `## What this report is NOT`)
# after the last finding; a finding body must stop there, not run to EOF.
_H2_BOUNDARY_RE = re.compile(r"^##(?!#)", re.MULTILINE)


def _extract_findings(md: str, *, term: str) -> list[Finding]:
    """Split the markdown on `### {term} N:` headers and parse each block.

    A finding's body ends at the FIRST of:
      - the next `### {term}` header,
      - the next `^## ` h2 boundary (trailing meta sections),
      - EOF.
    """
    header_re = _entity_header_re(term)
    prefix = "F" if term.lower() == "finding" else "H"
    headers = list(header_re.finditer(md))
    findings: list[Finding] = []
    for idx, h in enumerate(headers):
        body_start = h.end()
        next_header_start = (
            headers[idx + 1].start() if idx + 1 < len(headers) else len(md)
        )
        body_end = next_header_start
        h2 = _H2_BOUNDARY_RE.search(md, body_start, next_header_start)
        if h2 is not None:
            body_end = h2.start()
        body = md[body_start:body_end].strip("\n")
        number = int(h.group(1))
        raw_title = h.group(2).strip()
        layer_m = _LAYER_RE.search(raw_title)
        layer = int(layer_m.group(1)) if layer_m else None
        clean_title = _LAYER_RE.sub("", raw_title).rstrip(" ()").strip()
        findings.append(
            Finding(
                index=number,
                id=f"{prefix}{number}",
                title=clean_title,
                layer=layer,
                body=body,
                citations=extract_citations(body),
                applyable=_parse_applyable(body),
            )
        )
    return findings


def _parse_applyable(body: str) -> Optional[bool]:
    """Read the embedded ```json {"applyable": ...}``` block, if any."""
    m = _APPLYABLE_RE.search(body)
    if not m:
        return None
    try:
        obj = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    val = obj.get("applyable")
    return val if isinstance(val, bool) else None


# =========================================================================
# Rendering
# =========================================================================


def _render_pluma_markdown(report: PlumaReport) -> str:
    n = len(report.findings)
    lines: list[str] = []
    lines.append("# Pluma report")
    lines.append("")
    lines.append(f"Origin: {report.origin}")
    lines.append(f"Original entity term: {report.original_term}")
    lines.append(f"Source title: {report.title}")
    lines.append("")
    lines.append(f"## Findings ({n})")
    lines.append("")
    for f in report.findings:
        suffix = f" [Layer {f.layer}]" if f.layer is not None else ""
        lines.append(f"### Finding {f.index} — {f.title}{suffix}")
        lines.append("")
        lines.append(f.body)
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# =========================================================================
# Convenience: parse from a file path
# =========================================================================


def normalize_report(path: Path, *, origin: str) -> PlumaReport:
    """Read a sister-tool report from disk and parse it into a PlumaReport.

    Thin convenience wrapper around :func:`parse`. Phase 3's cross-tool report
    consumes this for each tool's cached output.
    """
    return parse(Path(path).read_text(), origin=origin)


# Backward-compat alias (matches the in-process API used elsewhere in Pluma).
parse_file = normalize_report
