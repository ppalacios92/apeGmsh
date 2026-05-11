"""Deprecation shim for the ConstraintKind / LoadKind relocation (Phase 8.1).

Canonical home is :mod:`apeGmsh.mesh.records._kinds`.
"""
from __future__ import annotations

import warnings

from apeGmsh.mesh.records._kinds import ConstraintKind, LoadKind

warnings.warn(
    "apeGmsh.solvers._kinds is deprecated; import ConstraintKind and "
    "LoadKind from apeGmsh.mesh.records instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["ConstraintKind", "LoadKind"]
