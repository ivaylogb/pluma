"""Cache contract tests. No I/O outside tmp_path."""

from __future__ import annotations

from pathlib import Path

import pytest

from pluma import cache
from pluma.runners import RunResult


def _touch(p: Path, content: str = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def test_compute_key_is_stable(tmp_path):
    f = _touch(tmp_path / "f.yaml", "name: test\n")
    k1 = cache.compute_key("funnel", [("funnel", f), ("model", "claude")])
    k2 = cache.compute_key("funnel", [("funnel", f), ("model", "claude")])
    assert k1 == k2


def test_compute_key_changes_with_file_content(tmp_path):
    f = _touch(tmp_path / "f.yaml", "name: a\n")
    k1 = cache.compute_key("funnel", [("funnel", f)])
    f.write_text("name: b\n")
    k2 = cache.compute_key("funnel", [("funnel", f)])
    assert k1 != k2


def test_compute_key_changes_with_flag_value(tmp_path):
    f = _touch(tmp_path / "f.yaml")
    k1 = cache.compute_key("funnel", [("funnel", f), ("model", "claude")])
    k2 = cache.compute_key("funnel", [("funnel", f), ("model", "opus")])
    assert k1 != k2


def test_compute_key_independent_of_path_name(tmp_path):
    """Renaming a file shouldn't invalidate the cache if contents are the same."""
    a = _touch(tmp_path / "a.yaml", "x: 1\n")
    b = _touch(tmp_path / "b.yaml", "x: 1\n")
    # Use the same label "funnel" so only the value differs (and only by path).
    k1 = cache.compute_key("funnel", [("funnel", a)])
    k2 = cache.compute_key("funnel", [("funnel", b)])
    assert k1 == k2


def test_compute_key_directory_hashed_by_manifest(tmp_path):
    d = tmp_path / "product"
    (d / "docs").mkdir(parents=True)
    (d / "docs" / "intro.md").write_text("hi\n")
    k1 = cache.compute_key("funnel", [("product", d)])
    (d / "docs" / "intro.md").write_text("BYE\n")
    k2 = cache.compute_key("funnel", [("product", d)])
    assert k1 != k2


def test_compute_key_handles_list_of_paths(tmp_path):
    a = _touch(tmp_path / "a.txt", "a")
    b = _touch(tmp_path / "b.txt", "b")
    k1 = cache.compute_key("funnel", [("extra", [a, b])])
    k2 = cache.compute_key("funnel", [("extra", [a, b])])
    k3 = cache.compute_key("funnel", [("extra", [a])])
    assert k1 == k2 != k3


# =========================================================================
# run_with_cache
# =========================================================================


def test_run_with_cache_miss_then_hit(tmp_path):
    root = tmp_path / "cache_root"
    f = _touch(tmp_path / "f.yaml", "x: 1\n")
    calls = []

    def runner(dest: Path) -> RunResult:
        calls.append(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("# generated\n")
        return RunResult(dest, 0)

    r1 = cache.run_with_cache("funnel", [("funnel", f)], runner, root=root)
    assert r1.exit_code == 0
    assert r1.from_cache is False
    assert len(calls) == 1

    r2 = cache.run_with_cache("funnel", [("funnel", f)], runner, root=root)
    assert r2.exit_code == 0
    assert r2.from_cache is True
    assert len(calls) == 1, "runner should not have re-invoked on cache hit"
    assert r1.output_path == r2.output_path


def test_run_with_cache_force_bypasses_hit(tmp_path):
    root = tmp_path / "cache_root"
    f = _touch(tmp_path / "f.yaml")
    calls = []

    def runner(dest: Path) -> RunResult:
        calls.append(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("# regen\n")
        return RunResult(dest, 0)

    cache.run_with_cache("funnel", [("funnel", f)], runner, root=root)
    cache.run_with_cache("funnel", [("funnel", f)], runner, root=root, force=True)
    assert len(calls) == 2, "force=True must re-invoke the runner"


def test_run_with_cache_invalidated_by_input_change(tmp_path):
    root = tmp_path / "cache_root"
    f = _touch(tmp_path / "f.yaml", "x: 1\n")
    calls = []

    def runner(dest: Path) -> RunResult:
        calls.append(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("ok")
        return RunResult(dest, 0)

    cache.run_with_cache("funnel", [("funnel", f)], runner, root=root)
    f.write_text("x: 2\n")  # invalidates
    r2 = cache.run_with_cache("funnel", [("funnel", f)], runner, root=root)

    assert len(calls) == 2
    assert r2.from_cache is False


def test_run_with_cache_does_not_cache_failures_implicitly(tmp_path):
    """A runner that returns non-zero should still return — the caller decides
    whether to retry. Subsequent runs with the same inputs will *not* hit the
    cache because no file was written."""
    root = tmp_path / "cache_root"
    f = _touch(tmp_path / "f.yaml")
    calls = []

    def runner(dest: Path) -> RunResult:
        calls.append(dest)
        # Simulate a runner that failed before writing.
        return RunResult(dest, 3)

    r1 = cache.run_with_cache("funnel", [("funnel", f)], runner, root=root)
    r2 = cache.run_with_cache("funnel", [("funnel", f)], runner, root=root)
    assert r1.exit_code == 3
    assert r2.exit_code == 3
    assert len(calls) == 2


def test_invalidate_removes_cache_entry(tmp_path):
    root = tmp_path / "cache_root"
    f = _touch(tmp_path / "f.yaml")

    def runner(dest: Path) -> RunResult:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("x")
        return RunResult(dest, 0)

    cache.run_with_cache("funnel", [("funnel", f)], runner, root=root)
    key = cache.compute_key("funnel", [("funnel", f)])

    assert cache.invalidate("funnel", key, root=root) is True
    assert cache.invalidate("funnel", key, root=root) is False  # already gone


def test_cache_path_uses_PLUMA_CACHE_ROOT_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUMA_CACHE_ROOT", str(tmp_path / "custom"))
    p = cache.cache_path("funnel", "abc123")
    assert str(p).startswith(str(tmp_path / "custom"))
