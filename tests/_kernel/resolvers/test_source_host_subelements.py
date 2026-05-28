"""Phase 2 — FEMDataSource.host_subelements_for (Compose v1.1-A.2 / ADR 0041).

Tests the new element-side query on
:class:`apeGmsh._kernel.resolvers._source.FEMDataSource`.  Builds
in-memory :class:`FEMData` fixtures with hex / tet / mixed-type
element groups, then exercises the resolution path + delegation to
:func:`decompose_hosts_to_subelements`.

No gmsh, no openseespy, no file I/O — pure broker construction.
"""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from apeGmsh._kernel.geometry._host_decomposition import (
    HEX8_TO_6_TETS,
)
from apeGmsh._kernel.record_sets import ComposeSet
from apeGmsh._kernel.resolvers._source import FEMDataSource
from apeGmsh.mesh._element_types import make_type_info
from apeGmsh.mesh._group_set import LabelSet, PhysicalGroupSet
from apeGmsh.mesh.FEMData import (
    ElementComposite,
    FEMData,
    MeshInfo,
    NodeComposite,
)
from apeGmsh._kernel.payloads import ElementGroup


# ---------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------


def _make_hex_fem(
    *,
    host_label: str = "soil",
    host_pg_tag: int = 5,
    extra_groups: list[tuple[int, np.ndarray, np.ndarray]] | None = None,
) -> FEMData:
    """Build a FEMData with one hex8 element in physical group ``host_label``.

    Returns a broker carrying:

    * 8 nodes at the unit-cube corners.
    * One hex8 element (id 100) connecting nodes 1..8 in Gmsh order.
    * An element-side physical group with name ``host_label`` and the
      hex element id.
    * Optional extra element groups for mixed-type scenarios.
    """
    node_ids = np.arange(1, 9, dtype=np.int64)
    coords = np.array(
        [
            [0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0], [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0], [1.0, 0.0, 1.0],
            [1.0, 1.0, 1.0], [0.0, 1.0, 1.0],
        ],
        dtype=np.float64,
    )

    hex_info = make_type_info(
        code=5, gmsh_name="Hexahedron 8", dim=3, order=1, npe=8, count=1,
    )
    hex_conn = np.array([[1, 2, 3, 4, 5, 6, 7, 8]], dtype=np.int64)
    hex_ids = np.array([100], dtype=np.int64)
    hex_group = ElementGroup(
        element_type=hex_info,
        ids=hex_ids,
        connectivity=hex_conn,
    )

    groups: dict[int, ElementGroup] = {5: hex_group}
    types = [hex_info]
    all_ids = list(hex_ids)
    if extra_groups:
        for code, ids, conn in extra_groups:
            type_info = make_type_info(
                code=code,
                gmsh_name={4: "Tetrahedron 4", 2: "Triangle 3"}.get(
                    code, f"etype-{code}",
                ),
                dim={4: 3, 2: 2, 5: 3}[code],
                order=1,
                npe={4: 4, 2: 3, 5: 8}[code],
                count=ids.size,
            )
            groups[code] = ElementGroup(
                element_type=type_info,
                ids=np.asarray(ids, dtype=np.int64),
                connectivity=np.asarray(conn, dtype=np.int64),
            )
            types.append(type_info)
            all_ids.extend(list(np.asarray(ids, dtype=np.int64)))

    elem_pgs = {
        (3, host_pg_tag): {
            "name": host_label,
            "element_ids": np.array(all_ids, dtype=np.int64),
            "node_ids": node_ids,
            "node_coords": coords,
        },
    }
    elements = ElementComposite(
        groups=groups,
        physical=PhysicalGroupSet(elem_pgs),
        labels=LabelSet({}),
    )
    nodes = NodeComposite(
        node_ids=node_ids,
        node_coords=coords,
        physical=PhysicalGroupSet({}),
        labels=LabelSet({}),
    )
    info = MeshInfo(
        n_nodes=node_ids.size,
        n_elems=len(all_ids),
        bandwidth=1,
        types=types,
    )
    return FEMData(
        nodes=nodes,
        elements=elements,
        info=info,
        composed_from=ComposeSet(()),
    )


# ---------------------------------------------------------------------
# Basic happy-path resolution
# ---------------------------------------------------------------------


class TestHostSubelementsHexPG:
    def test_resolves_hex_pg_to_six_tets(self) -> None:
        fem = _make_hex_fem(host_label="soil")
        src = FEMDataSource(fem)

        out = src.host_subelements_for("soil")
        assert out.shape == (6, 4)
        # Same Kuhn decomposition as the build path: each row picks
        # 4 nodes per ``HEX8_TO_6_TETS`` from the hex's connectivity.
        hex_conn = np.array([1, 2, 3, 4, 5, 6, 7, 8], dtype=int)
        for i, tet_idx in enumerate(HEX8_TO_6_TETS):
            np.testing.assert_array_equal(out[i], hex_conn[tet_idx])

    def test_unknown_target_raises_key_error(self) -> None:
        fem = _make_hex_fem()
        src = FEMDataSource(fem)
        with pytest.raises(KeyError, match="resolves to neither"):
            src.host_subelements_for("not_a_label")


# ---------------------------------------------------------------------
# Mixed-type host PG (hex + tet) - both decompose to 3D
# ---------------------------------------------------------------------


class TestHostSubelementsMixedType:
    def test_hex_plus_tet_aggregate_to_3d_rows(self) -> None:
        """A PG containing both hex and tet elements yields tet rows
        from both, vstacked (6 from hex + 1 from tet = 7)."""
        # Add a tet4 element using existing nodes 1, 2, 3, 5.
        tet_conn = np.array([[1, 2, 3, 5]], dtype=np.int64)
        tet_ids = np.array([200], dtype=np.int64)
        fem = _make_hex_fem(
            host_label="soil",
            extra_groups=[(4, tet_ids, tet_conn)],
        )
        src = FEMDataSource(fem)
        out = src.host_subelements_for("soil")
        assert out.shape == (7, 4)
        # Last row should be the tet's connectivity (in iteration order
        # of ``fem.elements._groups`` — dict-insertion-ordered, hex
        # first then tet, but the decompose function iterates groups
        # in passed order; verify both tet rows are present).
        rows = {tuple(int(x) for x in row) for row in out}
        assert (1, 2, 3, 5) in rows
        # All 6 hex Kuhn tets must also be present.
        hex_conn = np.array([1, 2, 3, 4, 5, 6, 7, 8], dtype=int)
        for tet_idx in HEX8_TO_6_TETS:
            assert tuple(hex_conn[tet_idx]) in rows


# ---------------------------------------------------------------------
# Higher-order host triggers per-(etype, target) warning
# ---------------------------------------------------------------------


class TestHigherOrderHostWarning:
    def test_tet10_emits_warning_once_per_target(self) -> None:
        """tet10 host fires a UserWarning once per call, mentioning the target."""
        # Build a FEMData with one tet10 element.
        node_ids = np.arange(1, 11, dtype=np.int64)
        coords = np.zeros((10, 3), dtype=np.float64)
        # Position corner nodes; midsides are placeholder for the
        # resolver but ``host_subelements_for`` itself doesn't read
        # coords — only connectivity.
        tet_info = make_type_info(
            code=11, gmsh_name="Tetrahedron 10", dim=3, order=2, npe=10,
            count=1,
        )
        tet_conn = np.array(
            [[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]], dtype=np.int64,
        )
        tet_ids = np.array([300], dtype=np.int64)
        tet_group = ElementGroup(
            element_type=tet_info,
            ids=tet_ids,
            connectivity=tet_conn,
        )
        elements = ElementComposite(
            groups={11: tet_group},
            physical=PhysicalGroupSet({
                (3, 7): {
                    "name": "concrete",
                    "element_ids": tet_ids,
                    "node_ids": node_ids,
                    "node_coords": coords,
                },
            }),
            labels=LabelSet({}),
        )
        nodes = NodeComposite(
            node_ids=node_ids,
            node_coords=coords,
            physical=PhysicalGroupSet({}),
            labels=LabelSet({}),
        )
        info = MeshInfo(
            n_nodes=10, n_elems=1, bandwidth=1, types=[tet_info],
        )
        fem = FEMData(
            nodes=nodes, elements=elements, info=info,
            composed_from=ComposeSet(()),
        )

        src = FEMDataSource(fem)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out = src.host_subelements_for("concrete")
        assert out.shape == (1, 4)
        # Corner-only fallback: first 4 nodes of the tet10.
        np.testing.assert_array_equal(out[0], [1, 2, 3, 4])

        user_warnings = [
            w for w in caught if issubclass(w.category, UserWarning)
        ]
        # Exactly one warning, naming the target label.
        assert len(user_warnings) == 1
        assert "concrete" in str(user_warnings[0].message)
        assert "tet10" in str(user_warnings[0].message)


# ---------------------------------------------------------------------
# Element-side label resolution (Tier 1)
# ---------------------------------------------------------------------


class TestLabelResolution:
    def test_element_side_label_resolves(self) -> None:
        """A Tier 1 element-side label resolves identically to a PG."""
        fem = _make_hex_fem(host_label="ignored")
        # Replace the PG with a Tier 1 label.  The key is the
        # ``(dim, tag)`` tuple per :class:`LabelSet` schema; the
        # required ``node_ids`` / ``node_coords`` describe the nodes
        # this label covers (unused by host_subelements_for but
        # required by the schema).
        labels = LabelSet({
            (3, 99): {
                "name": "soil",
                "element_ids": np.array([100], dtype=np.int64),
                "node_ids": fem.nodes.ids,
                "node_coords": fem.nodes.coords,
            },
        })
        new_elements = ElementComposite(
            groups=fem.elements._groups,
            physical=PhysicalGroupSet({}),
            labels=labels,
        )
        new_fem = FEMData(
            nodes=fem.nodes,
            elements=new_elements,
            info=fem.info,
            composed_from=ComposeSet(()),
        )
        src = FEMDataSource(new_fem)
        out = src.host_subelements_for("soil")
        assert out.shape == (6, 4)
