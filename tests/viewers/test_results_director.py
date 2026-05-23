"""ResultsDirector — stage / step state machine + observer chain (Phase 0).

Builds a small Results via NativeWriter (no Qt, no plotter) and
verifies:

* Director auto-picks the only stage.
* set_step clamps and fires step observers.
* set_stage re-attaches diagrams via the registry.
* set_time_mode rejects non-single modes (Phase 0 only).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from apeGmsh.results import Results
from apeGmsh.results.writers import NativeWriter
from apeGmsh.viewers.diagrams import (
    Diagram,
    DiagramRegistry,
    DiagramSpec,
    DiagramStyle,
    ResultsDirector,
    SlabSelector,
    TimeMode,
)

from tests.conftest import _open_model_from_h5


# =====================================================================
# Fixture: tiny native Results with two stages
# =====================================================================

@pytest.fixture
def two_stage_results(g, tmp_path: Path):
    """Build a Results with 'gravity' (5 steps) + 'dynamic' (3 steps)."""
    g.model.geometry.add_box(0, 0, 0, 1, 1, 1, label="cube")
    g.physical.add_volume("cube", name="Body")
    g.mesh.sizing.set_global_size(2.0)
    g.mesh.generation.generate(dim=3)
    fem = g.mesh.queries.get_fem_data(dim=3)
    n_nodes = len(fem.nodes.ids)
    node_ids = np.asarray(fem.nodes.ids, dtype=np.int64)

    path = tmp_path / "two_stage.h5"
    with NativeWriter(path) as w:
        w.open(fem=fem)
        # Stage 1: gravity, 5 steps
        s1 = w.begin_stage(
            name="gravity", kind="static",
            time=np.array([0.0, 0.25, 0.5, 0.75, 1.0]),
        )
        w.write_nodes(
            s1, "partition_0",
            node_ids=node_ids,
            components={
                "displacement_x": np.zeros((5, n_nodes)),
            },
        )
        w.end_stage()
        # Stage 2: dynamic, 3 steps
        s2 = w.begin_stage(
            name="dynamic", kind="transient",
            time=np.array([0.0, 0.1, 0.2]),
        )
        w.write_nodes(
            s2, "partition_0",
            node_ids=node_ids,
            components={
                "displacement_x": np.ones((3, n_nodes)),
            },
        )
        w.end_stage()
    return Results.from_native(path, model=_open_model_from_h5(path))


@pytest.fixture
def one_stage_results(g, tmp_path: Path):
    """Single-stage Results — Director should auto-pick it."""
    g.model.geometry.add_box(0, 0, 0, 1, 1, 1, label="cube")
    g.physical.add_volume("cube", name="Body")
    g.mesh.sizing.set_global_size(2.0)
    g.mesh.generation.generate(dim=3)
    fem = g.mesh.queries.get_fem_data(dim=3)
    n_nodes = len(fem.nodes.ids)
    node_ids = np.asarray(fem.nodes.ids, dtype=np.int64)

    path = tmp_path / "one_stage.h5"
    with NativeWriter(path) as w:
        w.open(fem=fem)
        sid = w.begin_stage(
            name="grav", kind="static",
            time=np.array([0.0, 0.5, 1.0]),
        )
        w.write_nodes(
            sid, "partition_0",
            node_ids=node_ids,
            components={
                "displacement_x": np.zeros((3, n_nodes)),
            },
        )
        w.end_stage()
    return Results.from_native(path, model=_open_model_from_h5(path))


# =====================================================================
# Stub Diagram for stage-change reattach test
# =====================================================================

class _StubDiagram(Diagram):
    kind = "stub"

    def __init__(self, spec):
        super().__init__(spec, results=None)
        self.attach_count = 0
        self.detach_count = 0
        self.update_calls: list[int] = []

    def attach(self, plotter, fem, scene=None):
        super().attach(plotter, fem, scene)
        self.attach_count += 1

    def update_to_step(self, step_index: int) -> None:
        self.update_calls.append(int(step_index))

    def detach(self) -> None:
        self.detach_count += 1
        super().detach()


def _make_stub_spec() -> DiagramSpec:
    return DiagramSpec(
        kind="stub",
        selector=SlabSelector(component="displacement_x"),
        style=DiagramStyle(),
    )


class _DummyPlotter:
    def remove_actor(self, *args, **kwargs):
        pass


# =====================================================================
# Auto-stage selection
# =====================================================================

def test_director_auto_picks_single_stage(one_stage_results):
    d = ResultsDirector(one_stage_results)
    assert d.stage_id is not None
    # 3-step time vector
    assert d.n_steps == 3


def test_director_does_not_auto_pick_multi_stage(two_stage_results):
    d = ResultsDirector(two_stage_results)
    assert d.stage_id is None
    assert d.n_steps == 0


# =====================================================================
# Stage selection
# =====================================================================

def test_set_stage_by_name(two_stage_results):
    d = ResultsDirector(two_stage_results)
    d.set_stage("gravity")
    assert d.n_steps == 5
    d.set_stage("dynamic")
    assert d.n_steps == 3


def test_set_stage_lands_on_last_step(two_stage_results):
    d = ResultsDirector(two_stage_results)
    d.set_stage("gravity")
    d.set_step(3)
    assert d.step_index == 3
    # Switching stage parks the cursor at end-of-history of the new
    # stage so freshly-attached diagrams paint at the final state.
    d.set_stage("dynamic")
    assert d.step_index == d.n_steps - 1


def test_set_unknown_stage_raises(two_stage_results):
    d = ResultsDirector(two_stage_results)
    with pytest.raises(KeyError):
        d.set_stage("nonexistent")


# =====================================================================
# Step navigation
# =====================================================================

def test_set_step_clamps_low(one_stage_results):
    d = ResultsDirector(one_stage_results)
    d.set_step(-99)
    assert d.step_index == 0


def test_set_step_clamps_high(one_stage_results):
    d = ResultsDirector(one_stage_results)
    d.set_step(99)
    assert d.step_index == d.n_steps - 1


def test_set_step_observer_fires(one_stage_results):
    d = ResultsDirector(one_stage_results)
    seen: list[int] = []
    d.subscribe_step(lambda i: seen.append(i))
    # Director constructs at the last step (n_steps - 1); move to 0
    # to trigger an observer fire.
    d.set_step(0)
    assert seen == [0]


def test_set_same_step_does_not_fire(one_stage_results):
    d = ResultsDirector(one_stage_results)
    d.set_step(1)
    seen: list[int] = []
    d.subscribe_step(lambda i: seen.append(i))
    d.set_step(1)
    assert seen == []


def test_step_to_time_snaps_nearest(one_stage_results):
    d = ResultsDirector(one_stage_results)
    # time vector is [0.0, 0.5, 1.0]
    d.step_to_time(0.4)
    assert d.step_index == 1
    d.step_to_time(0.9)
    assert d.step_index == 2


def test_current_time_at_step(one_stage_results):
    d = ResultsDirector(one_stage_results)
    d.set_step(0)
    assert d.current_time() == 0.0
    d.set_step(2)
    assert d.current_time() == 1.0


# =====================================================================
# Stage change re-attaches diagrams
# =====================================================================

def test_set_stage_reattaches_attached_diagrams(two_stage_results):
    d = ResultsDirector(two_stage_results)
    d.set_stage("gravity")
    d.bind_plotter(_DummyPlotter())
    stub = _StubDiagram(_make_stub_spec())
    d.registry.add(stub)
    assert stub.attach_count == 1

    d.set_stage("dynamic")
    # Reattach: detached + re-attached on stage change
    assert stub.detach_count == 1
    assert stub.attach_count == 2


def test_step_change_routes_through_visible_diagrams(two_stage_results):
    d = ResultsDirector(two_stage_results)
    d.set_stage("gravity")
    d.bind_plotter(_DummyPlotter())
    stub = _StubDiagram(_make_stub_spec())
    d.registry.add(stub)
    stub.update_calls.clear()    # ignore initial step-on-bind
    d.set_step(2)
    assert stub.update_calls == [2]


# =====================================================================
# Time mode (Phase 0 contract)
# =====================================================================

def test_time_mode_default_is_single(one_stage_results):
    d = ResultsDirector(one_stage_results)
    assert d.time_mode is TimeMode.SINGLE


def test_set_time_mode_single_ok(one_stage_results):
    d = ResultsDirector(one_stage_results)
    d.set_time_mode(TimeMode.SINGLE)
    d.set_time_mode("single")


def test_set_time_mode_other_raises(one_stage_results):
    d = ResultsDirector(one_stage_results)
    with pytest.raises(NotImplementedError):
        d.set_time_mode(TimeMode.RANGE)
    with pytest.raises(NotImplementedError):
        d.set_time_mode("animation")


# =====================================================================
# Render coalescing
# =====================================================================

def test_render_callback_fires_once_per_step(one_stage_results):
    d = ResultsDirector(one_stage_results)
    calls: list[int] = []
    d.bind_plotter(
        _DummyPlotter(),
        render_callback=lambda: calls.append(1),
    )
    n0 = len(calls)
    # Constructor lands on step n-1; move to 0 to actually change.
    d.set_step(0)
    # One render for the step move
    assert len(calls) == n0 + 1


def test_render_callback_does_not_fire_on_no_op(one_stage_results):
    d = ResultsDirector(one_stage_results)
    calls: list[int] = []
    d.bind_plotter(
        _DummyPlotter(),
        render_callback=lambda: calls.append(1),
    )
    d.set_step(1)
    n0 = len(calls)
    d.set_step(1)    # same — no fire
    assert len(calls) == n0


# =====================================================================
# Director without bound FEM raises on bind_plotter
# =====================================================================

def test_bind_without_fem_raises(tmp_path, g):
    """Construct a Results that has no fem (degenerate case) — bind fails."""
    # Build a normal results, then strip the fem reference to simulate
    # an in-memory Results that hasn't been bound. Easier than crafting
    # one from scratch.
    g.model.geometry.add_box(0, 0, 0, 1, 1, 1, label="cube")
    g.physical.add_volume("cube", name="Body")
    g.mesh.sizing.set_global_size(2.0)
    g.mesh.generation.generate(dim=3)
    fem = g.mesh.queries.get_fem_data(dim=3)
    n_nodes = len(fem.nodes.ids)
    node_ids = np.asarray(fem.nodes.ids, dtype=np.int64)

    path = tmp_path / "no_fem_bind.h5"
    with NativeWriter(path) as w:
        w.open(fem=fem)
        sid = w.begin_stage(name="g", kind="static", time=np.array([0.0]))
        w.write_nodes(
            sid, "partition_0",
            node_ids=node_ids,
            components={"displacement_x": np.zeros((1, n_nodes))},
        )
        w.end_stage()
    r = Results.from_native(path, model=_open_model_from_h5(path))
    r._fem = None    # force the unbound state
    d = ResultsDirector(r)
    with pytest.raises(RuntimeError):
        d.bind_plotter(_DummyPlotter())


# =====================================================================
# ADR 0026 PR7-d — bind_results() collapses set_model + _bind_model_h5
# =====================================================================
#
# bind_results(results) is the canonical single-call binder.  It must:
# * set ``opensees_model`` from ``results.model``
# * derive the tag-map file path via ``resolve_orientation_source``
# * tolerate Results with ``_path=None`` (in-memory / recorder)
# * clear ``_tag_map_cache`` when the bound path changes

from types import SimpleNamespace


def _stub_results(*, path, model):
    """Minimal Results stand-in — director only reads ``_path`` and
    ``model``."""
    return SimpleNamespace(_path=path, model=model, fem=None)


def test_bind_results_sets_opensees_model_handle(one_stage_results):
    d = ResultsDirector(one_stage_results)
    d._opensees_model = None  # reset for clarity
    handle = object()
    stub = _stub_results(path=None, model=handle)

    d.bind_results(stub)

    assert d.opensees_model is handle


def test_bind_results_with_no_path_clears_tag_map_path(one_stage_results):
    """In-memory Results (``_path=None``) → no tag-map path bound."""
    d = ResultsDirector(one_stage_results)
    stub = _stub_results(path=None, model=object())

    d.bind_results(stub)

    assert d.model_h5 is None


def test_bind_results_with_oriented_path_binds_tag_map_path(
    tmp_path: Path, one_stage_results,
):
    """When ``results._path`` points at a model.h5 with the
    ``/opensees/`` orientation zone, bind_results extracts the path
    and stores it for the tag_map factory."""
    from apeGmsh.opensees import ModelData
    from tests.opensees.fixtures.fem_stub import make_two_node_beam

    fem = make_two_node_beam()
    oriented = tmp_path / "oriented.h5"
    md = ModelData(fem, ndm=3, ndf=6, model_name="oriented")
    md.oriented_elements(pg="Cols", ele_type="forceBeamColumn",
                         vecxz=(1.0, 0.0, 0.0))
    md.write(str(oriented))

    d = ResultsDirector(one_stage_results)
    stub = _stub_results(path=oriented, model=object())

    d.bind_results(stub)

    assert d.model_h5 == oriented


def test_bind_results_bare_path_clears_tag_map_path(
    tmp_path: Path, one_stage_results,
):
    """A model.h5 WITHOUT the orientation zone → no tag-map path
    (the viewer must degrade)."""
    from apeGmsh.opensees import ModelData
    from tests.opensees.fixtures.fem_stub import make_two_node_beam

    fem = make_two_node_beam()
    bare = tmp_path / "bare.h5"
    md = ModelData(fem, ndm=3, ndf=6, model_name="bare")
    md.write(str(bare))

    d = ResultsDirector(one_stage_results)
    stub = _stub_results(path=bare, model=object())

    d.bind_results(stub)

    assert d.model_h5 is None


def test_bind_results_clears_tag_map_cache_when_path_changes(
    tmp_path: Path, one_stage_results,
):
    """Re-binding to a different oriented file invalidates the
    cached :class:`FemToOpsTagMap` (the path change is the cache key)."""
    from apeGmsh.opensees import ModelData
    from tests.opensees.fixtures.fem_stub import make_two_node_beam

    fem = make_two_node_beam()
    a = tmp_path / "a.h5"
    b = tmp_path / "b.h5"
    for p in (a, b):
        md = ModelData(fem, ndm=3, ndf=6, model_name="oriented")
        md.oriented_elements(pg="Cols", ele_type="forceBeamColumn",
                             vecxz=(1.0, 0.0, 0.0))
        md.write(str(p))

    d = ResultsDirector(one_stage_results)
    d.bind_results(_stub_results(path=a, model=object()))
    # Force the cache to populate.
    _ = d.tag_map
    cached_before = d._tag_map_cache
    assert cached_before is not None

    d.bind_results(_stub_results(path=b, model=object()))

    # Path changed → cache invalidated.
    assert d._tag_map_cache is None
    assert d.model_h5 == b
