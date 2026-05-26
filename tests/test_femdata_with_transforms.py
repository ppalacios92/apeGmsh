"""FEMData.with_constraint / with_load / with_mass pure transforms.

Phase 3B.2b-prep / ADR 0038 — verifies the canonical record-append
primitives that the upcoming compose merge engine (Phase 3B.2c) will
build on top of:

* ``with_constraint(record)`` / ``with_load(record)`` / ``with_mass(record)``
  return a NEW :class:`FEMData` with the record appended to the right
  sub-composite; ``self`` is never mutated.
* Dispatch is by record subclass; unknown subclasses raise
  ``TypeError`` (fail-loud).
* Chained transforms compose cleanly — the result of one
  ``.with_*(...)`` accepts another.
* The new FEMData and the predecessor do NOT share record-list state
  (defensive copy contract).

The fixture builds a minimum viable :class:`FEMData` directly via the
public ``FEMData.__init__`` to keep these tests pure-Python: no Gmsh
session, no resolver, no broker — just the transform contract.
"""
from __future__ import annotations

import numpy as np
import pytest

from apeGmsh._kernel.payloads import ElementGroup
from apeGmsh._kernel.records._constraints import (
    NodePairRecord, NodeGroupRecord, NodeToSurfaceRecord,
    InterpolationRecord, SurfaceCouplingRecord,
)
from apeGmsh._kernel.records._loads import (
    NodalLoadRecord, ElementLoadRecord, SPRecord,
)
from apeGmsh._kernel.records._masses import MassRecord
from apeGmsh.mesh.FEMData import (
    FEMData, NodeComposite, ElementComposite, MeshInfo,
)
from apeGmsh.mesh._element_types import ElementTypeInfo
from apeGmsh.mesh._group_set import PhysicalGroupSet, LabelSet


# =====================================================================
# Fixture — tiny in-memory FEMData
# =====================================================================

def _make_fem() -> FEMData:
    """Build a 2-node, 1-element FEMData without touching gmsh."""
    node_ids = np.array([1, 2], dtype=object)
    node_coords = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float64)
    physical = PhysicalGroupSet({})
    labels = LabelSet({})

    nodes = NodeComposite(
        node_ids=node_ids,
        node_coords=node_coords,
        physical=physical,
        labels=labels,
    )

    type_info = ElementTypeInfo(
        code=1, gmsh_name="Line 2", name="line2",
        dim=1, order=1, npe=2, count=1,
    )
    group = ElementGroup(
        element_type=type_info,
        ids=np.array([1], dtype=np.int64),
        connectivity=np.array([[1, 2]], dtype=np.int64),
    )
    elements = ElementComposite(
        groups={1: group},
        physical=physical,
        labels=labels,
    )

    info = MeshInfo(n_nodes=2, n_elems=1, bandwidth=1, types=[type_info])
    return FEMData(nodes=nodes, elements=elements, info=info)


@pytest.fixture
def fem() -> FEMData:
    """Tiny in-memory FEMData (2 nodes, 1 line2 element)."""
    return _make_fem()


# =====================================================================
# 1. with_constraint — pure transform, dispatch by record type
# =====================================================================

def test_with_constraint_returns_new_fem(fem: FEMData):
    """``with_constraint`` returns a NEW FEMData; ``self`` is unchanged."""
    rec = NodePairRecord(kind="equal_dof", master_node=1, slave_node=2,
                         dofs=[1, 2, 3])

    n_before = len(fem.nodes.constraints)
    new_fem = fem.with_constraint(rec)

    assert new_fem is not fem
    assert len(fem.nodes.constraints) == n_before, (
        "predecessor must not be mutated"
    )
    assert len(new_fem.nodes.constraints) == n_before + 1


def test_with_constraint_node_pair_lands_on_nodes_constraints(fem: FEMData):
    """NodePairRecord → fem.nodes.constraints."""
    rec = NodePairRecord(kind="equal_dof", master_node=1, slave_node=2,
                         dofs=[1, 2, 3])
    new_fem = fem.with_constraint(rec)

    assert rec in list(new_fem.nodes.constraints)
    # Element-side untouched.
    assert len(new_fem.elements.constraints) == 0


def test_with_constraint_node_group_lands_on_nodes_constraints(fem: FEMData):
    """NodeGroupRecord → fem.nodes.constraints."""
    rec = NodeGroupRecord(
        kind="rigid_diaphragm", master_node=1, slave_nodes=[2],
        dofs=[1, 2, 6])
    new_fem = fem.with_constraint(rec)
    assert rec in list(new_fem.nodes.constraints)


def test_with_constraint_node_to_surface_lands_on_nodes_constraints(
    fem: FEMData,
):
    """NodeToSurfaceRecord → fem.nodes.constraints."""
    rec = NodeToSurfaceRecord(
        kind="node_to_surface", master_node=1, slave_nodes=[2],
        phantom_nodes=[100],
    )
    new_fem = fem.with_constraint(rec)
    assert rec in list(new_fem.nodes.constraints)


def test_with_constraint_interpolation_lands_on_elements_constraints(
    fem: FEMData,
):
    """InterpolationRecord → fem.elements.constraints."""
    rec = InterpolationRecord(
        kind="tie", slave_node=2, master_nodes=[1],
        weights=np.array([1.0]), dofs=[1, 2, 3])
    new_fem = fem.with_constraint(rec)

    assert rec in list(new_fem.elements.constraints)
    # Node-side untouched.
    assert len(new_fem.nodes.constraints) == 0


def test_with_constraint_surface_coupling_lands_on_elements_constraints(
    fem: FEMData,
):
    """SurfaceCouplingRecord → fem.elements.constraints."""
    rec = SurfaceCouplingRecord(
        kind="mortar", master_nodes=[1], slave_nodes=[2], dofs=[1, 2, 3])
    new_fem = fem.with_constraint(rec)
    assert rec in list(new_fem.elements.constraints)


def test_with_constraint_sp_lands_on_nodes_sp(fem: FEMData):
    """SPRecord routed through ``with_constraint`` → fem.nodes.sp."""
    rec = SPRecord(node_id=1, dof=1, value=0.0, is_homogeneous=True)
    new_fem = fem.with_constraint(rec)

    assert rec in list(new_fem.nodes.sp)
    assert len(new_fem.nodes.constraints) == 0


def test_with_constraint_unknown_type_raises(fem: FEMData):
    """An unsupported record type is fail-loud TypeError."""
    with pytest.raises(TypeError, match="unsupported record type"):
        fem.with_constraint("not a record")  # type: ignore[arg-type]


# =====================================================================
# 2. with_load — pure transform, dispatch by record type
# =====================================================================

def test_with_load_returns_new_fem(fem: FEMData):
    """``with_load`` returns a NEW FEMData; ``self`` is unchanged."""
    rec = NodalLoadRecord(node_id=1, force_xyz=(1.0, 0.0, 0.0))
    n_before = len(fem.nodes.loads)
    new_fem = fem.with_load(rec)

    assert new_fem is not fem
    assert len(fem.nodes.loads) == n_before
    assert len(new_fem.nodes.loads) == n_before + 1


def test_with_load_nodal_lands_on_nodes_loads(fem: FEMData):
    """NodalLoadRecord → fem.nodes.loads."""
    rec = NodalLoadRecord(node_id=1, force_xyz=(1.0, 0.0, 0.0))
    new_fem = fem.with_load(rec)
    assert rec in list(new_fem.nodes.loads)


def test_with_load_element_lands_on_elements_loads(fem: FEMData):
    """ElementLoadRecord → fem.elements.loads."""
    rec = ElementLoadRecord(
        element_id=1, load_type="beamUniform", params={"wy": -1.0})
    new_fem = fem.with_load(rec)
    assert rec in list(new_fem.elements.loads)


def test_with_load_sp_lands_on_nodes_sp(fem: FEMData):
    """SPRecord routed through ``with_load`` → fem.nodes.sp."""
    rec = SPRecord(node_id=1, dof=1, value=0.5, is_homogeneous=False)
    new_fem = fem.with_load(rec)
    assert rec in list(new_fem.nodes.sp)


def test_with_load_unknown_type_raises(fem: FEMData):
    with pytest.raises(TypeError, match="unsupported record type"):
        fem.with_load(123)  # type: ignore[arg-type]


# =====================================================================
# 3. with_mass — pure transform
# =====================================================================

def test_with_mass_returns_new_fem(fem: FEMData):
    """``with_mass`` returns a NEW FEMData; ``self`` is unchanged."""
    rec = MassRecord(node_id=1, mass=(1.0, 1.0, 1.0, 0.0, 0.0, 0.0))
    n_before = len(fem.nodes.masses)
    new_fem = fem.with_mass(rec)

    assert new_fem is not fem
    assert len(fem.nodes.masses) == n_before
    assert len(new_fem.nodes.masses) == n_before + 1


def test_with_mass_record_lands_on_nodes_masses(fem: FEMData):
    """MassRecord → fem.nodes.masses."""
    rec = MassRecord(node_id=1, mass=(1.0, 1.0, 1.0, 0.0, 0.0, 0.0))
    new_fem = fem.with_mass(rec)
    assert rec in list(new_fem.nodes.masses)


def test_with_mass_unknown_type_raises(fem: FEMData):
    with pytest.raises(TypeError, match="unsupported record type"):
        fem.with_mass("not a mass")  # type: ignore[arg-type]


# =====================================================================
# 4. Chained transforms — compose cleanly
# =====================================================================

def test_transform_chain_produces_expected_final_state(fem: FEMData):
    """Chained ``.with_*`` calls yield a FEMData with every record."""
    cn = NodePairRecord(kind="equal_dof", master_node=1, slave_node=2,
                        dofs=[1, 2, 3])
    ld = NodalLoadRecord(node_id=2, force_xyz=(0.0, -10.0, 0.0))
    ms = MassRecord(node_id=1, mass=(5.0, 5.0, 5.0, 0.0, 0.0, 0.0))

    final = fem.with_constraint(cn).with_load(ld).with_mass(ms)

    assert cn in list(final.nodes.constraints)
    assert ld in list(final.nodes.loads)
    assert ms in list(final.nodes.masses)
    # Original untouched.
    assert len(fem.nodes.constraints) == 0
    assert len(fem.nodes.loads) == 0
    assert len(fem.nodes.masses) == 0


# =====================================================================
# 5. Defensive copy — no shared record-list state
# =====================================================================

def test_transform_does_not_share_composite_state(fem: FEMData):
    """Appending to the new FEMData's record list must not bleed back."""
    rec = NodePairRecord(kind="equal_dof", master_node=1, slave_node=2,
                         dofs=[1, 2, 3])
    new_fem = fem.with_constraint(rec)

    # The underlying lists are NOT the same object.
    assert (
        new_fem.nodes.constraints._records
        is not fem.nodes.constraints._records
    )

    # Mutate the new FEMData's list directly; predecessor unchanged.
    extra = NodePairRecord(kind="rigid_beam", master_node=1, slave_node=2,
                           dofs=[1, 2, 3])
    new_fem.nodes.constraints._records.append(extra)
    assert len(new_fem.nodes.constraints) == 2
    assert len(fem.nodes.constraints) == 0


# =====================================================================
# 6. Snapshot ID — transform invalidates cache on the new FEM
# =====================================================================

def test_transform_drops_snapshot_id_cache(fem: FEMData):
    """The new FEMData must NOT carry the predecessor's cached
    snapshot_id.  ``compute_snapshot_id`` only folds nodes / elements
    / physical groups / composed_from today (not loads / masses /
    constraints), so a transform that only touches the record sets
    won't change the hex digest — but the *cache* still has to be
    cleared so a future hash extension that folds in the record sets
    cannot leak a stale value across the transform boundary.
    """
    # Prime the cache on the predecessor.
    _ = fem.snapshot_id
    assert hasattr(fem, "_snapshot_id_cache")

    rec = NodalLoadRecord(node_id=1, force_xyz=(1.0, 0.0, 0.0))
    new_fem = fem.with_load(rec)

    assert not hasattr(new_fem, "_snapshot_id_cache"), (
        "transform leaked the predecessor's cached snapshot_id; a "
        "future hash extension that folds in the record sets would "
        "not see the new record state."
    )
