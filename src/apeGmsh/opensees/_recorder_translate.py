"""Canonical-name → OpenSees recorder token translation (Phase 9).

The :class:`~apeGmsh.opensees.recorder.RecorderDeclaration` carries
components in canonical vocabulary (``"displacement_x"``,
``"reaction_force_y"``, ``"axial_force"``, …). Emitting them as
OpenSees ``recorder`` commands requires translation to the native
token shapes (``"disp"`` + ``-dof 1``, ``"reaction"`` + ``-dof 5``,
``"section force"`` per integration point, …).

This module owns the translation tables for **node-level** components
(Phase 9 commit 3a). Element-level translation (elements / gauss /
line_stations) lands in commit 3b and lifts the heavier translation
logic from :mod:`apeGmsh.results.spec._emit`.

The :class:`Node`, :class:`Element`, and :class:`MPCO` typed
primitives in :mod:`apeGmsh.opensees.recorder` continue to take raw
OpenSees tokens directly (no translation needed); only the unified
``RecorderDeclaration`` consumed by
:func:`~apeGmsh.opensees._internal.build.emit_recorder_spec` flows
through these tables.
"""
from __future__ import annotations

from typing import Optional


# =====================================================================
# Per-axis DOF index tables
# =====================================================================

_TRANS_AXIS_TO_DOF: dict[str, int] = {"x": 1, "y": 2, "z": 3}
_ROT_AXIS_TO_DOF: dict[str, int] = {"x": 4, "y": 5, "z": 6}


# =====================================================================
# Canonical-prefix → (ops_recorder_token, axis_kind) table
# =====================================================================
#
# axis_kind ∈ {"trans", "rot"} selects which DOF table the axis
# suffix is read against. ``displacement_z`` → ("disp", 3); a 2-D
# ``rotation_z`` → ("disp", 6) (z-rotation in ndf=3 lives at DOF 3,
# but OpenSees promotes to the 3-D convention by default; emit-time
# clipping handles ndm/ndf consistency via the canonical-name set
# the bridge already validated).

_NODAL_PREFIX_TABLE: dict[str, tuple[str, str]] = {
    "displacement":           ("disp",      "trans"),
    "rotation":               ("disp",      "rot"),
    "velocity":               ("vel",       "trans"),
    "angular_velocity":       ("vel",       "rot"),
    "acceleration":           ("accel",     "trans"),
    "angular_acceleration":   ("accel",     "rot"),
    "displacement_increment": ("incrDisp",  "trans"),
    "reaction_force":         ("reaction",  "trans"),
    "reaction_moment":        ("reaction",  "rot"),
    # OpenSees ``unbalance`` returns residual nodal forces.
    "force":                  ("unbalance", "trans"),
    "moment":                 ("unbalance", "rot"),
}


# =====================================================================
# Scalar canonical names (no axis suffix)
# =====================================================================
#
# ``-1`` is a sentinel meaning "OpenSees infers the DOF" — used for
# pressure (the formulation-dependent pressure DOF). Real emitters
# decide based on the bridge's ``ndf`` whether to emit ``-dof <pdof>``
# explicitly or rely on the OpenSees default.

_NODAL_SCALAR_TABLE: dict[str, tuple[str, int]] = {
    "pore_pressure": ("pressure", -1),
}


# =====================================================================
# Public translation API
# =====================================================================


def node_component_to_ops(canonical: str) -> Optional[tuple[str, int]]:
    """Map a canonical node component to ``(ops_recorder_token, dof)``.

    Returns ``None`` if ``canonical`` is not a recognized node-level
    component (caller should fall through to error).

    Examples
    --------
    >>> node_component_to_ops("displacement_x")
    ('disp', 1)
    >>> node_component_to_ops("rotation_z")
    ('disp', 6)
    >>> node_component_to_ops("reaction_force_y")
    ('reaction', 2)
    >>> node_component_to_ops("pore_pressure")
    ('pressure', -1)
    >>> node_component_to_ops("bogus") is None
    True
    """
    if canonical in _NODAL_SCALAR_TABLE:
        return _NODAL_SCALAR_TABLE[canonical]
    if "_" not in canonical:
        return None
    prefix, axis = canonical.rsplit("_", 1)
    entry = _NODAL_PREFIX_TABLE.get(prefix)
    if entry is None:
        return None
    ops_token, axis_kind = entry
    dof_table = _TRANS_AXIS_TO_DOF if axis_kind == "trans" else _ROT_AXIS_TO_DOF
    if axis not in dof_table:
        return None
    return (ops_token, dof_table[axis])


def group_node_components_by_ops_token(
    components: tuple[str, ...],
) -> dict[str, tuple[int, ...]]:
    """Group node components by their OpenSees token.

    Components sharing the same ``ops_recorder_token`` collapse into
    one ``recorder Node`` line with a ``-dof`` list of all their DOFs.
    For example, ``("displacement_x", "displacement_y", "reaction_force_z")``
    produces:

        {"disp": (1, 2), "reaction": (3,)}

    Returns
    -------
    Mapping from ops token to ordered tuple of DOFs (1-based, OpenSees
    convention). Order within each group preserves component
    declaration order; ops tokens themselves are returned in
    discovery order.

    Raises
    ------
    ValueError
        If any component is not a recognized node-level canonical
        (caller is responsible for validating against the canonical
        vocabulary upstream; this raise is a defensive backstop).
    """
    grouped: dict[str, list[int]] = {}
    for comp in components:
        translated = node_component_to_ops(comp)
        if translated is None:
            raise ValueError(
                f"_recorder_translate.group_node_components_by_ops_token: "
                f"{comp!r} is not a recognized node-level canonical."
            )
        ops_token, dof = translated
        grouped.setdefault(ops_token, []).append(dof)
    # Deduplicate DOFs per token while preserving insertion order.
    return {
        token: tuple(dict.fromkeys(dofs)) for token, dofs in grouped.items()
    }
