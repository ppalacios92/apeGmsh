"""Moment-tensor source resolver — point → host → nodal forces (MT-2).

The orchestration half of ADR 0062: given a seismic moment tensor ``M``
(already in the mesh frame; built by
:mod:`apeGmsh._kernel.geometry._moment_tensor`) and a source point, find
the host continuum element (or nearest grid node) and turn the
representation-theorem body force into **nodal load** contributions.

Two methods, both mesh-objective:

* ``"consistent"`` — locate the host element, evaluate ``∂N/∂x`` at the
  source point, emit ``F^a = M·∇N_a`` on the host's corner nodes. Exact
  and works on any solid mesh.
* ``"dipole"`` — place the source at the nearest mesh node and apply
  force-dipoles on its ±axis neighbours. Trivial on a structured grid;
  the validation fallback.

Mirrors the reinforcement resolver
(:func:`apeGmsh._kernel.resolvers._reinforce.resolve_reinforce`): the
caller assembles per-host node ids / coords / kinds; this module is pure
NumPy with no Gmsh / OpenSees imports.
"""
from __future__ import annotations

import numpy as np
from numpy import ndarray

from apeGmsh._kernel.geometry._inverse_map import HOST_KINDS, locate_point
from apeGmsh._kernel.geometry._moment_tensor import (
    consistent_nodal_forces,
    dipole_nodal_forces,
)


__all__ = ["resolve_moment_tensor_source", "NET_FORCE_TOL"]

#: Tolerance (fraction of the largest nodal force magnitude) for the
#: net-force-zero invariant a physical seismic source must satisfy.
NET_FORCE_TOL = 1e-9


def _accumulate(
    out: dict[int, ndarray], node: int, force: ndarray, ndm: int,
) -> None:
    f3 = np.zeros(3)
    f3[:ndm] = force[:ndm]
    if node in out:
        out[node] = out[node] + f3
    else:
        out[node] = f3


def _assert_net_force_zero(out: dict[int, ndarray], where: str) -> None:
    if not out:
        return
    net = np.sum(np.vstack(list(out.values())), axis=0)
    scale = max(
        float(np.linalg.norm(f)) for f in out.values()
    ) or 1.0
    if float(np.linalg.norm(net)) > NET_FORCE_TOL * scale:
        raise ValueError(
            f"resolve_moment_tensor_source: net nodal force {net.tolist()} "
            f"is not zero ({where}) — a physical seismic source carries no "
            f"net force. This signals a frame / winding bug."
        )


def _find_axis_neighbours(
    center: ndarray,
    node_ids: ndarray,
    node_coords: ndarray,
    ndm: int,
    *,
    align_tol: float,
) -> tuple[list[int], list[float], list[int], list[float]]:
    """Nearest ±axis neighbour of *center* along each of ``ndm`` axes.

    A neighbour along axis ``j`` shares the other coordinates (within
    ``align_tol``) and differs only in ``x_j``; the nearest one on each
    side is taken. Returns ``(plus_ids, plus_h, minus_ids, minus_h)``.
    Fails loud if any side is missing (the dipole needs all 2·ndm).
    """
    plus_ids: list[int] = []
    plus_h: list[float] = []
    minus_ids: list[int] = []
    minus_h: list[float] = []
    for j in range(ndm):
        other = [k for k in range(ndm) if k != j]
        d = node_coords[:, :ndm] - center[:ndm]
        aligned = np.all(np.abs(d[:, other]) <= align_tol, axis=1)
        dj = d[:, j]
        plus_mask = aligned & (dj > align_tol)
        minus_mask = aligned & (dj < -align_tol)
        if not plus_mask.any() or not minus_mask.any():
            raise ValueError(
                f"resolve_moment_tensor_source: dipole method needs a ±"
                f"neighbour on axis {j} of the source node, but one side is "
                f"missing — the source must sit on an interior structured-"
                f"grid node. Use method='consistent' for an unstructured "
                f"mesh."
            )
        pi = int(np.argmin(np.where(plus_mask, dj, np.inf)))
        mi = int(np.argmax(np.where(minus_mask, dj, -np.inf)))
        plus_ids.append(int(node_ids[pi]))
        plus_h.append(float(dj[pi]))
        minus_ids.append(int(node_ids[mi]))
        minus_h.append(float(-dj[mi]))
    return plus_ids, plus_h, minus_ids, minus_h


def resolve_moment_tensor_source(
    *,
    position: ndarray,
    M: ndarray,
    method: str,
    host_node_ids: list[list[int]],
    host_node_coords: list[ndarray],
    host_kinds: list[str],
    node_ids: ndarray | None = None,
    node_coords: ndarray | None = None,
    tolerance: float = 1e-6,
    snap: bool = False,
    label: str = "",
) -> list[tuple[int, ndarray]]:
    """Resolve one moment-tensor source into ``(node_tag, force_xyz)`` pairs.

    Parameters
    ----------
    position
        Source point in mesh coordinates, shape ``(ndm,)`` or ``(3,)``.
    M
        Moment tensor (3×3, **mesh frame** — already frame-mapped and
        ``M0``-scaled by :func:`apeGmsh._kernel.geometry._moment_tensor.moment_tensor`).
    method
        ``"consistent"`` (host ``∂N/∂x``) or ``"dipole"`` (±neighbour
        couples).
    host_node_ids, host_node_coords, host_kinds
        Per host continuum element: corner node tags, ``(n_corner, ≥ndm)``
        coords, and inverse-map kind (``"hex8"`` / ``"tet4"`` / ``"quad4"``
        / ``"tri3"``). For ``"consistent"``.
    node_ids, node_coords
        All mesh nodes (parallel ``ids`` + ``(N, ≥ndm)`` coords). Required
        for ``"dipole"`` (it searches the global node cloud for axis
        neighbours); ignored for ``"consistent"``.
    tolerance, snap
        Inverse-map out-of-bounds policy — reject-by-default (the source
        is outside the continuum), opt-in snap.

    Returns the accumulated ``(node_tag, force)`` list (force padded to 3
    components), sorted by node tag. The net force is asserted zero.
    """
    if method not in ("consistent", "dipole"):
        raise ValueError(
            f"resolve_moment_tensor_source: method must be 'consistent' or "
            f"'dipole', got {method!r}."
        )
    pos = np.asarray(position, dtype=float)
    out: dict[int, ndarray] = {}

    if method == "consistent":
        res = locate_point(
            pos, host_node_coords, host_kinds,
            tol=tolerance, snap=snap, label=label,
        )
        kind = host_kinds[res.host_index]
        ndm = HOST_KINDS[kind][1]
        X = np.asarray(host_node_coords[res.host_index], dtype=float)
        host = host_node_ids[res.host_index]
        forces = consistent_nodal_forces(M, X, kind, res.xi)  # (n_nodes, ndm)
        if len(host) != forces.shape[0]:
            raise ValueError(
                f"resolve_moment_tensor_source: host element "
                f"{res.host_index} has {len(host)} nodes but the {kind} "
                f"force build produced {forces.shape[0]} rows."
            )
        for nid, f in zip(host, forces):
            _accumulate(out, int(nid), f, ndm)
    else:  # dipole
        if node_ids is None or node_coords is None:
            raise ValueError(
                "resolve_moment_tensor_source: method='dipole' needs "
                "node_ids + node_coords (the global node cloud) to find "
                "axis neighbours."
            )
        node_ids = np.asarray(node_ids)
        node_coords = np.asarray(node_coords, dtype=float)
        # Infer ndm from the supplied host kinds (the model dimension);
        # default to 3 when no hosts were passed.
        ndm = HOST_KINDS[host_kinds[0]][1] if host_kinds else 3
        # nearest node to the source point
        d = np.linalg.norm(node_coords[:, :ndm] - pos[:ndm], axis=1)
        center_i = int(np.argmin(d))
        center = node_coords[center_i]
        # characteristic spacing for the alignment tolerance
        span = float(
            np.linalg.norm(node_coords[:, :ndm].max(axis=0)
                           - node_coords[:, :ndm].min(axis=0))
        ) or 1.0
        align_tol = 1e-6 * span
        plus_ids, plus_h, minus_ids, minus_h = _find_axis_neighbours(
            center, node_ids, node_coords, ndm, align_tol=align_tol,
        )
        fp, fm = dipole_nodal_forces(
            M,
            plus_spacings=np.asarray(plus_h),
            minus_spacings=np.asarray(minus_h),
        )
        for j in range(ndm):
            _accumulate(out, plus_ids[j], fp[j], ndm)
            _accumulate(out, minus_ids[j], fm[j], ndm)

    _assert_net_force_zero(out, where=f"method={method!r}")
    return [(nid, out[nid]) for nid in sorted(out)]
