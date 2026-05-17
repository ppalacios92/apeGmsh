"""g.constraints.bc — homogeneous single-point constraint (fix to ground).

Covers the full declaration → get_fem_data → fem.nodes.sp path:

* default + custom restraint mask semantics ([1,1,1] convention)
* dimension-agnostic resolution (surface vs whole volume)
* explicit pg= resolution path
* fail-loud on a pattern that resolves to zero nodes
* HDF5 round-trip (BC-produced SPRecords persist like face_sp)
"""
from __future__ import annotations

from pathlib import Path

import gmsh
import pytest

from apeGmsh.mesh.FEMData import FEMData


# =====================================================================
# Helpers
# =====================================================================

def _unit_cube_with_top(g):
    """Unit cube; +z face named ``Top``, the solid named ``Body``."""
    g.model.geometry.add_box(0.0, 0.0, 0.0, 1.0, 1.0, 1.0, label='cube')
    top_tag = None
    for d, t in g.model.queries.boundary('cube', dim=2):
        com = g.model.queries.center_of_mass(int(t), dim=int(d))
        if abs(com[2] - 1.0) < 1e-6:
            top_tag = int(t)
            break
    assert top_tag is not None
    g.physical.add_volume('cube', name='Body')
    g.physical.add_surface([top_tag], name='Top')
    g.mesh.sizing.set_global_size(0.5)
    g.mesh.generation.generate(dim=3)


def _pg_node_ids(name: str) -> set[int]:
    """Mesh node IDs of the (single-dim) physical group ``name``."""
    found = None
    for d, t in gmsh.model.getPhysicalGroups():
        if gmsh.model.getPhysicalName(d, t) == name:
            found = (d, t)
            break
    assert found is not None, f"no PG named {name}"
    d, t = found
    ids: set[int] = set()
    for ent in gmsh.model.getEntitiesForPhysicalGroup(d, t):
        nt, _, _ = gmsh.model.mesh.getNodes(
            dim=d, tag=int(ent), includeBoundary=True,
            returnParametricCoord=False)
        ids.update(int(n) for n in nt)
    return ids


# =====================================================================
# Declaration
# =====================================================================

def test_bc_def_is_stored_off_constraint_defs(g):
    """A BC is kept apart from constraint_defs (no master/slave, not
    in _DISPATCH)."""
    g.model.geometry.add_box(0, 0, 0, 1, 1, 1, label='cube')
    g.physical.add_surface(
        [int(g.model.queries.boundary('cube', dim=2)[0][1])], name='Face')
    defn = g.constraints.bc('Face')
    assert defn.kind == 'bc'
    assert defn.dofs == [1, 1, 1]
    assert g.constraints._bc_defs == [defn]
    assert defn not in g.constraints.constraint_defs


def test_bc_default_mask_pins_xyz_on_surface(g):
    _unit_cube_with_top(g)
    g.constraints.bc('Top')
    fem = g.mesh.queries.get_fem_data(dim=3)

    top = _pg_node_ids('Top')
    sps = list(fem.nodes.sp)
    assert sps, "bc produced no SPRecords"
    assert all(sp.is_homogeneous for sp in sps)
    assert all(float(sp.value) == 0.0 for sp in sps)
    assert {int(sp.dof) for sp in sps} == {1, 2, 3}
    assert {int(sp.node_id) for sp in sps} == top
    # exactly one record per (node, restrained dof)
    assert len(sps) == 3 * len(top)


def test_bc_mask_skips_free_dofs(g):
    _unit_cube_with_top(g)
    g.constraints.bc('Top', dofs=[1, 0, 1])
    fem = g.mesh.queries.get_fem_data(dim=3)

    top = _pg_node_ids('Top')
    sps = list(fem.nodes.sp)
    assert {int(sp.dof) for sp in sps} == {1, 3}
    assert not any(int(sp.dof) == 2 for sp in sps)
    assert len(sps) == 2 * len(top)


def test_bc_six_dof_full_fixity(g):
    _unit_cube_with_top(g)
    g.constraints.bc('Top', dofs=[1, 1, 1, 1, 1, 1])
    fem = g.mesh.queries.get_fem_data(dim=3)
    sps = list(fem.nodes.sp)
    assert {int(sp.dof) for sp in sps} == {1, 2, 3, 4, 5, 6}
    assert len(sps) == 6 * len(_pg_node_ids('Top'))


def test_bc_explicit_pg_path_matches_auto(g):
    _unit_cube_with_top(g)
    g.constraints.bc(pg='Top')
    fem = g.mesh.queries.get_fem_data(dim=3)
    assert {int(sp.node_id) for sp in fem.nodes.sp} == _pg_node_ids('Top')


def test_bc_on_volume_fixes_every_interior_node(g):
    """Dimension-agnostic: a volume pattern fixes *all* its nodes —
    the documented footgun, asserted so the behaviour is locked."""
    _unit_cube_with_top(g)
    g.constraints.bc(pg='Body')
    fem = g.mesh.queries.get_fem_data(dim=3)
    assert {int(sp.node_id) for sp in fem.nodes.sp} == set(
        int(n) for n in fem.nodes.ids)


# =====================================================================
# Fail-loud
# =====================================================================

def test_bc_unknown_pattern_raises(g):
    _unit_cube_with_top(g)
    g.constraints.bc('NoSuchPattern')
    with pytest.raises((KeyError, ValueError)):
        g.mesh.queries.get_fem_data(dim=3)


# =====================================================================
# Persistence
# =====================================================================

def test_bc_sp_records_round_trip_h5(g, tmp_path: Path):
    _unit_cube_with_top(g)
    g.constraints.bc('Top', dofs=[1, 1, 0])
    fem = g.mesh.queries.get_fem_data(dim=3)
    before = sorted(
        (int(s.node_id), int(s.dof), float(s.value), bool(s.is_homogeneous))
        for s in fem.nodes.sp)

    out = tmp_path / "bc.h5"
    fem.to_h5(str(out))
    rebuilt = FEMData.from_h5(str(out))
    after = sorted(
        (int(s.node_id), int(s.dof), float(s.value), bool(s.is_homogeneous))
        for s in rebuilt.nodes.sp)

    assert before == after
    assert before, "expected non-empty SP set"
