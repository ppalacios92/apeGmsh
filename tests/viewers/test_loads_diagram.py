"""LoadsDiagram — emits a GlyphLayer through the render backend (ADR 0042 R-B.0).

The diagram no longer holds VTK objects; it emits a single arrow
:class:`GlyphLayer` via ``self._backend``. These tests pass a recording
stub backend (no GL, no plotter) and assert on the *emitted layer* —
the headless-testability win the render seam delivers.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from apeGmsh.results import Results
from apeGmsh.results.writers import NativeWriter
from apeGmsh.viewers.diagrams import (
    DiagramSpec,
    LoadsDiagram,
    LoadsStyle,
    SlabSelector,
)
from apeGmsh.viewers.scene_ir import GlyphLayer
from apeGmsh.viewers.scene.fem_scene import build_fem_scene

from tests.conftest import _open_model_from_h5


# --- Recording stub backend (RenderBackend conformant, no GL) ------------


class _Handle:
    def __init__(self, layer_id: str) -> None:
        self.layer_id = layer_id
        self.visible = True


class RecordingBackend:
    """Captures emitted layers; satisfies the RenderBackend Protocol."""

    def __init__(self) -> None:
        self.layers: dict[str, Any] = {}
        self.removed: list[str] = []

    def add_layer(self, layer: Any) -> _Handle:
        self.layers[layer.layer_id] = layer
        return _Handle(layer.layer_id)

    def update_layer(self, handle: _Handle, layer: Any) -> None:
        self.layers[handle.layer_id] = layer

    def remove_layer(self, handle: _Handle) -> None:
        self.layers.pop(handle.layer_id, None)
        self.removed.append(handle.layer_id)

    def set_visibility(self, handle: _Handle, mask: Any) -> None:
        pass

    def set_layer_visible(self, handle: _Handle, visible: bool) -> None:
        handle.visible = bool(visible)

    def add_scalar_bar(self, spec: Any) -> None:
        pass

    def remove_scalar_bar(self, layer_id: str) -> None:
        pass

    def reset_camera(self) -> None:
        pass

    def render(self) -> None:
        pass

    def screenshot(self, path: Any) -> None:
        pass

    def supports_picking(self) -> bool:
        return False


@pytest.fixture
def backend() -> RecordingBackend:
    return RecordingBackend()


@pytest.fixture
def loads_results(g, tmp_path: Path):
    """Cube with three nodal point loads across two patterns."""
    g.model.geometry.add_box(0, 0, 0, 1, 1, 1, label="cube")
    g.physical.add_volume("cube", name="Body")
    g.mesh.sizing.set_global_size(2.0)
    g.mesh.generation.generate(dim=3)
    fem = g.mesh.queries.get_fem_data(dim=3)
    n_ids = list(fem.nodes.ids)

    n_steps = 1
    node_ids = np.asarray(n_ids, dtype=np.int64)
    components = {
        "displacement_x": np.zeros((n_steps, node_ids.size)),
        "displacement_y": np.zeros((n_steps, node_ids.size)),
        "displacement_z": np.zeros((n_steps, node_ids.size)),
    }
    path = tmp_path / "loads.h5"
    with NativeWriter(path) as w:
        w.open(fem=fem)
        sid = w.begin_stage(
            name="static", kind="static",
            time=np.arange(n_steps, dtype=np.float64),
        )
        w.write_nodes(
            sid, "partition_0",
            node_ids=node_ids,
            components=components,
        )
        w.end_stage()
    results = Results.from_native(path, model=_open_model_from_h5(path))
    from apeGmsh._kernel.records import NodalLoadRecord
    fem_after = results.fem
    n_after = list(fem_after.nodes.ids)
    fem_after.nodes.loads._records.append(NodalLoadRecord(
        pattern="P1", node_id=int(n_after[0]),
        force_xyz=(10.0, 0.0, 0.0),
    ))
    fem_after.nodes.loads._records.append(NodalLoadRecord(
        pattern="P1", node_id=int(n_after[1]),
        force_xyz=(0.0, -5.0, 0.0),
    ))
    fem_after.nodes.loads._records.append(NodalLoadRecord(
        pattern="P2", node_id=int(n_after[0]),
        force_xyz=(0.0, 0.0, 7.0),
    ))
    return results


def _spec(pattern: str, scale: float | None = 1.0) -> DiagramSpec:
    return DiagramSpec(
        kind="loads",
        selector=SlabSelector(component=pattern),
        style=LoadsStyle(scale=scale),
    )


def test_construction_requires_loads_style(loads_results):
    from apeGmsh.viewers.diagrams._styles import DiagramStyle
    bad = DiagramSpec(
        kind="loads",
        selector=SlabSelector(component="P1"),
        style=DiagramStyle(),
    )
    with pytest.raises(TypeError, match="LoadsStyle"):
        LoadsDiagram(bad, loads_results)


def test_attach_requires_scene(loads_results, backend):
    diagram = LoadsDiagram(_spec("P1"), loads_results)
    with pytest.raises(RuntimeError, match="FEMSceneData"):
        diagram.attach(backend, loads_results.fem)


def test_attach_emits_arrow_glyph_layer(loads_results, backend):
    scene = build_fem_scene(loads_results.fem)
    diagram = LoadsDiagram(_spec("P1"), loads_results)
    diagram.attach(backend, loads_results.fem, scene)

    layer = diagram._layer
    assert isinstance(layer, GlyphLayer)
    assert layer.kind == "arrow"
    # Two records in P1 → two arrows.
    assert layer.positions.n_points == 2
    # Orientations are the force vectors — sum matches (10, -5, 0).
    np.testing.assert_allclose(layer.orientations.sum(axis=0), [10.0, -5.0, 0.0])
    # Scales = magnitude × scale (scale=1) → {5, 10}, order-agnostic.
    np.testing.assert_allclose(sorted(layer.scales.tolist()), [5.0, 10.0])
    # Emitted to the backend under the diagram's stable layer id.
    assert layer.layer_id in backend.layers


def test_attach_other_pattern_is_independent(loads_results, backend):
    scene = build_fem_scene(loads_results.fem)
    diagram = LoadsDiagram(_spec("P2"), loads_results)
    diagram.attach(backend, loads_results.fem, scene)
    layer = diagram._layer
    assert layer is not None
    assert layer.positions.n_points == 1
    np.testing.assert_allclose(layer.orientations[0], [0.0, 0.0, 7.0])


def test_attach_unknown_pattern_emits_nothing(loads_results, backend):
    scene = build_fem_scene(loads_results.fem)
    diagram = LoadsDiagram(_spec("DOES_NOT_EXIST"), loads_results)
    diagram.attach(backend, loads_results.fem, scene)
    assert diagram._layer is None
    assert diagram._handle is None
    assert backend.layers == {}


def test_update_to_step_is_noop(loads_results, backend):
    scene = build_fem_scene(loads_results.fem)
    diagram = LoadsDiagram(_spec("P1"), loads_results)
    diagram.attach(backend, loads_results.fem, scene)
    before = diagram._layer
    diagram.update_to_step(5)
    assert diagram._layer is before  # unchanged — no timeSeries in broker


def test_handle_stable_across_steps(loads_results, backend):
    scene = build_fem_scene(loads_results.fem)
    diagram = LoadsDiagram(_spec("P1"), loads_results)
    diagram.attach(backend, loads_results.fem, scene)
    initial_handle = diagram._handle
    for step in range(3):
        diagram.update_to_step(step)
    assert diagram._handle is initial_handle


def test_set_scale_rescales_layer(loads_results, backend):
    scene = build_fem_scene(loads_results.fem)
    diagram = LoadsDiagram(_spec("P1"), loads_results)
    diagram.attach(backend, loads_results.fem, scene)
    diagram.set_scale(5.0)
    assert diagram.current_scale() == 5.0
    # Scales rescaled to magnitude × 5 → {25, 50}.
    np.testing.assert_allclose(sorted(diagram._layer.scales.tolist()), [25.0, 50.0])
    # Same handle, updated in place on the backend.
    assert backend.layers[diagram._handle.layer_id] is diagram._layer


def test_auto_scale_when_none(loads_results, backend):
    scene = build_fem_scene(loads_results.fem)
    diagram = LoadsDiagram(_spec("P1", scale=None), loads_results)
    diagram.attach(backend, loads_results.fem, scene)
    expected = 0.10 * scene.model_diagonal / 10.0
    assert abs(diagram.current_scale() - expected) < 1e-9


def test_set_visible_routes_to_backend(loads_results, backend):
    scene = build_fem_scene(loads_results.fem)
    diagram = LoadsDiagram(_spec("P1"), loads_results)
    diagram.attach(backend, loads_results.fem, scene)
    handle = diagram._handle
    diagram.set_visible(False)
    assert handle.visible is False
    diagram.set_visible(True)
    assert handle.visible is True


def test_detach_removes_layer_and_clears_state(loads_results, backend):
    scene = build_fem_scene(loads_results.fem)
    diagram = LoadsDiagram(_spec("P1"), loads_results)
    diagram.attach(backend, loads_results.fem, scene)
    layer_id = diagram._handle.layer_id
    diagram.detach()
    assert diagram._layer is None
    assert diagram._handle is None
    assert not diagram.is_attached
    assert layer_id in backend.removed
    assert layer_id not in backend.layers


def test_zero_force_records_skipped(loads_results, backend):
    from apeGmsh._kernel.records import NodalLoadRecord
    loads_results.fem.nodes.loads._records.append(NodalLoadRecord(
        pattern="ZEROES", node_id=int(loads_results.fem.nodes.ids[0]),
        force_xyz=(0.0, 0.0, 0.0),
    ))
    scene = build_fem_scene(loads_results.fem)
    diagram = LoadsDiagram(_spec("ZEROES"), loads_results)
    diagram.attach(backend, loads_results.fem, scene)
    assert diagram._layer is None


def test_moment_only_records_skipped(loads_results, backend):
    from apeGmsh._kernel.records import NodalLoadRecord
    loads_results.fem.nodes.loads._records.append(NodalLoadRecord(
        pattern="MOMENT_ONLY",
        node_id=int(loads_results.fem.nodes.ids[0]),
        moment_xyz=(0.0, 0.0, 5.0),
    ))
    scene = build_fem_scene(loads_results.fem)
    diagram = LoadsDiagram(_spec("MOMENT_ONLY"), loads_results)
    diagram.attach(backend, loads_results.fem, scene)
    assert diagram._layer is None
