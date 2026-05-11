"""apeGmsh.mesh.records — Resolved FEM records, kinds, and the
constraint umbrella.

Primary surface: the **resolved** dataclasses produced by the
resolvers after meshing (constraint, load, and mass records) plus
the :class:`ConstraintKind` / :class:`LoadKind` classifiers that
label them.

For convenience, this package also re-exports the constraint
:class:`ConstraintDef` hierarchy and :class:`ConstraintResolver` so
``import apeGmsh.mesh.records as Constraints`` provides the same
umbrella surface that the (deprecated)
:mod:`apeGmsh.solvers.Constraints` module used to.

User-facing **definition** dataclasses (``*Def``) live in
:mod:`apeGmsh.core.constraints.defs`, :mod:`apeGmsh.core.loads.defs`,
and :mod:`apeGmsh.core.masses.defs` — they describe pre-mesh intent.
The **resolvers** that translate defs into records live in
:mod:`apeGmsh.mesh._constraint_resolver`,
:mod:`apeGmsh.mesh._load_resolver`, and
:mod:`apeGmsh.mesh._mass_resolver`.
"""

from __future__ import annotations

from apeGmsh.core.constraints.defs import (
    ConstraintDef,
    DistributingCouplingDef,
    EmbeddedDef,
    EqualDOFDef,
    KinematicCouplingDef,
    MortarDef,
    NodeToSurfaceDef,
    NodeToSurfaceSpringDef,
    PenaltyDef,
    RigidBodyDef,
    RigidDiaphragmDef,
    RigidLinkDef,
    TieDef,
    TiedContactDef,
)

from .._constraint_resolver import SHAPE_FUNCTIONS, ConstraintResolver
from ._constraints import (
    ConstraintRecord,
    InterpolationRecord,
    NodeGroupRecord,
    NodePairRecord,
    NodeToSurfaceRecord,
    SurfaceCouplingRecord,
)
from ._kinds import ConstraintKind, LoadKind
from ._loads import (
    ElementLoadRecord,
    LoadRecord,
    NodalLoadRecord,
    SPRecord,
)
from ._masses import MassRecord


__all__ = [
    # Kind enums
    "ConstraintKind",
    "LoadKind",
    # Constraint defs (re-export from core.constraints.defs)
    "ConstraintDef",
    "EqualDOFDef",
    "RigidLinkDef",
    "PenaltyDef",
    "RigidDiaphragmDef",
    "RigidBodyDef",
    "KinematicCouplingDef",
    "TieDef",
    "DistributingCouplingDef",
    "EmbeddedDef",
    "NodeToSurfaceDef",
    "NodeToSurfaceSpringDef",
    "TiedContactDef",
    "MortarDef",
    # Constraint records
    "ConstraintRecord",
    "NodePairRecord",
    "NodeGroupRecord",
    "InterpolationRecord",
    "SurfaceCouplingRecord",
    "NodeToSurfaceRecord",
    # Constraint resolver + geom helper
    "ConstraintResolver",
    "SHAPE_FUNCTIONS",
    # Load records
    "LoadRecord",
    "NodalLoadRecord",
    "ElementLoadRecord",
    "SPRecord",
    # Mass records
    "MassRecord",
]
