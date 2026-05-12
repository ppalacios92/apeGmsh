"""Throwaway perf research bench (NOT for CI).

Run with:
    pytest tests/viewers/test_scene_perf_research.py -m bench -s

Targets:
1. build_fem_scene on a non-trivial mesh — measure baseline + isolate
   the per-group dense lookup-table rebuild.
2. build_mesh_scene — measure baseline + isolate the second
   gmsh.model.mesh.getNodes(dim, tag, includeBoundary=True) loop.
3. mesh_viewer element-label centroid python-loop equivalent.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pyvista as pv
import pytest


def _build_box_mesh(g, n_per_side: int = 16):
    """Build a meshed cube, return apeGmsh session with mesh in place."""
    g.model.geometry.add_box(
        x=0.0, y=0.0, z=0.0, dx=1.0, dy=1.0, dz=1.0,
        label="cube",
    )
    g.physical.add_volume(["cube"], name="Solid")
    h = 1.0 / n_per_side
    g.mesh.sizing.set_global_size(h)
    g.mesh.generation.generate(dim=3)
    return g


@pytest.mark.bench
def test_build_fem_scene_baseline(g):
    from apeGmsh.viewers.scene.fem_scene import build_fem_scene
    _build_box_mesh(g, n_per_side=20)
    fem = g.mesh.queries.get_fem_data(dim=3)

    n_groups = len(list(fem.elements))
    n_nodes = len(list(fem.nodes.ids))
    n_elems = sum(len(grp) for grp in fem.elements)
    print(f"\n[fem_scene fixture] groups={n_groups}, nodes={n_nodes}, elems={n_elems}")

    # Warmup
    build_fem_scene(fem)
    n = 5
    t0 = time.perf_counter()
    for _ in range(n):
        build_fem_scene(fem)
    elapsed_ms = (time.perf_counter() - t0) / n * 1000.0
    print(f"build_fem_scene baseline: {elapsed_ms:.2f} ms / call")


@pytest.mark.bench
def test_fem_scene_lookup_table_rebuild_cost(g):
    """Show the cost of rebuilding id_to_idx_dense per group vs once."""
    _build_box_mesh(g, n_per_side=20)
    fem = g.mesh.queries.get_fem_data(dim=3)

    raw_node_ids = np.asarray(list(fem.nodes.ids), dtype=np.int64)
    n_nodes = raw_node_ids.shape[0]
    max_id = int(raw_node_ids.max())

    groups = list(fem.elements)
    n_groups = len(groups)

    # Measure the per-group rebuild path (current code).
    n = 50
    t0 = time.perf_counter()
    for _ in range(n):
        for _g in groups:
            id_to_idx_dense = np.full(max_id + 2, -1, dtype=np.int64)
            id_to_idx_dense[raw_node_ids] = np.arange(n_nodes, dtype=np.int64)
    per_group_ms = (time.perf_counter() - t0) / n * 1000.0

    # Measure the "build once" path.
    t0 = time.perf_counter()
    for _ in range(n):
        id_to_idx_dense = np.full(max_id + 2, -1, dtype=np.int64)
        id_to_idx_dense[raw_node_ids] = np.arange(n_nodes, dtype=np.int64)
    once_ms = (time.perf_counter() - t0) / n * 1000.0

    print(
        f"\n[fem_scene lookup] groups={n_groups}, nodes={n_nodes}, "
        f"max_id={max_id}\n"
        f"  rebuild-per-group : {per_group_ms:.2f} ms\n"
        f"  build-once        : {once_ms:.2f} ms\n"
        f"  savings/call      : {per_group_ms - once_ms:.2f} ms"
    )


@pytest.mark.bench
def test_mesh_scene_redundant_getnodes(g):
    """mesh_scene.py calls gmsh.model.mesh.getNodes(dim, tag,
    includeBoundary=True) twice for every entity: once in the actor
    loop (line ~408) and again in the per-dim node-cloud loop
    (~518). Measure the cost of the second pass alone.
    """
    import gmsh
    _build_box_mesh(g, n_per_side=20)

    dims = [1, 2, 3]
    n = 5
    t0 = time.perf_counter()
    for _ in range(n):
        for d in dims:
            for _, ent_tag in gmsh.model.getEntities(dim=d):
                try:
                    gmsh.model.mesh.getNodes(
                        dim=d, tag=ent_tag, includeBoundary=True,
                    )
                except Exception:
                    pass
    redundant_ms = (time.perf_counter() - t0) / n * 1000.0

    n_ents = sum(len(gmsh.model.getEntities(dim=d)) for d in dims)
    print(
        f"\n[mesh_scene redundant getNodes] dims={dims}, "
        f"entities={n_ents}\n"
        f"  second-pass cost: {redundant_ms:.2f} ms / build"
    )


@pytest.mark.bench
def test_mesh_viewer_label_centroid_loop(g):
    """Replicate the per-element python loop in mesh_viewer
    `_toggle_show_element_ids` that builds centroids by iterating
    elem_data and looking up coords node-by-node.
    """
    from apeGmsh.viewers.scene.mesh_scene import build_mesh_scene
    _build_box_mesh(g, n_per_side=20)

    plotter = pv.Plotter(off_screen=True)
    try:
        scene = build_mesh_scene(plotter, dims=[1, 2, 3])
    finally:
        pass  # close after measurement

    n_elems = len(scene.elem_data)
    print(f"\n[mesh_viewer label loop] elements={n_elems}")

    # Current python-loop path
    t0 = time.perf_counter()
    centers, labels = [], []
    for elem_tag, info in scene.elem_data.items():
        nodes = info.get("nodes", [])
        if not nodes:
            continue
        coords = []
        for nid in nodes:
            idx = scene.node_tag_to_idx.get(int(nid))
            if idx is not None:
                coords.append(scene.node_coords[idx])
        if coords:
            centers.append(np.mean(coords, axis=0))
            labels.append(str(elem_tag))
    py_ms = (time.perf_counter() - t0) * 1000.0

    # Vectorized path: build (n_elems, npe) connectivity once and
    # use scene.tag_to_idx (already a dense array on MeshSceneData).
    t0 = time.perf_counter()
    # Group elements by node-count first (varying per type).
    by_npe: dict[int, list[tuple[int, list[int]]]] = {}
    for et, info in scene.elem_data.items():
        nlist = info.get("nodes") or []
        if not nlist:
            continue
        by_npe.setdefault(len(nlist), []).append((et, nlist))
    centers_v, labels_v = [], []
    tag_to_idx = scene.tag_to_idx
    coords_arr = scene.node_coords
    max_t = len(tag_to_idx) - 1 if len(tag_to_idx) > 0 else -1
    for npe, items in by_npe.items():
        tags = np.fromiter((it[0] for it in items), dtype=np.int64, count=len(items))
        node_mat = np.empty((len(items), npe), dtype=np.int64)
        for i, (_t, nl) in enumerate(items):
            node_mat[i] = nl
        in_range = (node_mat >= 0) & (node_mat <= max_t)
        all_in = in_range.all(axis=1)
        if not all_in.any():
            continue
        idx_mat = tag_to_idx[node_mat[all_in]]
        valid = (idx_mat >= 0).all(axis=1)
        idx_mat = idx_mat[valid]
        if idx_mat.size == 0:
            continue
        c = coords_arr[idx_mat].mean(axis=1)
        centers_v.extend(c.tolist())
        labels_v.extend(str(t) for t in tags[all_in][valid])
    vec_ms = (time.perf_counter() - t0) * 1000.0

    print(
        f"  python loop   : {py_ms:.2f} ms\n"
        f"  vectorized    : {vec_ms:.2f} ms\n"
        f"  speedup       : {py_ms / max(vec_ms, 1e-6):.1f}x"
    )
    plotter.close()
