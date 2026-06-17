"""Seismic moment-tensor math — the pure core of ADR 0062 (MT-1).

A seismic point source is a **moment tensor** ``M_ij``. By the
representation theorem (Aki & Richards 2002, Ch. 3) its radiated field
equals that of an equivalent body force; projected onto the FE basis the
consistent nodal force on host node ``a`` is ``F^a_i = M_ij ∂N_a/∂x_j``.
This module owns the *tensor* half of that: building the unit
double-couple ``m_ij`` from a fault mechanism, scaling it by the scalar
moment ``M0``, and mapping the geophysics frame to the mesh frame. The
*force* half (``∂N/∂x`` projection) lives in
:mod:`apeGmsh._kernel.resolvers._moment_tensor`.

Frame convention
----------------
The unit tensor is built in the **Aki & Richards geographic frame**:
``x = North``, ``y = East``, ``z = Down`` — the same convention as
ShakerMaker's ``core/radiats.c`` (``nmtensor``), verified term-for-term.
The unit double-couple (A&R Eq. 4.83–4.88; ``φ`` strike, ``δ`` dip,
``λ`` rake, all degrees):

.. math::

    m_{xx} &= -(\\sin\\delta\\cos\\lambda\\sin2\\phi
               + \\sin2\\delta\\sin\\lambda\\sin^2\\phi)\\\\
    m_{yy} &=   \\sin\\delta\\cos\\lambda\\sin2\\phi
               - \\sin2\\delta\\sin\\lambda\\cos^2\\phi\\\\
    m_{zz} &=   \\sin2\\delta\\sin\\lambda = -(m_{xx}+m_{yy})\\\\
    m_{xy} &=   \\sin\\delta\\cos\\lambda\\cos2\\phi
               + \\tfrac12\\sin2\\delta\\sin\\lambda\\sin2\\phi\\\\
    m_{xz} &= -(\\cos\\delta\\cos\\lambda\\cos\\phi
               + \\cos2\\delta\\sin\\lambda\\sin\\phi)\\\\
    m_{yz} &= -(\\cos\\delta\\cos\\lambda\\sin\\phi
               - \\cos2\\delta\\sin\\lambda\\cos\\phi)

apeGmsh meshes are usually **z-up** (depth is a positive number *below*
the free surface), so :func:`to_mesh_frame` flips the ``z`` axis —
negating ``m_xz`` and ``m_yz`` while leaving the in-plane and ``m_zz``
components unchanged. Getting this wrong silently mirrors the radiation
pattern, so the high-level :func:`moment_tensor` requires an explicit
``frame``.

Units
-----
This module is **unit-neutral**. :func:`scalar_moment` returns
``mu * area * slip`` in whatever (consistent) units the caller passes.
:func:`magnitude_to_scalar_moment` follows the Hanks & Kanamori (1979)
SI convention ``M0 [N·m] = 10**(1.5*Mw + 9.1)`` — converting to the deck's
``kN·m`` is the ShakerMaker adapter's job (MT-4), not this layer's.

Pure NumPy — no Gmsh, no OpenSees imports.
"""
from __future__ import annotations

import numpy as np
from numpy import ndarray

from ._inverse_map import HOST_KINDS, _hex8_dN, _quad4_dN


__all__ = [
    "unit_moment_tensor",
    "scalar_moment",
    "magnitude_to_scalar_moment",
    "scalar_moment_to_magnitude",
    "to_mesh_frame",
    "moment_tensor",
    "MESH_FRAMES",
    "shape_gradient_phys",
    "consistent_nodal_forces",
    "dipole_nodal_forces",
]

#: Accepted ``frame`` values for :func:`moment_tensor` /
#: :func:`to_mesh_frame`. ``"z-up"`` is the typical apeGmsh continuum
#: convention (free surface at the top, depth positive downward) and
#: flips the A&R ``z``-down tensor; ``"z-down"`` keeps the A&R frame.
MESH_FRAMES = ("z-up", "z-down")


def unit_moment_tensor(*, strike: float, dip: float, rake: float) -> ndarray:
    """Unit double-couple ``m_ij`` (3×3) in the A&R z-**down** frame.

    ``strike`` (``φ``), ``dip`` (``δ``) and ``rake`` (``λ``) are in
    **degrees**. The returned tensor is symmetric, trace-free (a pure
    deviatoric double-couple), and **not** scaled by the scalar moment —
    multiply by ``M0`` (see :func:`moment_tensor`).

    The component layout is the standard ``(x=N, y=E, z=Down)`` Cartesian
    grid; ``m[0,2]`` is ``m_xz`` etc.
    """
    phi = np.radians(strike)
    delta = np.radians(dip)
    lam = np.radians(rake)

    sphi, cphi = np.sin(phi), np.cos(phi)
    s2phi, c2phi = np.sin(2 * phi), np.cos(2 * phi)
    sdel, cdel = np.sin(delta), np.cos(delta)
    s2del, c2del = np.sin(2 * delta), np.cos(2 * delta)
    slam, clam = np.sin(lam), np.cos(lam)

    m_xx = -(sdel * clam * s2phi + s2del * slam * sphi * sphi)
    m_yy = sdel * clam * s2phi - s2del * slam * cphi * cphi
    m_zz = s2del * slam
    m_xy = sdel * clam * c2phi + 0.5 * s2del * slam * s2phi
    m_xz = -(cdel * clam * cphi + c2del * slam * sphi)
    m_yz = -(cdel * clam * sphi - c2del * slam * cphi)

    return np.array(
        [
            [m_xx, m_xy, m_xz],
            [m_xy, m_yy, m_yz],
            [m_xz, m_yz, m_zz],
        ],
        dtype=float,
    )


def scalar_moment(*, mu: float, area: float, slip: float) -> float:
    """Scalar seismic moment ``M0 = μ·A·D̄``.

    ``mu`` is the (local) shear modulus, ``area`` the ruptured area, and
    ``slip`` the average slip. Unit-neutral: the result is in whatever
    consistent units the three inputs share (e.g. Pa·m²·m = N·m).
    """
    if mu <= 0 or area <= 0 or slip <= 0:
        raise ValueError(
            "scalar_moment: mu, area and slip must all be > 0 "
            f"(got mu={mu!r}, area={area!r}, slip={slip!r})."
        )
    return float(mu) * float(area) * float(slip)


def magnitude_to_scalar_moment(mw: float) -> float:
    """Moment magnitude ``Mw`` → scalar moment ``M0`` in **N·m**.

    Hanks & Kanamori (1979), SI form: ``M0 = 10**(1.5*Mw + 9.1)``.
    """
    return float(10.0 ** (1.5 * float(mw) + 9.1))


def scalar_moment_to_magnitude(m0: float) -> float:
    """Scalar moment ``M0`` (**N·m**) → moment magnitude ``Mw``.

    Inverse of :func:`magnitude_to_scalar_moment`:
    ``Mw = (log10(M0) - 9.1) / 1.5``.
    """
    if m0 <= 0:
        raise ValueError(
            f"scalar_moment_to_magnitude: M0 must be > 0 (got {m0!r})."
        )
    return float((np.log10(m0) - 9.1) / 1.5)


def to_mesh_frame(m: ndarray, *, frame: str) -> ndarray:
    """Map an A&R z-**down** tensor onto the mesh frame.

    ``frame="z-up"`` flips the vertical axis (negating ``m_xz`` and
    ``m_yz``; ``m_zz`` and the in-plane components are invariant under
    ``z → -z``). ``frame="z-down"`` returns a copy unchanged. Any other
    value fails loud — the flip is the #1 footgun (it silently mirrors
    the radiation pattern), so there is no default.
    """
    if frame not in MESH_FRAMES:
        raise ValueError(
            f"to_mesh_frame: frame must be one of {MESH_FRAMES}, got "
            f"{frame!r}. 'z-up' (typical apeGmsh: free surface on top, "
            f"depth positive downward) flips the A&R z-down tensor; "
            f"'z-down' keeps it. There is no default — the flip mirrors "
            f"the radiation pattern if wrong."
        )
    out = np.array(m, dtype=float, copy=True)
    if frame == "z-up":
        # z -> -z : negate the single-z components, leave m_zz / in-plane.
        out[0, 2] = -out[0, 2]
        out[2, 0] = -out[2, 0]
        out[1, 2] = -out[1, 2]
        out[2, 1] = -out[2, 1]
    return out


def moment_tensor(
    *,
    frame: str,
    M0: float = 1.0,
    strike: float | None = None,
    dip: float | None = None,
    rake: float | None = None,
    m_ij: ndarray | None = None,
) -> ndarray:
    """Full moment tensor ``M = M0 · m`` (3×3) in the **mesh** frame.

    Supply *either* a fault mechanism (``strike`` + ``dip`` + ``rake``,
    degrees) *or* a pre-built unit tensor ``m_ij`` (3×3, A&R z-down) —
    never both. ``M0`` is the scalar moment (default 1.0 → the scaled
    unit tensor). ``frame`` (required) selects the mesh vertical
    convention; see :func:`to_mesh_frame`.

    The result is symmetric and, for a double-couple, trace-free.
    """
    has_mech = strike is not None or dip is not None or rake is not None
    if has_mech == (m_ij is not None):
        raise ValueError(
            "moment_tensor: supply exactly one of a mechanism "
            "(strike+dip+rake) or m_ij (a unit tensor), not both / neither."
        )
    if has_mech:
        if strike is None or dip is None or rake is None:
            raise ValueError(
                "moment_tensor: a mechanism needs all of strike, dip, rake "
                f"(got strike={strike!r}, dip={dip!r}, rake={rake!r})."
            )
        m = unit_moment_tensor(strike=strike, dip=dip, rake=rake)
    else:
        assert m_ij is not None  # validated above
        m = np.asarray(m_ij, dtype=float)
        if m.shape != (3, 3):
            raise ValueError(
                f"moment_tensor: m_ij must be a 3x3 array, got shape {m.shape}."
            )
        if not np.allclose(m, m.T, atol=1e-12):
            raise ValueError(
                "moment_tensor: m_ij must be symmetric (a physical moment "
                "tensor has no net torque)."
            )
    return to_mesh_frame(float(M0) * m, frame=frame)


# ---------------------------------------------------------------------------
# MT-2 — equivalent nodal forces F^a_i = M_ij ∂N_a/∂x_j
# ---------------------------------------------------------------------------

# Constant reference-coord gradients ∂N/∂ξ for the linear simplex kinds
# (their physical gradient is constant over the element). Node order
# matches _inverse_map's barycentric free-coord convention:
# tri3 N = [1-ξ-η, ξ, η]; tet4 N = [1-ξ-η-ζ, ξ, η, ζ].
_TRI3_DN = np.array([[-1.0, -1.0], [1.0, 0.0], [0.0, 1.0]])
_TET4_DN = np.array(
    [[-1.0, -1.0, -1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
)


def _dN_ref(kind: str, xi: ndarray) -> ndarray:
    """Reference-coord shape gradients ``∂N/∂ξ`` (``n_nodes × ndm``)."""
    if kind == "hex8":
        return _hex8_dN(np.asarray(xi, dtype=float))
    if kind == "quad4":
        return _quad4_dN(np.asarray(xi, dtype=float))
    if kind == "tet4":
        return _TET4_DN
    if kind == "tri3":
        return _TRI3_DN
    raise ValueError(
        f"_dN_ref: unsupported host kind {kind!r} (supported: "
        f"{sorted(HOST_KINDS)})."
    )


def shape_gradient_phys(kind: str, X: ndarray, xi: ndarray) -> ndarray:
    """Physical shape-function gradient ``∂N_a/∂x_j`` at natural coord ``ξ``.

    ``X`` is the host's ``(n_nodes, ≥ndm)`` corner coordinates (only the
    first ``ndm`` columns are used — a 2D host's coords may carry a
    redundant ``z``), ``xi`` the natural coordinate from
    :func:`~apeGmsh._kernel.geometry._inverse_map.inverse_map_single`.

    Computes ``∂N/∂x = ∂N/∂ξ · J⁻¹`` with the Jacobian ``J = ∂x/∂ξ =
    Xᵀ·∂N/∂ξ`` — the projection the inverse map does **not** expose
    (ADR 0062 open-Q #3). Fails loud on a singular / degenerate host.
    """
    ndm = HOST_KINDS[kind][1]
    X = np.asarray(X, dtype=float)[:, :ndm]
    dN = _dN_ref(kind, xi)                      # (n_nodes, ndm)
    J = X.T @ dN                                # (ndm, ndm)
    detJ = float(np.linalg.det(J))
    span = float(np.linalg.norm(X.max(axis=0) - X.min(axis=0))) or 1.0
    if abs(detJ) < 1e-12 * span ** ndm:
        raise ValueError(
            f"shape_gradient_phys: {kind} host is degenerate / singular "
            f"(det(J)={detJ:.3e}); cannot evaluate ∂N/∂x. The moment-tensor "
            f"source point must sit in a non-degenerate continuum element."
        )
    return dN @ np.linalg.inv(J)               # (n_nodes, ndm)


def consistent_nodal_forces(
    M: ndarray, X: ndarray, kind: str, xi: ndarray,
) -> ndarray:
    """Consistent nodal forces ``F^a_i = M_ij ∂N_a/∂x_j`` on a host element.

    ``M`` is the full moment tensor (3×3, mesh frame); only its leading
    ``ndm × ndm`` block is used for a 2D host. Returns ``(n_nodes, ndm)``.

    The net force ``Σ_a F^a`` is identically zero (``Σ_a ∂N_a/∂x = 0`` for
    a complete shape-function set) — a physical seismic source carries no
    net force; :func:`net_force` asserts it.
    """
    ndm = HOST_KINDS[kind][1]
    grad = shape_gradient_phys(kind, X, xi)    # (n_nodes, ndm)
    Msub = np.asarray(M, dtype=float)[:ndm, :ndm]
    # F[a, i] = Σ_j grad[a, j] · M[i, j] = (grad @ Mᵀ)[a, i]
    return grad @ Msub.T


def dipole_nodal_forces(
    M: ndarray,
    *,
    plus_spacings: ndarray,
    minus_spacings: ndarray,
) -> tuple[ndarray, ndarray]:
    """Force-dipole equivalent of ``M`` on a node's ±axis neighbours.

    For each axis ``j`` (with ``+`` neighbour at distance ``h_+`` and
    ``-`` neighbour at ``h_-``) the couple is placed with a
    **compensating arm**: ``+M[:, j]/(h_+ + h_-)`` on the ``+`` neighbour
    and ``−M[:, j]/(h_+ + h_-)`` on the ``-`` neighbour. This gives a net
    force of **exactly zero** and a first moment that reproduces ``M``
    even on a *graded* grid (``h_+ ≠ h_-``); for a uniform grid
    (``h_+ = h_- = h``) it reduces to the textbook ``M[:, j]/(2h)``. The
    central node carries nothing (the couple lives on the neighbours).

    ``plus_spacings`` / ``minus_spacings`` are length-``ndm`` distances to
    the ``+`` and ``−`` neighbour along each axis. Returns
    ``(forces_plus, forces_minus)`` each ``(ndm, ndm)`` — row ``j`` is the
    force vector on the ``±j`` neighbour.
    """
    M = np.asarray(M, dtype=float)
    ndm = int(plus_spacings.shape[0])
    Msub = M[:ndm, :ndm]
    fp = np.zeros((ndm, ndm))
    fm = np.zeros((ndm, ndm))
    for j in range(ndm):
        hp = float(plus_spacings[j])
        hm = float(minus_spacings[j])
        if hp <= 0 or hm <= 0:
            raise ValueError(
                "dipole_nodal_forces: every ±axis neighbour spacing must be "
                f"> 0 (axis {j}: +{hp:g}, -{hm:g}). The dipole fallback "
                "needs all 2·ndm neighbours; place the source on an "
                "interior grid node."
            )
        # Compensating arm: F·(arm) reproduces M[:, j] while the equal-and-
        # opposite pair cancels the net force regardless of hp vs hm.
        fp[j] = Msub[:, j] / (hp + hm)
        fm[j] = -Msub[:, j] / (hp + hm)
    return fp, fm
