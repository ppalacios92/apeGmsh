"""
``g.rebar`` — the L2 reinforcement-cage authoring composite (ADR 0066).

Sits **above** the shipped ``g.reinforce`` binding composite: it owns the
L1 spec objects (:mod:`apeGmsh._kernel.defs.rebar`) + geometry generation
+ standardized-member generators, and **delegates** coupling —
*conformal* via ``g.mesh.editing.embed`` (this module, P1) and *embedded*
via ``g.reinforce`` (P2). It never emits an OpenSees element itself.

P1 scope: ``bar`` / ``stirrup`` / ``stirrup_rect`` spec emitters, eager
**polyline** geometry emission (``true_arc`` is deferred to P3), and
``place(cage, into, coupling="conformal")`` which embeds the bar curves
into the host solid before meshing so the host mesh conforms and the bars
share its nodes (perfect bond — the ``ladruno_rc.py`` behaviour
generalised off the grid).
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Iterable

from .._kernel.defs.rebar import METADATA, Bar, Cage, Hook, Path, Stirrup, Vec3
from ._compose_errors import chain_phase_guard
from ._helpers import resolve_to_tags

if TYPE_CHECKING:
    from .._core import _ApeGmshSession


# ── resolution-side records (not L1 specs) ───────────────────────────

@dataclass(frozen=True)
class RebarMember:
    """A placed bar/stirrup: the curve physical group + the intent the
    bridge needs to realise a Truss/CorotTruss/DispBeamColumn on it."""
    pg: str
    role: str
    db: float | str
    material: str
    element: str
    coupling: str
    line_tags: tuple[int, ...]


@dataclass(frozen=True)
class RebarPlacement:
    """The record of one ``place()`` call."""
    name: str
    host: str
    coupling: str
    members: tuple[RebarMember, ...]


# ── the composite ────────────────────────────────────────────────────

class RebarComposite:
    """``g.rebar`` — reinforcement-cage authoring (ADR 0066)."""

    def __init__(self, parent: "_ApeGmshSession") -> None:
        self._parent = parent
        self._standard: Any = None
        self.placements: list[RebarPlacement] = []

    # ---- detailing standard (used at resolve time, P3) --------------
    def use_standard(self, standard: Any) -> None:
        """Set the default :class:`DetailingStandard` for this session's
        cages (resolves ``"<k>db"`` tokens + hook factories at bind)."""
        self._standard = standard

    # ---- L1 spec emitters (thin) ------------------------------------
    def bar(self, points: Iterable[Vec3], *, db, material,
            role: str = "longitudinal", element: str = "truss",
            start_hook: Hook | None = None, end_hook: Hook | None = None,
            corner_radius=METADATA, name: str | None = None) -> Bar:
        return Bar(path=Path(tuple(points), corner_radius=corner_radius),
                   db=db, material=material, role=role, element=element,
                   start_hook=start_hook, end_hook=end_hook, name=name)

    def stirrup(self, points: Iterable[Vec3], *, db, material,
                closure_hook: Hook | None = None, role: str = "tie",
                corner_radius=METADATA, name: str | None = None) -> Stirrup:
        return Stirrup(path=Path(tuple(points), corner_radius=corner_radius),
                       db=db, material=material, role=role,
                       closure_hook=closure_hook or Hook.seismic_135(),
                       name=name)

    def stirrup_rect(self, bx: float, by: float, cover: float, *,
                     db, material, **kw) -> Stirrup:
        return Stirrup.rect(bx, by, cover, db=db, material=material, **kw)

    # ---- placement / coupling router --------------------------------
    def place(self, cage: Cage, into: str, *, coupling: str = "conformal",
              per_member_coupling: dict[str, str] | None = None,
              bond: str | None = None, perfect: float | None = None,
              kt=None, kt_alpha=None, enforce: str = "penalty",
              bipenalty: bool = False, dtcr=None, tolerance: float = 1.0e-6,
              snap: bool = False, host_dim: int | None = None,
              true_arc: bool = False, on_conformal_infeasible: str = "fail",
              name: str | None = None) -> RebarPlacement:
        """Emit the cage geometry and couple each member to host ``into``.

        ``coupling="conformal"`` embeds the bar curves into the host so the
        mesh conforms (shared nodes, perfect bond). ``coupling="embedded"``
        meshes the bars independently and forwards to ``g.reinforce`` (→
        ``LadrunoEmbeddedRebar``); it needs ``bond=`` (a ``LadrunoBondSlip``
        material name) **or** ``perfect=`` (a perfect-bond axial penalty).
        ``per_member_coupling={role: coupling}`` overrides per role for
        **mixed** cages (e.g. longitudinal conformal + ties embedded).
        """
        chain_phase_guard(self._parent, "g.rebar.place")
        if not isinstance(cage, Cage):
            raise TypeError(
                f"g.rebar.place: cage must be a Cage, got {type(cage).__name__}."
            )
        if true_arc:
            raise NotImplementedError(
                "g.rebar.place: true_arc fillet geometry is deferred to P3; "
                "use the polyline default (true_arc=False) for now."
            )
        if coupling not in ("conformal", "embedded"):
            raise ValueError(
                f"g.rebar.place: coupling must be 'conformal' or 'embedded', "
                f"got {coupling!r}."
            )
        if on_conformal_infeasible not in ("fail", "embedded"):
            raise ValueError(
                f"g.rebar.place: on_conformal_infeasible must be 'fail' or "
                f"'embedded', got {on_conformal_infeasible!r}."
            )
        rein_kw = dict(bond=bond, perfect=perfect, kt=kt, kt_alpha=kt_alpha,
                       enforce=enforce, bipenalty=bipenalty, dtcr=dtcr,
                       tolerance=tolerance, snap=snap)
        return self._place_members(
            cage, into, default_coupling=coupling,
            per_member_coupling=per_member_coupling or {},
            host_dim=host_dim, on_conformal_infeasible=on_conformal_infeasible,
            name=name, rein_kw=rein_kw,
        )

    def _place_members(self, cage: Cage, into: str, *, default_coupling: str,
                       per_member_coupling: dict[str, str], host_dim: int | None,
                       on_conformal_infeasible: str, name: str | None,
                       rein_kw: dict) -> RebarPlacement:
        g = self._parent
        geom = g.model.geometry
        in_dim = host_dim if host_dim is not None else self._detect_host_dim(into)
        base = name or "rebar"

        members: list[RebarMember] = []
        conformal_tags: list[int] = []
        # (RebarMember, spec) of conformal members, kept so an embed failure
        # can fall back to the embedded path under on_conformal_infeasible.
        conformal_specs: list = []

        # Pass 1 — emit all curve geometry (no PGs yet); validate coupling.
        emitted: list = []
        idx = 0
        for default_role, items in (("longitudinal", cage.bars),
                                    ("tie", cage.stirrups)):
            for m in items:
                role = getattr(m, "role", default_role)
                eff = per_member_coupling.get(role, default_coupling)
                if eff not in ("conformal", "embedded"):
                    raise ValueError(
                        f"g.rebar.place: per_member_coupling[{role!r}]={eff!r} "
                        f"must be 'conformal' or 'embedded'."
                    )
                lts = self._emit_polyline(geom, m.path.points)
                emitted.append((role, eff, m, lts, idx))
                idx += 1

        # Sync once so the new curve entities exist in the gmsh model before
        # we wrap them in physical groups (an unsynced PG resolves to nothing).
        g.model.sync()

        # Pass 2 — physical groups + coupling registration.
        for role, eff, m, lts, i in emitted:
            pg = f"{base}.{m.name or f'{role}_{i}'}"
            g.physical.add_curve(lts, name=pg)
            member = RebarMember(
                pg=pg, role=role, db=m.db, material=m.material,
                element=getattr(m, "element", "truss"),
                coupling=eff, line_tags=tuple(lts),
            )
            members.append(member)
            if eff == "conformal":
                conformal_tags.extend(lts)
                conformal_specs.append((member, m))
            else:
                self._register_embedded(into, pg, m, **rein_kw)

        if conformal_tags:
            try:
                # Conformal coupling: force the host mesh to conform to the
                # bar curves so generate() shares nodes (perfect bond).
                g.mesh.editing.embed(conformal_tags, into, dim=1, in_dim=in_dim)
            except Exception as exc:                       # embed-time failure
                if on_conformal_infeasible != "embedded":
                    raise
                warnings.warn(
                    f"g.rebar.place: conformal embed failed ({exc}); falling "
                    f"back to embedded coupling for {len(conformal_specs)} "
                    f"member(s).", stacklevel=2,
                )
                members = [
                    m if m.coupling == "embedded"
                    else replace(m, coupling="embedded")
                    for m in members
                ]
                for member, spec in conformal_specs:
                    self._register_embedded(into, member.pg, spec, **rein_kw)

        couplings = {m.coupling for m in members}
        placement = RebarPlacement(
            name=base, host=into,
            coupling=next(iter(couplings)) if len(couplings) == 1 else "mixed",
            members=tuple(members),
        )
        self.placements.append(placement)
        return placement

    def _register_embedded(self, into: str, pg: str, spec, *, bond, perfect,
                           kt, kt_alpha, enforce, bipenalty, dtcr, tolerance,
                           snap) -> None:
        """Forward one embedded member to the shipped ``g.reinforce``
        binding composite (→ ``LadrunoEmbeddedRebar``)."""
        if bond is None and perfect is None:
            raise ValueError(
                f"g.rebar.place: embedded coupling for {pg!r} needs "
                f"bond=<LadrunoBondSlip name> or perfect=<axial penalty>."
            )
        self._parent.reinforce.reinforce(
            host=into, bars=pg, bond=bond, perfect=perfect,
            bar_diameter=self._resolve_db_value(spec.db),
            bar_area=self._resolve_area_value(spec.db),
            kt=kt, kt_alpha=kt_alpha, enforce=enforce, bipenalty=bipenalty,
            dtcr=dtcr, tolerance=tolerance, snap=snap, name=pg,
        )

    def _resolve_db_value(self, db) -> float:
        if isinstance(db, (int, float)) and not isinstance(db, bool):
            return float(db)
        if self._standard is not None:
            return float(self._standard.bar_diameter(db))
        raise ValueError(
            f"g.rebar: db {db!r} is a designation but no DetailingStandard "
            f"is set; call g.rebar.use_standard(ACI318()) or pass a numeric db."
        )

    def _resolve_area_value(self, db) -> float:
        if isinstance(db, (int, float)) and not isinstance(db, bool):
            return math.pi * float(db) ** 2 / 4.0
        if self._standard is not None:
            return float(self._standard.bar_area(db))
        raise ValueError(
            f"g.rebar: db {db!r} is a designation but no DetailingStandard "
            f"is set; call g.rebar.use_standard(ACI318()) or pass a numeric db."
        )

    # ---- geometry helpers -------------------------------------------
    def _emit_polyline(self, geom, points: tuple[Vec3, ...]) -> list[int]:
        """Emit a polyline as gmsh points + line segments, returning the
        line tags. A closed loop (first == last) reuses the first point so
        the loop welds into one node ring."""
        closed = len(points) >= 2 and points[0] == points[-1]
        pt_tags: list[int] = []
        first_tag: int | None = None
        n = len(points)
        for i, p in enumerate(points):
            if closed and i == n - 1 and first_tag is not None:
                pt_tags.append(first_tag)
            else:
                t = geom.add_point(p[0], p[1], p[2], sync=False)
                if i == 0:
                    first_tag = t
                pt_tags.append(t)
        return [geom.add_line(pt_tags[i], pt_tags[i + 1], sync=False)
                for i in range(len(pt_tags) - 1)]

    def _detect_host_dim(self, into: str) -> int:
        """Resolve the host's dimension (3D solid preferred, then 2D)."""
        for d in (3, 2):
            try:
                if resolve_to_tags(into, dim=d, session=self._parent):
                    return d
            except Exception:
                continue
        raise ValueError(
            f"g.rebar.place: cannot resolve host {into!r} as a 3-D or 2-D "
            f"entity. Pass host_dim= explicitly or check the label."
        )

    # validate hook — resolution at get_fem_data (P3); nothing pre-mesh yet
    def validate_pre_mesh(self) -> None:
        return None
