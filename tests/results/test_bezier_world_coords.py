"""B4 — Bézier Gauss-point world-coordinate reconstruction via ``_basis``.

A ``.ladruno`` from a Bézier element (``BezierTri6`` / ``BezierTet10``) is
self-describing: each GP carries its parametric coordinate in
``QUADRATURE/GP_PARAM`` and the element declares ``FAMILY="bernstein"``.
``GaussSlab.global_coords(fem)`` now reconstructs the **world** coordinate
``x = B(ξ)·X`` over all control points via the neutral
:func:`apeGmsh._basis.basis_values` — instead of the centroid+bbox
approximation the linear Gmsh shape-function catalog falls back to for
these higher-order families.

Fork-free: reads the committed fork fixtures. ξ always comes from the
file's ``GP_PARAM`` (never a catalog GP order — the Bézier plan's Tri6
GP-index caveat).
"""
from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

from apeGmsh.results._gauss_world_coords import _bezier_basis_spec
from apeGmsh.results.readers._ladruno import LadrunoReader

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ladruno"
TRI6 = FIXTURES / "bezier_tri6.ladruno"
TET10 = FIXTURES / "bezier_tet10.ladruno"


# =====================================================================
# Routing helper
# =====================================================================

def test_bezier_basis_spec_recognises_families() -> None:
    class _ET:
        def __init__(self, name: str) -> None:
            self.gmsh_name = name

    assert _bezier_basis_spec(_ET("BezierTri6")) == ("tri", "bernstein")
    assert _bezier_basis_spec(_ET("BezierTet10")) == ("tet", "bernstein")
    # Non-Bézier elements are NOT routed through the bernstein basis.
    assert _bezier_basis_spec(_ET("SixNodeTri")) is None
    assert _bezier_basis_spec(_ET("TenNodeTetrahedron")) is None
    assert _bezier_basis_spec(_ET("")) is None


# =====================================================================
# Tri6 — reconstruct against an independent affine-barycentric corner map
# =====================================================================

def test_tri6_world_coords_match_affine_corner_map() -> None:
    with LadrunoReader(TRI6) as r:
        fem = r.fem()
        slab = r.read_gauss("stage_0", "stress_xx")
        world = slab.global_coords(fem)

        # ξ is the file's GP_PARAM (3 GPs × 2 free area coords).
        xi = slab.natural_coords
        assert xi.shape == (3, 2)

        # Independent ground truth: on this straight-sided (affine) element
        # the GP world coord is the barycentric blend of the 3 CORNER nodes
        # (a different formula from the Bernstein basis used internally).
        ids = np.asarray(fem.nodes.ids)
        coords = np.asarray(fem.nodes.coords)
        id_to_coord = {int(i): coords[k] for k, i in enumerate(ids)}
        conn = fem.elements.connectivity[0]  # 6 control points of element 1
        corners = np.array([id_to_coord[int(n)] for n in conn[:3]])

        expected = np.empty((3, 3))
        for i, (l2, l3) in enumerate(xi):
            l1 = 1.0 - l2 - l3
            expected[i] = l1 * corners[0] + l2 * corners[1] + l3 * corners[2]

        np.testing.assert_allclose(world, expected, atol=1e-12)


def test_tri6_world_coords_differ_from_bbox_fallback() -> None:
    # The reconstruction must actually replace the bbox approximation — on
    # this element they differ by a large amount.
    from apeGmsh.results._gauss_world_coords import _world_via_bbox

    with LadrunoReader(TRI6) as r:
        fem = r.fem()
        slab = r.read_gauss("stage_0", "stress_xx")
        world = slab.global_coords(fem)

        ids = np.asarray(fem.nodes.ids)
        coords = np.asarray(fem.nodes.coords)
        id_to_coord = {int(i): coords[k] for k, i in enumerate(ids)}
        x_ctrl = np.array(
            [id_to_coord[int(n)] for n in fem.elements.connectivity[0]]
        )
        bbox = np.array([
            _world_via_bbox(slab.natural_coords[i], x_ctrl) for i in range(3)
        ])
        assert np.max(np.abs(world - bbox)) > 0.1


# =====================================================================
# Tet10 — reconstruct against the file's own GLOBAL_GP_COORDS
# =====================================================================

def test_tet10_world_coords_match_file_global_gp_coords() -> None:
    with LadrunoReader(TET10) as r:
        fem = r.fem()
        slab = r.read_gauss("stage_0", "stress_xx")
        world = slab.global_coords(fem)
        assert slab.natural_coords.shape == (4, 3)  # 4 GPs × 3 free bary

    # The fork writes GLOBAL_GP_COORDS for the tet — the element's own GP
    # world coords, an independent oracle for B(ξ)·X.
    with h5py.File(TET10, "r") as f:
        grp = f["MODEL_STAGE[1]/MODEL/ELEMENTS/33001-BezierTet10[1000:1]"]
        ggc = np.asarray(grp["GLOBAL_GP_COORDS"][...]).reshape(-1, 3)

    np.testing.assert_allclose(world, ggc, atol=1e-10)
