"""Frozen invariants that keep the recurring "Outline dock stuck on the
upper edge" bug dead.

The bug returned 3+ times because each fix was a one-shot reset that left
the structural trap in place: a navigation dock added AFTER restoreState()
whose corrupt persisted placement was re-applied via Qt's
``restoreDockWidget``. The permanent fix (2026-05-31) makes the nav docks
construction-time docks (present at restore), deletes the
``restoreDockWidget`` escape hatch + the ``place_late_dock_left`` band-aid,
and heals any degenerate restored state via ``sanitize_dock_placement``.

These source-level assertions lock that contract so a future edit can't
quietly reintroduce the trap. They scan the WORKTREE source directly
(relative to this file) rather than importing ``apeGmsh`` — the editable
install resolves to the main-repo src, which would test the wrong tree.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src" / "apeGmsh" / "viewers"
_MESH = _SRC / "mesh_viewer.py"
_MODEL = _SRC / "model_viewer.py"
_REGISTRY = _SRC / "ui" / "_dock_registry.py"


def _read(p: Path) -> str:
    assert p.is_file(), f"expected source file at {p}"
    return p.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", [_MESH, _MODEL], ids=["mesh", "model"])
def test_no_restoreDockWidget_in_viewers(path):
    """``restoreDockWidget`` re-applies a late-added dock's persisted
    placement — including a corrupt one. It is the root trap and must
    never be called from either viewer again."""
    assert "restoreDockWidget" not in _read(path), (
        f"{path.name} must not call restoreDockWidget — it re-applies a "
        f"corrupt persisted nav-dock placement (the recurring bug). Nav "
        f"docks are now construction-time docks healed by "
        f"sanitize_dock_placement instead."
    )


def test_place_late_dock_left_is_gone():
    """The interim band-aid is deleted; its presence would mean someone
    resurrected the late-add path."""
    assert "place_late_dock_left" not in _read(_REGISTRY), (
        "place_late_dock_left was the interim fix that opted nav docks "
        "out of persistence. It is replaced by sanitize_dock_placement."
    )


def test_sanitize_helper_exists():
    assert "def sanitize_dock_placement(" in _read(_REGISTRY)


def test_mesh_outline_registered_at_construction_and_swapped():
    """mesh.viewer must register the Outline dock with sanitize=True and
    swap the real tree in via set_extension_dock_widget — i.e. it is a
    construction-time dock, not a late add."""
    src = _read(_MESH)
    assert 'dock_id="dock_mesh_outline"' in src
    assert "sanitize=True" in src
    assert 'set_extension_dock_widget(\n            "dock_mesh_outline"' in src \
        or 'set_extension_dock_widget("dock_mesh_outline"' in src


def test_model_nav_docks_registered_at_construction_and_swapped():
    src = _read(_MODEL)
    assert 'dock_id="dock_model_outline"' in src
    assert 'dock_id="dock_model_selection"' in src
    assert "sanitize=True" in src
    assert 'set_extension_dock_widget("dock_model_outline"' in src
    assert 'set_extension_dock_widget("dock_model_selection"' in src
