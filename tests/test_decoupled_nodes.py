"""Decoupled nodes — ADR 0049 PR-4 (g.decouple_node + factory-append).

A *decoupled node* is an auxiliary node that is **not** a Gmsh mesh
vertex.  PR-4 ships the identity-only primitive: the session verb
``g.decouple_node(coords=... | point=..., label=...)`` appends a node to
the broker at extraction with a deterministic tag above every mesh node
(dedup-immune by construction) and ``provenance == "decoupled"``.  It
carries **no** ndf (that's PR-5 / ``ops.ndf``).

These tests pin the five behaviours the handoff named plus the
``point=`` snapshot and the API guards.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from apeGmsh import apeGmsh
from apeGmsh.mesh.FEMData import (
    FEMData, PROVENANCE_DECOUPLED, PROVENANCE_MESH,
)


def _unit_box_session(*, decouple=None):
    """Build a 1×1×1 box session; optionally declare decoupled nodes.

    ``decouple`` is a list of ``(coords|None, point|None, label)`` tuples
    applied via ``g.decouple_node`` after geometry, before meshing.
    Returns ``(fem, handles)``.
    """
    g = apeGmsh(model_name="dn")
    g.begin()
    g.model.geometry.add_box(0, 0, 0, 1, 1, 1, label="body")
    g.physical.add_volume("body", name="Body")
    handles = []
    for coords, point, label in (decouple or []):
        handles.append(
            g.decouple_node(coords=coords, point=point, label=label))
    g.mesh.sizing.set_global_size(1.0)
    g.mesh.generation.generate(dim=3)
    fem = g.mesh.queries.get_fem_data(dim=3)
    return g, fem, handles


# ---------------------------------------------------------------------
# 1. Creation
# ---------------------------------------------------------------------

def test_decouple_node_creates_a_node() -> None:
    g, fem, (h,) = _unit_box_session(
        decouple=[((5.0, 5.0, 5.0), None, "ground")])
    try:
        ids = [int(x) for x in fem.nodes.ids]
        assert h.tag is not None
        assert h.tag in ids
        # provenance array marks exactly this node decoupled.
        assert fem.nodes.provenance is not None
        assert list(int(x) for x in fem.nodes.decoupled_ids) == [h.tag]
        # The decoupled coord is present.
        idx = ids.index(h.tag)
        assert np.allclose(fem.nodes.coords[idx], (5.0, 5.0, 5.0))
    finally:
        g.end()


def test_decoupled_tag_is_above_every_mesh_tag() -> None:
    """Tag = getMaxNodeTag()+k → disjoint from mesh + phantom range."""
    g, fem, (h,) = _unit_box_session(
        decouple=[((2.0, 0.0, 0.0), None, "aux")])
    try:
        mesh_ids = [int(x) for x in fem.nodes.ids if int(x) != h.tag]
        assert h.tag > max(mesh_ids)
    finally:
        g.end()


# ---------------------------------------------------------------------
# 2. Coincident-with-mesh survives dedup
# ---------------------------------------------------------------------

def test_coincident_decoupled_node_survives_dedup() -> None:
    """A decoupled node on a mesh corner is NOT welded away — it is
    never a Gmsh vertex, so it never reaches removeDuplicateNodes."""
    g, fem, (h,) = _unit_box_session(
        decouple=[((0.0, 0.0, 0.0), None, "coincident")])
    try:
        n_at_origin = sum(
            1 for c in fem.nodes.coords if np.allclose(c, (0, 0, 0)))
        assert n_at_origin == 2          # mesh corner + decoupled node
        # The decoupled one is the flagged row.
        assert list(int(x) for x in fem.nodes.decoupled_ids) == [h.tag]
    finally:
        g.end()


# ---------------------------------------------------------------------
# 3. Folds into fem_hash + no-decoupled stays None (byte-stability)
# ---------------------------------------------------------------------

def test_no_decoupled_nodes_leaves_provenance_none() -> None:
    """The all-mesh case is encoded as None so the snapshot_id + H5
    bytes stay identical to a model without the feature."""
    g, fem, _ = _unit_box_session()
    try:
        assert fem.nodes.provenance is None
        assert fem.nodes.decoupled_ids.size == 0
    finally:
        g.end()


def test_decoupled_node_changes_snapshot_id() -> None:
    g0, fem0, _ = _unit_box_session()
    h0 = fem0.snapshot_id
    g0.end()
    g1, fem1, _ = _unit_box_session(
        decouple=[((5.0, 5.0, 5.0), None, "ground")])
    h1 = fem1.snapshot_id
    g1.end()
    assert h0 != h1


# ---------------------------------------------------------------------
# 4. H5 round-trip
# ---------------------------------------------------------------------

def test_h5_round_trip_preserves_provenance(tmp_path: Path) -> None:
    g, fem, _ = _unit_box_session(
        decouple=[((5.0, 5.0, 5.0), None, "ground"),
                  ((0.0, 0.0, 0.0), None, "coincident")])
    try:
        out = tmp_path / "m.h5"
        fem.to_h5(str(out), model_name="dn")
        rt = FEMData.from_h5(str(out))
        assert rt.nodes.provenance is not None
        assert (sorted(int(x) for x in rt.nodes.decoupled_ids)
                == sorted(int(x) for x in fem.nodes.decoupled_ids))
        # Lossless: same snapshot_id after the round-trip.
        assert rt.snapshot_id == fem.snapshot_id
    finally:
        g.end()


# ---------------------------------------------------------------------
# 5. MP determinism — independent identical builds → identical tags
# ---------------------------------------------------------------------

def test_decoupled_tag_is_deterministic_across_builds() -> None:
    """Tag = getMaxNodeTag()+i (rank-invariant) → two identical builds
    assign the same tags (the cross-rank MP guarantee)."""
    g0, fem0, (a0,) = _unit_box_session(
        decouple=[((5.0, 5.0, 5.0), None, "g")])
    t0 = a0.tag
    g0.end()
    g1, fem1, (a1,) = _unit_box_session(
        decouple=[((5.0, 5.0, 5.0), None, "g")])
    t1 = a1.tag
    g1.end()
    assert t0 == t1


# ---------------------------------------------------------------------
# 6. point= snapshot
# ---------------------------------------------------------------------

def test_point_label_snapshots_coords() -> None:
    g = apeGmsh(model_name="dn")
    g.begin()
    g.model.geometry.add_box(0, 0, 0, 1, 1, 1, label="body")
    g.physical.add_volume("body", name="Body")
    g.model.geometry.add_point(3.0, 4.0, 5.0, label="anchor")
    h = g.decouple_node(point="anchor", label="from_point")
    g.mesh.sizing.set_global_size(1.0)
    g.mesh.generation.generate(dim=3)
    fem = g.mesh.queries.get_fem_data(dim=3)
    try:
        ids = [int(x) for x in fem.nodes.ids]
        assert h.tag in ids
        idx = ids.index(h.tag)
        assert np.allclose(fem.nodes.coords[idx], (3.0, 4.0, 5.0))
        # The def snapshotted coords onto its resolved tag.
        assert h.coords is None          # point= path leaves coords None
        assert h.point == "anchor"
    finally:
        g.end()


# ---------------------------------------------------------------------
# 7. API guards
# ---------------------------------------------------------------------

def test_requires_exactly_one_of_coords_or_point() -> None:
    g = apeGmsh(model_name="dn")
    g.begin()
    try:
        with pytest.raises(ValueError):
            g.decouple_node()                       # neither
        with pytest.raises(ValueError):
            g.decouple_node(coords=(0, 0, 0), point="p")   # both
        with pytest.raises(ValueError):
            g.decouple_node(coords=(0, 0))          # wrong arity
    finally:
        g.end()


def test_provenance_codes() -> None:
    assert PROVENANCE_MESH == 0
    assert PROVENANCE_DECOUPLED == 1
