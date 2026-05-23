"""Unit tests for runtime-conditional numberer / system fallback
(ADR 0027 INV-5 amendment 2026-05-23).

When ``len(fem.partitions) > 1`` and the user has not explicitly set
the numberer / system, the bridge auto-emits a **runtime-conditional**
fallback so the same deck runs under both OpenSeesMP (uses the primary
``ParallelPlain`` / ``Mumps``) and single-process OpenSees (catches
the parse / lookup error and falls back to ``RCM`` / ``UmfPack``).

These unit tests target the per-emitter primitives in isolation:

* ``parallel_runtime_fallback_numberer(primary, fallback)``
* ``parallel_runtime_fallback_system(primary, fallback)``

For the integrated behaviour through the bridge (apeSees + build()
+ emit), see
``tests/opensees/integration/test_emit_partitioned_auto_numberer_and_system.py``.
"""
from __future__ import annotations

import inspect
import warnings
from typing import Any, get_type_hints
from unittest.mock import MagicMock

import pytest

from apeGmsh.opensees.emitter.base import Emitter
from apeGmsh.opensees.emitter.py import PyEmitter
from apeGmsh.opensees.emitter.recording import RecordingEmitter
from apeGmsh.opensees.emitter.tcl import TclEmitter


# ---------------------------------------------------------------------------
# 1. Protocol contract
# ---------------------------------------------------------------------------


def test_protocol_has_parallel_runtime_fallback_methods() -> None:
    """``Emitter`` Protocol declares the two new runtime-fallback
    methods with ``(primary: str, fallback: str) -> None`` signatures.
    """
    assert hasattr(Emitter, "parallel_runtime_fallback_numberer"), (
        "Emitter Protocol must declare parallel_runtime_fallback_numberer "
        "(ADR 0027 INV-5 amendment 2026-05-23)."
    )
    assert hasattr(Emitter, "parallel_runtime_fallback_system"), (
        "Emitter Protocol must declare parallel_runtime_fallback_system "
        "(ADR 0027 INV-5 amendment 2026-05-23)."
    )

    # Signature shape for both.
    for method_name in (
        "parallel_runtime_fallback_numberer",
        "parallel_runtime_fallback_system",
    ):
        method = getattr(Emitter, method_name)
        hints = get_type_hints(method)
        assert hints.get("primary") is str, (
            f"{method_name}.primary must be typed as str; "
            f"got {hints.get('primary')!r}"
        )
        assert hints.get("fallback") is str, (
            f"{method_name}.fallback must be typed as str; "
            f"got {hints.get('fallback')!r}"
        )
        assert hints.get("return") is type(None), (
            f"{method_name} must return None"
        )

        sig = inspect.signature(method)
        params = [p.name for p in sig.parameters.values()]
        assert params == ["self", "primary", "fallback"], (
            f"{method_name} parameter shape must be "
            f"(self, primary, fallback); got {params}"
        )


# ---------------------------------------------------------------------------
# 2-3. TclEmitter — Tcl ``catch`` wrapper for numberer + system
# ---------------------------------------------------------------------------


def test_tcl_emitter_emits_catch_wrapped_numberer() -> None:
    """TclEmitter wraps ``numberer ParallelPlain`` in a Tcl ``catch``
    block with fallback ``numberer RCM``.
    """
    e = TclEmitter()
    e.parallel_runtime_fallback_numberer("ParallelPlain", "RCM")
    text = "\n".join(e.lines())

    expected = (
        "if {[catch {numberer ParallelPlain} _err]} { numberer RCM }"
    )
    assert expected in text, (
        f"expected Tcl catch wrapper for numberer; got:\n{text}"
    )


def test_tcl_emitter_emits_catch_wrapped_system() -> None:
    """TclEmitter wraps ``system Mumps`` in a Tcl ``catch`` block with
    fallback ``system UmfPack``.
    """
    e = TclEmitter()
    e.parallel_runtime_fallback_system("Mumps", "UmfPack")
    text = "\n".join(e.lines())

    expected = (
        "if {[catch {system Mumps} _err]} { system UmfPack }"
    )
    assert expected in text, (
        f"expected Tcl catch wrapper for system; got:\n{text}"
    )


# ---------------------------------------------------------------------------
# 4-5. PyEmitter — Python ``try / except`` wrapper for numberer + system
# ---------------------------------------------------------------------------


def test_py_emitter_emits_try_except_numberer() -> None:
    """PyEmitter wraps ``ops.numberer('ParallelPlain')`` in a Python
    ``try / except`` with fallback ``ops.numberer('RCM')``.
    """
    e = PyEmitter()
    e.parallel_runtime_fallback_numberer("ParallelPlain", "RCM")
    text = "\n".join(e.lines())

    # The block must contain (in order) the primary call inside a
    # ``try:`` and the fallback call inside the matching ``except``.
    assert "try:" in text
    assert "ops.numberer('ParallelPlain')" in text
    assert "except Exception:" in text
    assert "ops.numberer('RCM')" in text

    # The primary must precede the fallback (ordering is load-bearing).
    primary_idx = text.index("ops.numberer('ParallelPlain')")
    fallback_idx = text.index("ops.numberer('RCM')")
    assert primary_idx < fallback_idx, (
        f"primary must precede fallback; got:\n{text}"
    )


def test_py_emitter_emits_try_except_system() -> None:
    """PyEmitter wraps ``ops.system('Mumps')`` in a Python ``try / except``
    with fallback ``ops.system('UmfPack')``.
    """
    e = PyEmitter()
    e.parallel_runtime_fallback_system("Mumps", "UmfPack")
    text = "\n".join(e.lines())

    assert "try:" in text
    assert "ops.system('Mumps')" in text
    assert "except Exception:" in text
    assert "ops.system('UmfPack')" in text

    primary_idx = text.index("ops.system('Mumps')")
    fallback_idx = text.index("ops.system('UmfPack')")
    assert primary_idx < fallback_idx, (
        f"primary must precede fallback; got:\n{text}"
    )


# ---------------------------------------------------------------------------
# 6-7. LiveOpsEmitter — exception-driven fallback in-process
# ---------------------------------------------------------------------------


def _build_live_emitter_with_fake_ops() -> Any:
    """Build a LiveOpsEmitter whose ``_ops`` is a MagicMock.

    Loads LiveOpsEmitter lazily after monkey-patching ``_get_ops`` so
    constructing the emitter does not require openseespy to be
    installed.
    """
    from apeGmsh.opensees.emitter import live as live_mod

    fake_ops = MagicMock()
    fake_ops.wipe = MagicMock()
    # Replace ``_get_ops`` with one returning our fake.  ``LiveOpsEmitter``
    # validates the return is a ``ModuleType``; bypass that with a
    # subclass that skips the assert.
    original_get_ops = live_mod._get_ops
    live_mod._get_ops = lambda: fake_ops  # type: ignore[assignment]
    try:
        # Build with wipe=False to avoid the wipe call routing through
        # the assert in ``_get_ops`` (we replaced the function but the
        # assert lives in the original); construct directly.
        emitter = live_mod.LiveOpsEmitter.__new__(live_mod.LiveOpsEmitter)
        emitter._ops = fake_ops
        emitter._real_ops = fake_ops
        emitter._partition_warned = False
        emitter._in_partition = False
    finally:
        live_mod._get_ops = original_get_ops  # type: ignore[assignment]
    return emitter, fake_ops


def test_live_emitter_falls_back_on_unavailable_numberer() -> None:
    """LiveOpsEmitter.parallel_runtime_fallback_numberer — when the
    primary raises, the fallback is called and a UserWarning fires.
    """
    emitter, fake_ops = _build_live_emitter_with_fake_ops()

    # Configure: ``numberer('ParallelPlain')`` raises; ``numberer('RCM')``
    # succeeds.
    def numberer_side_effect(name: str) -> None:
        if name == "ParallelPlain":
            raise RuntimeError("ParallelPlain not registered")
        return None
    fake_ops.numberer.side_effect = numberer_side_effect

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        emitter.parallel_runtime_fallback_numberer("ParallelPlain", "RCM")

    # Both calls happened — primary first, fallback after.
    call_args = [c.args for c in fake_ops.numberer.call_args_list]
    assert call_args == [("ParallelPlain",), ("RCM",)], (
        f"expected primary then fallback; got {call_args}"
    )

    # UserWarning fired flagging the fallback.
    messages = [str(w.message) for w in caught if w.category is UserWarning]
    assert any(
        "ParallelPlain" in m and "RCM" in m and "OpenSeesMP" in m
        for m in messages
    ), f"expected UserWarning about ParallelPlain → RCM fallback; got {messages}"


def test_live_emitter_succeeds_with_parallelplain_when_available() -> None:
    """LiveOpsEmitter.parallel_runtime_fallback_numberer — happy path:
    primary succeeds, fallback is not called, no warning.
    """
    emitter, fake_ops = _build_live_emitter_with_fake_ops()

    # Configure: every ``numberer(...)`` succeeds.
    fake_ops.numberer.return_value = None

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        emitter.parallel_runtime_fallback_numberer("ParallelPlain", "RCM")

    # Only the primary was called.
    call_args = [c.args for c in fake_ops.numberer.call_args_list]
    assert call_args == [("ParallelPlain",)], (
        f"happy path: fallback must not be called; got {call_args}"
    )
    # No UserWarning about fallback.
    messages = [str(w.message) for w in caught if w.category is UserWarning]
    assert not any("falling back" in m for m in messages), (
        f"happy path: no fallback warning; got {messages}"
    )


# ---------------------------------------------------------------------------
# 8. RecordingEmitter — captures both events
# ---------------------------------------------------------------------------


def test_recording_emitter_records_runtime_fallback_pair() -> None:
    """RecordingEmitter captures both ``parallel_runtime_fallback_numberer``
    and ``parallel_runtime_fallback_system`` calls with their
    ``(primary, fallback)`` args.
    """
    e = RecordingEmitter()
    e.parallel_runtime_fallback_numberer("ParallelPlain", "RCM")
    e.parallel_runtime_fallback_system("Mumps", "UmfPack")

    assert e.calls == [
        (
            "parallel_runtime_fallback_numberer",
            ("ParallelPlain", "RCM"),
            {},
        ),
        (
            "parallel_runtime_fallback_system",
            ("Mumps", "UmfPack"),
            {},
        ),
    ]
