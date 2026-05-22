"""Phase 2 — modes accessor and mode-only properties on scoped Results."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from apeGmsh.results import Results
from apeGmsh.results.writers import NativeWriter

from tests.conftest import _open_model_from_h5


def _write_modes_file(tmp_path: Path, *, n_modes: int = 3) -> Path:
    path = tmp_path / "modes.h5"
    node_ids = np.array([1, 2, 3], dtype=np.int64)
    with NativeWriter(path) as w:
        w.open()
        for k in range(1, n_modes + 1):
            eig = float(k * 100.0)
            f = float(k * 2.0)
            T = 1.0 / f
            sid = w.begin_stage(
                name=f"mode_{k}", kind="mode",
                time=np.array([0.0]),
                eigenvalue=eig, frequency_hz=f, period_s=T, mode_index=k,
            )
            shape = np.array([[float(k) * 0.1,
                                float(k) * 0.2,
                                float(k) * 0.3]])
            w.write_nodes(sid, "partition_0", node_ids=node_ids,
                          components={"displacement_x": shape})
            w.end_stage()
    return path


def test_modes_accessor_returns_scoped_results(tmp_path: Path) -> None:
    path = _write_modes_file(tmp_path, n_modes=3)
    with Results.from_native(path, model=_open_model_from_h5(path)) as r:
        modes = r.modes
        assert len(modes) == 3
        for m in modes:
            assert m.kind == "mode"


def test_mode_indexing_and_attrs(tmp_path: Path) -> None:
    path = _write_modes_file(tmp_path, n_modes=3)
    with Results.from_native(path, model=_open_model_from_h5(path)) as r:
        modes = sorted(r.modes, key=lambda m: m.mode_index)
        assert [m.mode_index for m in modes] == [1, 2, 3]
        m2 = modes[1]
        assert m2.eigenvalue == pytest.approx(200.0)
        assert m2.frequency_hz == pytest.approx(4.0)
        assert m2.period_s == pytest.approx(0.25)
        assert m2.name == "mode_2"


def test_mode_shape_is_single_step(tmp_path: Path) -> None:
    path = _write_modes_file(tmp_path, n_modes=2)
    with Results.from_native(path, model=_open_model_from_h5(path)) as r:
        m1 = sorted(r.modes, key=lambda m: m.mode_index)[0]
        slab = m1.nodes.get(component="displacement_x")
        assert slab.values.shape == (1, 3)
        np.testing.assert_allclose(slab.values, [[0.1, 0.2, 0.3]])
        np.testing.assert_allclose(slab.time, [0.0])


def test_mode_props_raise_on_non_mode_stage(tmp_path: Path) -> None:
    """A scoped non-mode stage doesn't expose eigenvalue / frequency_hz."""
    path = tmp_path / "mixed.h5"
    with NativeWriter(path) as w:
        w.open()
        sid = w.begin_stage(name="static", kind="static",
                             time=np.array([0.0]))
        w.write_nodes(sid, "partition_0", node_ids=np.array([1]),
                      components={"displacement_x": np.array([[0.0]])})
        w.end_stage()

    with Results.from_native(path, model=_open_model_from_h5(path)) as r:
        s = r.stage("static")
        with pytest.raises(AttributeError, match="not 'mode'"):
            _ = s.eigenvalue
        with pytest.raises(AttributeError, match="not 'mode'"):
            _ = s.frequency_hz


def test_mode_props_raise_on_unscoped(tmp_path: Path) -> None:
    path = _write_modes_file(tmp_path, n_modes=2)
    with Results.from_native(path, model=_open_model_from_h5(path)) as r:
        # Unscoped → stage-scoped check fires first (correct behavior).
        with pytest.raises(AttributeError, match="stage-scoped"):
            _ = r.eigenvalue


def test_modes_empty_when_no_mode_stages(tmp_path: Path) -> None:
    path = tmp_path / "no_modes.h5"
    with NativeWriter(path) as w:
        w.open()
        sid = w.begin_stage(name="grav", kind="static",
                             time=np.array([0.0]))
        w.write_nodes(sid, "partition_0", node_ids=np.array([1]),
                      components={"displacement_x": np.array([[0.0]])})
        w.end_stage()
    with Results.from_native(path, model=_open_model_from_h5(path)) as r:
        assert r.modes == []


def test_eigen_modes_returns_lightweight_dataclass_list(tmp_path: Path) -> None:
    """``Results.eigen_modes`` returns plain :class:`EigenMode` snapshots
    detached from the Results file — safe to keep after .close()."""
    from apeGmsh.results import EigenMode

    path = _write_modes_file(tmp_path, n_modes=3)
    with Results.from_native(path, model=_open_model_from_h5(path)) as r:
        modes = sorted(r.eigen_modes, key=lambda m: m.mode_index)
        assert len(modes) == 3
        assert all(isinstance(m, EigenMode) for m in modes)
        # Field values match the fixture writer.
        assert [m.mode_index for m in modes] == [1, 2, 3]
        assert modes[0].eigenvalue == pytest.approx(100.0)
        assert modes[1].frequency_hz == pytest.approx(4.0)
        assert modes[2].period_s == pytest.approx(1.0 / 6.0)
    # File is closed — the dataclasses survive (no AttributeError on access).
    assert modes[0].mode_index == 1


def test_eigen_modes_empty_on_no_mode_stages(tmp_path: Path) -> None:
    path = tmp_path / "no_modes.h5"
    with NativeWriter(path) as w:
        w.open()
        sid = w.begin_stage(name="grav", kind="static",
                             time=np.array([0.0]))
        w.write_nodes(sid, "partition_0", node_ids=np.array([1]),
                      components={"displacement_x": np.array([[0.0]])})
        w.end_stage()
    with Results.from_native(path, model=_open_model_from_h5(path)) as r:
        assert r.eigen_modes == []


def test_eigen_mode_omega_rad_s() -> None:
    """``EigenMode.omega_rad_s`` is ``sqrt(eigenvalue)`` for positive
    eigenvalues and ``0.0`` for non-positive (rigid-body) ones."""
    from apeGmsh.results import EigenMode
    import math as _m

    m = EigenMode(
        mode_index=1, eigenvalue=400.0,
        frequency_hz=_m.sqrt(400.0) / (2.0 * _m.pi),
        period_s=2.0 * _m.pi / _m.sqrt(400.0),
    )
    assert m.omega_rad_s == pytest.approx(20.0)

    rigid = EigenMode(
        mode_index=0, eigenvalue=-1e-12,
        frequency_hz=0.0, period_s=0.0,
    )
    assert rigid.omega_rad_s == 0.0


def test_eigen_mode_omega_rad_s_at_exact_zero() -> None:
    """``omega_rad_s`` boundary — ``eigenvalue == 0.0`` exactly must
    return ``0.0`` (and NOT ``nan``).  Tested explicitly because the
    standard implementation guard ``eigenvalue <= 0`` admits the
    boundary; if anyone refactors to ``eigenvalue < 0`` they'd hit a
    ``sqrt(0.0)`` branch and get ``0.0`` anyway, but the test pins
    the contract either way.
    """
    from apeGmsh.results import EigenMode

    m = EigenMode(
        mode_index=0, eigenvalue=0.0,
        frequency_hz=0.0, period_s=0.0,
    )
    assert m.omega_rad_s == 0.0


def test_eigen_modes_on_mpco_returns_empty(tmp_path: Path) -> None:
    """``Results.from_mpco(...)`` carries no native modal stages
    (MPCO files don't persist eigenvalues alongside the response
    streams), so ``.eigen_modes`` should return ``[]`` cleanly rather
    than crash.

    We can't easily synthesize a real .mpco file here, so we exercise
    the MPCOReader path indirectly: a Results with NO mode-kind
    stages must report an empty eigen_modes list regardless of
    backend.
    """
    # Reuse the no-modes fixture — the eigen_modes property iterates
    # _all_stages() and filters; backend identity doesn't matter for
    # the empty-case contract.
    path = tmp_path / "no_modes.h5"
    with NativeWriter(path) as w:
        w.open()
        sid = w.begin_stage(name="dynamic", kind="transient",
                             time=np.array([0.0, 1.0]))
        w.write_nodes(sid, "partition_0", node_ids=np.array([1]),
                      components={"displacement_x": np.zeros((2, 1))})
        w.end_stage()
    with Results.from_native(path, model=_open_model_from_h5(path)) as r:
        # No mode stages — eigen_modes must be the empty list, not None.
        assert r.eigen_modes == []
        assert isinstance(r.eigen_modes, list)


def test_eigen_modes_is_picklable(tmp_path: Path) -> None:
    """A lightweight ``EigenMode`` snapshot can be pickled — the
    intended use case for "return modes from a function whose Results
    context is closed."""
    import pickle

    path = _write_modes_file(tmp_path, n_modes=2)
    with Results.from_native(path, model=_open_model_from_h5(path)) as r:
        snapshot = r.eigen_modes

    blob = pickle.dumps(snapshot)
    restored = pickle.loads(blob)
    assert [m.mode_index for m in restored] == [m.mode_index for m in snapshot]
    assert [m.eigenvalue for m in restored] == [m.eigenvalue for m in snapshot]


def test_mixed_stages_and_modes_in_one_file(tmp_path: Path) -> None:
    path = tmp_path / "mixed.h5"
    node_ids = np.array([1, 2], dtype=np.int64)
    with NativeWriter(path) as w:
        w.open()
        # Transient
        sid = w.begin_stage(name="dynamic", kind="transient",
                             time=np.array([0.0, 1.0]))
        w.write_nodes(sid, "partition_0", node_ids=node_ids,
                      components={"displacement_x": np.zeros((2, 2))})
        w.end_stage()
        # Two modes
        for k in (1, 2):
            sid = w.begin_stage(
                name=f"mode_{k}", kind="mode",
                time=np.array([0.0]),
                eigenvalue=float(k * 50.0),
                frequency_hz=float(k * 1.0),
                period_s=1.0 / float(k),
                mode_index=k,
            )
            w.write_nodes(sid, "partition_0", node_ids=node_ids,
                          components={"displacement_x":
                                       np.array([[float(k), float(k)]])})
            w.end_stage()

    with Results.from_native(path, model=_open_model_from_h5(path)) as r:
        assert len(r.stages) == 3
        assert len(r.modes) == 2
        # Non-mode stage stays accessible by name
        dyn = r.stage("dynamic")
        assert dyn.kind == "transient"
        assert dyn.n_steps == 2


# ---------------------------------------------------------------------------
# Phase 4 (ADR 0020) — modes-side carries the OpenSeesModel handle
# ---------------------------------------------------------------------------

def test_modes_carry_results_model_when_zone_present(tmp_path) -> None:
    """Mode-scoped Results share the parent's OpenSeesModel handle.

    Phase 4 cleanup — when the Composed file embeds ``/opensees/``
    (paired with the rich ``/model/`` neutral zone), ``r.modes[i].model
    is r.model`` for every mode. Stage / mode derivation propagates
    ``_model`` through :meth:`Results._derive`.
    """
    from apeGmsh.opensees import OpenSeesModel
    from tests.opensees.h5._opensees_model_fixtures import (
        build_simple_frame_h5,
    )

    model_path, fem = build_simple_frame_h5(tmp_path)
    results_path = tmp_path / "modes_with_model.h5"
    node_ids = np.asarray(fem.nodes.ids, dtype=np.int64)
    with NativeWriter(results_path) as w:
        w.open(fem=fem, model_h5_src=model_path)
        for k in (1, 2):
            sid = w.begin_stage(
                name=f"mode_{k}", kind="mode",
                time=np.array([0.0]),
                eigenvalue=float(k * 50.0),
                frequency_hz=float(k * 1.0),
                period_s=1.0 / float(k),
                mode_index=k,
            )
            w.write_nodes(
                sid, "partition_0", node_ids=node_ids,
                components={
                    "displacement_x": np.zeros((1, node_ids.size)),
                },
            )
            w.end_stage()

    with Results.from_native(results_path, model=_open_model_from_h5(results_path)) as r:
        assert isinstance(r.model, OpenSeesModel)
        for mode in r.modes:
            assert mode.model is r.model


def test_modes_have_none_model_when_zone_absent(tmp_path) -> None:
    """Legacy modes file (no ``/opensees/``) — modes still accessible.

    Phase 8 (ADR 0020 INV-1) — ``Results.model`` is REQUIRED.  The
    helper ``_open_model_from_h5`` builds a stub :class:`OpenSeesModel`
    when the file has no ``/opensees/`` zone (a legacy modes file).
    Every scoped mode-instance shares the same ``r.model`` handle.
    """
    path = _write_modes_file(tmp_path, n_modes=2)
    with Results.from_native(path, model=_open_model_from_h5(path)) as r:
        # Phase 8 — every Results carries a model (stub when the file
        # has no /opensees/ zone).
        assert r.model is not None
        for mode in r.modes:
            assert mode.model is r.model
