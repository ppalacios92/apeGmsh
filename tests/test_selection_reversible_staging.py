"""ADR 0045 S3c-2 — reversible group staging through the SelectionLog.

Group activate / stage / apply / rename / delete are now replayable ops,
so undo/redo cross a group switch. The active group's working set is
auto-materialised into staging on every replay, so ``staged_groups``
always reflects live members. Fully headless — no gmsh (the log + reducer
are pure; only flush touches gmsh, exercised elsewhere).
"""
from __future__ import annotations

from apeGmsh.viewers.core.selection import SelectionState

A, B, C = (3, 1), (3, 2), (3, 3)


def test_active_group_members_are_live_in_staging() -> None:
    sel = SelectionState()
    sel.set_active_group("G")
    sel.pick(A)
    sel.pick(B)
    # No commit gesture needed — the reducer materialises working->staged.
    assert {t.dimtag for t in sel.staged_groups["G"]} == {A, B}


def test_undo_crosses_group_switch() -> None:
    sel = SelectionState()
    sel.set_active_group("A")
    sel.pick(A)
    sel.set_active_group("B")
    sel.pick(B)
    assert sel.active_group == "B" and sel.picks == [B]

    assert sel.undo()                      # undo the B pick
    assert sel.active_group == "B" and sel.picks == []
    assert sel.undo()                      # undo the switch A->B
    assert sel.active_group == "A" and sel.picks == [A]   # back in A!
    # A's staged members preserved across the round-trip.
    assert {t.dimtag for t in sel.staged_groups["A"]} == {A}


def test_redo_reapplies_switch_and_pick() -> None:
    sel = SelectionState()
    sel.set_active_group("A")
    sel.pick(A)
    sel.set_active_group("B")
    sel.pick(B)
    sel.undo(); sel.undo()                 # back in A
    assert sel.redo() and sel.active_group == "B" and sel.picks == []
    assert sel.redo() and sel.picks == [B]


def test_delete_group_is_undoable() -> None:
    sel = SelectionState()
    sel.set_active_group("G")
    sel.pick(A)
    sel.set_active_group(None)             # deactivate so G is just staged
    assert "G" in sel.staged_groups
    sel.delete_group("G")
    assert "G" not in sel.staged_groups
    assert "G" in sel._pending_deletes     # tombstoned
    assert sel.undo()                      # undo the delete
    assert "G" in sel.staged_groups
    assert {t.dimtag for t in sel.staged_groups["G"]} == {A}
    assert "G" not in sel._pending_deletes


def test_rename_group_is_undoable() -> None:
    sel = SelectionState()
    sel.set_active_group("Old")
    sel.pick(A)
    sel.set_active_group(None)
    sel.rename_group("Old", "New")
    assert "New" in sel.staged_groups and "Old" not in sel.staged_groups
    assert sel.undo()
    assert "Old" in sel.staged_groups and "New" not in sel.staged_groups


def test_stage_group_then_activate_loads_members() -> None:
    sel = SelectionState()
    sel.pick(A)
    sel.pick(B)
    sel.stage_group("G", sel.targets)      # new-group flow
    sel.set_active_group("G")
    assert sel.active_group == "G"
    assert sel.picks == [A, B]


def test_rename_onto_existing_group_is_rejected_not_clobbered() -> None:
    # Adversarial-review finding: renaming A->B when B exists must NOT
    # silently overwrite B's members or duplicate the order entry.
    sel = SelectionState()
    sel.set_active_group("A")
    sel.pick(A)
    sel.set_active_group("B")
    sel.pick(B)
    sel.set_active_group(None)
    sel.rename_group("A", "B")             # B already exists — reject
    assert {t.dimtag for t in sel.staged_groups["B"]} == {B}   # B intact
    assert "A" in sel.staged_groups        # A unchanged
    assert sel.group_order.count("B") == 1  # no duplicate in order


def test_rename_preserves_order_position() -> None:
    sel = SelectionState()
    sel.set_active_group("A")
    sel.pick(A)
    sel.set_active_group("B")
    sel.pick(B)
    sel.set_active_group(None)
    assert sel.group_order == ["A", "B"]
    sel.rename_group("A", "Z")
    assert sel.group_order == ["Z", "B"]   # in place, not moved to end


def test_clear_with_active_group_preserves_members_and_no_drift() -> None:
    # Adversarial-review finding: clear() must not directly mutate the
    # active-group cache (drift) nor wipe the active group's members.
    sel = SelectionState()
    sel.set_active_group("G")
    sel.pick(A)
    sel.pick(B)
    sel.clear()
    assert sel.picks == []
    assert sel.active_group is None
    # The group's members survive the clear (deactivate stages them).
    assert {t.dimtag for t in sel.staged_groups["G"]} == {A, B}
    # No cache drift: the cache agrees with a fresh replay.
    assert sel.active_group == sel._log.replay_state().active
    # Clear is undoable — restores the active group + working set.
    assert sel.undo()
    assert sel.active_group == "G" and sel.picks == [A, B]


def test_reactivating_deleted_name_starts_empty_and_revives() -> None:
    sel = SelectionState()
    sel.set_active_group("G")
    sel.pick(A)
    sel.set_active_group(None)
    sel.delete_group("G")
    sel.set_active_group("G")              # re-activate the tombstoned name
    assert sel.picks == []                 # fresh, NOT the deleted members
    assert "G" not in sel._pending_deletes  # tombstone cleared (live again)
