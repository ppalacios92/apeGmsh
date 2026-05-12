"""Throwaway benchmarks for viewers/core perf review.

Marked ``@pytest.mark.bench`` so they don't run in normal CI:
    pytest -m bench tests/viewers/test_core_perf.py -s

Targets:
1. ``results_pick._project_points_to_display`` — Python loop over
   VTK ``WorldToDisplay`` per point. Compared against a vectorised
   matrix-multiply via ``camera.GetCompositeProjectionTransformMatrix``.
2. ``color_manager._set_cells_rgb`` per-entity write loop versus
   ``recolor_all`` batched-per-dim write.
3. ``entity_registry.entity_points`` ``mesh.get_cell()`` per-cell
   loop versus a one-shot ``cells_dict`` lookup.
"""
from __future__ import annotations

import time
from typing import Callable

import numpy as np
import pyvista as pv
import pytest


pytestmark = pytest.mark.bench


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _bench(label: str, fn: Callable, repeat: int = 5) -> float:
    # Warmup
    fn()
    samples = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    best_ms = min(samples) * 1000.0
    median_ms = sorted(samples)[len(samples) // 2] * 1000.0
    print(f"  {label:50s} best={best_ms:8.2f} ms  median={median_ms:8.2f} ms")
    return best_ms


def _make_offscreen_plotter(grid: pv.UnstructuredGrid) -> pv.Plotter:
    p = pv.Plotter(off_screen=True, window_size=(800, 600))
    p.add_mesh(grid)
    p.show(auto_close=False)
    return p


# ---------------------------------------------------------------------
# 1. Display projection: VTK loop vs vectorised matmul
# ---------------------------------------------------------------------

def _project_loop(points: np.ndarray, renderer) -> np.ndarray:
    """Replicates results_pick._project_points_to_display."""
    out = np.empty((points.shape[0], 2), dtype=np.float64)
    for i in range(points.shape[0]):
        renderer.SetWorldPoint(
            float(points[i, 0]),
            float(points[i, 1]),
            float(points[i, 2]),
            1.0,
        )
        renderer.WorldToDisplay()
        d = renderer.GetDisplayPoint()
        out[i, 0] = d[0]
        out[i, 1] = d[1]
    return out


def _project_vectorised(points: np.ndarray, renderer) -> np.ndarray:
    """Single matrix multiply — what the loop should do."""
    cam = renderer.GetActiveCamera()
    aspect = renderer.GetTiledAspectRatio()
    M = cam.GetCompositeProjectionTransformMatrix(aspect, 0.0, 1.0)
    # vtkMatrix4x4 -> 4x4 numpy
    arr = np.empty((4, 4), dtype=np.float64)
    for i in range(4):
        for j in range(4):
            arr[i, j] = M.GetElement(i, j)
    n = points.shape[0]
    homog = np.empty((n, 4), dtype=np.float64)
    homog[:, :3] = points
    homog[:, 3] = 1.0
    clip = homog @ arr.T  # (n, 4)
    w = clip[:, 3:4]
    ndc = clip[:, :3] / np.where(w == 0.0, 1.0, w)
    # NDC ([-1,1]) -> display pixels
    size = renderer.GetSize()
    vp = renderer.GetViewport()  # (xmin, ymin, xmax, ymax) in [0,1]
    win_w, win_h = size[0], size[1]
    vp_x0 = vp[0] * win_w
    vp_y0 = vp[1] * win_h
    vp_w = (vp[2] - vp[0]) * win_w
    vp_h = (vp[3] - vp[1]) * win_h
    out = np.empty((n, 2), dtype=np.float64)
    out[:, 0] = vp_x0 + (ndc[:, 0] * 0.5 + 0.5) * vp_w
    out[:, 1] = vp_y0 + (ndc[:, 1] * 0.5 + 0.5) * vp_h
    return out


def test_project_points_to_display_perf():
    print("\n[1] Projection: WorldToDisplay loop vs. matmul")
    rng = np.random.default_rng(0)
    grid = pv.ImageData(dimensions=(50, 50, 50)).cast_to_unstructured_grid()
    p = _make_offscreen_plotter(grid)
    renderer = p.renderer

    for n in (1_000, 10_000, 100_000):
        pts = rng.random((n, 3)) * 100.0
        # Force a render so the camera transform is finalised.
        p.render()
        loop_ms = _bench(
            f"loop  n={n:>6d}",
            lambda: _project_loop(pts, renderer),
        )
        vec_ms = _bench(
            f"matmul n={n:>6d}",
            lambda: _project_vectorised(pts, renderer),
        )
        # Sanity: results agree to within ~1 px (float roundoff)
        a = _project_loop(pts[:64], renderer)
        b = _project_vectorised(pts[:64], renderer)
        max_err = float(np.max(np.abs(a - b)))
        print(f"    n={n} max_pixel_err={max_err:.3f} speedup={loop_ms/vec_ms:.1f}x")
    p.close()


# ---------------------------------------------------------------------
# 2. ColorManager._repaint per-entity vs batched recolor_all
# ---------------------------------------------------------------------

def test_color_repaint_perf():
    print("\n[2] Per-entity colour writes vs. batched recolor_all")
    from apeGmsh.viewers.core.color_manager import ColorManager
    from apeGmsh.viewers.core.entity_registry import EntityRegistry

    rng = np.random.default_rng(0)

    def build(n_entities: int, cells_per_entity: int):
        n_cells = n_entities * cells_per_entity
        # Build a synthetic UnstructuredGrid of n_cells triangles.
        n_pts = n_cells * 3
        pts = rng.random((n_pts, 3))
        cells = np.empty((n_cells, 4), dtype=np.int64)
        cells[:, 0] = 3
        cells[:, 1:] = np.arange(n_pts).reshape(n_cells, 3)
        ctypes = np.full(n_cells, pv.CellType.TRIANGLE, dtype=np.uint8)
        grid = pv.UnstructuredGrid(cells.flatten(), ctypes, pts)
        grid.cell_data["colors"] = np.full(
            (n_cells, 3), 128, dtype=np.uint8,
        )
        cell_to_dt = {
            ci: (2, ci // cells_per_entity) for ci in range(n_cells)
        }
        # Bypass plotter — registry.dim_meshes / dim_actors only need
        # presence for ColorManager paths exercised here.
        reg = EntityRegistry()
        reg.dim_meshes[2] = grid
        reg.dim_actors[2] = object()
        reg._cell_to_dt[2] = cell_to_dt
        for ci, dt in cell_to_dt.items():
            reg._dt_to_cells.setdefault(dt, []).append(ci)
        return reg, grid

    for n_ent in (200, 2_000, 20_000):
        cells_per = 5
        reg, grid = build(n_ent, cells_per)
        cm = ColorManager(reg)
        all_dts = list(reg._dt_to_cells.keys())
        picks = set(all_dts[: n_ent // 10])

        def per_entity():
            # Mimic ColorModeController._repaint
            for dt in all_dts:
                cm.set_entity_state(dt, picked=dt in picks)

        def batched():
            cm.recolor_all(picks)

        per_ms = _bench(f"per-entity n_ent={n_ent:>5d}", per_entity, repeat=3)
        bat_ms = _bench(f"recolor_all n_ent={n_ent:>5d}", batched, repeat=3)
        print(f"    n_ent={n_ent} speedup={per_ms/bat_ms:.1f}x")


# ---------------------------------------------------------------------
# 3. entity_points get_cell loop vs cells_dict
# ---------------------------------------------------------------------

def test_entity_points_perf():
    print("\n[3] entity_points: get_cell loop vs cells_dict lookup")
    from apeGmsh.viewers.core.entity_registry import EntityRegistry

    # 50k triangles, all "owned" by one entity for worst-case.
    rng = np.random.default_rng(0)
    n_cells = 50_000
    n_pts = n_cells * 3
    pts = rng.random((n_pts, 3))
    cells = np.empty((n_cells, 4), dtype=np.int64)
    cells[:, 0] = 3
    cells[:, 1:] = np.arange(n_pts).reshape(n_cells, 3)
    ctypes = np.full(n_cells, pv.CellType.TRIANGLE, dtype=np.uint8)
    grid = pv.UnstructuredGrid(cells.flatten(), ctypes, pts)

    reg = EntityRegistry()
    reg.dim_meshes[2] = grid
    cell_indices = list(range(n_cells))
    dt = (2, 1)
    reg._dt_to_cells[dt] = cell_indices

    def loop_get_cell():
        # Exact code from entity_registry.entity_points
        cell_arr = np.asarray(cell_indices)
        pt_ids = set()
        for ci in cell_arr:
            cell_pt_ids = grid.get_cell(ci).point_ids
            pt_ids.update(cell_pt_ids)
        idx = np.array(sorted(pt_ids))
        return np.asarray(grid.points[idx])

    def vector_offset():
        # Use the connectivity array directly: for an UnstructuredGrid,
        # cells_dict[cell_type] is (n_cells, n_verts) connectivity.
        cd = grid.cells_dict
        all_pts = np.concatenate([v.ravel() for v in cd.values()])
        idx = np.unique(all_pts)
        return grid.points[idx]

    loop_ms = _bench("get_cell loop n_cells=50k", loop_get_cell, repeat=3)
    vec_ms = _bench("cells_dict     n_cells=50k", vector_offset, repeat=3)
    print(f"    speedup={loop_ms/vec_ms:.1f}x")
