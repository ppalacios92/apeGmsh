"""``line_force`` beam orientation from the recorder frame (L3 follow-up).

The matplotlib diagram historically derived its local axes geometrically
from the two end nodes (`compute_local_axes`), which can't recover the
cross-section roll. With L2b-2 line reads + L3 `MODEL/LOCAL_AXES` both on
main, `LineStationSlab` now carries the recorder's per-row quaternion and
`line_force` prefers it. These checks are **GPU-free** (matplotlib Agg) and
assert the orientation *source*, not pixels — the visual still wants an eyeball.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")

from apeGmsh.results import Results
from apeGmsh.results.plot._beams import axes_from_quaternion
from apeGmsh.results._slabs import LocalAxes

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ladruno"
BEAM = FIXTURES / "beam3d.ladruno"


def test_axes_from_quaternion_matches_localaxes_rows() -> None:
    # The plot helper must agree with LocalAxes (one source of truth).
    q = np.array([0.5, 0.5, 0.5, 0.5])           # a non-identity unit quat
    x, y, z = axes_from_quaternion(q)
    m = LocalAxes(np.array([0]), q.reshape(1, 4)).matrices[0]
    np.testing.assert_allclose(np.vstack([x, y, z]), m, atol=1e-12)


def test_line_force_frame_is_the_recorder_frame() -> None:
    # The frame the plot fills along comes from the recorder quaternion: its
    # x-axis is the beam axis and it is orthonormal. (For beam3d the model's
    # geomTransf vecxz=(0,0,1) equals compute_local_axes' default, so the
    # recorder and geometric frames happen to coincide — the rewire only
    # changes the picture for rolled sections; here we assert the source is
    # the recorder frame, which is what matters.)
    r = Results.from_ladruno(BEAM)
    slab = r.elements.line_stations.get(component="bending_moment_z")
    assert slab.local_axes_quaternion is not None
    x, y, z = axes_from_quaternion(slab.local_axes_quaternion[0])
    beam = np.array([3.0, 1.0, 2.0])
    beam /= np.linalg.norm(beam)
    np.testing.assert_allclose(x, beam, atol=1e-6)
    R = np.vstack([x, y, z])
    np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-9)


def test_line_force_runs_headless_with_recorder_frame() -> None:
    # Smoke: the quaternion-preferring branch executes end to end and returns
    # a 3-D Axes (visual correctness is a GPU/eyeball check).
    r = Results.from_ladruno(BEAM)
    ax = r.plot.line_force(component="bending_moment_z")
    assert ax is not None
    assert type(ax).__name__ == "Axes3D"
