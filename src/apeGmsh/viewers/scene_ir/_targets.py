"""Selection-target value types — ADR 0045 §Decision Part 1.

The ``vtkSelectionNode`` analog: a VTK-free, frozen, hashable identity
for one selected thing, **uniform across the three viewers' substrates**
(model BREP / mesh topology / results topology) without collapsing their
id spaces (INV-3). One ``SelectionState`` + ``SelectionLog`` (S3) serve
all three because the *type* is unified even though the *values* are not.

INV-1 (ADR 0042, extended by ADR 0045): imports neither ``vtk`` nor
``pyvista``. Enforced by ``tests/test_scene_ir_pure.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Substrate(Enum):
    """Which of the three pick substrates a target refers to.

    Kept **distinct** so a BREP ``(dim, occ_tag)``, a mesh
    ``node_id`` / ``element_id``, and a results ``element_id`` never
    collide in one id space (INV-3).
    """

    MODEL_BREP = "model_brep"      # (dim, occ_tag) — today's DimTag
    MESH_TOPO = "mesh_topo"        # FE node_id / element_id
    RESULTS_TOPO = "results_topo"  # element_id / (element_id, gp_index) / fiber


# The dimensional classes the 0/1/2/3/4 FilterController scopes on:
# 0 = vertex/node, 1 = edge/line, 2 = face, 3 = volume.
_VALID_DIMS = frozenset({0, 1, 2, 3})


@dataclass(frozen=True)
class SelectionTarget:
    """One selected entity — frozen + hashable, for set membership in a
    ``SelectionState``.

    Fields
    ------
    substrate
        Which viewer substrate (`Substrate`); keeps id spaces distinct.
    dim
        Dimensional class (0=vertex/node, 1=edge/line, 2=face,
        3=volume) — what the ``0/1/2/3/4`` filter scopes on.
    key
        The substrate-native identity: ``occ_tag`` for BREP,
        ``node_id`` / ``element_id`` for mesh, ``element_id`` for
        results.
    sub
        A secondary index (e.g. ``gp_index`` for a gauss target);
        ``None`` for a plain entity.
    parent
        Links a gauss target to its element / a boundary face to its
        volume — the cross-dim flush channel (additive widening, INV-8).
        ``None`` for a top-level target.

    ``frozen=True`` with the default ``eq`` / ``hash`` makes targets
    usable as set/dict members (all fields are hashable: ``Substrate``
    is an enum, the ints are ints, ``parent`` recurses). Equality is by
    value, so two targets naming the same entity compare equal — the
    behaviour a selection set needs.
    """

    substrate: Substrate
    dim: int
    key: int
    sub: Optional[int] = None
    parent: Optional["SelectionTarget"] = None

    def __post_init__(self) -> None:
        if not isinstance(self.substrate, Substrate):
            raise TypeError(
                "SelectionTarget.substrate must be a Substrate; got "
                f"{type(self.substrate).__name__}."
            )
        dim = int(self.dim)
        if dim not in _VALID_DIMS:
            raise ValueError(
                f"SelectionTarget.dim must be one of {sorted(_VALID_DIMS)}; "
                f"got {self.dim!r}."
            )
        object.__setattr__(self, "dim", dim)
        object.__setattr__(self, "key", int(self.key))
        if self.sub is not None:
            object.__setattr__(self, "sub", int(self.sub))


__all__ = ["Substrate", "SelectionTarget"]
