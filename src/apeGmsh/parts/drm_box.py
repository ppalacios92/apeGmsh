"""
DRMBox — Domain-Reduction-Method box geometry primitive.

A DRM box is a structured layered solid used in seismic
soil-structure-interaction modelling: three concentric regions per
lateral axis (inner core, transition layer, outer absorbing layer)
and a downward-only Z stack (top / mid / bottom layers).  The
classic symmetric case has 5 segments along X, 5 along Y, 3 along
Z, giving ``5 * 5 * 3 = 75`` axis-aligned hex sub-volumes that need
structured-hex meshing with per-region element counts.

This module owns:

* :class:`DRMBox` — a :class:`~apeGmsh.core.Part.Part` subclass that
  builds the sliced geometry in its own Gmsh session.  Geometry
  only — no labels, no physical groups, no mesh settings.  Persists
  to STEP exactly like any other Part.
* :class:`DRMBoxResult` — frozen dataclass returned by the assembly
  helper ``g.parts.add_DRM_box(...)`` summarising the named PGs and
  Axis1D descriptors so the user can refer to them later.
* :func:`classify_drm_box_lines` — pure classifier that maps a set
  of curve tags into ``{line_pg_name: [edge_tags]}`` by replaying
  the centroid-in-local-frame + endpoint-direction predicate.
  Reused both at construction (``add_DRM_box``) and after a boolean
  mutates the box (``rebuild_drm_box_line_pgs``) so a cut against
  the box can drop the line PGs and reconstruct them from the same
  geometry-derived rule.

The assembly-side wiring (PG tagging + transfinite cascade) lives
in :func:`apeGmsh.core._parts_registry.PartsRegistry.add_DRM_box`,
not here — transfinite directives don't survive STEP, so they must
be applied post-import on the assembly's session.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

import gmsh
import numpy as np

from ..core.Part import Part
from ._axis1d import Axis1D

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class DRMBoxResult:
    """Summary of a DRM-box placement.

    Returned by :func:`PartsRegistry.add_DRM_box`.  The user keeps it
    for downstream references — PG names to feed into recorders or
    constraints, Axis1D descriptors to drive auxiliary mesh sizing.
    """

    inner_pg: str
    transition_pg: str
    outer_pg: str
    line_pgs: dict[str, str] = field(default_factory=dict)
    axes: dict[str, Axis1D] = field(default_factory=dict)
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_z: float = 0.0


class DRMBox(Part):
    """Layered DRM-box geometry, built in its own Gmsh session.

    The box is centred laterally on ``(0, 0)`` and descends from
    ``z = 0`` (top of the inner box, free-surface convention).  No
    labels or physical groups are attached — the assembly-side helper
    re-classifies sub-volumes by centroid + Axis1D lookup after
    import, which is robust to STEP renumbering and to the
    placement transform.

    Parameters
    ----------
    x_inner, x_layer, x_outer, y_inner, y_layer, y_outer :
        ``(size, n_elements)`` tuples — symmetric layered axes
        (outer | layer | inner | layer | outer) along X and Y.
    z_top, z_mid, z_bottom :
        ``(size, n_elements)`` tuples — downward Z stack
        (bottom | mid | top, ``hi = 0``).
    name :
        Gmsh model name and default Part / instance name.
    """

    def __init__(
        self,
        *,
        x_inner: tuple[float, int],
        x_layer: tuple[float, int],
        x_outer: tuple[float, int],
        y_inner: tuple[float, int],
        y_layer: tuple[float, int],
        y_outer: tuple[float, int],
        z_top: tuple[float, int],
        z_mid: tuple[float, int],
        z_bottom: tuple[float, int],
        name: str = "drm_box",
    ) -> None:
        super().__init__(name=name)
        self.axis_x = Axis1D.symmetric_layered(
            "x", inner=x_inner, layer=x_layer, outer=x_outer,
        )
        self.axis_y = Axis1D.symmetric_layered(
            "y", inner=y_inner, layer=y_layer, outer=y_outer,
        )
        self.axis_z = Axis1D.downward_layered(
            "z", top=z_top, mid=z_mid, bottom=z_bottom,
        )
        # Stored so the assembly-side helper can re-create them via
        # ``result.axes`` if it skipped the live-Part path.
        self.properties.update({
            "drm_box": {
                "x_inner": tuple(x_inner),
                "x_layer": tuple(x_layer),
                "x_outer": tuple(x_outer),
                "y_inner": tuple(y_inner),
                "y_layer": tuple(y_layer),
                "y_outer": tuple(y_outer),
                "z_top": tuple(z_top),
                "z_mid": tuple(z_mid),
                "z_bottom": tuple(z_bottom),
            },
        })

    # ------------------------------------------------------------------
    # Geometry build
    # ------------------------------------------------------------------

    def build(self) -> "DRMBox":
        """Build the 75-volume sliced box inside the Part's session.

        Must be called inside ``with drm_box:``.  Returns ``self`` so
        the caller can chain ``with DRMBox(...) as d: d.build()`` if
        desired.  Idempotent within a session — repeated calls slice
        nothing on the already-fully-sliced model.
        """
        if not self._active:
            raise RuntimeError(
                f"DRMBox({self.name!r}).build(): Part session is not "
                f"active.  Call build() inside a `with` block."
            )

        x_breaks = self.axis_x.breaks
        y_breaks = self.axis_y.breaks
        z_breaks = self.axis_z.breaks

        x0, x_end = x_breaks[0], x_breaks[-1]
        y0, y_end = y_breaks[0], y_breaks[-1]
        z0, z_end = z_breaks[0], z_breaks[-1]

        self.model.geometry.add_box(
            x0, y0, z0,
            x_end - x0, y_end - y0, z_end - z0,
        )

        for x in self.axis_x.slice_offsets():
            self.model.geometry.slice(axis="x", offset=float(x))
        for y in self.axis_y.slice_offsets():
            self.model.geometry.slice(axis="y", offset=float(y))
        for z in self.axis_z.slice_offsets():
            self.model.geometry.slice(axis="z", offset=float(z))

        return self


# ---------------------------------------------------------------------------
# Line-PG classifier (pure function — replayable post-boolean)
# ---------------------------------------------------------------------------


def classify_drm_box_lines(
    *,
    axis_x: Axis1D,
    axis_y: Axis1D,
    axis_z: Axis1D,
    center: tuple[float, float, float],
    rotation_z: float,
    line_pg_names: dict[str, str],
    curve_tags: Iterable[int],
) -> dict[str, list[int]]:
    """Classify a set of curve tags into DRM-box line-PG buckets.

    The same predicate that ``add_DRM_box`` uses at construction:
    transform the edge midpoint into the local (un-rotated,
    un-translated) frame, look up the lateral or vertical region via
    :class:`Axis1D`, and bucket by endpoint direction (local-X /
    local-Y / local-Z, within ~5°).  Pure function — no Gmsh state
    mutation, no PG creation.  Caller decides which curves to feed
    in (all model curves at construction, only curves bounding the
    box's volumes after a boolean).

    Edges that don't cleanly align with a local axis are skipped
    silently (matches construction behaviour — OCC sometimes
    introduces tiny non-axis-aligned seams).  Edges whose midpoint
    falls outside every axis range likewise skip; this can happen
    on the cut interface where the box's BRep was reshaped by a
    tool volume.

    Parameters
    ----------
    axis_x, axis_y, axis_z
        Axis1D descriptors carrying region breakpoints.
    center
        World-coordinate translation applied to the box.
    rotation_z
        CCW rotation about +Z applied at ``center``, in radians.
    line_pg_names
        Dict mapping region keys (``'inner_x'``, ``'top_z'``, etc.)
        to the PG name to use.  Edges classified into a key absent
        from this dict are dropped.
    curve_tags
        Curve tags to classify.

    Returns
    -------
    dict[str, list[int]]
        ``{pg_name: sorted_unique_edge_tags}`` for every PG name
        that picked up at least one edge.  Empty entries are
        omitted.
    """
    cx, cy, cz = (float(v) for v in center)
    theta = float(rotation_z)
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    def to_local(world_xyz: tuple[float, float, float]) -> tuple[float, float, float]:
        wx, wy, wz = world_xyz
        dx, dy, dz = wx - cx, wy - cy, wz - cz
        lx = cos_t * dx + sin_t * dy
        ly = -sin_t * dx + cos_t * dy
        return lx, ly, dz

    ex = np.array([cos_t, sin_t, 0.0])
    ey = np.array([-sin_t, cos_t, 0.0])
    ez = np.array([0.0, 0.0, 1.0])
    align_tol = math.cos(math.radians(5.0))

    buckets: dict[str, list[int]] = {k: [] for k in line_pg_names}

    for ctag in curve_tags:
        ctag = int(ctag)
        bnd = gmsh.model.getBoundary(
            [(1, ctag)], oriented=False, recursive=False,
        )
        pts = [b for b in bnd if b[0] == 0]
        if len(pts) < 2:
            continue
        p0 = np.array(
            gmsh.model.getValue(0, int(pts[0][1]), []), dtype=float,
        )
        p1 = np.array(
            gmsh.model.getValue(0, int(pts[-1][1]), []), dtype=float,
        )
        d = p1 - p0
        dn = float(np.linalg.norm(d))
        if dn < 1e-12:
            continue
        dhat = d / dn

        dots = (
            float(abs(np.dot(dhat, ex))),
            float(abs(np.dot(dhat, ey))),
            float(abs(np.dot(dhat, ez))),
        )
        axis_idx = int(np.argmax(dots))
        if dots[axis_idx] < align_tol:
            continue

        mid_world = 0.5 * (p0 + p1)
        lx, ly, lz = to_local((float(mid_world[0]), float(mid_world[1]), float(mid_world[2])))

        try:
            if axis_idx == 0:  # local-X — region keyed by Y
                clamped = max(min(ly, axis_y.hi), axis_y.lo)
                region = axis_y.region_of(clamped)
                key = f"{region}_x"
            elif axis_idx == 1:  # local-Y — region keyed by X
                clamped = max(min(lx, axis_x.hi), axis_x.lo)
                region = axis_x.region_of(clamped)
                key = f"{region}_y"
            else:  # local-Z
                clamped = max(min(lz, axis_z.hi), axis_z.lo)
                region = axis_z.region_of(clamped)
                key = f"{region}_z"
        except (ValueError, KeyError):
            # Midpoint falls outside any region — happens on edges
            # introduced by a boolean cut at the box boundary.
            continue

        if key in buckets:
            buckets[key].append(ctag)

    return {
        line_pg_names[k]: sorted(set(v))
        for k, v in buckets.items() if v
    }


def rebuild_drm_box_line_pgs(parent, inst) -> set[str]:
    """Re-derive line PGs for a DRM-box Instance after a boolean op.

    Drops any existing line PGs by name (matching what's stored on
    the Instance), then re-runs :func:`classify_drm_box_lines`
    against the curves currently bounding the Instance's volumes.
    Idempotent — calling it on an untouched box yields the same
    PGs.

    Returns the set of PG names that were rebuilt (or attempted —
    a PG that picked up zero edges is silently dropped).  Caller
    uses this to inform the ``pg_preserved`` skip set.
    """
    drm_meta = inst.properties.get("drm_box")
    if not drm_meta or "line_pgs" not in drm_meta:
        return set()

    line_pg_names: dict[str, str] = dict(drm_meta["line_pgs"])
    if not line_pg_names:
        return set()

    # Rebuild Axis1D from the stored construction params so the
    # predicate runs against the same regions as at construction.
    p = drm_meta
    axis_x = Axis1D.symmetric_layered(
        "x", inner=p["x_inner"], layer=p["x_layer"], outer=p["x_outer"],
    )
    axis_y = Axis1D.symmetric_layered(
        "y", inner=p["y_inner"], layer=p["y_layer"], outer=p["y_outer"],
    )
    axis_z = Axis1D.downward_layered(
        "z", top=p["z_top"], mid=p["z_mid"], bottom=p["z_bottom"],
    )

    # Scope: only curves bounding the box's volumes.  After a cut
    # against a foreign tool (e.g. an embedded structure), the
    # model holds curves that don't belong to the box; passing
    # them through the classifier would mis-tag them as box edges.
    box_vols = [(3, int(t)) for t in inst.entities.get(3, [])]
    if not box_vols:
        return set()

    # gmsh's ``getBoundary(..., recursive=True)`` collapses to dim-0
    # vertices instead of returning every intermediate dim, so we
    # descend manually: volumes -> faces -> edges.
    face_dts = gmsh.model.getBoundary(
        box_vols, oriented=False, recursive=False, combined=False,
    )
    edges_dts = gmsh.model.getBoundary(
        [(d, t) for d, t in face_dts if int(d) == 2],
        oriented=False, recursive=False, combined=False,
    )
    curve_tags = sorted({int(t) for d, t in edges_dts if int(d) == 1})

    # Drop the prior line PGs by name AND by name->tag binding.
    # synchronize() releases the PG tags but leaves gmsh's internal
    # name->tag map stale; ``setPhysicalName`` then silently no-ops
    # when we try to bind the same name to a new tag.
    # ``removePhysicalName`` clears the binding so the rebuild's
    # ``setPhysicalName`` can claim the name on the new PG.
    physical = parent.physical
    for pg_name in line_pg_names.values():
        tag = physical.get_tag(1, pg_name)
        if tag is not None:
            try:
                gmsh.model.removePhysicalGroups([(1, tag)])
            except Exception:
                pass
        try:
            gmsh.model.removePhysicalName(pg_name)
        except Exception:
            pass

    classified = classify_drm_box_lines(
        axis_x=axis_x, axis_y=axis_y, axis_z=axis_z,
        center=tuple(drm_meta.get("center", inst.translate)),
        rotation_z=float(drm_meta.get("rotation_z", 0.0)),
        line_pg_names=line_pg_names,
        curve_tags=curve_tags,
    )

    for pg_name, edge_tags in classified.items():
        physical.add(1, edge_tags, name=pg_name)

    return set(line_pg_names.values())
