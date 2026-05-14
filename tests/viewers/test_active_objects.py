"""Unit tests for :class:`ActiveObjects` (plan 04 step 1).

Tests the signal-driven state coordinator in isolation — no viewer
construction, no VTK, just QObject signals + state.
"""
from __future__ import annotations

import pytest

pytest.importorskip("qtpy.QtCore")

from apeGmsh.viewers.core._active_objects import ActiveObjects


@pytest.fixture(scope="module")
def qapp():
    from qtpy import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def active(qapp):
    return ActiveObjects()


def _collect(signal):
    """Subscribe a list-appender to ``signal``; return the list."""
    bucket: list = []
    signal.connect(lambda value: bucket.append(value))
    return bucket


# =====================================================================
# Initial state
# =====================================================================


def test_initial_state_is_empty(active):
    assert active.selection is None
    assert active.active_view is None
    assert active.active_layer is None
    assert active.active_geometry is None
    assert active.active_stage is None
    assert active.active_step == -1
    assert active.active_pick_mode == ""


def test_snapshot_returns_initial_state(active):
    snap = active.snapshot()
    assert snap == {
        "selection": None,
        "active_view": None,
        "active_layer": None,
        "active_geometry": None,
        "active_stage": None,
        "active_step": -1,
        "active_pick_mode": "",
    }


# =====================================================================
# selectionChanged
# =====================================================================


def test_set_selection_emits_on_change(active):
    bucket = _collect(active.selectionChanged)
    sentinel = object()
    active.set_selection(sentinel)
    assert bucket == [sentinel]
    assert active.selection is sentinel


def test_set_selection_no_op_on_same_reference(active):
    bucket = _collect(active.selectionChanged)
    sentinel = object()
    active.set_selection(sentinel)
    active.set_selection(sentinel)    # second call should NOT emit
    assert len(bucket) == 1


def test_set_selection_emits_when_clearing_to_none(active):
    bucket = _collect(active.selectionChanged)
    sentinel = object()
    active.set_selection(sentinel)
    active.set_selection(None)
    assert bucket == [sentinel, None]
    assert active.selection is None


# =====================================================================
# Results-viewer signals
# =====================================================================


def test_set_active_layer_emits(active):
    bucket = _collect(active.activeLayerChanged)
    layer = object()
    active.set_active_layer(layer)
    assert bucket == [layer]
    assert active.active_layer is layer


def test_set_active_layer_no_op_on_same(active):
    bucket = _collect(active.activeLayerChanged)
    layer = object()
    active.set_active_layer(layer)
    active.set_active_layer(layer)
    assert len(bucket) == 1


def test_set_active_geometry_emits(active):
    bucket = _collect(active.activeGeometryChanged)
    geom = object()
    active.set_active_geometry(geom)
    assert bucket == [geom]
    assert active.active_geometry is geom


def test_set_active_stage_emits(active):
    bucket = _collect(active.activeStageChanged)
    stage = object()
    active.set_active_stage(stage)
    assert bucket == [stage]
    assert active.active_stage is stage


def test_set_active_step_uses_value_equality(active):
    """Steps are ints — value comparison, not identity."""
    bucket = _collect(active.activeStepChanged)
    active.set_active_step(5)
    active.set_active_step(5)    # same value → no emit
    assert bucket == [5]
    assert active.active_step == 5


def test_set_active_step_emits_on_each_distinct_value(active):
    bucket = _collect(active.activeStepChanged)
    active.set_active_step(0)
    active.set_active_step(1)
    active.set_active_step(2)
    assert bucket == [0, 1, 2]


def test_set_active_step_coerces_to_int(active):
    bucket = _collect(active.activeStepChanged)
    active.set_active_step(3)    # int
    active.set_active_step("3")  # string-of-int → coerced; no emit
    assert bucket == [3]


# =====================================================================
# Mesh-viewer pick mode
# =====================================================================


def test_set_active_pick_mode_emits(active):
    bucket = _collect(active.activePickModeChanged)
    active.set_active_pick_mode("element")
    assert bucket == ["element"]
    assert active.active_pick_mode == "element"


def test_set_active_pick_mode_no_op_on_same(active):
    bucket = _collect(active.activePickModeChanged)
    active.set_active_pick_mode("brep")
    active.set_active_pick_mode("brep")
    assert len(bucket) == 1


def test_set_active_pick_mode_empty_string_is_no_active(active):
    bucket = _collect(active.activePickModeChanged)
    active.set_active_pick_mode("node")
    active.set_active_pick_mode("")
    assert bucket == ["node", ""]


def test_set_active_pick_mode_none_treated_as_empty(active):
    bucket = _collect(active.activePickModeChanged)
    active.set_active_pick_mode("element")
    active.set_active_pick_mode(None)    # None → ""
    assert bucket == ["element", ""]


# =====================================================================
# active_view
# =====================================================================


def test_set_active_view_emits(active):
    bucket = _collect(active.activeViewChanged)
    view = object()
    active.set_active_view(view)
    assert bucket == [view]


# =====================================================================
# Cross-signal independence
# =====================================================================


def test_setting_one_kind_does_not_emit_others(active):
    """Setting selection must NOT fire activeLayerChanged etc."""
    layer_bucket = _collect(active.activeLayerChanged)
    geom_bucket  = _collect(active.activeGeometryChanged)
    step_bucket  = _collect(active.activeStepChanged)
    active.set_selection(object())
    assert layer_bucket == []
    assert geom_bucket == []
    assert step_bucket == []


def test_snapshot_reflects_full_state_after_multiple_sets(active):
    sel = object()
    layer = object()
    geom = object()
    active.set_selection(sel)
    active.set_active_layer(layer)
    active.set_active_geometry(geom)
    active.set_active_step(7)
    active.set_active_pick_mode("element")

    snap = active.snapshot()
    assert snap["selection"]       is sel
    assert snap["active_layer"]    is layer
    assert snap["active_geometry"] is geom
    assert snap["active_step"]     == 7
    assert snap["active_pick_mode"] == "element"


# =====================================================================
# Parent ownership — Qt's parent-tracked GC
# =====================================================================


def test_parent_keeps_active_objects_alive(qapp):
    from qtpy import QtWidgets

    # Construct an ActiveObjects parented to a QWidget; verify it
    # survives at least until the parent is destroyed.
    parent = QtWidgets.QWidget()
    active = ActiveObjects(parent=parent)
    assert active.parent() is parent
