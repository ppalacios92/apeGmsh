"""apeGmsh.core.loads — Model-level load definitions.

Hosts the user-facing :class:`LoadDef` subclasses that describe
*intent* at the geometry/PG/part level before meshing.  The
post-mesh **resolved** counterparts live in
:mod:`apeGmsh.mesh.records._loads`; the machinery that translates
defs into records lives in :mod:`apeGmsh.mesh._load_resolver`.
"""

from __future__ import annotations

from .defs import (
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


__all__ = [
    "LoadDef",
    "PointLoadDef",
    "PointClosestLoadDef",
    "LineLoadDef",
    "SurfaceLoadDef",
    "GravityLoadDef",
    "BodyLoadDef",
    "FaceLoadDef",
    "FaceSPDef",
]
