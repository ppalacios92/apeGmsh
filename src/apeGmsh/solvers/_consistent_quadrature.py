"""Deprecation shim for the consistent-quadrature relocation (Phase 8.1).

Canonical home is :mod:`apeGmsh.mesh._consistent_quadrature`.
"""
from __future__ import annotations

import warnings

from apeGmsh.mesh._consistent_quadrature import (
    _SUPPORTED_EDGE_NODES,
    _SUPPORTED_FACE_NODES,
    integrate_edge,
    integrate_face,
)

warnings.warn(
    "apeGmsh.solvers._consistent_quadrature is deprecated; import from "
    "apeGmsh.mesh._consistent_quadrature instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "integrate_edge",
    "integrate_face",
    "_SUPPORTED_EDGE_NODES",
    "_SUPPORTED_FACE_NODES",
]
