"""MT-2 (ADR 0062) — equivalent nodal-force build + resolver.

The decisive physics invariant: the equivalent nodal forces must have
**zero net force** and a **first moment that recovers M**
(``Σ_a x_a ⊗ F_a = M``) — this is the discrete representation theorem and
holds for both the consistent and dipole methods.
"""
from __future__ import annotations

import numpy as np
import pytest

from apeGmsh._kernel.geometry._inverse_map import _HEX8_SIGNS
from apeGmsh._kernel.geometry._moment_tensor import (
    consistent_nodal_forces,
    dipole_nodal_forces,
    moment_tensor,
    shape_gradient_phys,
    unit_moment_tensor,
)
from apeGmsh._kernel.resolvers._moment_tensor import (
    resolve_moment_tensor_source,
)


def _cube(origin=(0.0, 0.0, 0.0), h=2.0):
    """hex8 corner coords (gmsh order) for an axis-aligned cube."""
    o = np.asarray(origin, dtype=float)
    return o + (np.asarray(_HEX8_SIGNS) * 0.5 + 0.5) * h


def _first_moment(coords, forces):
    """``Σ_a x_a ⊗ F_a`` over the supplied nodes (centered at centroid)."""
    coords = np.asarray(coords, dtype=float)
    forces = np.asarray(forces, dtype=float)
    ndm = forces.shape[1]
    c = coords[:, :ndm] - coords[:, :ndm].mean(axis=0)
    return c.T @ forces


# --- shape_gradient_phys --------------------------------------------------

def test_shape_gradient_unit_cube_is_reference_gradient():
    """On a [-1,1]³ cube, J = I, so ∂N/∂x == ∂N/∂ξ."""
    X = np.asarray(_HEX8_SIGNS, dtype=float)  # cube [-1,1]³
    grad = shape_gradient_phys("hex8", X, np.zeros(3))
    # partition of unity: Σ_a ∂N_a/∂x = 0
    assert np.allclose(grad.sum(axis=0), 0.0, atol=1e-13)


def test_shape_gradient_reproduces_linear_field():
    """Σ_a x_a · ∂N_a/∂x = I (an isoparametric completeness check)."""
    X = _cube(origin=(3.0, -1.0, 5.0), h=4.0)
    grad = shape_gradient_phys("hex8", X, np.array([0.2, -0.3, 0.1]))
    assert np.allclose(X.T @ grad, np.eye(3), atol=1e-12)


def test_shape_gradient_singular_host_fails_loud():
    X = np.asarray(_HEX8_SIGNS, dtype=float).copy()
    X[:, 2] = 0.0  # flatten z → degenerate
    with pytest.raises(ValueError, match="degenerate / singular"):
        shape_gradient_phys("hex8", X, np.zeros(3))


# --- consistent_nodal_forces ---------------------------------------------

@pytest.mark.parametrize(
    "strike,dip,rake", [(350, 40, 113), (0, 90, 0), (30, 45, 90)]
)
def test_consistent_forces_recover_moment_tensor(strike, dip, rake):
    """First moment of the consistent forces == M; net force == 0."""
    M = moment_tensor(strike=strike, dip=dip, rake=rake, M0=1.5e15, frame="z-up")
    X = _cube(origin=(2.0, 2.0, -10.0), h=3.0)
    xi = np.array([0.1, -0.2, 0.05])
    F = consistent_nodal_forces(M, X, "hex8", xi)
    scale = np.abs(F).max()
    assert np.allclose(F.sum(axis=0), 0.0, atol=1e-9 * scale)      # net force 0
    assert np.allclose(_first_moment(X, F), M, rtol=1e-9, atol=1)  # recovers M


def test_consistent_forces_tet4():
    """The simplex path (constant gradient) also recovers M."""
    M = moment_tensor(strike=10, dip=60, rake=20, M0=1.0, frame="z-down")
    X = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    )
    F = consistent_nodal_forces(M, X, "tet4", np.array([0.25, 0.25, 0.25]))
    assert np.allclose(F.sum(axis=0), 0.0, atol=1e-12)
    assert np.allclose(_first_moment(X, F), M, atol=1e-10)


# --- resolver: consistent -------------------------------------------------

def test_resolver_consistent_single_host():
    M = moment_tensor(strike=350, dip=40, rake=113, M0=2.0e15, frame="z-up")
    X = _cube(origin=(0.0, 0.0, -5.0), h=4.0)
    host_ids = [[11, 12, 13, 14, 15, 16, 17, 18]]
    pairs = resolve_moment_tensor_source(
        position=X.mean(axis=0),
        M=M,
        method="consistent",
        host_node_ids=host_ids,
        host_node_coords=[X],
        host_kinds=["hex8"],
    )
    nodes = [n for n, _ in pairs]
    forces = np.vstack([f for _, f in pairs])
    assert nodes == sorted(host_ids[0])
    assert np.allclose(forces.sum(axis=0), 0.0, atol=1e-9 * np.abs(forces).max())
    # recover M from the (node→force) map
    coord_of = dict(zip(host_ids[0], X))
    fm = _first_moment([coord_of[n] for n in nodes], forces)
    assert np.allclose(fm, M, rtol=1e-9, atol=1)


def test_resolver_point_outside_continuum_fails_loud():
    X = _cube(origin=(0.0, 0.0, 0.0), h=2.0)
    M = unit_moment_tensor(strike=0, dip=90, rake=0)
    with pytest.raises(ValueError, match="outside every host"):
        resolve_moment_tensor_source(
            position=np.array([100.0, 100.0, 100.0]),
            M=M,
            method="consistent",
            host_node_ids=[[1, 2, 3, 4, 5, 6, 7, 8]],
            host_node_coords=[X],
            host_kinds=["hex8"],
        )


# --- resolver: dipole -----------------------------------------------------

def _structured_grid(n=3, h=1.0):
    """(node_ids, node_coords) for an n×n×n structured grid, 1-based ids."""
    pts = []
    for k in range(n):
        for j in range(n):
            for i in range(n):
                pts.append((i * h, j * h, k * h))
    coords = np.asarray(pts, dtype=float)
    ids = np.arange(1, len(pts) + 1)
    return ids, coords


def test_resolver_dipole_recovers_moment_tensor():
    """Dipole on a structured grid: first moment of the couples == M."""
    M = moment_tensor(strike=30, dip=45, rake=90, M0=1.0, frame="z-up")
    ids, coords = _structured_grid(n=3, h=2.0)
    center = np.array([2.0, 2.0, 2.0])  # the interior node of a 3³ grid
    pairs = resolve_moment_tensor_source(
        position=center,
        M=M,
        method="dipole",
        host_node_ids=[],
        host_node_coords=[],
        host_kinds=["hex8"],          # only used to infer ndm
        node_ids=ids,
        node_coords=coords,
    )
    nodes = [n for n, _ in pairs]
    forces = np.vstack([f for _, f in pairs])
    coord_of = dict(zip(ids.tolist(), coords))
    assert np.allclose(forces.sum(axis=0), 0.0, atol=1e-12)  # net force 0
    fm = _first_moment([coord_of[n] for n in nodes], forces)
    assert np.allclose(fm, M, atol=1e-10)                    # recovers M


def test_dipole_nodal_forces_zero_net_on_graded_spacing():
    """Compensating-arm couple: net force 0 + first moment M even when
    the ± neighbour spacings differ (graded grid, hp != hm)."""
    M = moment_tensor(strike=30, dip=45, rake=90, M0=1.0, frame="z-up")
    plus = np.array([1.0, 1.0, 1.0])
    minus = np.array([2.0, 0.5, 1.5])          # asymmetric arms
    fp, fm = dipole_nodal_forces(M, plus_spacings=plus, minus_spacings=minus)
    # net force exactly zero
    assert np.allclose(fp.sum(axis=0) + fm.sum(axis=0), 0.0, atol=1e-13)
    # first moment Σ x⊗f over the 6 neighbours recovers M
    fmnt = np.zeros((3, 3))
    for j in range(3):
        fmnt += np.outer(plus[j] * np.eye(3)[j], fp[j])
        fmnt += np.outer(-minus[j] * np.eye(3)[j], fm[j])
    assert np.allclose(fmnt, M, atol=1e-12)


def test_resolver_dipole_graded_grid_recovers_moment_tensor():
    """End-to-end resolver dipole on a grid graded along x (hp != hm at the
    interior node) — net force 0, first moment M, no spurious raise."""
    M = moment_tensor(strike=350, dip=40, rake=113, M0=1.0, frame="z-up")
    # x stations graded (0, 1, 3), y/z uniform (0, 2, 4)
    xs, ys, zs = [0.0, 1.0, 3.0], [0.0, 2.0, 4.0], [0.0, 2.0, 4.0]
    pts, ids, k = [], [], 1
    id_map = {}
    for z in zs:
        for y in ys:
            for x in xs:
                pts.append((x, y, z))
                ids.append(k)
                id_map[k] = (x, y, z)
                k += 1
    coords = np.asarray(pts)
    ids = np.asarray(ids)
    center = np.array([1.0, 2.0, 2.0])         # interior node, hp=2 hm=1 on x
    pairs = resolve_moment_tensor_source(
        position=center, M=M, method="dipole",
        host_node_ids=[], host_node_coords=[], host_kinds=["hex8"],
        node_ids=ids, node_coords=coords,
    )
    nodes = [n for n, _ in pairs]
    forces = np.vstack([f for _, f in pairs])
    assert np.allclose(forces.sum(axis=0), 0.0, atol=1e-12)
    fm = _first_moment([id_map[n] for n in nodes], forces)
    assert np.allclose(fm, M, atol=1e-10)


def test_resolver_dipole_missing_neighbour_fails_loud():
    M = unit_moment_tensor(strike=0, dip=90, rake=0)
    ids, coords = _structured_grid(n=3, h=1.0)
    corner = np.array([0.0, 0.0, 0.0])  # a corner node has no - neighbours
    with pytest.raises(ValueError, match="neighbour on axis"):
        resolve_moment_tensor_source(
            position=corner,
            M=M,
            method="dipole",
            host_node_ids=[],
            host_node_coords=[],
            host_kinds=["hex8"],
            node_ids=ids,
            node_coords=coords,
        )
