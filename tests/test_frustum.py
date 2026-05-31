"""ADR 0045 S5-box — pure frustum geometry (headless).

Pins the plane construction + containment that powers exact 3D box-select.
"""
from __future__ import annotations

import numpy as np

from apeGmsh.viewers.core.frustum import (
    frustum_planes,
    points_inside_frustum,
    entity_in_frustum,
)


def _axis_box(x0, x1, y0, y1, z0=-1.0, z1=1.0):
    """An axis-aligned box frustum spanning [x0,x1]x[y0,y1]x[z0,z1].

    near/far quads in CCW [bl, br, tr, tl] order at z0 / z1."""
    near = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0]])
    far = np.array([[x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]])
    return frustum_planes(near, far)


def test_point_inside_and_outside_axis_box() -> None:
    planes = _axis_box(-1, 1, -1, 1)
    pts = np.array([
        [0.0, 0.0, 0.0],     # centre — inside
        [0.9, 0.9, 0.9],     # near corner — inside
        [2.0, 0.0, 0.0],     # past +x — outside
        [0.0, 0.0, 5.0],     # past far — outside
        [0.0, -3.0, 0.0],    # below — outside
    ])
    inside = points_inside_frustum(planes, pts)
    assert inside.tolist() == [True, True, False, False, False]


def test_face_points_count_as_inside() -> None:
    planes = _axis_box(-1, 1, -1, 1)
    face = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    assert points_inside_frustum(planes, face).all()


def test_window_vs_crossing_modes() -> None:
    planes = _axis_box(-1, 1, -1, 1)
    # One point inside, one outside.
    pts = np.array([[0.0, 0.0, 0.0], [5.0, 0.0, 0.0]])
    assert entity_in_frustum(planes, pts, crossing=True) is True    # any
    assert entity_in_frustum(planes, pts, crossing=False) is False  # not all
    # Both inside → window mode selects.
    pts_in = np.array([[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]])
    assert entity_in_frustum(planes, pts_in, crossing=False) is True


def test_true_perspective_frustum_narrows_toward_camera() -> None:
    # A perspective frustum: near quad small, far quad large (apex toward
    # -z). A point near the apex must fall outside the narrow near region.
    near = np.array([[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]],
                    dtype=float)
    far = np.array([[-4, -4, 6], [4, -4, 6], [4, 4, 6], [-4, 4, 6]],
                   dtype=float)
    planes = frustum_planes(near, far)
    # On the centre axis, inside at any depth in range.
    assert points_inside_frustum(planes, [[0, 0, 3]])[0]
    # At x=3 the point is outside near the front (narrow) but inside deep
    # (wide) — proves the side planes actually slope.
    assert not points_inside_frustum(planes, [[3, 0, 0.5]])[0]
    assert points_inside_frustum(planes, [[3, 0, 5.5]])[0]


def test_near_and_far_planes_clip_depth() -> None:
    # The core 3D guarantee over the 2D path: points outside the [z0, z1]
    # depth range are rejected even when they project into the screen box.
    planes = _axis_box(-1, 1, -1, 1, z0=-1.0, z1=1.0)
    on_axis = np.array([
        [0.0, 0.0, -3.0],   # before the near plane -> outside
        [0.0, 0.0, -1.0],   # on the near plane     -> inside
        [0.0, 0.0, 0.0],    # mid                   -> inside
        [0.0, 0.0, 1.0],    # on the far plane      -> inside
        [0.0, 0.0, 3.0],    # beyond the far plane  -> outside
    ])
    assert points_inside_frustum(planes, on_axis).tolist() == [
        False, True, True, True, False,
    ]


def test_degenerate_zero_area_box_does_not_crash() -> None:
    # Collapsed box (x0==x1): planes must be well-formed, no exception.
    planes = _axis_box(0.0, 0.0, -1.0, 1.0)
    assert planes.shape == (6, 4)
    # Nothing strictly inside a zero-width slab except on the x=0 plane.
    assert points_inside_frustum(planes, [[0.0, 0.0, 0.0]])[0]
