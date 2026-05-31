"""Decoupled-node definitions — pre-mesh user-facing intent (ADR 0049).

A *decoupled node* is an auxiliary node that is **not** a Gmsh mesh
vertex: a spring/dashpot ground for SSI, a rigidDiaphragm master, a
control node, or a load/mass anchor.  The user declares one on the
session via ``g.decouple_node(coords=... | point=..., label=...)``; the
FEM factory appends it to the broker's node arrays at extraction time
(where the Gmsh-gathered nodes enter), assigning a deterministic tag
above every mesh node so it is dedup-immune by construction.

PR-4 scope is **identity only** — coordinates, an optional friendly
label, and the resolved tag.  It carries **no** ``ndf``/DOF count: per
the ADR 0049 redesign, DOF lives on the bridge (``ops.ndf``), never on
the session or the neutral broker.

These classes have no Gmsh dependency, no session plumbing, and no
factory methods — pure data containers consumed by the FEM factory.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DecoupledNodeDef:
    """A single user-declared decoupled node (identity only).

    Exactly one of ``coords`` / ``point`` locates the node:

    * ``coords=(x, y, z)`` — an explicit coordinate triple.
    * ``point="label"`` — a geometry point label, resolved to its
      coordinates **at mesh-extraction time** (a snapshot, not tracked
      through later transforms).

    ``label`` is an optional friendly name for the node (distinct from
    ``point``, which is a *geometry* label used only to locate it).

    ``tag`` is ``None`` until the FEM factory resolves the model and
    assigns a deterministic tag; the factory writes it back onto this
    def so the handle returned from ``g.decouple_node(...)`` exposes the
    final tag after meshing.
    """
    coords: tuple[float, float, float] | None = None
    point: str | None = None
    label: str | None = None
    tag: int | None = None


__all__ = ["DecoupledNodeDef"]
