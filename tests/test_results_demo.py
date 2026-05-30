"""make_demo_results / Results.demo — zero-setup sample results.

Headless: builds the demo (mesh + apeSees model emit + synthetic
pushover, no OpenSees solve, no render) and checks the shape of the
result — one pushover stage, the right step count, and a deflection
that ramps from zero to the requested tip drift. The viewer rendering
itself is covered by the WebViewer / viewer tests.
"""
from __future__ import annotations

from pathlib import Path

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


def test_demo_composed_model_zone_is_readable():
    """OpenSeesModel.from_h5(composed results.h5) reads the embedded zone.

    Regression for the composed-file read gap (ADR 0020): the rich
    neutral zone lives under ``/model/`` while the file-root ``/meta``
    is only the results envelope's lineage stub.  Passing the composed
    file straight to ``from_h5`` (no ``fem_root`` override) used to raise
    ``MalformedH5Error: /meta/schema_version attribute is empty``; it now
    auto-detects the ``/model/`` zone.
    """
    from apeGmsh.results import make_demo_results
    from apeGmsh.opensees import OpenSeesModel

    r = make_demo_results(n_elements=4, n_steps=3)
    model = OpenSeesModel.from_h5(str(r._path))
    assert model.model_name == "demo_model"
    # The embedded zone rehydrates to the same snapshot the writer
    # stamped on /model/meta.
    assert model.snapshot_id
    assert model.fem.nodes.ids.size > 0
    r.close()


def test_demo_records_model_path_in_viewer_argv():
    """The non-blocking subprocess viewer must forward --model-h5 to the
    sibling demo_model.h5, since the composed demo_results.h5 has no
    independently-readable /model zone."""
    from apeGmsh.results import Results

    r = Results.demo(n_steps=3, n_elements=4)
    try:
        assert r._model_path is not None
        assert r._model_path.name == "demo_model.h5"
        argv = r._build_viewer_argv(title=None)
        assert "--model-h5" in argv
        assert str(r._model_path) in argv
    finally:
        r.close()


def test_demo_subprocess_viewer_opens():
    """Regression: `Results.demo().viewer(blocking=False)` crashed the child
    with MalformedH5Error (/model zone empty) because --model-h5 was never
    forwarded. Run the real child argv (APEGMSH_SKIP_VIEWER so it opens the
    results then skips the GUI) and assert it exits 0."""
    import os
    import subprocess
    from apeGmsh.results import Results

    r = Results.demo(n_steps=3, n_elements=4)
    argv = r._build_viewer_argv(title=None)
    r.close()  # release the file handle before the child opens it (Windows)

    env = dict(os.environ, APEGMSH_SKIP_VIEWER="1")
    src = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(argv, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr[-2000:]


def test_demo_viewer_data_reads_composed_file():
    """The blocking desktop viewer's read seam — `ViewerData.from_h5` →
    `h5_reader.open` — must open the composed demo_results.h5 directly:
    the `/model` neutral zone is auto-detected while `/opensees`
    orientation stays at root. Regression for the in-process
    `Results.demo().viewer()` crash (`MalformedH5Error: /meta/schema_version
    attribute is empty` — the root `/meta` is only a lineage stub)."""
    from apeGmsh.results import make_demo_results
    from apeGmsh.viewers.data._h5_probe import resolve_orientation_source
    from apeGmsh.viewers.data._viewer_data import ViewerData

    r = make_demo_results(n_elements=4, n_steps=3)
    try:
        # The viewer resolves its read source to the composed results file
        # (it carries /opensees orientation at root), then reads it.
        source = resolve_orientation_source(r)
        assert source is not None and str(source) == str(r._path)
        vd = ViewerData.from_h5(str(source))
        assert vd.nodes.ids.size > 0
        assert vd.snapshot_id
    finally:
        r.close()
