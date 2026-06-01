"""
``apeGmsh.profiler`` — open Ladruno-fork profiler output (``profile.h5``).

apeGmsh **emits** the profiler bracket (see ``ops.profiler.*`` on the
``apeSees`` bridge) but ships **no reader**: ``profile.h5`` is read by the
fork's out-of-tree viewer at ``Ladruno_tools/profiler_viewer``. This module is
a thin convenience bridge — it forwards to that viewer's ``ProfilerResults``
loader (headless, Jupyter-usable) and its one-process web UI launcher if they
are importable, and otherwise raises a clear, actionable error. It
**re-exports**; it never re-implements the profiler analysis (no duplicated
rollup / diff / normalizer logic).

Nothing here imports the fork (or ``h5py``) at apeGmsh import time — the fork
import happens inside :func:`open` / :func:`show_web`, so ``import apeGmsh``
stays fork-free on stock installs.

The viewer directory must be importable. Point at it once, any of:

* ``viewer_dir=`` kwarg — ``profiler.open(path, viewer_dir=r"<OpenSees>/Ladruno_tools/profiler_viewer")``
* the ``LADRUNO_PROFILER_VIEWER`` environment variable set to that directory
* it already being on ``sys.path``

The one-click ``Profiler_Viewer.bat`` (Windows) / ``profiler_viewer.sh`` opens a
``profile.h5`` in a browser without any of this — this module is for the
in-notebook / scripted path.
"""
from __future__ import annotations

import os
import sys
from typing import Any

__all__ = ["open", "show_web"]


_INSTALL_HINT = (
    "apeGmsh.profiler requires the Ladruno fork's out-of-tree profiler viewer "
    "(it provides the canonical ProfilerResults reader; apeGmsh ships none). "
    "Put 'Ladruno_tools/profiler_viewer' on the import path: pass "
    "viewer_dir='<OpenSees>/Ladruno_tools/profiler_viewer', set the "
    "LADRUNO_PROFILER_VIEWER environment variable to that directory, or run its "
    "requirements.txt there. The one-click Profiler_Viewer.bat (Windows) / "
    "profiler_viewer.sh opens a profile.h5 in a browser without any of this."
)


def _ensure_viewer_on_path(viewer_dir: str | os.PathLike[str] | None) -> None:
    """Prepend the viewer directory to ``sys.path`` (kwarg, else env var)."""
    cand = viewer_dir or os.environ.get("LADRUNO_PROFILER_VIEWER")
    if cand:
        cand_str = str(cand)
        if cand_str not in sys.path:
            sys.path.insert(0, cand_str)


def _import_viewer_module(viewer_dir: str | os.PathLike[str] | None) -> Any:
    """Import the fork's ``profiler_results`` module or fail with a hint."""
    _ensure_viewer_on_path(viewer_dir)
    try:
        import profiler_results  # fork's out-of-tree loader (not a dep)
    except ImportError as e:
        raise ImportError(_INSTALL_HINT) from e
    return profiler_results


def open(  # noqa: A001 — deliberate: mirrors ProfilerResults("profile.h5")
    path: str | os.PathLike[str],
    *,
    viewer_dir: str | os.PathLike[str] | None = None,
) -> Any:
    """Open a ``profile.h5`` and return the fork's ``ProfilerResults`` loader.

    A re-export of ``Ladruno_tools/profiler_viewer/profiler_results.py`` —
    the returned object is the fork's own loader, a context manager exposing
    ``manifest()`` / ``rollup(run)`` / ``series(run)`` / ``memory(run)`` /
    ``diff(base, cand)`` (the per-step ``series`` is the "monitor" time
    history). apeGmsh adds nothing on top.

    Parameters
    ----------
    path
        The ``profile.h5`` written by ``ops.profiler.report(...)`` (or the
        live ``ops.analyze(profile=...)`` bracket).
    viewer_dir
        Path to the fork's ``Ladruno_tools/profiler_viewer`` directory, if it
        is not already importable. Falls back to the
        ``LADRUNO_PROFILER_VIEWER`` environment variable.

    Raises
    ------
    ImportError
        If the viewer is not importable — the message says exactly how to
        point apeGmsh at it.

    Examples
    --------
    >>> with apeGmsh.profiler.open("profile.h5") as pr:  # doctest: +SKIP
    ...     pr.manifest()
    ...     pr.series("caseA")   # the per-step monitor
    """
    mod = _import_viewer_module(viewer_dir)
    return mod.ProfilerResults(str(path))


def show_web(
    path: str | os.PathLike[str],
    *,
    viewer_dir: str | os.PathLike[str] | None = None,
) -> Any:
    """Launch the fork's one-process web viewer (React UI + API) on ``path``.

    Locates ``launch.py`` beside the importable ``profiler_results`` module
    and runs it in a background process; ``launch.py`` provisions its own
    private venv, builds the UI (needs Node 18+ once), serves UI + API from a
    single process, and opens the browser at ``http://127.0.0.1:8000/``.
    Returns the :class:`subprocess.Popen` handle (kill it to stop the server).

    This forwards to the fork's launcher — it is the scripted equivalent of
    double-clicking ``Profiler_Viewer.bat``. Like the GPU viewers, the live
    browser UI itself is not unit-verifiable here; the launch command is.
    """
    import subprocess
    from pathlib import Path

    mod = _import_viewer_module(viewer_dir)
    launch_py = Path(mod.__file__).resolve().parent / "launch.py"
    if not launch_py.is_file():
        raise FileNotFoundError(
            f"Found the profiler viewer at {launch_py.parent} but no launch.py "
            f"beside it — update your Ladruno checkout, or use the one-click "
            f"Profiler_Viewer.bat / profiler_viewer.sh instead."
        )
    return subprocess.Popen([sys.executable, str(launch_py), str(path)])
