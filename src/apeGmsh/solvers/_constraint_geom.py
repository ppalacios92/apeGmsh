"""Deprecation shim for the constraint-geom relocation (Phase 8.1).

Canonical home is :mod:`apeGmsh.mesh._constraint_resolver._geom`.
"""
from __future__ import annotations

import warnings

from apeGmsh.mesh._constraint_resolver._geom import (
    SHAPE_FUNCTIONS,
    _SpatialIndex,
    _is_inside_parametric,
    _project_point_to_face,
    _shape_quad4,
    _shape_quad8,
    _shape_tri3,
    _shape_tri6,
)

warnings.warn(
    "apeGmsh.solvers._constraint_geom is deprecated; import from "
    "apeGmsh.mesh._constraint_resolver instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "SHAPE_FUNCTIONS",
    "_SpatialIndex",
    "_project_point_to_face",
    "_is_inside_parametric",
    "_shape_tri3",
    "_shape_quad4",
    "_shape_tri6",
    "_shape_quad8",
]
