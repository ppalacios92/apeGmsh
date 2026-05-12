"""Deprecation shim for the element capability map relocation (Phase 8.3b).

Canonical home is :mod:`apeGmsh.opensees._element_capabilities`.  The
registry is OpenSees-class metadata; it lives next to the response
catalog so the bridge owns its element vocabulary in one place.
"""
from __future__ import annotations

import warnings

from apeGmsh.opensees._element_capabilities import (
    _DEFAULTS,
    _ELEM_REGISTRY,
    _ElemSpec,
    _ETYPE_INFO,
    _render_py,
    _render_tcl,
)

__all__ = [
    "_DEFAULTS",
    "_ELEM_REGISTRY",
    "_ElemSpec",
    "_ETYPE_INFO",
    "_render_py",
    "_render_tcl",
]

warnings.warn(
    "apeGmsh.solvers._element_specs is deprecated; import from "
    "apeGmsh.opensees._element_capabilities instead.",
    DeprecationWarning,
    stacklevel=2,
)
