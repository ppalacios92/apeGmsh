"""Deprecation shim for the constraint-resolver relocation (Phase 8.1).

Canonical home is :mod:`apeGmsh.mesh._constraint_resolver`.
"""
from __future__ import annotations

import warnings

from apeGmsh.mesh._constraint_resolver import ConstraintResolver

warnings.warn(
    "apeGmsh.solvers._constraint_resolver is deprecated; import "
    "ConstraintResolver from apeGmsh.mesh._constraint_resolver instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["ConstraintResolver"]
