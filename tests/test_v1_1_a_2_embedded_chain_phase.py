"""Compose v1.1-A.2 — EmbeddedDef chain-phase routing (ADR 0041).

Tests the new ``_route_embedded`` branch in
:mod:`apeGmsh._kernel.resolvers._chain_phase_router`.  Builds in-
memory :class:`FEMData` fixtures with a hex host + interior embedded
node, exercises the chain-phase router end-to-end, asserts the
resulting :class:`InterpolationRecord`s land on
``fem.elements.constraints``, and locks an H5 round-trip.

No live gmsh session, no openseespy.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pytest

from apeGmsh._core import apeGmsh
from apeGmsh._kernel.defs.constraints import EmbeddedDef
from apeGmsh._kernel.payloads import ElementGroup
from apeGmsh._kernel.record_sets import ComposeSet
from apeGmsh._kernel.records._constraints import (
    ConstraintKind,
    InterpolationRecord,
)
from apeGmsh._kernel.resolvers._chain_phase_router import (
    route_def_to_fem,
    try_chain_phase_route,
)
from apeGmsh._kernel.resolvers._source import FEMDataSource
from apeGmsh.mesh._element_types import make_type_info
from apeGmsh.mesh._group_set import LabelSet, PhysicalGroupSet
from apeGmsh.mesh.FEMData import (
    ElementComposite,
    FEMData,
    MeshInfo,
    NodeComposite,
)


# ---------------------------------------------------------------------
# Fixture: hex host + embedded interior node
# ---------------------------------------------------------------------


def _make_hex_with_embedded_node_fem(
    *,
    host_label: str = "soil",
    embed_label: str = "rebar",
    embed_inside: bool = True,
) -> FEMData:
    """Build a FEMData with:

    * 8 hex8 corner nodes at the unit-cube corners (ids 1..8).
    * 1 embedded interior node (id 9) at the centre of the cube
      (or outside the cube when ``embed_inside=False``).
    * One hex8 element (id 100) in physical group ``host_label``.
    * One virtual point element / label for the embedded node in
      physical group ``embed_label``.
    """
    hex_corners = np.array(
        [
            [0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0], [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0], [1.0, 0.0, 1.0],
            [1.0, 1.0, 1.0], [0.0, 1.0, 1.0],
        ],
        dtype=np.float64,
    )
    if embed_inside:
        embed_xyz = np.array([[0.5, 0.5, 0.5]], dtype=np.float64)
    else:
        # Far outside the cube — guaranteed to fail the barycentric
        # tolerance gate.
        embed_xyz = np.array([[10.0, 10.0, 10.0]], dtype=np.float64)

    coords = np.vstack([hex_corners, embed_xyz])
    node_ids = np.arange(1, 10, dtype=np.int64)

    hex_info = make_type_info(
        code=5, gmsh_name="Hexahedron 8", dim=3, order=1, npe=8, count=1,
    )
    hex_conn = np.array([[1, 2, 3, 4, 5, 6, 7, 8]], dtype=np.int64)
    hex_ids = np.array([100], dtype=np.int64)
    hex_group = ElementGroup(
        element_type=hex_info, ids=hex_ids, connectivity=hex_conn,
    )

    # Element-side LABEL for the host (Tier 1).  Use a LabelSet rather
    # than a PhysicalGroupSet here because the schema 2.9 H5 writer
    # has a known snapshot-id drift bug for hand-constructed FEMData
    # carrying element-side PGs (the round-trip recomputes a
    # different snapshot_id and rejects the load).  Element-side
    # LABELS round-trip cleanly.  Real-world meshes don't hit this
    # because they come from gmsh extraction; this is a hand-built
    # fixture limitation only.
    elem_labels = {
        (3, 99): {
            "name": host_label,
            "element_ids": hex_ids,
            "node_ids": np.arange(1, 9, dtype=np.int64),
            "node_coords": hex_corners,
        },
    }
    # Node-side PG for the embedded label (node 9 only).
    node_pgs = {
        (0, 7): {
            "name": embed_label,
            "node_ids": np.array([9], dtype=np.int64),
            "node_coords": embed_xyz,
        },
    }

    elements = ElementComposite(
        groups={5: hex_group},
        physical=PhysicalGroupSet({}),
        labels=LabelSet(elem_labels),
    )
    nodes = NodeComposite(
        node_ids=node_ids,
        node_coords=coords,
        physical=PhysicalGroupSet(node_pgs),
        labels=LabelSet({}),
    )
    info = MeshInfo(
        n_nodes=node_ids.size, n_elems=1, bandwidth=1, types=[hex_info],
    )
    return FEMData(
        nodes=nodes,
        elements=elements,
        info=info,
        composed_from=ComposeSet(()),
    )


def _save(fem: FEMData, tmp_path: Path, name: str = "h.h5") -> Path:
    path = tmp_path / name
    fem.to_h5(str(path))
    return path


# ---------------------------------------------------------------------
# Embedded chain-phase routing happy path
# ---------------------------------------------------------------------


class TestEmbeddedChainPhase:
    def test_route_def_to_fem_produces_interpolation_record(self) -> None:
        """Embedded node at centre → one InterpolationRecord coupling it
        to the 4 corners of one Kuhn sub-tet."""
        fem = _make_hex_with_embedded_node_fem()
        defn = EmbeddedDef(
            master_label="soil",
            slave_label="rebar",
            tolerance=1e-6,
            name="emb1",
        )

        new_fem = route_def_to_fem(fem, defn)

        assert new_fem is not None
        assert new_fem is not fem
        recs = list(new_fem.elements.constraints)
        assert len(recs) == 1
        rec = recs[0]
        assert isinstance(rec, InterpolationRecord)
        assert rec.kind == ConstraintKind.EMBEDDED
        assert rec.name == "emb1"
        assert rec.slave_node == 9
        # Master nodes must be 4 of the host's corners (one Kuhn sub-tet).
        assert len(rec.master_nodes) == 4
        for m in rec.master_nodes:
            assert m in (1, 2, 3, 4, 5, 6, 7, 8)
        # Weights sum to 1 (barycentric / linear shape functions).
        assert sum(rec.weights) == pytest.approx(1.0, abs=1e-9)
        assert rec.dofs == [1, 2, 3]

    def test_chain_phase_session_path(self, tmp_path: Path) -> None:
        """End-to-end via ``g.constraints.embedded(...)`` after
        ``apeGmsh.from_h5(...)``."""
        path = _save(_make_hex_with_embedded_node_fem(), tmp_path)
        g = apeGmsh.from_h5(path)
        fem_before = g._fem
        assert len(list(fem_before.elements.constraints)) == 0

        g.constraints.embedded(
            host_label="soil", embedded_label="rebar", tolerance=1e-6,
        )

        fem_after = g._fem
        # Identity changes — the chain-phase router replaced ``_fem``.
        assert fem_after is not fem_before
        recs = list(fem_after.elements.constraints)
        assert len(recs) == 1
        assert isinstance(recs[0], InterpolationRecord)
        assert recs[0].slave_node == 9

    def test_unknown_host_target_falls_back_silently(self) -> None:
        """An unknown ``host_label`` raises KeyError inside the router;
        :func:`try_chain_phase_route` swallows it and returns False
        (matches the v1.1-A KeyError handling for backward compat —
        labels may be defined later)."""
        fem = _make_hex_with_embedded_node_fem()
        defn = EmbeddedDef(
            master_label="not_a_label",
            slave_label="rebar",
            tolerance=1e-6,
        )

        # Direct route_def_to_fem call propagates KeyError.
        with pytest.raises(KeyError):
            route_def_to_fem(fem, defn)

        # The composite-level entry point swallows the KeyError.
        class Stub:
            _fem = fem

        s = Stub()
        assert try_chain_phase_route(s, defn) is False
        # No transform applied.
        assert s._fem is fem

    def test_embedded_outside_host_raises_value_error(self) -> None:
        """Embedded node well outside the hex → resolver fail-loud."""
        fem = _make_hex_with_embedded_node_fem(embed_inside=False)
        defn = EmbeddedDef(
            master_label="soil",
            slave_label="rebar",
            tolerance=0.0,
        )
        with pytest.raises(ValueError, match="lies outside"):
            route_def_to_fem(fem, defn)

    def test_embedded_node_coincident_with_host_corner_skipped(self) -> None:
        """An embedded node that IS a host corner is dropped before
        the resolver runs — no record, fem returned unchanged."""
        # Build a model where the embedded label points at host corner
        # node 1 (which is also part of the hex).
        fem = _make_hex_with_embedded_node_fem()
        # Replace the embedded PG to point at host corner node 1.
        new_node_pgs = {
            (0, 7): {
                "name": "rebar",
                "node_ids": np.array([1], dtype=np.int64),
                "node_coords": fem.nodes.coords[:1],
            },
        }
        new_nodes = NodeComposite(
            node_ids=fem.nodes.ids,
            node_coords=fem.nodes.coords,
            physical=PhysicalGroupSet(new_node_pgs),
            labels=LabelSet({}),
        )
        fem2 = FEMData(
            nodes=new_nodes,
            elements=fem.elements,
            info=fem.info,
            composed_from=ComposeSet(()),
        )
        defn = EmbeddedDef(
            master_label="soil",
            slave_label="rebar",
            tolerance=1e-6,
        )
        new_fem = route_def_to_fem(fem2, defn)
        # No new records (coincident corner filter dropped node 1).
        assert new_fem is fem2
        assert len(list(new_fem.elements.constraints)) == 0


# ---------------------------------------------------------------------
# Higher-order host warning + mixed-type host
# ---------------------------------------------------------------------


class TestHigherOrderHostFiresWarning:
    def test_tet10_host_fires_per_target_warning(self) -> None:
        """A tet10 host in chain phase fires a UserWarning per target."""
        # Build FEMData: one tet10 host + one interior embedded node.
        # Use a regular tet with corners at unit-simplex + midsides at
        # edge centres so the interior node falls in the corner tet.
        corners = np.array(
            [
                [0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0], [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        midsides = np.array(
            [
                [0.5, 0.0, 0.0], [0.5, 0.5, 0.0], [0.0, 0.5, 0.0],
                [0.0, 0.0, 0.5], [0.0, 0.5, 0.5], [0.5, 0.0, 0.5],
            ],
            dtype=np.float64,
        )
        embed_xyz = np.array([[0.1, 0.1, 0.1]], dtype=np.float64)
        coords = np.vstack([corners, midsides, embed_xyz])
        node_ids = np.arange(1, coords.shape[0] + 1, dtype=np.int64)

        tet_info = make_type_info(
            code=11, gmsh_name="Tetrahedron 10", dim=3, order=2, npe=10,
            count=1,
        )
        tet_conn = np.array(
            [[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]], dtype=np.int64,
        )
        tet_ids = np.array([100], dtype=np.int64)
        tet_group = ElementGroup(
            element_type=tet_info, ids=tet_ids, connectivity=tet_conn,
        )

        elem_labels = {
            (3, 99): {
                "name": "concrete",
                "element_ids": tet_ids,
                "node_ids": np.arange(1, 11, dtype=np.int64),
                "node_coords": np.vstack([corners, midsides]),
            },
        }
        node_pgs = {
            (0, 7): {
                "name": "rebar",
                "node_ids": np.array([11], dtype=np.int64),
                "node_coords": embed_xyz,
            },
        }
        elements = ElementComposite(
            groups={11: tet_group},
            physical=PhysicalGroupSet({}),
            labels=LabelSet(elem_labels),
        )
        nodes = NodeComposite(
            node_ids=node_ids,
            node_coords=coords,
            physical=PhysicalGroupSet(node_pgs),
            labels=LabelSet({}),
        )
        info = MeshInfo(
            n_nodes=11, n_elems=1, bandwidth=1, types=[tet_info],
        )
        fem = FEMData(
            nodes=nodes, elements=elements, info=info,
            composed_from=ComposeSet(()),
        )
        defn = EmbeddedDef(
            master_label="concrete",
            slave_label="rebar",
            tolerance=1e-6,
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            new_fem = route_def_to_fem(fem, defn)
        assert new_fem is not None
        recs = list(new_fem.elements.constraints)
        assert len(recs) == 1

        user_warnings = [
            w for w in caught if issubclass(w.category, UserWarning)
        ]
        assert len(user_warnings) == 1
        msg = str(user_warnings[0].message)
        assert "concrete" in msg
        assert "tet10" in msg


# ---------------------------------------------------------------------
# Mixed-type host (hex + tet in same PG) decomposes correctly
# ---------------------------------------------------------------------


class TestMixedTypeHost:
    def test_hex_plus_tet_in_same_pg_produces_records(self) -> None:
        """Mixed hex+tet host PG decomposes to 7 tet sub-elements; the
        interior embedded node is coupled by the resolver to one of them."""
        # Start from the hex fixture and add a tet using existing corner
        # nodes 1,2,3,5 (these are 3 of the bottom-face corners + node 5
        # which is the top-front-left corner; this defines a tet
        # adjacent to the cube).  The interior embedded node remains at
        # (0.5, 0.5, 0.5) which is inside the cube.
        fem = _make_hex_with_embedded_node_fem()

        # Build a tet group via the existing node ids.
        tet_info = make_type_info(
            code=4, gmsh_name="Tetrahedron 4", dim=3, order=1, npe=4,
            count=1,
        )
        tet_conn = np.array([[1, 2, 3, 5]], dtype=np.int64)
        tet_ids = np.array([200], dtype=np.int64)
        tet_group = ElementGroup(
            element_type=tet_info, ids=tet_ids, connectivity=tet_conn,
        )
        # Append tet to the broker's element groups + update PG to
        # include both element ids under "soil".
        new_groups = dict(fem.elements._groups)
        new_groups[4] = tet_group
        new_labels = {
            (3, 99): {
                "name": "soil",
                "element_ids": np.array([100, 200], dtype=np.int64),
                "node_ids": np.arange(1, 9, dtype=np.int64),
                "node_coords": fem.nodes.coords[:8],
            },
        }
        new_elements = ElementComposite(
            groups=new_groups,
            physical=PhysicalGroupSet({}),
            labels=LabelSet(new_labels),
        )
        fem2 = FEMData(
            nodes=fem.nodes,
            elements=new_elements,
            info=fem.info,
            composed_from=ComposeSet(()),
        )
        defn = EmbeddedDef(
            master_label="soil",
            slave_label="rebar",
            tolerance=1e-6,
        )
        new_fem = route_def_to_fem(fem2, defn)
        assert new_fem is not None
        recs = list(new_fem.elements.constraints)
        assert len(recs) == 1


# ---------------------------------------------------------------------
# H5 round-trip — embedded constraint persists
# ---------------------------------------------------------------------


class TestH5RoundTrip:
    def test_embedded_record_persists_through_h5(
        self, tmp_path: Path,
    ) -> None:
        """After chain-phase routing, save + reload preserves the
        ``InterpolationRecord`` on ``elements.constraints``."""
        path = _save(_make_hex_with_embedded_node_fem(), tmp_path, "host.h5")
        g = apeGmsh.from_h5(path)
        g.constraints.embedded(
            host_label="soil", embedded_label="rebar", tolerance=1e-6,
            name="emb_h5",
        )

        out = tmp_path / "after.h5"
        g._fem.to_h5(str(out))

        # Reload as a fresh chain-phase session.
        g2 = apeGmsh.from_h5(out)
        recs = list(g2._fem.elements.constraints)
        assert len(recs) == 1
        rec = recs[0]
        assert isinstance(rec, InterpolationRecord)
        assert rec.kind == ConstraintKind.EMBEDDED
        assert rec.name == "emb_h5"
        assert rec.slave_node == 9


# ---------------------------------------------------------------------
# Build-phase EmbeddedDef behaviour unchanged (regression)
# ---------------------------------------------------------------------


class TestBuildPhaseUnchanged:
    def test_route_returns_none_in_build_phase_without_fem(self) -> None:
        """When ``session._fem is None``, ``try_chain_phase_route`` is
        a no-op (build phase keeps using the bump-counter pattern)."""

        class Stub:
            _fem = None

        defn = EmbeddedDef(
            master_label="a", slave_label="b", tolerance=1e-6,
        )
        assert try_chain_phase_route(Stub(), defn) is False
