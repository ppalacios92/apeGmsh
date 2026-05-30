"""Canonical bounding-box value type — ADR 0045 §Decision Part 1.

INV-2 (ADR 0045): there is exactly **one** bounding-box value type.
Every 8-corner and 6-tuple consumer *derives* from it; no
``np.tile(centroid, (8, 1))`` centroid-tile, no projected-AABB stored as
truth. The frame is **world**, always — ``origin_shift`` is applied at
projection time by a backend, never baked into ``min`` / ``max`` — which
ends the shifted-vs-world disagreement among the six notions this type
replaces (``EntityRegistry._bboxes``, the degenerate tile fallback,
``entity_points``, BREP ``instance.bbox``, ``_world_bbox``,
``_compute_model_diagonal``).

INV-1 (ADR 0042, extended by ADR 0045): imports neither ``vtk`` nor
``pyvista``. Enforced by ``tests/test_scene_ir_pure.py`` (which walks
every file under ``scene_ir/``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass(frozen=True, eq=False)
class BBox:
    """An axis-aligned bounding box in the world frame.

    ``min`` / ``max`` are coerced to ``(3,)`` C-contiguous ``float64``
    and validated (``min <= max`` component-wise) at construction — an
    inverted or mis-shaped box fails loud rather than producing silent
    garbage downstream. ``eq=False`` because the fields are arrays (the
    auto ``__eq__`` would raise on the ambiguous array truth value);
    tests compare ``.min`` / ``.max`` explicitly.
    """

    min: np.ndarray
    max: np.ndarray

    def __post_init__(self) -> None:
        lo = np.ascontiguousarray(self.min, dtype=np.float64).reshape(-1)
        hi = np.ascontiguousarray(self.max, dtype=np.float64).reshape(-1)
        if lo.shape != (3,) or hi.shape != (3,):
            raise ValueError(
                f"BBox min/max must each be a 3-vector; got shapes "
                f"{lo.shape} / {hi.shape}."
            )
        if bool(np.any(hi < lo)):
            raise ValueError(
                f"BBox requires min <= max component-wise; got "
                f"min={lo.tolist()} max={hi.tolist()}."
            )
        object.__setattr__(self, "min", lo)
        object.__setattr__(self, "max", hi)

    # -- derived views (the six old notions fold into these) ----------

    @property
    def corners8(self) -> np.ndarray:
        """The 8 AABB corners, ``(8, 3)`` float64 — every (x, y, z)
        min/max combination, ordered z-slowest."""
        lo, hi = self.min, self.max
        return np.array(
            [
                [lo[0], lo[1], lo[2]], [hi[0], lo[1], lo[2]],
                [lo[0], hi[1], lo[2]], [hi[0], hi[1], lo[2]],
                [lo[0], lo[1], hi[2]], [hi[0], lo[1], hi[2]],
                [lo[0], hi[1], hi[2]], [hi[0], hi[1], hi[2]],
            ],
            dtype=np.float64,
        )

    @property
    def center(self) -> np.ndarray:
        """The box centre, ``(3,)`` float64."""
        return (self.min + self.max) * 0.5

    @property
    def diagonal(self) -> float:
        """The space-diagonal length (the ``_compute_model_diagonal``
        consumer)."""
        return float(np.linalg.norm(self.max - self.min))

    def union(self, other: "BBox") -> "BBox":
        """The smallest box enclosing both — the fold operator that
        replaces the ad-hoc bbox merges (``_world_bbox`` etc.)."""
        return BBox(
            np.minimum(self.min, other.min),
            np.maximum(self.max, other.max),
        )

    def contains(self, pt: Sequence[float]) -> bool:
        """Whether a world point lies within the box (inclusive)."""
        p = np.asarray(pt, dtype=np.float64).reshape(-1)
        if p.shape != (3,):
            raise ValueError(f"contains() needs a 3-vector; got {p.shape}.")
        return bool(np.all(p >= self.min) and np.all(p <= self.max))

    @classmethod
    def from_points(cls, points: np.ndarray) -> "BBox":
        """Tight AABB of a non-empty ``(n, 3)`` point cloud.

        The constructor S1's per-substrate providers use to derive a real
        box from an entity's vertices — the replacement for the
        degenerate ``np.tile(centroid, (8, 1))`` fallback.
        """
        pts = np.ascontiguousarray(points, dtype=np.float64)
        if pts.ndim != 2 or pts.shape[1] != 3 or pts.shape[0] == 0:
            raise ValueError(
                f"from_points needs a non-empty (n, 3) array; got "
                f"shape {pts.shape}."
            )
        return cls(pts.min(axis=0), pts.max(axis=0))


__all__ = ["BBox"]
