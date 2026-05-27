"""Chain-phase routing helpers — Phase 3B.2d / ADR 0038.

When a session is in *chain phase* (``g._fem is not None``) the broker
is canonical and the legacy "store def → re-extract on next
get_fem_data()" pattern is broken: chain-phase ``get_fem_data()`` short-
circuits to the cached FEMData and never re-resolves the def lists.

This module provides the bridge: given a session whose latest broker
snapshot is ``g._fem``, plus a freshly-built definition (``BCDef`` /
``PointMassDef`` / etc.), it resolves the def against the FEMData
via :class:`FEMDataSource` and returns a new :class:`FEMData` with
the resulting records appended via the broker's ``with_*`` transforms.

Scope (intentional minimum-viable surface)
------------------------------------------
The chain-phase router covers the def types whose resolution needs
only **node ids + names** — no element connectivity, no face area, no
edge tributary, no quadrature.  Concretely:

* ``BCDef`` → one :class:`SPRecord` per restrained DOF per node.
* ``PointMassDef`` → one :class:`MassRecord` per resolved node.
* ``PointLoadDef`` → one :class:`NodalLoadRecord` per resolved node.

Defs that need geometry-aware reduction (line / face / body loads;
line / face / body masses; interface-bridging constraints like
``embedded`` / ``tied_contact`` / ``equalDOF`` / ``rigid_link`` /
``rigid_diaphragm``) fall back to the bump-counter pattern in chain
phase.  Those are deferred to a follow-up that widens the
:class:`FEMDataSource` adapter with element-side queries (face area,
edge tributary).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from apeGmsh.mesh.FEMData import FEMData


def try_chain_phase_route(session, defn) -> bool:
    """Composite-side entry point: try routing ``defn`` against ``session._fem``.

    Returns ``True`` when the def was successfully resolved + applied to
    ``session._fem`` (which is replaced with a new snapshot in place);
    returns ``False`` when ``defn``'s shape exceeds this minimum-viable
    router's coverage or the session is in build phase (``_fem is None``).
    The caller falls back to the bump-counter pattern in the False case.

    Catches :class:`KeyError` from name resolution so a missing target
    surfaces only at extraction time (preserves backward-compat with
    the existing build-phase behaviour where defs may reference names
    that get created later in the session).
    """
    fem = getattr(session, "_fem", None)
    if fem is None:
        return False
    try:
        new_fem = route_def_to_fem(fem, defn)
    except (KeyError, TypeError):
        # Name resolution failure or unsupported target shape — fall
        # back to bump-counter.  In chain phase the def silently won't
        # be applied (documented limitation of this slice).
        return False
    if new_fem is None:
        return False
    session._fem = new_fem
    # Mark the cache fresh so the next ``get_fem_data()`` returns the
    # updated snapshot without an extraction attempt (the broker is
    # already in sync via the ``with_*`` transform).
    if hasattr(session, "_mark_fem_fresh"):
        session._mark_fem_fresh()
    return True


def route_def_to_fem(fem: "FEMData", defn) -> "FEMData | None":
    """Try to resolve ``defn`` directly into ``fem`` via ``with_*``.

    Returns a new :class:`FEMData` with the records appended on
    success; returns ``None`` when ``defn``'s shape needs geometry-
    aware reduction this minimum-viable router does not cover yet
    (the caller falls back to the bump-counter pattern).

    No exceptions escape — resolution failures (e.g. unknown target
    name) propagate as :class:`KeyError` from the underlying source
    adapter; type-mismatch falls through as ``None``.
    """
    from apeGmsh._kernel.defs.constraints import BCDef
    from apeGmsh._kernel.defs.masses import PointMassDef
    from apeGmsh._kernel.defs.loads import PointLoadDef
    from apeGmsh._kernel.records._loads import (
        NodalLoadRecord,
        SPRecord,
    )
    from apeGmsh._kernel.records._masses import MassRecord
    from ._source import FEMDataSource

    source = FEMDataSource(fem)

    # ── BCDef → SPRecord ──────────────────────────────────────────
    if isinstance(defn, BCDef):
        node_ids = _resolve_target_to_node_ids(source, defn.target)
        new_fem = fem
        for nid in sorted(node_ids):
            for d_idx, mask in enumerate(defn.dofs):
                if mask != 1:
                    continue
                rec = SPRecord(
                    name=defn.name,
                    node_id=int(nid),
                    dof=d_idx + 1,
                    value=0.0,
                    is_homogeneous=True,
                )
                new_fem = new_fem.with_load(rec)
        return new_fem

    # ── PointMassDef → MassRecord ────────────────────────────────
    if isinstance(defn, PointMassDef):
        node_ids = _resolve_target_to_node_ids(source, defn.target)
        rot = defn.rotational or (0.0, 0.0, 0.0)
        dofs = defn.dofs or [1, 2, 3]
        mass_by_dof = {d: defn.mass for d in dofs}
        new_fem = fem
        for nid in sorted(node_ids):
            translational = tuple(
                float(mass_by_dof.get(i + 1, 0.0)) for i in range(3)
            )
            mass6 = (
                translational[0], translational[1], translational[2],
                float(rot[0]), float(rot[1]), float(rot[2]),
            )
            rec = MassRecord(
                name=defn.name,
                node_id=int(nid),
                mass=mass6,
            )
            new_fem = new_fem.with_mass(rec)
        return new_fem

    # ── PointLoadDef → NodalLoadRecord ───────────────────────────
    if isinstance(defn, PointLoadDef):
        node_ids = _resolve_target_to_node_ids(source, defn.target)
        f = defn.force_xyz
        m = defn.moment_xyz
        force_xyz = (
            (float(f[0]), float(f[1]), float(f[2]))
            if f is not None and any(abs(float(v)) > 0.0 for v in f)
            else None
        )
        moment_xyz = (
            (float(m[0]), float(m[1]), float(m[2]))
            if m is not None and any(abs(float(v)) > 0.0 for v in m)
            else None
        )
        if force_xyz is None and moment_xyz is None:
            # Zero load — nothing to apply.
            return fem
        new_fem = fem
        for nid in sorted(node_ids):
            rec = NodalLoadRecord(
                pattern=defn.pattern,
                name=defn.name,
                node_id=int(nid),
                force_xyz=force_xyz,
                moment_xyz=moment_xyz,
            )
            new_fem = new_fem.with_load(rec)
        return new_fem

    # ── Unsupported def shape ─────────────────────────────────────
    return None


def _resolve_target_to_node_ids(source, target) -> np.ndarray:
    """Coerce a ``target`` field (str, int, list of ...) to int64 ids.

    Strings route through :meth:`FEMDataSource.nodes_for`; raw ints
    (or lists thereof) are taken at face value.  This is intentionally
    narrow — defs with mesh-selection sentinels, ``(dim, tag)`` lists,
    or other complex targets fall through to ``None`` at the caller.
    """
    if isinstance(target, str):
        return source.nodes_for(target)
    if isinstance(target, int):
        return np.array([int(target)], dtype=np.int64)
    if isinstance(target, (list, tuple)):
        ints: list[int] = []
        for x in target:
            if isinstance(x, int):
                ints.append(int(x))
            elif (
                isinstance(x, tuple) and len(x) == 2
                and all(isinstance(y, int) for y in x)
            ):
                # (dim, tag) — for nodes only (dim=0).  Otherwise we
                # do not have enough info to resolve here; let the
                # caller fall back to bump-counter.
                d, t = x
                if d == 0:
                    ints.append(int(t))
                else:
                    raise TypeError(
                        f"chain-phase routing: (dim, tag) target with "
                        f"dim={d} requires element-connectivity walk "
                        f"not yet wired in chain phase."
                    )
            else:
                raise TypeError(
                    f"chain-phase routing: unsupported target element "
                    f"{x!r} (type {type(x).__name__})."
                )
        return np.array(sorted(set(ints)), dtype=np.int64)
    raise TypeError(
        f"chain-phase routing: unsupported target type "
        f"{type(target).__name__}; pass a label/PG name (str), a bare "
        f"node id (int), or a list of those."
    )
