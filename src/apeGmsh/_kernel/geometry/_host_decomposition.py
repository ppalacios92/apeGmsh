"""Kuhn decomposition of host elements into linear sub-tris / sub-tets.

Lifted from ``ConstraintsComposite._collect_host_subelements`` per
ADR 0041 §"Decision 1 — lift Kuhn decomposition into a geometric
utility module".  The lift is a refactor: the per-etype switch and
the three Kuhn-tet tables move here verbatim, parameterised to accept
``(etype, conn)`` pairs from any source (gmsh queries in build phase,
:class:`apeGmsh._kernel.payloads.ElementGroup` in chain phase) so both
phases share one decomposition implementation.

Why a separate module
---------------------
The Kuhn tables and the per-etype dispatch are **pure geometry** —
they have no notion of constraint resolver, FEMData broker, or gmsh
session.  Putting them under ``_constraint_resolver/`` would mis-scope
them: future loads / masses / viewer slices need the same
decomposition without going through the constraint composite.  See
ADR 0041 §1 for the layering rationale.

Backward compat
---------------
The three tables are re-exported from
``apeGmsh.core.ConstraintsComposite`` as aliases so existing imports
(``from apeGmsh.core.ConstraintsComposite import HEX8_TO_6_TETS``)
keep working unchanged.  ``tests/test_embedded_decomposition.py`` is
the documented consumer; future direct imports should target
``apeGmsh._kernel.geometry._host_decomposition``.
"""
from __future__ import annotations

from typing import Callable, Iterable

import numpy as np
from numpy import ndarray


# =====================================================================
# Kuhn decomposition tables
# =====================================================================
#
# These three tables encode the canonical Kuhn-style decomposition of
# Gmsh's hex8 / prism6 / pyramid5 element types into right-handed
# (positive-volume) tetrahedra.  Indices are 0-based positions into
# the host element's connectivity row in the canonical Gmsh vertex
# ordering; the resulting sub-tets share corner nodes with the host
# (no new node introduction).  Each table row is one Kuhn tet.
#
# Positive-volume + Gmsh-ordering invariants are property-tested in
# ``tests/test_embedded_decomposition.py`` against
# ``gmsh.model.mesh.getElementProperties(...)``; ANY change here must
# come with a fresh table that survives those tests.

# Decomposition of a hex8 into 6 right-handed Kuhn tets that share the
# main diagonal (vertex 0 → vertex 6).  Indices refer to Gmsh hex8
# vertex ordering (bottom face [0,1,2,3] CCW from +z, top face
# [4,5,6,7] aligned above).
HEX8_TO_6_TETS = np.array(
    [
        [0, 1, 2, 6],
        [0, 2, 3, 6],
        [0, 3, 7, 6],
        [0, 7, 4, 6],
        [0, 4, 5, 6],
        [0, 5, 1, 6],
    ],
    dtype=int,
)

# Decomposition of a prism6 (3-node triangle bottom + top, with
# vertical edges) into 3 right-handed Kuhn-style tets sharing the
# diagonal (vertex 0 → vertex 5).  Indices refer to Gmsh prism6
# vertex ordering (bottom triangle [0, 1, 2], top triangle [3, 4, 5]
# aligned above).
PRISM6_TO_3_TETS = np.array(
    [
        [0, 1, 2, 5],
        [0, 1, 5, 4],
        [0, 4, 5, 3],
    ],
    dtype=int,
)

# Decomposition of a pyramid5 (square base + apex) into 2 tets sharing
# the (0, 2) diagonal of the base, both sharing the apex (vertex 4).
# Indices refer to Gmsh pyramid5 vertex ordering (base [0, 1, 2, 3]
# CCW from +z, apex node 4).
PYRAMID5_TO_2_TETS = np.array(
    [
        [0, 1, 2, 4],
        [0, 2, 3, 4],
    ],
    dtype=int,
)


# =====================================================================
# Dispatch metadata
# =====================================================================
#
# Human-readable Gmsh element type names (subset relevant to embedded
# hosts) — keyed by the integer etype code.  Used to phrase the
# higher-order warning and the unsupported-etype fail-loud.
_ETYPE_NAMES = {
    1: "line2", 2: "tri3", 3: "quad4", 4: "tet4",
    5: "hex8", 6: "prism6", 7: "pyramid5", 8: "line3",
    9: "tri6", 10: "quad9", 11: "tet10", 15: "point1",
    16: "quad8", 17: "hex20", 18: "prism15",
    14: "pyramid13",
}

# Higher-order etypes whose decomposition discards the host's native
# interpolation richness (midside / center nodes) and falls back to
# linear-over-corners coupling.  Callers fire a UserWarning the first
# time one of these is decomposed in a given context (build phase: per
# (etype, entity); chain phase: per (etype, target-label)).
_HIGHER_ORDER_CODES = frozenset({9, 10, 11, 14, 16, 17, 18})


# Type alias for the higher-order warning callback supplied by the
# caller.  Receives ``(etype_code, etype_name)`` so the caller controls
# the message phrasing (build phase wants entity tags; chain phase
# wants target labels).
WarnHigherOrder = Callable[[int, str], None]


# =====================================================================
# Public API — decompose_hosts_to_subelements
# =====================================================================


def decompose_hosts_to_subelements(
    groups: Iterable[tuple[int, ndarray]],
    *,
    warn_higher_order: WarnHigherOrder | None = None,
) -> ndarray:
    """Return ``ndarray(F, 3 | 4)`` of virtual tri / tet sub-element rows.

    Per-etype dispatch identical to
    :meth:`ConstraintsComposite._collect_host_subelements` (ADR 0036):

    ============== ====== =====================================
    Gmsh etype     Code   Decomposition (corner nodes only)
    ============== ====== =====================================
    tri3 (CST)     2      identity (1 tri per host)
    tet4           4      identity (1 tet per host)
    quad4          3      2 tris via (0,2) diagonal split
    hex8           5      6 right-handed Kuhn tets
                          (:data:`HEX8_TO_6_TETS`)
    prism6         6      3 tets (:data:`PRISM6_TO_3_TETS`)
    pyramid5       7      2 tets (:data:`PYRAMID5_TO_2_TETS`)
    tri6 (LST)     9      corners only → 1 tri (midsides discarded)
    tet10          11     corners only → 1 tet
    pyramid13      14     corners only → 2 tets
    quad8 / quad9  16/10  corners only → 2 tris
    hex20          17     corners only → 6 Kuhn tets
    prism15        18     corners only → 3 tets
    ============== ====== =====================================

    Parameters
    ----------
    groups : iterable of (etype, conn)
        ``(etype_code, connectivity_array)`` pairs already extracted
        from any source — gmsh queries in build phase, FEMData
        ``ElementGroup`` connectivity in chain phase.  Each ``conn``
        is a flat ``ndarray`` of node tags or a ``(N, npe)`` rectangle
        (``np.asarray(...).reshape(-1, npe)`` is applied internally).
    warn_higher_order : callable, optional
        Called once per ``(etype, conn)`` whose etype is in
        :data:`_HIGHER_ORDER_CODES`.  Receives ``(etype_code,
        etype_name)``.  Caller controls message phrasing + stacklevel.
        When ``None`` the warning is suppressed (caller knows the
        decomposition is acceptable in their context).

    Returns
    -------
    ndarray
        ``(F, 4)`` of tet sub-element rows when any 3D hosts were
        decomposed; ``(F, 3)`` of tri sub-element rows when only 2D
        hosts were decomposed; ``np.empty((0, 0), dtype=int)`` when
        no host elements produced rows.

    Raises
    ------
    ValueError
        When an unsupported etype is encountered (the caller should
        not have included it).  Names the etype in the error message
        so the caller can locate the offending host.

        When both 2D sub-tris and 3D sub-tets are produced — mixed-dim
        hosts (shell PG + brick PG combined) cannot be deterministically
        coupled by the linear shape-function path.  See ADR 0036.

    Notes
    -----
    Returned rows are **not** real gmsh elements — they are a
    coupling-layer fabrication.  The embedded coupling is consequently
    linear regardless of the host's native interpolation order; see
    :class:`EmbeddedDef` for the ``host_coupling="linear"`` contract.

    Source-agnostic: this function does not touch gmsh, FEMData, or
    any other apeGmsh state.  Inputs are numpy arrays; output is a
    numpy array; the function is idempotent.
    """
    tri_rows: list[ndarray] = []
    tet_rows: list[ndarray] = []
    warned_codes: set[int] = set()

    for etype, conn in groups:
        code = int(etype)
        nodes = np.asarray(conn, dtype=int)
        if nodes.size == 0:
            continue

        # Fire the higher-order warning at most once per (code, group)
        # in this call.  Caller's callback decides per-context cadence
        # (build phase: per (code, entity); chain phase: per (code,
        # target)).  We dedupe within this call to avoid duplicate
        # warnings if the caller passes multiple groups of the same
        # higher-order etype — the warning's job is one message per
        # context, not one message per element.
        if (
            code in _HIGHER_ORDER_CODES
            and warn_higher_order is not None
            and code not in warned_codes
        ):
            warned_codes.add(code)
            warn_higher_order(code, _ETYPE_NAMES.get(code, f"etype={code}"))

        if code == 2:                                # tri3 (CST)
            tri_rows.append(nodes.reshape(-1, 3))
        elif code == 4:                              # tet4
            tet_rows.append(nodes.reshape(-1, 4))
        elif code == 3:                              # quad4
            q = nodes.reshape(-1, 4)
            tri_rows.append(q[:, [0, 1, 2]])
            tri_rows.append(q[:, [0, 2, 3]])
        elif code == 5:                              # hex8
            h = nodes.reshape(-1, 8)
            for tet_idx in HEX8_TO_6_TETS:
                tet_rows.append(h[:, tet_idx])
        elif code == 9:                              # tri6 (LST)
            tri_rows.append(nodes.reshape(-1, 6)[:, :3])
        elif code == 11:                             # tet10
            tet_rows.append(nodes.reshape(-1, 10)[:, :4])
        elif code in (16, 10):                       # quad8 / quad9
            n_per_elem = {16: 8, 10: 9}[code]
            q = nodes.reshape(-1, n_per_elem)[:, :4]
            tri_rows.append(q[:, [0, 1, 2]])
            tri_rows.append(q[:, [0, 2, 3]])
        elif code == 17:                             # hex20
            h = nodes.reshape(-1, 20)[:, :8]
            for tet_idx in HEX8_TO_6_TETS:
                tet_rows.append(h[:, tet_idx])
        elif code == 6:                              # prism6
            p = nodes.reshape(-1, 6)
            for tet_idx in PRISM6_TO_3_TETS:
                tet_rows.append(p[:, tet_idx])
        elif code == 18:                             # prism15
            p = nodes.reshape(-1, 15)[:, :6]
            for tet_idx in PRISM6_TO_3_TETS:
                tet_rows.append(p[:, tet_idx])
        elif code == 7:                              # pyramid5
            p = nodes.reshape(-1, 5)
            for tet_idx in PYRAMID5_TO_2_TETS:
                tet_rows.append(p[:, tet_idx])
        elif code == 14:                             # pyramid13
            p = nodes.reshape(-1, 13)[:, :5]
            for tet_idx in PYRAMID5_TO_2_TETS:
                tet_rows.append(p[:, tet_idx])
        else:
            name = _ETYPE_NAMES.get(code, f"etype={code}")
            raise ValueError(
                f"embedded: host carries {name} elements.  "
                f"ASDEmbeddedNodeElement hosts supported: tri3 / tri6 / "
                f"quad4 / quad8 / quad9 (2D); tet4 / tet10 / hex8 / "
                f"hex20 / prism6 / prism15 / pyramid5 / pyramid13 "
                f"(3D).  Higher-order and non-tet hosts are decomposed "
                f"to linear sub-elements using corner nodes only — the "
                f"embedded coupling is linear regardless of the host's "
                f"native interpolation order.  Got an etype not in the "
                f"supported set; remesh the host or open an issue."
            )

    # Mixed-dim host (shell PG + brick PG combined) is fail-loud: an
    # embedded node near the shell/brick interface would couple to
    # either side's corners depending on opaque kNN search outcome —
    # different physics, silently chosen.  Caller must split the host
    # into separate calls or restrict to a single dimensionality.
    if tet_rows and tri_rows:
        raise ValueError(
            "embedded: host entities produced BOTH 2D sub-tris and 3D "
            "sub-tets — the linear coupling cannot pick between them "
            "deterministically (kNN would dispatch an embedded node to "
            "either side based on centroid proximity, which is opaque "
            "physics).  Split the host into separate "
            "`g.constraints.embedded(...)` calls — one for the 2D "
            "part, one for the 3D part — or restrict the host PG to a "
            "single dimensionality."
        )
    if tet_rows:
        return np.vstack(tet_rows)
    if tri_rows:
        return np.vstack(tri_rows)
    return np.empty((0, 0), dtype=int)
