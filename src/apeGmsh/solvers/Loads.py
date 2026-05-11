"""Deprecation shim for the Loads relocation (Phase 8.1).

Loads has been split three ways:

* :class:`LoadDef` and its subclasses moved to
  :mod:`apeGmsh.core.loads.defs` (pre-mesh user-facing intent).
* :class:`LoadRecord` and its subclasses moved to
  :mod:`apeGmsh.mesh.records._loads` (post-mesh resolved records).
* :class:`LoadResolver` moved to :mod:`apeGmsh.mesh._load_resolver`
  (broker-layer mesh math).

This module keeps re-exporting the union surface so legacy
``from apeGmsh.solvers.Loads import …`` imports continue to work for
one release cycle with a one-shot :class:`DeprecationWarning`.
"""
from __future__ import annotations

import warnings

from apeGmsh.core.loads.defs import (
    BodyLoadDef,
    FaceLoadDef,
    FaceSPDef,
    GravityLoadDef,
    LineLoadDef,
    LoadDef,
    PointClosestLoadDef,
    PointLoadDef,
    SurfaceLoadDef,
)
from apeGmsh.mesh._load_resolver import LoadResolver
from apeGmsh.mesh.records._loads import (
    ElementLoadRecord,
    LoadRecord,
    NodalLoadRecord,
    SPRecord,
)

warnings.warn(
    "apeGmsh.solvers.Loads is deprecated; import LoadDef subclasses from "
    "apeGmsh.core.loads.defs, LoadRecord subclasses from "
    "apeGmsh.mesh.records, and LoadResolver from "
    "apeGmsh.mesh._load_resolver.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    # Defs
    "LoadDef",
    "PointLoadDef",
    "PointClosestLoadDef",
    "LineLoadDef",
    "SurfaceLoadDef",
    "GravityLoadDef",
    "BodyLoadDef",
    "FaceLoadDef",
    "FaceSPDef",
    # Records
    "LoadRecord",
    "NodalLoadRecord",
    "ElementLoadRecord",
    "SPRecord",
    # Resolver
    "LoadResolver",
]
