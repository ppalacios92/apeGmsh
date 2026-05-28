"""Render backends — concrete implementers of
:class:`~apeGmsh.viewers.scene_ir.RenderBackend`.

Each backend consumes the backend-agnostic ``scene_ir`` value types and
owns *all* VTK / pyvista / trame construction (ADR 0042, INV-2).  The
domain layer never imports a backend's render library directly.

``PyVistaQtBackend`` is the reference (desktop) backend.  ``TrameBackend``
(web/Jupyter) lands in Phase R-C.
"""
from __future__ import annotations

from .pyvista_qt import (
    PyVistaQtBackend,
    apply_visibility_mask,
    mesh_layer_to_grid,
)

__all__ = [
    "PyVistaQtBackend",
    "mesh_layer_to_grid",
    "apply_visibility_mask",
]
