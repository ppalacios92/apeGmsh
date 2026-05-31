"""Selection-frustum geometry — ADR 0045 S5-box.

A box-drag on screen sweeps a 3D *frustum* (a truncated pyramid) through
the scene. Testing each entity's points against the frustum's six bounding
planes is exact in 3D, where the legacy path projected points to 2D and
tested a screen-space box — which over-selects at angled views (the 3D AABB
corners of a curve/surface project to a rectangle much wider than the
silhouette) and ignores near/far clipping.

This module is pure NumPy: it turns the eight world-space frustum corners
(the four screen-box corners un-projected at the near and far clip depths)
into six inward-facing planes, and tests points against them. The renderer-
dependent un-projection lives in the pick engine; everything here is
headless-testable and doubles as the parity oracle for the box-select.
"""
from __future__ import annotations

import numpy as np

# Corner ordering for one quad (near or far), counter-clockwise looking
# along the view direction: bottom-left, bottom-right, top-right, top-left.
#   3 --- 2
#   |     |
#   0 --- 1


def _plane_through(a: np.ndarray, b: np.ndarray, c: np.ndarray,
                   inside: np.ndarray) -> np.ndarray:
    """Plane ``[nx, ny, nz, d]`` through points a, b, c, with the normal
    oriented so *inside* satisfies ``n . p + d >= 0``."""
    n = np.cross(b - a, c - a)
    norm = np.linalg.norm(n)
    if norm == 0.0:
        # Degenerate (collinear) corners — return a plane that admits
        # everything so a flat/zero-area box never spuriously rejects.
        return np.array([0.0, 0.0, 0.0, 1.0])
    n = n / norm
    d = -float(np.dot(n, a))
    # Flip so the interior reference point is on the non-negative side.
    if np.dot(n, inside) + d < 0:
        n, d = -n, -d
    return np.array([n[0], n[1], n[2], d])


def frustum_planes(near: np.ndarray, far: np.ndarray) -> np.ndarray:
    """Six inward planes of the frustum, as a ``(6, 4)`` array.

    Parameters
    ----------
    near, far
        ``(4, 3)`` world-space corners of the near and far quads, each in
        the CCW order [bottom-left, bottom-right, top-right, top-left]
        (the four screen-box corners un-projected at clip depth 0 and 1).

    A point is inside the frustum iff ``planes[:, :3] @ p + planes[:, 3]``
    is ``>= 0`` for all six rows.
    """
    near = np.asarray(near, dtype=float)
    far = np.asarray(far, dtype=float)
    centroid = (near.mean(axis=0) + far.mean(axis=0)) * 0.5
    nbl, nbr, ntr, ntl = near
    fbl, fbr, ftr, ftl = far
    planes = np.array([
        _plane_through(nbl, nbr, ntr, centroid),     # near
        _plane_through(fbr, fbl, ftl, centroid),     # far
        _plane_through(nbl, ntl, ftl, centroid),     # left
        _plane_through(nbr, fbr, ftr, centroid),     # right
        _plane_through(ntl, ntr, ftr, centroid),     # top
        _plane_through(nbl, fbl, fbr, centroid),     # bottom
    ])
    return planes


def points_inside_frustum(planes: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Boolean mask of which ``pts`` (``(N, 3)``) lie inside the frustum.

    A point is inside iff it is on the non-negative side of every plane
    (with a tiny tolerance so points exactly on a face count as inside)."""
    pts = np.atleast_2d(np.asarray(pts, dtype=float))
    # signed distance to each plane: (N, 6)
    dist = pts @ planes[:, :3].T + planes[:, 3]
    return np.all(dist >= -1e-9, axis=1)


def entity_in_frustum(planes: np.ndarray, pts: np.ndarray,
                      crossing: bool) -> bool:
    """Box-select containment for one entity's sample points.

    Window mode (``crossing=False``): every point inside the frustum.
    Crossing mode (``crossing=True``): any point inside the frustum.
    """
    inside = points_inside_frustum(planes, pts)
    if crossing:
        return bool(np.any(inside))
    return bool(np.all(inside)) if len(inside) else False


__all__ = ["frustum_planes", "points_inside_frustum", "entity_in_frustum"]
