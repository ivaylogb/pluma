"""Input-hash-based cache for tool runs.

Stores each tool invocation's markdown output at ``~/.pluma/cache/<tool>_<hash>.md``.
The hash key covers file *contents* (not paths) and flag values — so renaming
an input directory doesn't invalidate the cache, but editing a single byte of
any input does. ``force=True`` bypasses the cache and overwrites the stored
copy.

The hashable-input contract is intentionally simple: anything that goes into
the LLM prompt (or that the upstream tool's loader reads) must be in the
hash. ``runners.py`` callers pass a flat list of (label, value) pairs; the
helper distinguishes Paths (hashed by content) from scalars (hashed by repr).
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Union

from .runners import RunResult


InputSpec = Union[list[tuple[str, Any]], Mapping[str, Any]]


def _default_root() -> Path:
    return Path(os.environ.get("PLUMA_CACHE_ROOT") or Path.home() / ".pluma" / "cache")


def _hash_path(path: Path) -> str:
    """SHA-256 of a file's contents, or of a sorted manifest for a directory.

    Directories are walked; each entry contributes (relative-path, content-hash)
    to the manifest. Symlinks are followed.
    """
    h = hashlib.sha256()
    if path.is_file():
        h.update(path.read_bytes())
        return h.hexdigest()
    if path.is_dir():
        # Sorted relative paths → content. Stable across machines.
        entries: list[tuple[str, str]] = []
        for child in sorted(path.rglob("*")):
            if child.is_file():
                rel = str(child.relative_to(path))
                entries.append((rel, hashlib.sha256(child.read_bytes()).hexdigest()))
        for rel, digest in entries:
            h.update(rel.encode())
            h.update(b"\0")
            h.update(digest.encode())
            h.update(b"\0")
        return h.hexdigest()
    # Missing path: hash a sentinel so the key is stable but distinct from "empty".
    h.update(b"<missing:")
    h.update(str(path).encode())
    h.update(b">")
    return h.hexdigest()


def _compute_cache_key(tool: str, inputs: InputSpec) -> str:
    """Build a cache key from a tool name + (label → value) inputs.

    Accepts either a ``Mapping`` (sorted by key for stability) or a
    ``list[tuple[str, Any]]`` (preserved in caller order). Path values are
    hashed by content; everything else by ``repr()``. Labels participate in
    the key so two values with identical repr but different meanings don't
    collide.

    The leading underscore signals "private API, but stable" — Pluma's spot-
    check probes and Phase 3's cross-tool orchestrator both call this.
    """
    if isinstance(inputs, Mapping):
        pairs: list[tuple[str, Any]] = sorted(inputs.items())
    else:
        pairs = list(inputs)

    h = hashlib.sha256()
    h.update(tool.encode())
    h.update(b"\0")
    for label, value in pairs:
        h.update(label.encode())
        h.update(b"=")
        if isinstance(value, Path):
            h.update(_hash_path(value).encode())
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, Path):
                    h.update(_hash_path(item).encode())
                else:
                    h.update(repr(item).encode())
                h.update(b",")
        else:
            h.update(repr(value).encode())
        h.update(b"\0")
    return h.hexdigest()[:16]  # 16 hex chars = 64 bits — plenty for local cache


# Backward-compat alias used by Pluma's internal call sites + Phase 2 tests.
compute_key = _compute_cache_key


@dataclass
class CachedRun:
    """The thing run_with_cache returns: the run's exit code, output path, and
    whether the result came from cache."""

    output_path: Path
    exit_code: int
    from_cache: bool


def cache_path(tool: str, key: str, *, root: Path | None = None) -> Path:
    """Where the cached markdown for (tool, key) lives."""
    return (root or _default_root()) / f"{tool}_{key}.md"


def run_with_cache(
    tool: str,
    inputs: InputSpec,
    runner: Callable[[Path], RunResult],
    *,
    force: bool = False,
    root: Path | None = None,
) -> CachedRun:
    """Cache wrapper around a runner.

    The runner is a callable taking a destination ``output_path`` and returning
    a ``RunResult``. The cache decides where to write — runners stay
    ignorant of caching.

    Cache hit: if ``force=False`` and ``cache_path(tool, key)`` exists, return
    it without invoking ``runner``. Exit code is always 0 on a hit (a cached
    file is by definition a successful prior run).

    Cache miss: ``runner`` is called with the destination path. On exit code 0,
    the file is left in place (it's already at ``cache_path``). Non-zero exit
    codes still return — the caller decides whether to surface the error.
    """
    root = root or _default_root()
    root.mkdir(parents=True, exist_ok=True)

    key = _compute_cache_key(tool, inputs)
    dest = cache_path(tool, key, root=root)

    if dest.is_file() and not force:
        return CachedRun(output_path=dest, exit_code=0, from_cache=True)

    result = runner(dest)
    return CachedRun(
        output_path=result.output_path,
        exit_code=result.exit_code,
        from_cache=False,
    )


def invalidate(tool: str, key: str, *, root: Path | None = None) -> bool:
    """Remove a cached entry. Returns True if a file was deleted."""
    p = cache_path(tool, key, root=root)
    if p.is_file():
        p.unlink()
        return True
    return False
