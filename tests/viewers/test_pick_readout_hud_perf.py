"""PickReadoutHUD dispatcher migration (UI storm follow-up #3).

The HUD subscribes to ``director.subscribe_step`` + ``subscribe_stage``
to re-read HDF5 values at the last pick whenever the time scrubber
moves. Without coalesce, dragging the scrubber issues one HDF5 read
per slider tick. ``attach_dispatcher`` swaps in a UI-lane
``dispatcher.subscribe`` so a rapid drag collapses to one read per
Qt tick.

Same ``attach_dispatcher`` pattern as OutlineTree (#131) /
DiagramSettingsTab (#132); the only difference is the event kinds
(STEP_CHANGED / STAGE_CHANGED instead of the geometry kinds).
"""
from __future__ import annotations

import os
from typing import Any

import pytest


# Force offscreen Qt before importing qtpy.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _ProbeOverlayStub:
    def __init__(self):
        self.on_point_result = None


class _DirectorStub:
    """Minimal Director for the HUD: step/stage subscribers + a
    ``read_at_pick`` shim that just records call count."""

    def __init__(self):
        self._on_step = []
        self._on_stage = []
        self.read_calls = 0
        self.stage_id = None

    def subscribe_step(self, cb):
        self._on_step.append(cb)
        return lambda: (
            self._on_step.remove(cb) if cb in self._on_step else None
        )

    def subscribe_stage(self, cb):
        self._on_stage.append(cb)
        return lambda: (
            self._on_stage.remove(cb) if cb in self._on_stage else None
        )

    def _fire_step(self, step_index: int) -> None:
        """Simulate Director firing on_step_changed callbacks."""
        for cb in list(self._on_step):
            cb(step_index)

    def _fire_stage(self, stage_id: Any) -> None:
        for cb in list(self._on_stage):
            cb(stage_id)

    def read_at_pick(self, *args, **kwargs):
        """The HUD's ``_refresh_values_for_last_pick`` reads HDF5 via
        this entry point. We just count invocations for the storm
        bench."""
        self.read_calls += 1
        # Return a shape the HUD will accept; empty values are fine.
        return {"node_id": 1, "coord": (0.0, 0.0, 0.0), "field_values": {}}


def _build_hud_with_stubs():
    """Construct PickReadoutHUD with a stub overlay + director, plus a
    parented viewport widget (offscreen Qt)."""
    from qtpy import QtWidgets
    _ = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    viewport = QtWidgets.QWidget()

    overlay = _ProbeOverlayStub()
    director = _DirectorStub()

    from apeGmsh.viewers.ui._pick_readout_hud import PickReadoutHUD
    hud = PickReadoutHUD(viewport, overlay, director)
    return hud, viewport, overlay, director


def test_attach_dispatcher_swaps_step_subscription() -> None:
    """After ``attach_dispatcher``, a Director step fire must NOT
    trigger the HUD's step handler synchronously — the dispatcher's UI
    lane owns the timing."""
    from apeGmsh.viewers.diagrams._dispatch import Dispatcher

    hud, _viewport, _overlay, director = _build_hud_with_stubs()

    # Pre-migration: the HUD is subscribed to director.on_step_changed.
    # Fire a step → HUD's _on_step_changed runs synchronously →
    # _refresh_values_for_last_pick calls director.read_at_pick.
    # Without a last pick the HUD short-circuits before reading; we
    # detect via the subscriber-list state instead.
    assert len(director._on_step) == 1, "HUD should hold legacy step sub"
    assert len(director._on_stage) == 1

    # Attach dispatcher.
    deferred = []
    dispatcher = Dispatcher(
        director=director,
        pump_step=lambda _l: None,
        pump_deform=lambda _l: None,
        pump_gate=lambda: None,
        pump_restack=lambda: None,
        render=lambda: None,
        defer_fn=deferred.append,
    )
    hud.attach_dispatcher(dispatcher)

    # Legacy subs are dropped.
    assert len(director._on_step) == 0, (
        "attach_dispatcher must drop the legacy subscribe_step wiring"
    )
    assert len(director._on_stage) == 0


@pytest.mark.bench
def test_rapid_scrubber_drag_collapses_to_few_reads() -> None:
    """Simulate a 100-tick scrubber drag (each tick fires STEP_CHANGED).
    Without coalesce that would be 100 HDF5 re-reads; with the UI lane,
    one read per Qt tick."""
    from apeGmsh.viewers.diagrams._dispatch import (
        Dispatcher,
        STEP_CHANGED,
    )

    hud, _viewport, _overlay, director = _build_hud_with_stubs()

    deferred = []
    dispatcher = Dispatcher(
        director=director,
        pump_step=lambda _l: None,
        pump_deform=lambda _l: None,
        pump_gate=lambda: None,
        pump_restack=lambda: None,
        render=lambda: None,
        defer_fn=deferred.append,
    )
    hud.attach_dispatcher(dispatcher)

    # Patch _on_step_changed to count callbacks. The dispatcher
    # subscription lambda resolves ``self._on_step_changed`` at call
    # time, so an instance-attribute patch is honored.
    callbacks = [0]
    original = hud._on_step_changed.__func__

    def _counting_on_step(step_index):
        callbacks[0] += 1
        original(hud, step_index)

    hud._on_step_changed = _counting_on_step    # type: ignore[method-assign]

    # 100 step fires in one tick.
    for step in range(100):
        dispatcher.fire(STEP_CHANGED, payload=None)

    # Pre-drain: callbacks queued but not fired.
    assert callbacks[0] == 0

    # Drain.
    for fn in list(deferred):
        fn()

    print(
        f"\n[hud scrubber storm] 100 STEP_CHANGED fires -> "
        f"{callbacks[0]} callbacks after coalesce flush"
    )

    # Coalesce contract: STEP_CHANGED with key_fn=None and payload=None
    # collapses every fire to the same dedup key → exactly 1 callback.
    assert callbacks[0] == 1, (
        f"Expected 1 callback after coalesce; got {callbacks[0]} "
        f"for 100 STEP_CHANGED fires"
    )
