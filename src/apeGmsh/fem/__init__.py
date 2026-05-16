"""
apeGmsh FEM kernel — shared building blocks used by both the input side
(mesh, mass resolver) and the output side (results, viewers).

This package exists to give shape functions, quadrature rules, and other
element-aware primitives a single home that neither ``mesh/`` nor
``results/`` owns.  Both sides import from here.

Public surface (re-exported at the package level):

``_shape_functions``
    Per-element-type shape functions ``N`` and derivatives ``dN``,
    isoparametric mapping helpers, Jacobian determinants, and the
    ``get_shape_functions(elem_type)`` dispatch.  Covers line2, tri3,
    tri6, quad4, quad8, quad9, tet4, tet10, hex8, hex20, hex27, wedge6.
"""
from __future__ import annotations

from . import _shape_functions

__all__ = ["_shape_functions"]
