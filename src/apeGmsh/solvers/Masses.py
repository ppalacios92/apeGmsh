"""Deprecation shim for the Masses relocation (Phase 8.1).

Masses has been split three ways:

* :class:`MassDef` and its subclasses moved to
  :mod:`apeGmsh.core.masses.defs` (pre-mesh user-facing intent).
* :class:`MassRecord` moved to
  :mod:`apeGmsh.mesh.records._masses` (post-mesh resolved record).
* :class:`MassResolver` moved to :mod:`apeGmsh.mesh._mass_resolver`
  (broker-layer mesh math).

This module keeps re-exporting the union surface so legacy
``from apeGmsh.solvers.Masses import …`` imports continue to work for
one release cycle with a one-shot :class:`DeprecationWarning`.
"""
from __future__ import annotations

import warnings

from apeGmsh.core.masses.defs import (
    LineMassDef,
    MassDef,
    PointMassDef,
    SurfaceMassDef,
    VolumeMassDef,
)
from apeGmsh.mesh._mass_resolver import MassResolver
from apeGmsh.mesh.records._masses import MassRecord

warnings.warn(
    "apeGmsh.solvers.Masses is deprecated; import MassDef subclasses from "
    "apeGmsh.core.masses.defs, MassRecord from apeGmsh.mesh.records, and "
    "MassResolver from apeGmsh.mesh._mass_resolver.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "MassDef",
    "PointMassDef",
    "LineMassDef",
    "SurfaceMassDef",
    "VolumeMassDef",
    "MassRecord",
    "MassResolver",
]
