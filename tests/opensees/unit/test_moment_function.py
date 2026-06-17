"""MT-3 (ADR 0062) — normalized moment-function S(t) helpers.

``MomentStep`` (erf ramp) and ``Yoffe`` (regularized modified-Yoffe) are
``timeSeries Path`` façades whose samples rise 0 → 1 (the moment
function, NOT the slip-rate). A band-limit warning fires when the
slip-rate spectrum exceeds the caller's mesh-resolvable ``f_max``.
"""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from apeGmsh.opensees.emitter.recording import RecordingEmitter
from apeGmsh.opensees.time_series.time_series import (
    MomentStep,
    WarnMomentFunctionBandwidth,
    Yoffe,
)


# --- MomentStep -----------------------------------------------------------

def test_moment_step_rises_zero_to_one():
    ms = MomentStep(half_duration=0.5, t_total=10.0, dt=0.01, t0=3.0)
    t, v = ms.samples()
    v = np.asarray(v)
    assert v[0] == pytest.approx(0.0, abs=1e-3)
    assert v[-1] == pytest.approx(1.0, abs=1e-3)
    assert np.all(np.diff(v) >= -1e-12)              # monotonic non-decreasing


def test_moment_step_half_at_centroid():
    ms = MomentStep(half_duration=0.4, t_total=8.0, dt=0.01, t0=2.5)
    t, v = ms.samples()
    i = int(round(2.5 / 0.01))
    assert v[i] == pytest.approx(0.5, abs=1e-6)      # S(t0) = 1/2


def test_moment_step_slip_rate_integral_is_one():
    """∫ Ṡ dt == ΔS == 1 (S is the integral of the slip-rate)."""
    ms = MomentStep(half_duration=0.3, t_total=6.0, dt=0.005, t0=2.0)
    _, v = ms.samples()
    assert v[-1] - v[0] == pytest.approx(1.0, abs=1e-3)


@pytest.mark.parametrize("bad", [
    dict(half_duration=0.0, t_total=1.0, dt=0.1),
    dict(half_duration=0.1, t_total=0.0, dt=0.1),
    dict(half_duration=0.1, t_total=1.0, dt=0.0),
])
def test_moment_step_validation(bad):
    with pytest.raises(ValueError):
        MomentStep(**bad)


def test_moment_step_emits_path():
    ms = MomentStep(half_duration=0.5, t_total=4.0, dt=0.05, t0=1.0)
    rec = RecordingEmitter()
    ms._emit(rec, 7)
    assert rec.calls[0][0] == "timeSeries"
    assert rec.calls[0][1][0] == "Path"


# --- Yoffe ----------------------------------------------------------------

def test_yoffe_rises_zero_to_one():
    y = Yoffe(rise_time=2.0, peak_time=0.3, t_total=8.0, dt=0.01, t0=1.0)
    t, v = y.samples()
    v = np.asarray(v)
    assert v[0] == pytest.approx(0.0, abs=1e-9)
    assert v[-1] == pytest.approx(1.0, abs=1e-6)
    assert np.all(np.diff(v) >= -1e-12)


def test_yoffe_zero_before_onset():
    y = Yoffe(rise_time=2.0, peak_time=0.3, t_total=8.0, dt=0.01, t0=1.0)
    t, v = y.samples()
    v = np.asarray(v)
    before = np.asarray(t) < 1.0
    assert np.allclose(v[before], 0.0, atol=1e-12)


def test_yoffe_slip_rate_peaks_after_onset():
    """The regularized slip-rate peaks ~peak_time after onset, not at t=0."""
    y = Yoffe(rise_time=3.0, peak_time=0.5, t_total=10.0, dt=0.01, t0=2.0)
    t, v = y.samples()
    rate = np.gradient(np.asarray(v), 0.01)
    t_peak = np.asarray(t)[int(np.argmax(rate))]
    assert 2.0 < t_peak < 2.0 + 3.0                 # within onset..onset+rise
    assert t_peak == pytest.approx(2.0 + 0.5, abs=0.4)


def test_yoffe_peak_time_must_be_under_half_rise():
    with pytest.raises(ValueError, match="rise_time/2"):
        Yoffe(rise_time=1.0, peak_time=0.6, t_total=4.0, dt=0.01)


# --- Band-limit warning ---------------------------------------------------

def test_band_limit_warns_when_too_sharp():
    """A sharp rise (high-freq slip-rate) against a low f_max warns."""
    ms = MomentStep(
        half_duration=0.02, t_total=4.0, dt=0.002, t0=1.0, f_max=2.0,
    )
    with pytest.warns(WarnMomentFunctionBandwidth, match="f_max"):
        ms._emit(RecordingEmitter(), 1)


def test_band_limit_silent_when_resolved():
    """A smooth rise well inside f_max does not warn."""
    ms = MomentStep(
        half_duration=1.0, t_total=20.0, dt=0.02, t0=5.0, f_max=20.0,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", WarnMomentFunctionBandwidth)
        ms._emit(RecordingEmitter(), 1)             # must not raise


def test_band_limit_noop_without_f_max():
    ms = MomentStep(half_duration=0.02, t_total=4.0, dt=0.002, t0=1.0)
    with warnings.catch_warnings():
        warnings.simplefilter("error", WarnMomentFunctionBandwidth)
        ms._emit(RecordingEmitter(), 1)             # f_max=None → silent


# --- Namespace wiring -----------------------------------------------------

def test_namespace_registers_moment_functions():
    from apeGmsh.opensees import apeSees
    from tests.opensees.fixtures.fem_stub import make_two_node_beam

    ops = apeSees(make_two_node_beam())
    ms = ops.timeSeries.MomentStep(half_duration=0.5, t_total=4.0, dt=0.05)
    yf = ops.timeSeries.Yoffe(
        rise_time=2.0, peak_time=0.3, t_total=8.0, dt=0.01,
    )
    assert isinstance(ms, MomentStep)
    assert isinstance(yf, Yoffe)
