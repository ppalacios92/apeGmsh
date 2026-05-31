"""ADR 0045 S5-box — frustum box-select smoke with a real renderer.

The pure plane math is covered in test_frustum.py; this exercises the
renderer-dependent half: PickEngine._box_frustum_planes un-projecting the
screen box through a real (offscreen) camera, and _do_box routing through
the frustum path. Skips cleanly where there is no offscreen GL context
(the on-screen pixel-accuracy itself is GPU-eyeball-gated).
"""
from __future__ import annotations

import numpy as np
import pytest

from apeGmsh.viewers.core.frustum import points_inside_frustum
from apeGmsh.viewers.core.pick_engine import PickEngine


@pytest.fixture
def offscreen_plotter():
    pv = pytest.importorskip("pyvista")
    try:
        p = pv.Plotter(off_screen=True, window_size=(400, 300))
        p.add_mesh(pv.Cube())          # something to render a camera around
        p.reset_camera()
        p.render()
    except Exception:                  # pragma: no cover - no GL context
        pytest.skip("no offscreen render context")
    yield p
    p.close()


class _OneEntityRegistry:
    """One entity whose sample points are the unit cube around origin."""
    dims = [3]

    def all_entities(self):
        return [(3, 1)]

    def entity_points(self, dt):
        c = 0.4
        return np.array([[x, y, z]
                         for x in (-c, c) for y in (-c, c) for z in (-c, c)],
                        dtype=float)

    def bbox(self, dt):
        return None

    def centroid(self, dt):
        return np.zeros(3)


def test_box_frustum_planes_are_well_formed_and_contain_focal_point(
    offscreen_plotter,
):
    engine = PickEngine(offscreen_plotter, _OneEntityRegistry())
    w, h = offscreen_plotter.window_size
    planes = engine._box_frustum_planes(0, 0, int(w), int(h))
    # Full-screen box -> the whole view frustum; never the 2D fallback.
    assert planes is not None
    assert planes.shape == (6, 4)
    focal = np.asarray(
        offscreen_plotter.renderer.GetActiveCamera().GetFocalPoint()
    )
    assert points_inside_frustum(planes, focal.reshape(1, 3))[0]


def _engine_with_hits(plotter):
    engine = PickEngine(plotter, _OneEntityRegistry())
    engine._pickable_dims = {3}
    engine._hidden_check = lambda dt: False
    hits: list = []
    engine.on_box_select = lambda h, ctrl: hits.extend(h)
    return engine, hits


def test_full_screen_box_selects_centered_entity(offscreen_plotter):
    engine, hits = _engine_with_hits(offscreen_plotter)
    w, h = offscreen_plotter.window_size
    # Drag the full window (window mode: x1 > x0).
    engine._do_box(0, 0, int(w), int(h), ctrl=False)
    assert (3, 1) in hits


def test_full_screen_crossing_box_selects_centered_entity(offscreen_plotter):
    # Crossing mode (x1 < x0) through the real-renderer frustum path.
    engine, hits = _engine_with_hits(offscreen_plotter)
    w, h = offscreen_plotter.window_size
    engine._do_box(int(w), 0, 0, int(h), ctrl=False)   # x1 < x0 => crossing
    assert (3, 1) in hits


def test_frustum_and_2d_fallback_agree_on_front_view(
    offscreen_plotter, monkeypatch,
):
    # The 2D projection is the documented parity oracle: on a centred
    # entity the frustum path and the forced-2D escape hatch must agree.
    w, h = offscreen_plotter.window_size
    box = (0, 0, int(w), int(h))

    engine_f, hits_f = _engine_with_hits(offscreen_plotter)
    engine_f._do_box(*box, ctrl=False)                 # frustum (default)

    monkeypatch.setenv("APEGMSH_BOX_2D", "1")
    engine_2d, hits_2d = _engine_with_hits(offscreen_plotter)
    # Sanity: the escape hatch really forces the 2D path (planes -> None).
    assert engine_2d._box_frustum_planes(*box) is None
    engine_2d._do_box(*box, ctrl=False)                # forced 2D oracle

    assert hits_f == hits_2d == [(3, 1)]
