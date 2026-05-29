"""make_demo_results / Results.demo — zero-setup sample results.

Headless: builds the demo (mesh + apeSees model emit + synthetic
pushover, no OpenSees solve, no render) and checks the shape of the
result — one pushover stage, the right step count, and a deflection
that ramps from zero to the requested tip drift. The viewer rendering
itself is covered by the WebViewer / viewer tests.
"""
from __future__ import annotations

import numpy as np
import pytest

# apeSees model emit needs the opensees bridge; mesh needs gmsh (base dep).
pytest.importorskip("openseespy.opensees", reason="apeSees bridge import")


def test_make_demo_results_shape():
    from apeGmsh.results import make_demo_results

    r = make_demo_results(length=10.0, n_elements=6, n_steps=5, tip_drift=2.0)
    slab = r.nodes.get(component="displacement_x")
    vals = np.asarray(slab.values, dtype=np.float64)   # (n_steps, n_nodes)
    assert vals.shape[0] == 5
    # Step 0 is the undeformed reference.
    np.testing.assert_allclose(vals[0], 0.0, atol=1e-12)
    # Last step is non-trivially deflected.
    assert np.abs(vals[-1]).max() > 0.0
    # Monotone ramp at the most-deflected node.
    tip_col = int(np.argmax(np.abs(vals[-1])))
    series = vals[:, tip_col]
    assert np.all(np.diff(series) >= -1e-12)
    # Tip drift lands near the requested amplitude (analytic shape == 1.0
    # at the free end, ramped to tip_drift).
    np.testing.assert_allclose(np.abs(series[-1]), 2.0, rtol=0.05)
    r.close()


def test_results_demo_classmethod():
    from apeGmsh.results import Results

    r = Results.demo(n_steps=3, n_elements=4)
    slab = r.nodes.get(component="displacement_x")
    assert np.asarray(slab.values).shape[0] == 3
    r.close()


def test_demo_rejects_bad_args():
    from apeGmsh.results import make_demo_results

    with pytest.raises(ValueError):
        make_demo_results(n_steps=0)
    with pytest.raises(ValueError):
        make_demo_results(n_elements=0)
