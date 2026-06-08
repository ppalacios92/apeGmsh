"""TwoNodeLink element — typed primitive for ``element twoNodeLink``.

OpenSees command::

    element twoNodeLink tag iNode jNode \
        -mat $matTag1 ... -dir $dir1 ... \
        [-orient <$x1 $x2 $x3> $y1 $y2 $y3] \
        [-pDelta $Mratios...] \
        [-shearDist $sDratios...] \
        [-doRayleigh] \
        [-mass $m]

The two-node "spring" cousin of :class:`ZeroLength`: it takes the same
list of ``(material, dof)`` pairs but is **not** zero-length-only — it
reads the nodal geometry to compute a finite length, which enables the
moment-arm coupling (``-shearDist``) and geometric P-Delta stiffness
(``-pDelta``) that independent ZeroLength springs cannot express. It is
also the only spring element that carries lumped mass (``-mass``).

Two contrasts with :class:`ZeroLength` worth noting:

* ``-doRayleigh`` is a **bare flag** (no value) — its presence turns the
  *extra* Rayleigh term on. Material damping (a ``Viscous`` etc.) is
  applied **regardless** of the flag (``TwoNodeLink.cpp:731-734``).
* Local x is derived from the node geometry when the nodes are not
  coincident; ``-orient`` then supplies only the y'-vector (3 values).
  For coincident nodes pass the full ``(x, y')`` 6-tuple.

Element fan-out follows the same contract as :mod:`.zero_length`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .._internal.tag_resolution import (
    current_element_nodes,
    resolve_tag,
)
from .._internal.types import (
    Element,
    Primitive,
    UniaxialMaterial,
)
from .zero_length import NodeRef, ZeroLengthMatDir, _validate_pg_xor_nodes

if TYPE_CHECKING:
    from ..emitter.base import Emitter


__all__ = ["TwoNodeLink"]


@dataclass(frozen=True, kw_only=True, slots=True)
class TwoNodeLink(Element):
    """``element twoNodeLink`` — finite-length coupled (material, dof) springs.

    Parameters
    ----------
    pg
        Physical-group label whose 2-node "line" entries receive this
        spec.  Mutually exclusive with ``nodes``.
    nodes
        Node-pair form (ADR 0049): ``(node_i, node_j)`` of :data:`NodeRef`
        endpoints, wiring a single link directly without a meshed line.
        Mutually exclusive with ``pg``.
    mat_dirs
        Tuple of :class:`ZeroLengthMatDir` value objects (reused from
        the ZeroLength family), each binding a uniaxial material to one
        local DOF. At least one pair is required.
    orient
        Optional ``(y1, y2, y3)`` (local y'-vector only, when local x is
        taken from geometry) **or** ``(x1, x2, x3, y1, y2, y3)`` (full
        local frame, required for coincident nodes). ``None`` uses the
        OpenSees default.
    p_delta
        Optional P-Delta moment ratios — ``(rMz1, rMz2)`` in 2D or
        ``(rMy1, rMy2, rMz1, rMz2)`` in 3D — adding geometric stiffness
        and distributing the P-Delta moments.
    shear_dist
        Optional shear-distance ratios in ``[0, 1]`` placing the shear
        resultant along the link — ``(sDy,)`` in 2D or ``(sDy, sDz)`` in
        3D (OpenSees defaults each to ``0.5``).
    do_rayleigh
        Include the element in the *extra* Rayleigh damping term
        (``-doRayleigh``, a bare flag). Defaults ``False``. Note that
        material damping is applied regardless of this flag.
    mass
        Optional lumped element mass (``-mass``), split 50/50 on the two
        nodes, translational DOFs only. ``None`` omits the flag (mass 0).
    """

    pg: str | None = None
    nodes: tuple[NodeRef, NodeRef] | None = None
    mat_dirs: tuple[ZeroLengthMatDir, ...] = ()
    orient: tuple[float, ...] | None = None
    p_delta: tuple[float, ...] | None = None
    shear_dist: tuple[float, ...] | None = None
    do_rayleigh: bool = False
    mass: float | None = None

    def __post_init__(self) -> None:
        _validate_pg_xor_nodes("TwoNodeLink", self.pg, self.nodes)
        if not self.mat_dirs:
            raise ValueError(
                "TwoNodeLink: at least one (material, dof) pair required."
            )
        if self.orient is not None and len(self.orient) not in (3, 6):
            raise ValueError(
                "TwoNodeLink: orient must be a 3-tuple (y' only) or a "
                f"6-tuple (x, y'), got length {len(self.orient)}."
            )
        if self.p_delta is not None and len(self.p_delta) not in (2, 4):
            raise ValueError(
                "TwoNodeLink: p_delta must be length 2 (2D) or 4 (3D), "
                f"got {len(self.p_delta)}."
            )
        if self.shear_dist is not None and len(self.shear_dist) not in (1, 2):
            raise ValueError(
                "TwoNodeLink: shear_dist must be length 1 (2D) or 2 (3D), "
                f"got {len(self.shear_dist)}."
            )
        if self.mass is not None and self.mass < 0:
            raise ValueError(
                f"TwoNodeLink: mass must be >= 0, got {self.mass!r}"
            )

    def dependencies(self) -> tuple[Primitive, ...]:
        # Multiple springs can share a material — dedup by id, keep order.
        seen: dict[int, UniaxialMaterial] = {}
        for md in self.mat_dirs:
            seen.setdefault(id(md.material), md.material)
        return tuple(seen.values())

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        nodes = current_element_nodes(emitter)
        if len(nodes) != 2:
            raise ValueError(
                f"TwoNodeLink: expected 2 node tags, got {len(nodes)}"
            )
        mat_tags = tuple(
            resolve_tag(emitter, md.material) for md in self.mat_dirs
        )
        dirs = tuple(md.dof for md in self.mat_dirs)
        args: list[int | float | str] = [
            *nodes,
            "-mat", *mat_tags,
            "-dir", *dirs,
        ]
        if self.orient is not None:
            args += ["-orient", *self.orient]
        if self.p_delta is not None:
            args += ["-pDelta", *self.p_delta]
        if self.shear_dist is not None:
            args += ["-shearDist", *self.shear_dist]
        if self.do_rayleigh:
            # Bare flag — no value (TwoNodeLink.cpp:175-176).
            args += ["-doRayleigh"]
        if self.mass is not None:
            args += ["-mass", self.mass]
        emitter.element("twoNodeLink", tag, *args)
