"""Scene-build -> ``scene_ir`` adapter (ADR 0042, Phase R-A).

Emits a :class:`~apeGmsh.viewers.scene_ir.MeshLayer` from a
:class:`~apeGmsh.viewers.data.ViewerData` substrate.  This is the
"scene build" half of R-A's first routed surface: the same linearised
geometry ``build_fem_scene`` produces, expressed as backend-neutral IR
instead of a ``pyvista`` grid.

The gmsh -> linear-VTK mapping is *not* duplicated here — it is
imported from :mod:`apeGmsh.viewers.scene.fem_scene` so the two paths
can never drift.  This adapter only re-expresses the result as
``CellBlocks`` (neutral string tokens) + an ``element_id`` cell field,
in a cell order that matches the grid a backend rebuilds from it.

Verified for parity against ``build_fem_scene`` in
``tests/test_scene_ir_adapter_parity.py``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import numpy as np

from apeGmsh.viewers.scene_ir import (
    CellBlocks,
    ColorSpec,
    MeshLayer,
    PointSet,
    ScalarField,
)

from .fem_scene import GMSH_LINEAR, GMSH_LINEAR_FALLBACK

if TYPE_CHECKING:
    from apeGmsh.viewers.data import ViewerData

# Inverse of PyVistaQtBackend.TOKEN_TO_VTK — VTK cell-type int back to
# the neutral token the IR carries. Defined here (not imported from the
# backend) so the adapter, like the IR, stays pyvista-free.
_VTK_TO_TOKEN: dict[int, str] = {
    1: "vertex",
    3: "line",
    5: "triangle",
    9: "quad",
    10: "tetra",
    12: "hexahedron",
    13: "wedge",
    14: "pyramid",
}


def mesh_layer_from_viewer_data(
    view: "ViewerData",
    *,
    layer_id: str = "fem",
    element_rgb: Optional[np.ndarray] = None,
) -> MeshLayer:
    """Build a :class:`MeshLayer` from a :class:`ViewerData` substrate.

    Parameters
    ----------
    view
        The viewer-facing structural snapshot (``ViewerData.from_fem``
        / ``from_h5``); a raw FEMData also works via duck typing, as in
        :func:`build_fem_scene`.
    layer_id
        Stable id for the emitted layer.
    element_rgb
        Optional ``(n_cells, 3)`` per-cell RGB (float ``[0, 1]`` or
        ``uint8``), aligned with the emitted cell order.  When given,
        the layer's :class:`ColorSpec` is ``per_entity_rgb`` — this is
        the IR-level expression of a ColorMode assignment.  Build it
        from the same cell order this adapter emits (token-grouped, in
        group-iteration order) — read it back off the returned layer's
        ``element_id`` field if in doubt.
    """
    raw_node_ids = np.asarray(list(view.nodes.ids), dtype=np.int64)
    raw_node_coords = np.asarray(view.nodes.coords, dtype=np.float64)
    n_nodes = raw_node_ids.shape[0]

    if n_nodes:
        max_id = int(raw_node_ids.max())
        id_to_idx = np.full(max_id + 2, -1, dtype=np.int64)
        id_to_idx[raw_node_ids] = np.arange(n_nodes, dtype=np.int64)
    else:
        id_to_idx = None

    # Accumulate connectivity + element ids per neutral token, in
    # group-iteration order. dict insertion order == grid cell order a
    # backend rebuilds, so the element_id field below stays aligned.
    conn_by_token: dict[str, list[np.ndarray]] = {}
    eid_by_token: dict[str, list[np.ndarray]] = {}

    for group in view.elements:
        etype = group.element_type
        code = int(etype.code)
        mapping = GMSH_LINEAR.get(code)
        if mapping is None:
            mapping = GMSH_LINEAR_FALLBACK.get((int(etype.dim), int(etype.npe)))
        if mapping is None:
            continue  # exotic type — dropped, same as build_fem_scene
        vtk_type, n_corner = mapping
        token = _VTK_TO_TOKEN[vtk_type]

        conn = np.asarray(group.connectivity, dtype=np.int64)
        ids = np.asarray(group.ids, dtype=np.int64)
        if conn.ndim != 2 or conn.shape[1] < n_corner:
            continue
        corner = conn[:, :n_corner]
        mapped = id_to_idx[corner] if id_to_idx is not None else corner

        conn_by_token.setdefault(token, []).append(mapped)
        eid_by_token.setdefault(token, []).append(ids)

    blocks: dict[str, np.ndarray] = {}
    eid_chunks: list[np.ndarray] = []
    for token, chunks in conn_by_token.items():
        blocks[token] = np.concatenate(chunks, axis=0)
        eid_chunks.append(np.concatenate(eid_by_token[token], axis=0))

    element_ids = (
        np.concatenate(eid_chunks) if eid_chunks else np.array([], dtype=np.int64)
    )

    color = ColorSpec()
    if element_rgb is not None:
        color = ColorSpec(mode="per_entity_rgb", entity_rgb=element_rgb)

    return MeshLayer(
        layer_id=layer_id,
        points=PointSet(raw_node_coords),
        cells=CellBlocks(blocks),
        fields=(
            ScalarField("element_id", element_ids, location="cell"),
        )
        if element_ids.size
        else (),
        color=color,
    )


__all__ = ["mesh_layer_from_viewer_data"]
