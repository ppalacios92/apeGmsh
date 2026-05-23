"""``Results._spawn_viewer_subprocess`` — argv emission contract.

The matching ``__main__`` parser side is covered by
``test_viewers_main.py``. This file pins the emitter side: that
``Results.viewer(blocking=False, ...)`` produces a well-formed argv
the parser can decode.

Phase 8 (ADR 0020 INV-1) — the legacy ``model_h5=`` kwarg on
:meth:`Results.viewer` was deleted; orientation is auto-resolved
from the Composed-file ``results.h5`` for native results.  MPCO is
asymmetric: ``.mpco`` files carry no embedded ``/opensees/`` zone,
so the spawn argv MUST forward ``--model-h5`` pointing at the
sibling archive that was supplied to :meth:`Results.from_mpco`.
The argv contract is:
- native: ``[python, -m, apeGmsh.viewers, <path>, ?--title <str>]``
- MPCO:   ``[..., <mpco_path>, ?--title <str>, --model-h5 <model_h5>]``
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from apeGmsh import results as results_pkg


# =====================================================================
# Helpers
# =====================================================================

class _CapturedPopen:
    """Stub for ``subprocess.Popen`` — records the argv it was called with."""

    instances: "list[_CapturedPopen]" = []

    def __init__(self, args, *_, **__) -> None:
        self.args = list(args)
        self.returncode = None
        _CapturedPopen.instances.append(self)

    def wait(self) -> int:  # pragma: no cover — tests don't wait
        return 0


@pytest.fixture
def patch_popen(monkeypatch):
    """Replace ``subprocess.Popen`` in the Results module with a stub."""
    _CapturedPopen.instances = []
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", _CapturedPopen)
    return _CapturedPopen


@pytest.fixture
def disk_results(tmp_path: Path):
    """Build a minimal native ``Results`` with a non-None ``_path`` so
    the subprocess guard passes.  ``_model_path`` is None (native
    results are self-describing — the Composed file carries the
    embedded ``/opensees/`` zone)."""
    from apeGmsh.results.Results import Results
    fpath = tmp_path / "run.h5"
    fpath.write_bytes(b"")
    r = Results.__new__(Results)
    r._path = fpath
    r._reader = None
    r._fem = None
    r._stage_id = None
    r._stages_cache = None
    r._model = None
    r._model_path = None
    return r


@pytest.fixture
def mpco_results(tmp_path: Path):
    """Build a minimal MPCO-backed ``Results`` — ``_path`` points at
    the ``.mpco`` and ``_model_path`` carries the sibling archive
    supplied to :meth:`Results.from_mpco`.  Exercises the asymmetry
    the parent must respect when spawning the subprocess."""
    from apeGmsh.results.Results import Results
    mpco = tmp_path / "run.mpco"
    mpco.write_bytes(b"")
    model_h5 = tmp_path / "model.h5"
    model_h5.write_bytes(b"")
    r = Results.__new__(Results)
    r._path = mpco
    r._reader = None
    r._fem = None
    r._stage_id = None
    r._stages_cache = None
    r._model = None
    r._model_path = model_h5
    return r


# =====================================================================
# Tests
# =====================================================================

def test_spawn_native_omits_model_h5_token(disk_results, patch_popen):
    """Native results — ``--model-h5`` is NOT in argv.

    The Composed-file ``results.h5`` carries the embedded
    ``/opensees/`` zone; the child auto-resolves orientation via
    :meth:`Results.from_native` without needing a sibling archive.
    """
    disk_results._spawn_viewer_subprocess(title=None)
    assert len(patch_popen.instances) == 1
    argv = patch_popen.instances[0].args
    assert "--model-h5" not in argv


def test_spawn_mpco_forwards_model_h5_token(mpco_results, patch_popen):
    """MPCO results — ``--model-h5`` MUST appear in argv.

    ``.mpco`` files carry no embedded ``/opensees/`` zone, so the
    child needs the sibling archive path that was supplied to
    :meth:`Results.from_mpco`.  Without this flag the child exits(2)
    at :func:`apeGmsh.viewers.__main__._open_results` and the parent
    sees a silent failure (fire-and-forget ``Popen``).
    """
    mpco_results._spawn_viewer_subprocess(title=None)
    assert len(patch_popen.instances) == 1
    argv = patch_popen.instances[0].args
    assert "--model-h5" in argv
    assert argv[argv.index("--model-h5") + 1] == str(mpco_results._model_path)


def test_spawn_includes_title(disk_results, patch_popen):
    """``--title`` is forwarded when set."""
    disk_results._spawn_viewer_subprocess(title="My Run")

    argv = patch_popen.instances[0].args
    assert "--title" in argv
    assert argv[argv.index("--title") + 1] == "My Run"


def test_spawn_argv_is_parseable_by_main_parser(disk_results, patch_popen):
    """End-to-end argv contract: what ``_spawn_viewer_subprocess`` emits
    is exactly what ``__main__``'s argparse decodes. Pins the wire
    between the two halves so future drift on either side surfaces here.
    """
    disk_results._spawn_viewer_subprocess(title="My Run")

    argv = patch_popen.instances[0].args
    # Strip the leading [python, -m, apeGmsh.viewers] — pass only the
    # arguments the parser would see.
    parser_argv = argv[3:]

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--title", default=None)
    ns = parser.parse_args(parser_argv)

    assert ns.path == str(disk_results._path)
    assert ns.title == "My Run"


def test_spawn_raises_for_in_memory_results(patch_popen):
    """In-memory Results refuses to spawn."""
    from apeGmsh.results.Results import Results
    r = Results.__new__(Results)
    r._path = None
    r._reader = None
    r._fem = None
    r._stage_id = None
    r._stages_cache = None
    r._model = None
    r._model_path = None

    with pytest.raises(RuntimeError, match="In-memory Results cannot launch"):
        r._spawn_viewer_subprocess(title=None)


def test_spawn_mpco_argv_is_parseable_by_main_parser(mpco_results, patch_popen):
    """End-to-end MPCO argv contract: what the parent emits is
    exactly what ``__main__``'s argparse decodes, including the
    ``--model-h5`` token that the child requires for ``.mpco``."""
    mpco_results._spawn_viewer_subprocess(title="My MPCO Run")
    argv = patch_popen.instances[0].args
    parser_argv = argv[3:]

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--title", default=None)
    parser.add_argument("--model-h5", dest="model_h5", default=None, type=Path)
    ns = parser.parse_args(parser_argv)

    assert ns.path == str(mpco_results._path)
    assert ns.title == "My MPCO Run"
    assert ns.model_h5 == mpco_results._model_path


# =====================================================================
# Subprocess failure monitor (PR-ε / audit-gap closure)
# =====================================================================
#
# _spawn_viewer_subprocess returns a fire-and-forget Popen; without
# the monitor, child failures (corrupt file, missing dep, exit(2))
# are invisible to the parent.  These tests exercise the helper in
# isolation (the spawn path is exercised above; the helper has no
# Results dependency).


def test_monitor_silent_on_zero_exit(capsys):
    """Exit code 0 → monitor prints nothing.  The thread waits, sees
    zero, and the call vanishes silently — the success case must
    not pollute stderr."""
    from apeGmsh.results.Results import _start_subprocess_monitor

    class FakeHandle:
        def wait(self):
            return 0

    _start_subprocess_monitor(FakeHandle(), ["python", "-m", "x"])
    # Give the daemon thread a moment to run.
    import time
    time.sleep(0.05)

    out, err = capsys.readouterr()
    assert err == ""
    assert out == ""


def test_monitor_surfaces_nonzero_exit_to_stderr(capsys):
    """Exit code != 0 → one line on stderr with the code and argv.
    This is the audit-gap closure: a child that exited(2) (the B1
    MPCO failure mode) now leaves a footprint in the parent's
    stderr instead of vanishing."""
    from apeGmsh.results.Results import _start_subprocess_monitor

    class FakeHandle:
        def wait(self):
            return 2

    argv = ["python", "-m", "apeGmsh.viewers", "/tmp/bad.mpco"]
    _start_subprocess_monitor(FakeHandle(), argv)
    import time
    time.sleep(0.05)

    out, err = capsys.readouterr()
    assert "viewer subprocess exited with code 2" in err
    assert "/tmp/bad.mpco" in err
    # stdout is untouched — only the parent's stderr carries the alert.
    assert out == ""


def test_monitor_swallows_wait_exception(capsys):
    """If ``handle.wait()`` itself raises (rare — Popen is robust),
    the monitor logs to stderr and does NOT re-raise.  A monitor
    crash must never propagate to the parent thread."""
    from apeGmsh.results.Results import _start_subprocess_monitor

    class FakeHandle:
        def wait(self):
            raise OSError("simulated wait failure")

    _start_subprocess_monitor(FakeHandle(), ["python"])
    import time
    time.sleep(0.05)

    out, err = capsys.readouterr()
    assert "viewer subprocess monitor failed" in err
    assert "simulated wait failure" in err


def test_monitor_thread_is_daemon():
    """The monitor thread must be a daemon — otherwise the parent
    process cannot exit cleanly until every spawned viewer closes,
    breaking the fire-and-forget contract."""
    from apeGmsh.results.Results import _start_subprocess_monitor
    import threading

    class FakeHandle:
        def wait(self):
            import time
            time.sleep(0.5)
            return 0

    before = {t.name for t in threading.enumerate()}
    _start_subprocess_monitor(FakeHandle(), ["python"])
    after = {t.name for t in threading.enumerate()}
    new_threads = after - before

    assert "apeGmsh-viewer-monitor" in new_threads
    monitor_thread = next(
        t for t in threading.enumerate()
        if t.name == "apeGmsh-viewer-monitor"
    )
    assert monitor_thread.daemon is True
