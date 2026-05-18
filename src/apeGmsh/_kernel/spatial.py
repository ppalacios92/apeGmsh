"""apeGmsh._kernel.spatial — the one point-family spatial kernel.

selection-unification-v2 **P3-K** (behaviour-INVISIBLE relocation;
`docs/plans/selection-unification-v2.md` §6.2 P3-K +
`selection-unification-v2-p3k-execmap.md`).

Before P3-K the box / sphere / plane coordinate-mask math was a
**byte-identical** copy in each of the four legacy point chains
(`mesh/_node_chain.py:48-84`, `mesh/_elem_chain.py:124-160`,
`results/_result_chain.py:247-283`,
`mesh/_mesh_selection_chain.py:265-301` — verified char-for-char).
P3-K collapses `MeshSelection`'s `_delegate()` and lifts that one
shared kernel here, so the dedup is real (4 copies → 1) while the math
stays *exactly* what every chain computed.

Pure leaf: numpy + stdlib only (no ``apeGmsh.*`` import — keeps the
``_kernel`` import-DAG polarity; `mesh/_mesh_selection.py` already
carries the frozen ``("mesh","_kernel","mesh/_mesh_selection.py")``
BASELINE triple, so importing this adds no new edge).

Contract preserved verbatim from the legacy chains:

* ``box`` — half-open ``[lo, hi)`` by default (canonical, R4); closed
  ``[lo, hi]`` with ``inclusive=True`` (S2 parity);
* ``sphere`` — closed ball ``|c - center| <= radius``;
* ``plane`` — ``|(c - point) · n̂| <= tol``.

These return the boolean mask only.  The callers
(:class:`~apeGmsh.mesh._mesh_selection.MeshSelection`) keep the legacy
argument-validation + empty-atoms guard + ``_coords_of`` wrapper
verbatim and in the legacy order (radius/tol/normal validation *before*
the empty-atoms short-circuit), so behaviour — including the raise on a
bad ``radius``/``tol``/``normal`` for an empty selection — is
byte-identical to the pre-P3-K chains.  The element-centroid
``_coords_of`` source (and its fail-loud policy) stays per-engine in
``MeshSelection`` (the engines diverge — e.g. the live-mesh path skips
``n < 0`` connectivity padding); the ``_mesh_filters`` silent-row-0
centroid unification is a P3-R concern, not P3-K.
"""

from __future__ import annotations

import numpy as np


def box_mask(
    coords: np.ndarray, lo, hi, *, inclusive: bool
) -> np.ndarray:
    """``(N,)`` bool mask of rows of ``coords`` inside the box.

    Verbatim from the legacy chains' ``_spatial_box``: half-open
    ``[lo, hi)`` by default, closed ``[lo, hi]`` when ``inclusive``.
    """
    lo = np.asarray(lo, dtype=np.float64).reshape(3)
    hi = np.asarray(hi, dtype=np.float64).reshape(3)
    if inclusive:                       # closed [lo, hi]
        return np.all((coords >= lo) & (coords <= hi), axis=1)
    # half-open [lo, hi)  (canonical)
    return np.all((coords >= lo) & (coords < hi), axis=1)


def sphere_mask(
    coords: np.ndarray, center, radius: float
) -> np.ndarray:
    """``(N,)`` bool mask of rows within the closed ball.

    Verbatim from the legacy chains' ``_spatial_sphere`` (the
    ``radius < 0`` guard stays in the caller, in the legacy order).
    """
    ctr = np.asarray(center, dtype=np.float64).reshape(3)
    return np.linalg.norm(coords - ctr, axis=1) <= radius     # closed ball


def plane_mask(
    coords: np.ndarray, point, unit_normal: np.ndarray, tol: float
) -> np.ndarray:
    """``(N,)`` bool mask of rows within ``tol`` of the plane.

    ``unit_normal`` is the already-normalised normal (the caller keeps
    the legacy ``normal``-zero / ``tol < 0`` validation and normalises,
    in the legacy order, so the raises are byte-identical).  Mask math
    verbatim from the legacy chains' ``_spatial_plane``:
    ``|(c - point) · n̂| <= tol``.
    """
    p = np.asarray(point, dtype=np.float64).reshape(3)
    return np.abs((coords - p) @ unit_normal) <= tol
