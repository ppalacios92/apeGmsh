"""Deprecation shim for the constraint record relocation (Phase 8.1).

Canonical home is :mod:`apeGmsh.mesh.records._constraints`.
"""
from __future__ import annotations

import warnings

from apeGmsh.mesh.records._constraints import (
    ConstraintRecord,
    InterpolationRecord,
    NodeGroupRecord,
    NodePairRecord,
    NodeToSurfaceRecord,
    SurfaceCouplingRecord,
)

warnings.warn(
    "apeGmsh.solvers._constraint_records is deprecated; import constraint "
    "record types from apeGmsh.mesh.records instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "ConstraintRecord",
    "NodePairRecord",
    "NodeGroupRecord",
    "InterpolationRecord",
    "SurfaceCouplingRecord",
    "NodeToSurfaceRecord",
]
