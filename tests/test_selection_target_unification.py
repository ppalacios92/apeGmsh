"""ADR 0045 keystone — DimTag → SelectionTarget unification.

``SelectionState`` now holds ``SelectionTarget`` internally while callers
may still pass bare ``(dim, tag)`` DimTags. These tests pin the bridge:
the ``from_dimtag`` / ``dimtag`` round-trip, the ``.picks`` (DimTag shim)
vs ``.targets`` (structured) duality, normalization at the front door,
and value-equality dedup across the two input forms.

Fully headless — no gmsh / Qt / VTK.
"""
from __future__ import annotations

import pytest

from apeGmsh.viewers.core.selection import SelectionState
from apeGmsh.viewers.scene_ir import SelectionTarget, Substrate


# ── SelectionTarget DimTag bridge ───────────────────────────────────

def test_from_dimtag_builds_model_brep_target() -> None:
    t = SelectionTarget.from_dimtag((2, 7))
    assert t.substrate is Substrate.MODEL_BREP
    assert t.dim == 2 and t.key == 7
    assert t.sub is None and t.parent is None


def test_dimtag_round_trips() -> None:
    for dt in [(0, 1), (1, 4), (2, 9), (3, 12)]:
        assert SelectionTarget.from_dimtag(dt).dimtag == dt


def test_dimtag_raises_for_non_brep() -> None:
    node = SelectionTarget(Substrate.MESH_TOPO, 0, 5)
    with pytest.raises(ValueError, match="MODEL_BREP"):
        _ = node.dimtag


# ── SelectionState holds targets, exposes both views ────────────────

def test_picks_shim_returns_dimtags() -> None:
    sel = SelectionState()
    sel.pick((2, 1))
    sel.pick((3, 5))
    assert sel.picks == [(2, 1), (3, 5)]


def test_targets_returns_selection_targets() -> None:
    sel = SelectionState()
    sel.pick((2, 1))
    (t,) = sel.targets
    assert isinstance(t, SelectionTarget)
    assert t.substrate is Substrate.MODEL_BREP and t.dimtag == (2, 1)


def test_dimtag_and_target_inputs_dedup_by_value() -> None:
    sel = SelectionState()
    sel.pick((2, 1))
    # The same entity expressed as an explicit target must not re-add.
    sel.pick(SelectionTarget.from_dimtag((2, 1)))
    assert sel.picks == [(2, 1)]
    assert len(sel.targets) == 1


def test_target_input_unpicks_dimtag() -> None:
    sel = SelectionState()
    sel.pick((2, 1))
    sel.unpick(SelectionTarget(Substrate.MODEL_BREP, 2, 1))
    assert sel.picks == []


# ── batch / box ops normalize too ───────────────────────────────────

def test_select_batch_mixed_input_forms() -> None:
    sel = SelectionState()
    sel.select_batch([(2, 1), SelectionTarget.from_dimtag((2, 2))])
    assert sel.picks == [(2, 1), (2, 2)]
    assert all(isinstance(t, SelectionTarget) for t in sel.targets)


def test_box_add_returns_distinct_count_with_targets() -> None:
    sel = SelectionState()
    sel.pick((2, 1))
    added = sel.box_add([(2, 1), SelectionTarget.from_dimtag((2, 2))])
    assert added == 1                      # (2,1) already present
    assert sel.picks == [(2, 1), (2, 2)]


# ── undo/redo still works through the target store ──────────────────

def test_undo_redo_round_trips_targets() -> None:
    sel = SelectionState()
    sel.box_add([(2, 1), (2, 2), (3, 5)])
    assert sel.picks == [(2, 1), (2, 2), (3, 5)]
    assert sel.undo() and sel.picks == []
    assert sel.redo() and sel.picks == [(2, 1), (2, 2), (3, 5)]


# ── staged groups hold targets (group I/O contract) ─────────────────

def test_staged_groups_hold_targets() -> None:
    sel = SelectionState()
    sel.pick((3, 1))
    sel.pick((3, 2))
    # Mirrors model_viewer _on_new_group staging current picks.
    sel.stage_group("Foo", sel.targets)
    assert all(isinstance(t, SelectionTarget) for t in sel.staged_groups["Foo"])
