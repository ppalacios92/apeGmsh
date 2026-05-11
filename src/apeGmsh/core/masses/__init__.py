"""apeGmsh.core.masses — Model-level mass definitions.

Hosts the user-facing :class:`MassDef` subclasses that describe
*intent* at the geometry/PG/part level before meshing.  The
post-mesh **resolved** counterpart lives in
:mod:`apeGmsh.mesh.records._masses`; the machinery that translates
defs into records lives in :mod:`apeGmsh.mesh._mass_resolver`.
"""

from __future__ import annotations

from .defs import (
    LineMassDef,
    MassDef,
    PointMassDef,
    SurfaceMassDef,
    VolumeMassDef,
)


__all__ = [
    "MassDef",
    "PointMassDef",
    "LineMassDef",
    "SurfaceMassDef",
    "VolumeMassDef",
]
