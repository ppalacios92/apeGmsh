"""VisualDataStore - eager float16 cache for the post-solve viewer.

Covers the pure-visual performance layer introduced to stop the time
scrubber re-reading the full (T, N) HDF5 dataset every frame:
  * load_stage materializes every node + gauss component as float16
    and records per-component (vmin, vmax) in the same pass;
  * the byte budget gates only the eager pre-fetch (lazy access still
    serves a live request past the cap);
  * ContourDiagram slices the cached float16 row on update_to_step
    and falls back to the per-step read path when no store is stamped.

Headless: uses NativeWriter + an offscreen plotter, no Qt window.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from apeGmsh.results import Results
from apeGmsh.results.writers import NativeWriter
from apeGmsh.viewers.diagrams import (
    ContourDiagram,
    ContourStyle,
    DiagramSpec,
    SlabSelector,
)
from apeGmsh.viewers.diagrams._visual_store import VisualDataStore
from apeGmsh.viewers.scene.fem_scene import build_fem_scene

from tests.conftest import _open_model_from_h5


# ---------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------
@pytest.fixture
def results_with_known_disp(g, tmp_path: Path):
    """Native HDF5 with displacement_z = nid + t * 1000 per (node, step)."""
    g.model.geometry.add_box(0, 0, 0, 1, 1, 1, label="cube")
    g.physical.add_volume("cube", name="Body")
    g.mesh.sizing.set_global_size(2.0)
    g.mesh.generation.generate(dim=3)
    fem = g.mesh.queries.get_fem_data(dim=3)
    node_ids = np.asarray(fem.nodes.ids, dtype=np.int64)
    n_nodes = node_ids.size
    n_steps = 4

    values = np.zeros((n_steps, n_nodes), dtype=np.float64)
    for t in range(n_steps):
        values[t] = node_ids + t * 1000.0

    path = tmp_path / "known_disp.h5"
    with NativeWriter(path) as w:
        w.open(fem=fem)
        sid = w.begin_stage(
            name="grav", kind="static",
            time=np.arange(n_steps, dtype=np.float64),
        )
        w.write_nodes(
            sid, "partition_0",
            node_ids=node_ids,
            components={"displacement_z": values},
        )
        w.end_stage()
    return Results.from_native(path, model=_open_model_from_h5(path))


def _stage_id(results) -> str:
    return results.stages[0].id


def _make_spec(component="displacement_z") -> DiagramSpec:
    return DiagramSpec(
        kind="contour",
        selector=SlabSelector(component=component),
        style=ContourStyle(),
    )


# ---------------------------------------------------------------------
# Store unit tests
# ---------------------------------------------------------------------
def test_load_stage_materializes_float16_and_clim(results_with_known_disp):
    store = VisualDataStore()
    sid = _stage_id(results_with_known_disp)
    store.load_stage(results_with_known_disp, sid)

    slab = store.nodes_slab(results_with_known_disp.stage(sid), sid, "displacement_z")
    assert slab is not None
    # float16 resident (the whole point: half-width, slice-not-read).
    assert slab.values.dtype == np.float16
    assert slab.values.shape == (4, len(results_with_known_disp.fem.nodes.ids))

    # color limits match the global finite min/max of the float16 slab.
    clim = store.color_limits(sid, "displacement_z")
    assert clim is not None
    finite = slab.values[np.isfinite(slab.values)]
    assert clim == (float(finite.min()), float(finite.max()))


def test_byte_budget_gates_eager_but_lazy_still_serves(results_with_known_disp):
    # A zero ceiling blocks eager pre-fetch entirely.
    store = VisualDataStore(byte_budget=0)
    sid = _stage_id(results_with_known_disp)
    store.load_stage(results_with_known_disp, sid)
    assert store.loaded_bytes == 0

    # A live request still loads (the cap never refuses a render).
    slab = store.nodes_slab(results_with_known_disp.stage(sid), sid, "displacement_z")
    assert slab is not None
    assert slab.values.dtype == np.float16
    assert store.loaded_bytes > 0


def test_invalidate_stage_drops_only_that_stage(results_with_known_disp):
    store = VisualDataStore()
    sid = _stage_id(results_with_known_disp)
    store.load_stage(results_with_known_disp, sid)
    assert store.loaded_bytes > 0
    store.invalidate_stage(sid)
    assert store.loaded_bytes == 0
    assert store.color_limits(sid, "displacement_z") is None


def test_missing_component_returns_none(results_with_known_disp):
    store = VisualDataStore()
    sid = _stage_id(results_with_known_disp)
    assert store.nodes_slab(results_with_known_disp.stage(sid), sid, "nope") is None


# ---------------------------------------------------------------------
# Contour integration: cache hit vs fallback
# ---------------------------------------------------------------------
def _attach_contour(results, headless_plotter, *, store=None):
    scene = build_fem_scene(results.fem)
    diagram = ContourDiagram(_make_spec(), results)
    if store is not None:
        diagram._visual_store = store  # noqa: SLF001 - mimic the registry stamp
    diagram.attach(headless_plotter, results.fem, scene)
    return diagram, scene


def test_contour_uses_visual_store_and_does_not_reread(
    results_with_known_disp, headless_plotter,
):
    results = results_with_known_disp
    sid = _stage_id(results)
    store = VisualDataStore()
    store.load_stage(results, sid)

    diagram, scene = _attach_contour(results, headless_plotter, store=store)

    # The attach precomputed the id->column map into the cached slab.
    assert diagram._visual_node_slab_ref is not None  # noqa: SLF001
    assert diagram._visual_node_cols is not None  # noqa: SLF001

    # Count HDF5 reads through the reader: attach already loaded the
    # component once (lazy load inside _resolve_visual_node_columns).
    reader = results._reader  # noqa: SLF001
    reads = {"n": 0}
    orig = reader.read_nodes

    def counting(*a, **k):
        reads["n"] += 1
        return orig(*a, **k)

    reader.read_nodes = counting
    try:
        for step in range(4):
            diagram.update_to_step(step)
    finally:
        reader.read_nodes = orig

    # No per-step HDF5 read: the cache path slices a float16 row.
    assert reads["n"] == 0, f"expected 0 HDF5 reads during playback, got {reads['n']}"

    # And the painted values still match nid + t*1000 (correctness).
    node_ids = np.asarray(results.fem.nodes.ids, dtype=np.int64)
    grid = scene.grid
    # Map substrate rows -> fem node ids via the contour's own lookup.
    pos = diagram._submesh_pos_of_id  # noqa: SLF001
    arr = np.asarray(diagram._scalar_values)  # noqa: SLF001
    for step in range(4):
        diagram.update_to_step(step)
        expected = node_ids + step * 1000.0
        got = arr[pos[node_ids]]
        # float16 round-trip tolerance (~1 part in 1000 for these magnitudes).
        np.testing.assert_allclose(got, expected, rtol=2e-3, atol=1e-6)


def test_contour_falls_back_without_store(results_with_known_disp, headless_plotter):
    results = results_with_known_disp
    diagram, scene = _attach_contour(results, headless_plotter, store=None)

    # No store stamped -> no cache wiring -> per-step read path.
    assert diagram._visual_node_slab_ref is None  # noqa: SLF001

    node_ids = np.asarray(results.fem.nodes.ids, dtype=np.int64)
    pos = diagram._submesh_pos_of_id  # noqa: SLF001
    arr = np.asarray(diagram._scalar_values)  # noqa: SLF001
    for step in range(4):
        diagram.update_to_step(step)
        expected = node_ids + step * 1000.0
        got = arr[pos[node_ids]]
        np.testing.assert_allclose(got, expected, rtol=1e-9, atol=1e-9)