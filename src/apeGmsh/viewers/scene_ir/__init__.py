"""Backend-agnostic scene description for the viewer subsystem.

The render-side seam introduced by
[ADR 0042](../../opensees/architecture/decisions/0042-render-backend-seam.md):
domain logic emits :class:`SceneLayer` value types and drives a
:class:`RenderBackend`; backends (PyVistaQt desktop, trame web) own all
VTK/pyvista/trame construction.

INV-1: this package imports neither ``vtk`` nor ``pyvista``.  Enforced
by ``tests/test_scene_ir_pure.py``.
"""
from __future__ import annotations

from ._backend import LayerHandle, RenderBackend
from ._layers import (
    CellBlocks,
    ColorSpec,
    GlyphLayer,
    LabelLayer,
    LutSpec,
    MeshLayer,
    PointSet,
    ScalarBarSpec,
    ScalarField,
    SceneLayer,
    VisibilityMask,
)

__all__ = [
    # value types
    "PointSet",
    "CellBlocks",
    "ScalarField",
    "LutSpec",
    "ColorSpec",
    "VisibilityMask",
    "MeshLayer",
    "GlyphLayer",
    "LabelLayer",
    "ScalarBarSpec",
    "SceneLayer",
    # protocols
    "LayerHandle",
    "RenderBackend",
]
