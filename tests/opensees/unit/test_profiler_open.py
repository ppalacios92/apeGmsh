"""Unit tests for ``apeGmsh.profiler`` (the P3 re-export of the fork viewer).

``apeGmsh.profiler.open`` / ``.show_web`` forward to the Ladruno fork's
out-of-tree ``Ladruno_tools/profiler_viewer`` (``ProfilerResults`` + the
one-process web launcher). apeGmsh re-exports, never re-implements. These
tests run **without** the fork: the fork module is faked in ``sys.modules``
(or forced absent), and ``subprocess.Popen`` is monkeypatched — so the
forwarding contract, the actionable error, the ``viewer_dir`` path wiring,
and the launch command are all covered fork-free.
"""
from __future__ import annotations

import subprocess
import sys
import types

import pytest

from apeGmsh import profiler


def _fake_viewer_module() -> types.ModuleType:
    mod = types.ModuleType("profiler_results")

    class _ProfilerResults:
        def __init__(self, path: str) -> None:
            self.path = path

    mod.ProfilerResults = _ProfilerResults  # type: ignore[attr-defined]
    return mod


def test_open_forwards_to_profiler_results(monkeypatch) -> None:
    fake = _fake_viewer_module()
    monkeypatch.setitem(sys.modules, "profiler_results", fake)
    pr = profiler.open("profile.h5")
    assert isinstance(pr, fake.ProfilerResults)  # type: ignore[attr-defined]
    assert pr.path == "profile.h5"


def test_open_accepts_pathlike(monkeypatch, tmp_path) -> None:
    fake = _fake_viewer_module()
    monkeypatch.setitem(sys.modules, "profiler_results", fake)
    pr = profiler.open(tmp_path / "profile.h5")
    assert pr.path == str(tmp_path / "profile.h5")


def test_open_absent_viewer_raises_actionable_error(monkeypatch) -> None:
    # A ``None`` entry in sys.modules forces ``import profiler_results`` to fail.
    monkeypatch.setitem(sys.modules, "profiler_results", None)
    with pytest.raises(ImportError, match="Ladruno"):
        profiler.open("profile.h5")


def test_viewer_dir_is_prepended_to_syspath(monkeypatch) -> None:
    fake = _fake_viewer_module()
    monkeypatch.setitem(sys.modules, "profiler_results", fake)
    monkeypatch.setattr(sys, "path", list(sys.path))  # isolate the mutation
    profiler.open("profile.h5", viewer_dir=r"Z:/opensees/profiler_viewer")
    assert r"Z:/opensees/profiler_viewer" in sys.path


def test_env_var_is_prepended_to_syspath(monkeypatch) -> None:
    fake = _fake_viewer_module()
    monkeypatch.setitem(sys.modules, "profiler_results", fake)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setenv("LADRUNO_PROFILER_VIEWER", r"Z:/env/profiler_viewer")
    profiler.open("profile.h5")
    assert r"Z:/env/profiler_viewer" in sys.path


def test_show_web_launches_sibling_launch_py(monkeypatch, tmp_path) -> None:
    (tmp_path / "launch.py").write_text("# stub launcher\n", encoding="utf-8")
    fake = _fake_viewer_module()
    fake.__file__ = str(tmp_path / "profiler_results.py")
    monkeypatch.setitem(sys.modules, "profiler_results", fake)

    captured: dict[str, object] = {}

    def _fake_popen(args, *a, **k):  # type: ignore[no-untyped-def]
        captured["args"] = args
        return "POPEN_HANDLE"

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    handle = profiler.show_web("profile.h5")
    assert handle == "POPEN_HANDLE"
    args = captured["args"]
    assert args[0] == sys.executable
    assert str(args[1]).endswith("launch.py")
    assert args[2] == "profile.h5"


def test_show_web_missing_launch_py_raises(monkeypatch, tmp_path) -> None:
    # Viewer importable but no launch.py beside it.
    fake = _fake_viewer_module()
    fake.__file__ = str(tmp_path / "profiler_results.py")
    monkeypatch.setitem(sys.modules, "profiler_results", fake)
    with pytest.raises(FileNotFoundError, match="launch.py"):
        profiler.show_web("profile.h5")
