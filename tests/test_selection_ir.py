"""S0 acceptance — the ADR 0045 selection IR value types.

Fully headless (no VTK, no GPU): exercises ``Substrate`` /
``SelectionTarget`` / ``BBox`` construction, validation (fail-loud),
hashing/equality (set membership — the property a ``SelectionState``
needs), and the derived ``BBox`` views the six old bbox notions fold
into. Purity (INV-1) is covered by ``test_scene_ir_pure.py``, which
walks every file under ``scene_ir/`` including the new modules.
"""
from __future__ import annotations

import numpy as np
import pytest

from apeGmsh.viewers.scene_ir import BBox, SelectionTarget, Substrate


# ---------------------------------------------------------------------------
# Substrate
# ---------------------------------------------------------------------------


def test_substrate_members_distinct() -> None:
    assert {s.value for s in Substrate} == {
        "model_brep",
        "mesh_topo",
        "results_topo",
    }


# ---------------------------------------------------------------------------
# SelectionTarget
# ---------------------------------------------------------------------------


def test_target_basic_construction() -> None:
    t = SelectionTarget(Substrate.MODEL_BREP, dim=3, key=7)
    assert t.substrate is Substrate.MODEL_BREP
    assert t.dim == 3 and t.key == 7
    assert t.sub is None and t.parent is None


def test_target_is_hashable_and_value_equal() -> None:
    a = SelectionTarget(Substrate.MESH_TOPO, dim=2, key=42)
    b = SelectionTarget(Substrate.MESH_TOPO, dim=2, key=42)
    # Value equality + hashability ⇒ set membership de-dupes (what a
    # SelectionState relies on).
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1


def test_target_substrate_keeps_id_spaces_distinct() -> None:
    # Same dim+key, different substrate ⇒ different targets (INV-3).
    brep = SelectionTarget(Substrate.MODEL_BREP, dim=2, key=5)
    mesh = SelectionTarget(Substrate.MESH_TOPO, dim=2, key=5)
    assert brep != mesh
    assert len({brep, mesh}) == 2


def test_target_gauss_carries_sub_and_parent() -> None:
    elem = SelectionTarget(Substrate.RESULTS_TOPO, dim=3, key=11)
    gp = SelectionTarget(
        Substrate.RESULTS_TOPO, dim=3, key=11, sub=2, parent=elem
    )
    assert gp.sub == 2
    assert gp.parent == elem
    assert gp != elem  # sub distinguishes them


def test_target_coerces_numpy_ints() -> None:
    t = SelectionTarget(Substrate.MESH_TOPO, dim=np.int64(1), key=np.int64(9))
    assert isinstance(t.dim, int) and isinstance(t.key, int)
    assert t.dim == 1 and t.key == 9


def test_target_rejects_out_of_range_dim() -> None:
    with pytest.raises(ValueError, match="dim must be one of"):
        SelectionTarget(Substrate.MODEL_BREP, dim=4, key=1)


def test_target_rejects_non_substrate() -> None:
    with pytest.raises(TypeError, match="must be a Substrate"):
        SelectionTarget("model_brep", dim=0, key=1)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# BBox
# ---------------------------------------------------------------------------


def test_bbox_construction_and_views() -> None:
    bb = BBox([0.0, 0.0, 0.0], [2.0, 4.0, 6.0])
    assert bb.min.tolist() == [0.0, 0.0, 0.0]
    assert bb.max.tolist() == [2.0, 4.0, 6.0]
    assert bb.center.tolist() == [1.0, 2.0, 3.0]
    assert bb.diagonal == pytest.approx(np.sqrt(4 + 16 + 36))
    assert bb.corners8.shape == (8, 3)
    # All 8 corners are min/max combinations.
    for c in bb.corners8:
        assert c[0] in (0.0, 2.0) and c[1] in (0.0, 4.0) and c[2] in (0.0, 6.0)


def test_bbox_union() -> None:
    a = BBox([0, 0, 0], [1, 1, 1])
    b = BBox([-1, 0.5, 2], [0.5, 3, 4])
    u = a.union(b)
    assert u.min.tolist() == [-1.0, 0.0, 0.0]
    assert u.max.tolist() == [1.0, 3.0, 4.0]


def test_bbox_contains() -> None:
    bb = BBox([0, 0, 0], [10, 10, 10])
    assert bb.contains([5, 5, 5])
    assert bb.contains([0, 0, 0])      # inclusive
    assert bb.contains([10, 10, 10])   # inclusive
    assert not bb.contains([5, 5, 11])


def test_bbox_from_points() -> None:
    pts = np.array([[1, 2, 3], [-1, 5, 0], [4, 0, 2]], dtype=np.float64)
    bb = BBox.from_points(pts)
    assert bb.min.tolist() == [-1.0, 0.0, 0.0]
    assert bb.max.tolist() == [4.0, 5.0, 3.0]


def test_bbox_rejects_inverted_box() -> None:
    with pytest.raises(ValueError, match="min <= max"):
        BBox([1, 1, 1], [0, 0, 0])


def test_bbox_rejects_bad_shape() -> None:
    with pytest.raises(ValueError, match="3-vector"):
        BBox([0, 0], [1, 1])


def test_bbox_from_points_rejects_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        BBox.from_points(np.empty((0, 3)))
