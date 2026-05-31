"""Coincident-pick tiebreak for the BREP viewer (ADR 0045 S5-tiebreak).

A volume's visible boundary is a ``dim=2`` surface actor coincident with the
``dim=3`` volume actor. With every dim active, a ``vtkCellPicker`` ray hits the
surface on top, so a click on a solid's face used to select the *face* even
though the volume is equally under the cursor.

This module turns one resolved pick into the ordered stack of entities that are
geometrically coincident there, highest dim first. The viewer selects the head
(highest active dim — the volume) by default, so a click on a solid's boundary
face picks the solid, not the face. The ordered tail is the basis for a future
"select other" cycle (deferred — Qt focus traversal swallows the Tab key).

Pure and VTK-free: the caller supplies the face→volume adjacency as a callable,
so the resolution is unit-testable without a renderer.
"""
from __future__ import annotations

from typing import Callable, Iterable, List, Tuple

DimTag = Tuple[int, int]


def coincident_stack(
    dt: DimTag,
    active_dims: Iterable[int],
    volumes_of_face: Callable[[DimTag], List[DimTag]],
) -> List[DimTag]:
    """Ordered, active-filtered coincident pick candidates, highest dim first.

    Parameters
    ----------
    dt
        The resolved ``(dim, tag)`` the picker returned.
    active_dims
        The dims currently honoured by the filter (the ``FilterController``
        active set). Only candidates of an active dim are included.
    volumes_of_face
        ``(2, tag) -> [(3, vtag), ...]`` — the owning volume(s) of a boundary
        face (empty for a free surface). For an internal face shared by two
        volumes this returns both; they precede the face in the stack so Tab
        can reach either.

    Returns
    -------
    list of ``(dim, tag)``
        Deduped, highest-dim-first. The head is the default selection. A
        non-face hit (or a face with no active owning volume) yields just the
        hit entity. Empty only if ``dt``'s own dim is inactive (the picker
        gate normally prevents that).
    """
    active = {int(d) for d in active_dims}
    dim, tag = int(dt[0]), int(dt[1])

    out: List[DimTag] = []
    if dim == 2 and 3 in active:
        vols = [
            (int(v[0]), int(v[1]))
            for v in volumes_of_face((2, tag))
            if int(v[0]) in active
        ]
        out.extend(sorted(set(vols)))    # stable order for the internal-face case
    if dim in active:
        out.append((dim, tag))

    seen: set = set()
    res: List[DimTag] = []
    for t in out:
        if t not in seen:
            seen.add(t)
            res.append(t)
    return res


__all__ = ["coincident_stack"]
