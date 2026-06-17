"""MT-1 (ADR 0062) — pure moment-tensor math.

Validates :mod:`apeGmsh._kernel.geometry._moment_tensor` against the
ADR's hand-computed vector, the ShakerMaker ``nmtensor`` oracle
(reimplemented here for the pure double-couple case), canonical
mechanisms, and the z-up frame flip.
"""
from __future__ import annotations

import numpy as np
import pytest

from apeGmsh._kernel.geometry._moment_tensor import (
    magnitude_to_scalar_moment,
    moment_tensor,
    scalar_moment,
    scalar_moment_to_magnitude,
    to_mesh_frame,
    unit_moment_tensor,
)


# --- ShakerMaker oracle (radiats.c::nmtensor, iso=0 clvd=0) ---------------

def _shakermaker_nmtensor(strike: float, dip: float, rake: float) -> np.ndarray:
    """Pure double-couple unit tensor as ShakerMaker's ``nmtensor`` builds it.

    Mirrors ``shakermaker/core/radiats.c`` (iso=clvd=0, dum=dev=1). The
    apeGmsh implementation must match this term-for-term (A&R z-down).
    """
    s = np.radians(strike)
    d = np.radians(dip)
    r = np.radians(rake)
    sstr, cstr = np.sin(s), np.cos(s)
    sstr2, cstr2 = 2 * sstr * cstr, 1 - 2 * sstr * sstr
    sdip, cdip = np.sin(d), np.cos(d)
    sdip2, cdip2 = 2 * sdip * cdip, 1 - 2 * sdip * sdip
    crak, srak = np.cos(r), np.sin(r)
    t = np.zeros((3, 3))
    t[0, 0] = -(sdip * crak * sstr2 + sdip2 * srak * sstr * sstr)
    t[0, 1] = sdip * crak * cstr2 + 0.5 * sdip2 * srak * sstr2
    t[0, 2] = -(cdip * crak * cstr + cdip2 * srak * sstr)
    t[1, 1] = sdip * crak * sstr2 - sdip2 * srak * cstr * cstr
    t[1, 2] = cdip2 * srak * cstr - cdip * crak * sstr
    t[2, 2] = sdip2 * srak
    t[1, 0], t[2, 0], t[2, 1] = t[0, 1], t[0, 2], t[1, 2]
    return t


# --- The ADR's hand-computed value ---------------------------------------

def test_adr_hand_computed_value():
    """ADR 0062 MT-1: phi=350, dip=40, rake=113 → the quoted tensor."""
    m = unit_moment_tensor(strike=350, dip=40, rake=113)
    # ADR quotes [m_xx, m_yy, m_zz; m_xy, m_xz, m_yz].
    assert m[0, 0] == pytest.approx(-0.113, abs=1e-3)
    assert m[1, 1] == pytest.approx(-0.793, abs=1e-3)
    assert m[2, 2] == pytest.approx(0.906, abs=1e-3)
    assert m[0, 1] == pytest.approx(-0.391, abs=1e-3)
    assert m[0, 2] == pytest.approx(0.323, abs=1e-3)
    assert m[1, 2] == pytest.approx(0.105, abs=1e-3)


@pytest.mark.parametrize(
    "strike,dip,rake",
    [(350, 40, 113), (0, 90, 0), (30, 45, 90), (123, 67, -45), (200, 10, 170)],
)
def test_matches_shakermaker_oracle(strike, dip, rake):
    """apeGmsh tensor == ShakerMaker nmtensor (the convention oracle)."""
    m = unit_moment_tensor(strike=strike, dip=dip, rake=rake)
    ref = _shakermaker_nmtensor(strike, dip, rake)
    assert np.allclose(m, ref, atol=1e-12)


@pytest.mark.parametrize(
    "strike,dip,rake",
    [(350, 40, 113), (0, 90, 0), (30, 45, 90), (123, 67, -45), (200, 10, 170)],
)
def test_symmetric_and_traceless(strike, dip, rake):
    """A double-couple is symmetric (no net torque) and deviatoric."""
    m = unit_moment_tensor(strike=strike, dip=dip, rake=rake)
    assert np.allclose(m, m.T, atol=1e-14)
    assert np.trace(m) == pytest.approx(0.0, abs=1e-12)


def test_canonical_vertical_strike_slip():
    """strike=0, dip=90, rake=0 → pure m_xy double-couple."""
    m = unit_moment_tensor(strike=0, dip=90, rake=0)
    expected = np.array([[0, 1, 0], [1, 0, 0], [0, 0, 0]], dtype=float)
    assert np.allclose(m, expected, atol=1e-12)


def test_canonical_45deg_dip_slip():
    """strike=0, dip=45, rake=90 → m_yy=-1, m_zz=+1, off-diagonals 0."""
    m = unit_moment_tensor(strike=0, dip=45, rake=90)
    expected = np.array([[0, 0, 0], [0, -1, 0], [0, 0, 1]], dtype=float)
    assert np.allclose(m, expected, atol=1e-12)


# --- Frame flip -----------------------------------------------------------

def test_to_mesh_frame_zup_flips_only_vertical_shear():
    m = unit_moment_tensor(strike=350, dip=40, rake=113)
    up = to_mesh_frame(m, frame="z-up")
    # In-plane + m_zz invariant under z -> -z.
    assert up[0, 0] == m[0, 0]
    assert up[1, 1] == m[1, 1]
    assert up[2, 2] == m[2, 2]
    assert up[0, 1] == m[0, 1]
    # m_xz, m_yz negated.
    assert up[0, 2] == -m[0, 2]
    assert up[1, 2] == -m[1, 2]
    # Still symmetric.
    assert np.allclose(up, up.T, atol=1e-14)


def test_to_mesh_frame_zdown_is_identity():
    m = unit_moment_tensor(strike=123, dip=67, rake=-45)
    assert np.allclose(to_mesh_frame(m, frame="z-down"), m, atol=1e-14)


def test_to_mesh_frame_rejects_unknown_frame():
    m = unit_moment_tensor(strike=0, dip=90, rake=0)
    with pytest.raises(ValueError, match="frame must be one of"):
        to_mesh_frame(m, frame="enu")


# --- Scalar moment --------------------------------------------------------

def test_scalar_moment_product():
    assert scalar_moment(mu=3.0e10, area=2.0, slip=0.5) == pytest.approx(3.0e10)


@pytest.mark.parametrize("bad", [dict(mu=0, area=1, slip=1), dict(mu=1, area=-1, slip=1)])
def test_scalar_moment_fails_loud(bad):
    with pytest.raises(ValueError):
        scalar_moment(**bad)


def test_magnitude_moment_round_trip():
    for mw in (4.0, 5.5, 6.3, 7.8):
        m0 = magnitude_to_scalar_moment(mw)
        assert scalar_moment_to_magnitude(m0) == pytest.approx(mw, abs=1e-9)


def test_magnitude_to_moment_known_value():
    # Mw 6.0 -> M0 = 10**(1.5*6 + 9.1) = 10**18.1 N·m ≈ 1.2589e18.
    assert magnitude_to_scalar_moment(6.0) == pytest.approx(10 ** 18.1, rel=1e-12)


# --- moment_tensor convenience -------------------------------------------

def test_moment_tensor_scales_and_flips():
    m_unit = unit_moment_tensor(strike=350, dip=40, rake=113)
    M = moment_tensor(strike=350, dip=40, rake=113, M0=2.0e15, frame="z-up")
    expected = to_mesh_frame(2.0e15 * m_unit, frame="z-up")
    assert np.allclose(M, expected, atol=1e-3)


def test_moment_tensor_accepts_explicit_m_ij():
    m_unit = unit_moment_tensor(strike=30, dip=45, rake=90)
    M = moment_tensor(m_ij=m_unit, M0=5.0, frame="z-down")
    assert np.allclose(M, 5.0 * m_unit, atol=1e-12)


def test_moment_tensor_requires_exactly_one_source():
    with pytest.raises(ValueError, match="exactly one"):
        moment_tensor(frame="z-up", M0=1.0)
    with pytest.raises(ValueError, match="exactly one"):
        moment_tensor(strike=0, dip=90, rake=0, m_ij=np.eye(3), frame="z-up")


def test_moment_tensor_rejects_asymmetric_m_ij():
    bad = np.array([[0, 1, 0], [0, 0, 0], [0, 0, 0]], dtype=float)
    with pytest.raises(ValueError, match="symmetric"):
        moment_tensor(m_ij=bad, frame="z-up")
