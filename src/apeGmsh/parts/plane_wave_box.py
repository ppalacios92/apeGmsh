"""
PlaneWaveBox — structured soil box wrapped by an ASDAbsorbingBoundary skin.

Builds, in the *live session* (not a Part/STEP round-trip), an axis-aligned
structured soil box plus a one-element-thick absorbing **offset shell** on its
five truncation faces (the local +Z top is the free surface and is never
shelled).  Soil + shell are a single plain rectangular block: slicing only at the
region breakpoints yields **18 sub-volumes** — one soil region plus up to 17
skin regions (5 face panels, 4 vertical edges, 4 bottom edges, 4 bottom
corners).  Each skin region is tagged with its OpenSees ``btype`` (the set of
truncation faces it lies outside of, OR-combined) so the bridge fans out one
``ASDAbsorbingBoundary3D`` per element with the shared btype.

This is the shared session-geometry core behind
``g.parts.add_plane_wave_box`` (ADR 0054 / plan_absorbing_skin_ab1.md, slice
AB-1a).  It deliberately does NOT depend on :class:`~apeGmsh.parts.drm_box.DRMBox`
(that serves the Domain Reduction Method) and does NOT use the Part/STEP vehicle
(it builds directly in the session, avoiding the ``setCurrent`` footgun).

btype → axis mapping (proven against the element source and a real STKO export):
``L`` = min-X, ``R`` = max-X, ``F`` = min-Y, ``K`` = max-Y, ``B`` = min-Z
(bottom).  Letters are canonically ordered ``BLRFK``.  Opposite-face combos
(``LR``/``FK``) are illegal and cannot arise from this grid by construction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import gmsh

from ._axis1d import Axis1D

if TYPE_CHECKING:
    from ..core._session import _SessionBase  # pragma: no cover

# Canonical btype letter order — also the OpenSees-accepted set.
_BTYPE_ORDER = "BLRFK"


@dataclass(frozen=True)
class AbsorbingSkinResult:
    """Summary of a :func:`build_plane_wave_box` placement.

    Returned to the user so downstream code can refer to the generated
    physical groups without touching tags.
    """

    soil_pg: str
    """PG name of the intact interior soil volume."""
    skin_pgs: dict[str, str] = field(default_factory=dict)
    """``btype -> PG name`` for every skin region present (e.g.
    ``{"L": "absorbing_L", "LF": "absorbing_LF", "BLF": "absorbing_BLF"}``).
    The bridge emits one ``ASDAbsorbingBoundary3D`` declaration per entry."""
    skin_all_pg: str = ""
    """Roll-up PG over every skin region — the set the staged
    ``s.activate_absorbing()`` flip and the Rayleigh region target."""
    bottom_pgs: tuple[str, ...] = ()
    """Skin PG names whose btype contains ``B`` — the base-input targets."""
    free_surface_pg: str = ""
    """PG (dim 2) of the soil top face at the local free surface (z=0)."""
    axes: dict[str, Axis1D] = field(default_factory=dict)
    """``x``/``y``/``z`` :class:`Axis1D` descriptors for downstream sizing."""
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_z: float = 0.0
    """Applied rotation about +Z, in radians (always 0.0 in AB-1a)."""
    n_layers: int = 1
    """Number of soil layers (1 = homogeneous).  Layers are ordered top → bottom,
    index 0 = top (free surface)."""
    soil_pgs: tuple[str, ...] = ()
    """Per-layer soil PG names, top → bottom (index 0 = top).  For a homogeneous
    box this is ``(soil_pg,)``.  Emit one ``stdBrick`` per entry with that layer's
    material."""
    skin_pgs_by_layer: dict[int, dict[str, str]] = field(default_factory=dict)
    """``layer -> {btype -> PG name}`` for the per-layer skin regions.  For a
    homogeneous box this is ``{0: skin_pgs}``.  The bridge fans one
    ``ASDAbsorbingBoundary3D`` per entry with that layer's material when
    ``absorbing_boundary(materials=...)`` is used."""


def _btype_for(rx: str, ry: str, rz: str) -> str:
    """Canonical btype for a sub-volume from its per-axis region labels.

    Returns ``""`` for the interior soil cell.
    """
    faces = []
    if rx in ("L", "R"):
        faces.append(rx)
    if ry in ("F", "K"):
        faces.append(ry)
    if rz == "B":
        faces.append("B")
    return "".join(sorted(faces, key=_BTYPE_ORDER.index))


def _as_size_count(value, who: str) -> tuple[float, int]:
    """Validate and unpack a ``(size, n_elements)`` axis tuple."""
    try:
        size, n = value
    except (TypeError, ValueError):
        raise ValueError(
            f"add_plane_wave_box: {who} must be a (size, n_elements) "
            f"tuple, got {value!r}."
        )
    size_f, n_i = float(size), int(n)
    if size_f <= 0.0:
        raise ValueError(
            f"add_plane_wave_box: {who} size must be > 0, got {size_f}."
        )
    if n_i < 1:
        raise ValueError(
            f"add_plane_wave_box: {who} n_elements must be >= 1, got {n_i}."
        )
    return size_f, n_i


def _as_xyz(value, who: str) -> tuple[float, float, float]:
    """Validate a scalar-or-``(x, y, z)`` positive-float spec → ``(vx, vy, vz)``.

    ``who`` is the caller-context label used in error messages (e.g.
    ``"add_absorbing_shell: element_size"``).
    """
    if isinstance(value, (int, float)):
        vx = vy = vz = float(value)
    else:
        try:
            vx, vy, vz = (float(t) for t in value)
        except (TypeError, ValueError):
            raise ValueError(
                f"{who} must be a scalar or an (x, y, z) tuple, got {value!r}."
            )
    for v, ax in ((vx, "x"), (vy, "y"), (vz, "z")):
        if v <= 0.0:
            raise ValueError(f"{who} on {ax} must be > 0, got {v}.")
    return vx, vy, vz


_ALL_FACES = ("L", "R", "F", "K", "B")


def _resolve_active_faces(faces) -> set[str]:
    """Validate the optional ``faces=`` subset → a set of active face letters.

    ``None`` → all five truncation faces.  The local +Z top is the free surface
    and is never a valid entry (no ``"T"``).
    """
    if faces is None:
        return set(_ALL_FACES)
    active: set[str] = set()
    for f in faces:
        if f not in _ALL_FACES:
            raise ValueError(
                f"add_absorbing_shell: faces entries must be one of "
                f"{_ALL_FACES} (the +Z top is the free surface and is never "
                f"shelled), got {f!r}."
            )
        active.add(f)
    if not active:
        raise ValueError(
            "add_absorbing_shell: faces must name at least one face."
        )
    return active


def _is_soil_region(region: str) -> bool:
    """True for a soil region (``"soil"`` or ``"soil_<k>"``), False for a face."""
    return region not in _ALL_FACES


def _layer_of(rz: str, n_layers: int) -> int:
    """Layer index of a cell from its z-region (top → bottom, 0 = top).

    The base skin (``rz == "B"``) belongs to the **bottom** layer — STKO gives
    each absorbing element its adjacent soil element's properties.
    """
    if rz == "B":
        return n_layers - 1
    if rz.startswith("soil_"):
        return int(rz[5:])
    return 0  # "soil" — homogeneous


def _layered_axis_z(
    ztop: float,
    layers: list[tuple[float, int]],
    tz: float,
    b_active: bool,
) -> Axis1D:
    """Z-axis from a top-down ``[(depth, n), ...]`` stack + optional base skin.

    Regions increase in z: ``B`` (if active), then the soil layers deepest-first.
    A single layer is named ``"soil"`` (byte-identical to the homogeneous case);
    multiple layers are ``"soil_0"`` (top) … ``"soil_{N-1}"`` (bottom).
    """
    depths = [float(d) for d, _ in layers]
    counts = [int(n) for _, n in layers]
    n_layers = len(layers)
    bounds = [ztop]
    acc = ztop
    for d in depths:
        acc -= d
        bounds.append(acc)            # bounds[k] = top of layer k, bounds[k+1] = its bottom
    zbot = bounds[-1]

    segs: list[tuple[str, float, float, int]] = []
    if b_active:
        segs.append(("B", zbot - tz, zbot, 1))
    for k in range(n_layers - 1, -1, -1):   # deepest first (increasing z)
        region = "soil" if n_layers == 1 else f"soil_{k}"
        segs.append((region, bounds[k + 1], bounds[k], counts[k]))
    return Axis1D("z", tuple(segs))


def _axes_from_extent(
    extent: tuple[float, float, float, float, float, float],
    sizes: tuple[float, float, float],
    thick: tuple[float, float, float],
    active: set[str],
    layers: list[tuple[float, int]] | None = None,
) -> tuple[Axis1D, Axis1D, Axis1D]:
    """Three world-frame :class:`Axis1D` from a box AABB + element size + skin.

    Soil-segment counts are ``max(1, round(length / size))``; each outer skin
    segment is one element thick.  Outer segments are emitted only for active
    faces; the +Z top is never shelled.  When ``layers`` is given the z-axis is
    stratified (one ``soil_<k>`` segment per layer); otherwise a single ``soil``
    segment sized by ``sz``.
    """
    xmin, ymin, zmin, xmax, ymax, zmax = extent
    sx, sy, sz = sizes
    tx, ty, tz = thick
    nx = max(1, round((xmax - xmin) / sx))
    ny = max(1, round((ymax - ymin) / sy))

    x_segs: list[tuple[str, float, float, int]] = []
    if "L" in active:
        x_segs.append(("L", xmin - tx, xmin, 1))
    x_segs.append(("soil", xmin, xmax, nx))
    if "R" in active:
        x_segs.append(("R", xmax, xmax + tx, 1))

    y_segs: list[tuple[str, float, float, int]] = []
    if "F" in active:
        y_segs.append(("F", ymin - ty, ymin, 1))
    y_segs.append(("soil", ymin, ymax, ny))
    if "K" in active:
        y_segs.append(("K", ymax, ymax + ty, 1))

    z_layers = layers if layers is not None else [
        (zmax - zmin, max(1, round((zmax - zmin) / sz))),
    ]
    axis_z = _layered_axis_z(zmax, z_layers, tz, b_active="B" in active)

    return (
        Axis1D("x", tuple(x_segs)),
        Axis1D("y", tuple(y_segs)),
        axis_z,
    )


def _tag_and_structure(
    session: "_SessionBase",
    vols: list[int],
    *,
    axis_x: Axis1D,
    axis_y: Axis1D,
    axis_z: Axis1D,
    to_local,
    name: str | None,
    names: dict[str, str] | None,
    apply_transfinite: bool,
    center: tuple[float, float, float],
    soil_pg_name: str | None = None,
) -> AbsorbingSkinResult:
    """Classify volumes by btype, create PGs, apply the transfinite cascade.

    Shared tail of :func:`build_plane_wave_box` (build-then-slice) and
    :func:`build_absorbing_shell` (weld-then-fragment).  ``vols`` is the full
    set of sub-volumes (one soil interior + the skin cells); each is classified
    by its centroid in the local frame.  When ``soil_pg_name`` is given the soil
    interior is reported under that existing name and **no** soil PG is created
    (the caller's box already carries it); otherwise a ``<prefix>soil`` PG is
    made over the interior cell.  The free surface is the soil top face at local
    ``z = axis_z.hi`` (no skin sits above it).
    """
    queries = session.model.queries
    n_layers = sum(
        1 for seg in axis_z.segments if _is_soil_region(seg[0])
    )

    # ── Classify each sub-volume by (layer, btype) ──────────────────
    soil_by_layer: dict[int, list[int]] = {}
    skin_by_layer: dict[int, dict[str, list[int]]] = {}
    per_vol_counts: list[tuple[int, int, int, int]] = []

    for vtag in vols:
        lx, ly, lz = to_local(queries.center_of_mass(int(vtag), dim=3))
        rx, ry, rz = axis_x.region_of(lx), axis_y.region_of(ly), axis_z.region_of(lz)
        btype = _btype_for(rx, ry, rz)
        layer = _layer_of(rz, n_layers)
        if btype:
            skin_by_layer.setdefault(layer, {}).setdefault(btype, []).append(int(vtag))
        else:
            soil_by_layer.setdefault(layer, []).append(int(vtag))
        per_vol_counts.append((
            int(vtag),
            axis_x.count_for(lx), axis_y.count_for(ly), axis_z.count_for(lz),
        ))

    prefix = f"{name}_" if name else ""

    def pg_name(base: str) -> str:
        if names and base in names:
            return str(names[base])
        return f"{prefix}{base}"

    physical = session.physical

    # ── Soil PGs — per layer (+ all-soil roll-up when stratified) ───
    soil_pgs: list[str] = []
    all_soil_vols: list[int] = []
    for k in range(n_layers):
        kv = soil_by_layer.get(k, [])
        all_soil_vols.extend(kv)
        if n_layers == 1 and soil_pg_name is not None:
            soil_pgs.append(soil_pg_name)   # caller's box already carries the PG
            continue
        nm = pg_name("soil") if n_layers == 1 else pg_name(f"soil_layer{k}")
        soil_pgs.append(nm)
        if kv:
            physical.add(3, kv, name=nm)
    if soil_pg_name is not None:
        soil_pg = soil_pg_name              # box PG already spans all soil layers
    elif n_layers == 1:
        soil_pg = soil_pgs[0]
    else:
        soil_pg = pg_name("soil")
        if all_soil_vols:
            physical.add(3, all_soil_vols, name=soil_pg)

    # ── Skin PGs — per (layer, btype), per-btype roll-up, global roll-up ─
    skin_pgs_by_layer: dict[int, dict[str, str]] = {}
    by_btype_vols: dict[str, list[int]] = {}
    all_skin_vols: list[int] = []
    for k in range(n_layers):
        lb = skin_by_layer.get(k, {})
        for btype in sorted(lb, key=lambda b: (len(b), b)):
            bvols = lb[btype]
            nm = (pg_name(f"absorbing_{btype}") if n_layers == 1
                  else pg_name(f"absorbing_{btype}_layer{k}"))
            physical.add(3, bvols, name=nm)
            skin_pgs_by_layer.setdefault(k, {})[btype] = nm
            by_btype_vols.setdefault(btype, []).extend(bvols)
            all_skin_vols.extend(bvols)

    skin_pgs: dict[str, str] = {}
    for btype in sorted(by_btype_vols, key=lambda b: (len(b), b)):
        if n_layers == 1:
            skin_pgs[btype] = skin_pgs_by_layer[0][btype]   # the only PG; no roll-up
        else:
            nm = pg_name(f"absorbing_{btype}")
            physical.add(3, by_btype_vols[btype], name=nm)
            skin_pgs[btype] = nm

    skin_all_pg = pg_name("absorbing")
    if all_skin_vols:
        physical.add(3, all_skin_vols, name=skin_all_pg)

    bottom_pgs = tuple(
        skin_pgs[bt] for bt in sorted(skin_pgs, key=lambda b: (len(b), b))
        if "B" in bt
    )

    # ── Free surface: soil top faces at local z = axis_z.hi ─────────
    extent = max(axis_x.hi - axis_x.lo, axis_y.hi - axis_y.lo, axis_z.hi - axis_z.lo)
    z_tol = 1e-6 * extent
    top = axis_z.hi
    free_faces: list[int] = []
    for _d, ftag in gmsh.model.getEntities(2):
        lx, ly, lz = to_local(queries.center_of_mass(int(ftag), dim=2))
        if abs(lz - top) > z_tol:
            continue
        try:  # faces from unrelated geometry fall outside this box's axes
            in_soil = (_is_soil_region(axis_x.region_of(lx))
                       and _is_soil_region(axis_y.region_of(ly)))
        except ValueError:
            continue
        if in_soil:
            free_faces.append(int(ftag))
    free_surface_pg = pg_name("free_surface")
    if free_faces:
        physical.add(2, free_faces, name=free_surface_pg)

    # ── Transfinite cascade per sub-volume ──────────────────────────
    if apply_transfinite:
        structured = session.mesh.structured
        for vtag, cnx, cny, cnz in per_vol_counts:
            structured.set_transfinite(
                (3, vtag),
                n=(cnx + 1, cny + 1, cnz + 1),
                recombine=True,
            )

    return AbsorbingSkinResult(
        soil_pg=soil_pg,
        skin_pgs=skin_pgs,
        skin_all_pg=skin_all_pg,
        bottom_pgs=bottom_pgs,
        free_surface_pg=free_surface_pg if free_faces else "",
        axes={"x": axis_x, "y": axis_y, "z": axis_z},
        center=center,
        rotation_z=0.0,
        n_layers=n_layers,
        soil_pgs=tuple(soil_pgs),
        skin_pgs_by_layer=skin_pgs_by_layer,
    )


def build_plane_wave_box(
    session: "_SessionBase",
    *,
    x: tuple[float, int],
    y: tuple[float, int],
    z,
    skin_thickness=None,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation_z_deg: float = 0.0,
    name: str | None = None,
    names: dict[str, str] | None = None,
    apply_transfinite: bool = True,
) -> AbsorbingSkinResult:
    """Build a plane-wave soil box + absorbing skin in the live session.

    See module docstring and ``g.parts.add_plane_wave_box`` for the user-facing
    contract.  AB-1a scope: axis-aligned (``rotation_z_deg == 0``), single soil
    segment per axis (layered Z is AB-1c).
    """
    # ── Fail-loud guards ────────────────────────────────────────────
    if abs(float(rotation_z_deg)) > 1e-15:
        raise NotImplementedError(
            "add_plane_wave_box: rotation is AB-1c; rotation_z_deg must be 0.0."
        )

    Lx, nx = _as_size_count(x, "x")
    Ly, ny = _as_size_count(y, "y")
    # z is a single (depth, n) tuple OR a top→bottom list of layers (stratigraphy).
    if isinstance(z, list):
        if not z:
            raise ValueError("add_plane_wave_box: z layer list cannot be empty.")
        layers = [_as_size_count(seg, f"z[{i}]") for i, seg in enumerate(z)]
    else:
        layers = [_as_size_count(z, "z")]
    Lz = sum(d for d, _ in layers)
    d_bottom, n_bottom = layers[-1]

    # Skin thickness per axis — default = adjacent soil element size (the base
    # skin is adjacent to the bottom layer, so tz defaults to its element size).
    if skin_thickness is None:
        tx, ty, tz = Lx / nx, Ly / ny, d_bottom / n_bottom
    elif isinstance(skin_thickness, (int, float)):
        tx = ty = tz = float(skin_thickness)
    else:
        try:
            tx, ty, tz = (float(v) for v in skin_thickness)
        except (TypeError, ValueError):
            raise ValueError(
                "add_plane_wave_box: skin_thickness must be None, a scalar, "
                f"or a (tx, ty, tz) tuple, got {skin_thickness!r}."
            )
    for t, ax in ((tx, "x"), (ty, "y"), (tz, "z")):
        if t <= 0.0:
            raise ValueError(
                f"add_plane_wave_box: skin_thickness on {ax} must be > 0, got {t}."
            )

    # ── Axis descriptors (local frame; soil centred laterally, top z=0) ──
    axis_x = Axis1D("x", (
        ("L", -Lx / 2 - tx, -Lx / 2, 1),
        ("soil", -Lx / 2, Lx / 2, nx),
        ("R", Lx / 2, Lx / 2 + tx, 1),
    ))
    axis_y = Axis1D("y", (
        ("F", -Ly / 2 - ty, -Ly / 2, 1),
        ("soil", -Ly / 2, Ly / 2, ny),
        ("K", Ly / 2, Ly / 2 + ty, 1),
    ))
    axis_z = _layered_axis_z(0.0, layers, tz, b_active=True)

    cx, cy, cz = (float(v) for v in center)

    def to_local(world_xyz):
        wx, wy, wz = world_xyz
        return wx - cx, wy - cy, wz - cz

    # Build + slice in the LOCAL frame (centred near the origin, where the
    # slice cutting-plane reliably covers the box — it is sized around the
    # origin, so a box translated far away would slice to nothing), then
    # translate to ``center``.  Mirrors the DRMBox build-local-then-place model.
    geom = session.model.geometry
    before_vols = {int(t) for _d, t in gmsh.model.getEntities(3)}

    geom.add_box(
        axis_x.lo, axis_y.lo, axis_z.lo,
        axis_x.hi - axis_x.lo, axis_y.hi - axis_y.lo, axis_z.hi - axis_z.lo,
    )

    def _box_vols() -> list[int]:
        return sorted({int(t) for _d, t in gmsh.model.getEntities(3)} - before_vols)

    for off in axis_x.slice_offsets():
        geom.slice(target=_box_vols(), axis="x", offset=float(off))
    for off in axis_y.slice_offsets():
        geom.slice(target=_box_vols(), axis="y", offset=float(off))
    for off in axis_z.slice_offsets():
        geom.slice(target=_box_vols(), axis="z", offset=float(off))

    # Place: translate the whole block to the requested center.  Done before
    # PG-tagging / transfinite so no synchronize follows group creation.
    if cx or cy or cz:
        gmsh.model.occ.translate([(3, v) for v in _box_vols()], cx, cy, cz)
        gmsh.model.occ.synchronize()

    # ── Classify sub-volumes, tag PGs, apply the transfinite cascade ─
    return _tag_and_structure(
        session,
        _box_vols(),
        axis_x=axis_x,
        axis_y=axis_y,
        axis_z=axis_z,
        to_local=to_local,
        name=name,
        names=names,
        apply_transfinite=apply_transfinite,
        center=(cx, cy, cz),
    )


def build_absorbing_shell(
    session: "_SessionBase",
    *,
    box,
    element_size,
    skin_thickness=None,
    faces=None,
    layers: list[tuple[float, int]] | None = None,
    name: str | None = None,
    names: dict[str, str] | None = None,
    apply_transfinite: bool = True,
) -> AbsorbingSkinResult:
    """Weld a one-element absorbing skin onto a user's existing soil box.

    See ``g.parts.add_absorbing_shell`` for the user-facing contract (ADR 0054,
    AB-1b/AB-1c).  ``box`` resolves to a single axis-aligned *rectangular*
    volume; the skin discretization is **size-based** and (re)applied to box +
    skin after the weld — gmsh cannot report transfinite counts back and the
    ``fragment`` renumbers entities, so the box's prior mesh state is irrelevant
    (this call makes it structured).  ``layers`` (top→bottom ``[(depth, n), …]``,
    summing to the box's z-extent) stratifies the box + lateral skin per layer
    (AB-1c).  ``rotation`` / graded skins remain deferred.
    """
    from apeGmsh.core._helpers import resolve_to_dimtags

    # ── Resolve + validate the box (exactly one rectangular volume) ──
    dts = resolve_to_dimtags(box, default_dim=3, session=session)
    box_vols = [int(t) for d, t in dts if int(d) == 3]
    if len(box_vols) != 1:
        raise ValueError(
            f"add_absorbing_shell: box must resolve to exactly one dim-3 "
            f"volume, got {len(box_vols)} ({box!r}).  It wraps a single "
            "axis-aligned rectangular soil box."
        )
    box_vol = box_vols[0]

    queries = session.model.queries
    xmin, ymin, zmin, xmax, ymax, zmax = queries.bounding_box(box_vol, dim=3)
    aabb = (xmax - xmin) * (ymax - ymin) * (zmax - zmin)
    gmsh.model.occ.synchronize()
    mass = gmsh.model.occ.getMass(3, int(box_vol))
    if aabb <= 0.0 or abs(mass - aabb) > 1e-6 * aabb:
        raise ValueError(
            "add_absorbing_shell: box is not an axis-aligned rectangular "
            f"block (volume {mass:.6g} != bounding-box product {aabb:.6g}).  "
            "It requires a rectangular box; rotated / curved geometry is AB-1c."
        )

    sizes = _as_xyz(element_size, "add_absorbing_shell: element_size")
    thick = (
        sizes if skin_thickness is None
        else _as_xyz(skin_thickness, "add_absorbing_shell: skin_thickness")
    )
    active = _resolve_active_faces(faces)

    # ── Validate layered stratigraphy against the box's z-extent ─────
    if layers is not None:
        layers = [_as_size_count(seg, f"layers[{i}]") for i, seg in enumerate(layers)]
        if not layers:
            raise ValueError("add_absorbing_shell: layers cannot be empty.")
        total = sum(d for d, _ in layers)
        if abs(total - (zmax - zmin)) > 1e-6 * max(zmax - zmin, 1.0):
            raise ValueError(
                f"add_absorbing_shell: layers depths sum to {total:.6g}, which "
                f"does not match the box z-extent {zmax - zmin:.6g}."
            )

    axis_x, axis_y, axis_z = _axes_from_extent(
        (xmin, ymin, zmin, xmax, ymax, zmax), sizes, thick, active, layers=layers,
    )

    geom = session.model.geometry
    tolb = 1e-6 * max(xmax - xmin, ymax - ymin, zmax - zmin)

    def _soil_region_vols() -> list[int]:
        """Current volumes inside the box AABB (the soil; slabs are outside)."""
        out: list[int] = []
        for _d, vt in gmsh.model.getEntities(3):
            cx_, cy_, cz_ = queries.center_of_mass(int(vt), dim=3)
            if (xmin - tolb <= cx_ <= xmax + tolb
                    and ymin - tolb <= cy_ <= ymax + tolb
                    and zmin - tolb <= cz_ <= zmax + tolb):
                out.append(int(vt))
        return out

    # ── Stratify: slice the box at the interior layer interfaces ─────
    if layers is not None and len(layers) > 1:
        acc = zmax
        for d, _n in layers[:-1]:
            acc -= d                       # interface z, strictly inside (zmin, zmax)
            geom.slice(target=_soil_region_vols(), axis="z", offset=float(acc))

    box_now = _soil_region_vols()          # the (possibly sliced) soil volumes

    # ── Build the skin slabs (every grid cell that is a skin cell) ───
    # The slabs MUST be synchronised before the weld: fragmenting a synced box
    # against unsynced slabs leaves coincident-but-separate faces (duplicate
    # interface nodes ⇒ a disconnected, singular model).
    slab_vols: list[int] = []
    for rx, xlo, xhi, _cx in axis_x.segments:
        for ry, ylo, yhi, _cy in axis_y.segments:
            for rz, zlo, zhi, _cz in axis_z.segments:
                if not _btype_for(rx, ry, rz):
                    continue  # interior soil cell — comes from the box, not a slab
                slab_vols.append(int(geom.add_box(
                    xlo, ylo, zlo, xhi - xlo, yhi - ylo, zhi - zlo, sync=True,
                )))

    # ── Weld conformally: self-fragment box + slabs (PGs auto-remap) ─
    session.model.boolean.fragment([*box_now, *slab_vols], [], dim=3)

    # ── Collect the welded box + skin volumes (centroid in the outer
    #    block AABB), tolerant of any other geometry in the session ───
    tol = 1e-6 * max(
        axis_x.hi - axis_x.lo, axis_y.hi - axis_y.lo, axis_z.hi - axis_z.lo,
    )
    vols: list[int] = []
    for _d, vt in gmsh.model.getEntities(3):
        ccx, ccy, ccz = queries.center_of_mass(int(vt), dim=3)
        if (axis_x.lo - tol <= ccx <= axis_x.hi + tol
                and axis_y.lo - tol <= ccy <= axis_y.hi + tol
                and axis_z.lo - tol <= ccz <= axis_z.hi + tol):
            vols.append(int(vt))

    soil_pg_name = box if isinstance(box, str) else None
    return _tag_and_structure(
        session,
        vols,
        axis_x=axis_x,
        axis_y=axis_y,
        axis_z=axis_z,
        to_local=lambda xyz: xyz,   # world frame (axis-aligned)
        name=name,
        names=names,
        apply_transfinite=apply_transfinite,
        center=(0.5 * (xmin + xmax), 0.5 * (ymin + ymax), 0.5 * (zmin + zmax)),
        soil_pg_name=soil_pg_name,
    )
