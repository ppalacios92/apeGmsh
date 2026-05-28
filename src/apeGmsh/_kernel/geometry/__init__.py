"""apeGmsh._kernel.geometry — pure-numpy geometric utilities.

Leaf module: no apeGmsh imports above ``_kernel``; no gmsh imports.
Holds geometric primitives that are reusable across the resolver and
viewer layers without dragging in domain-specific composites.

Currently houses:

* :mod:`_host_decomposition` — Kuhn decomposition of hex / prism /
  pyramid host elements into right-handed tetrahedra (used by the
  embedded constraint resolver in both build phase and chain phase).

No submodule is re-exported here — explicit imports keep the
dependency graph readable.
"""
from __future__ import annotations
