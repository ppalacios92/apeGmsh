"""Unit tests for ``ops.damping.rayleigh`` (ADR 0053, D1 — global form).

RecordingEmitter + direct Tcl/Py emitter calls only — no openseespy, no
gmsh, no subprocess.  Run with::

    pytest tests/opensees/unit/primitives/test_damping.py -v
"""
from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

import pytest

from apeGmsh.opensees import apeSees
from apeGmsh.opensees.analysis.rayleigh import rayleigh_from_ratio
from apeGmsh.opensees.apesees import BuiltModel
from apeGmsh.opensees._internal.build import RayleighRecord
from apeGmsh.opensees.emitter.py import PyEmitter
from apeGmsh.opensees.emitter.recording import RecordingEmitter
from apeGmsh.opensees.emitter.tcl import TclEmitter


def _make_ops() -> apeSees:
    """apeSees with a stub FEMData — the damping namespace ignores it."""
    return apeSees(cast("object", MagicMock(name="FEMData")))  # type: ignore[arg-type]


def _built(*rayleigh_records: RayleighRecord) -> BuiltModel:
    """A minimal BuiltModel carrying only the rayleigh records under test."""
    return BuiltModel(
        primitives=(),
        tag_for={},
        ndm=3,
        ndf=3,
        fem=cast("object", MagicMock(name="FEMData")),  # type: ignore[arg-type]
        fix_records=(),
        mass_records=(),
        region_records=(),
        rayleigh_records=rayleigh_records,
    )


# --- recording the declaration ---------------------------------------------

class TestRayleighRecording:
    def test_raw_form_records_four_coefficients(self) -> None:
        ops = _make_ops()
        ops.damping.rayleigh(alpha_m=0.1, beta_k=0.01)
        (rec,) = ops._rayleigh_records
        assert (rec.alpha_m, rec.beta_k, rec.beta_k_init, rec.beta_k_comm) == (
            0.1, 0.01, 0.0, 0.0,
        )

    def test_raw_form_initial_and_committed_slots(self) -> None:
        ops = _make_ops()
        ops.damping.rayleigh(beta_k_init=0.02, beta_k_comm=0.03)
        (rec,) = ops._rayleigh_records
        assert (rec.beta_k_init, rec.beta_k_comm) == (0.02, 0.03)

    def test_ratio_form_matches_helper_and_defaults_to_initial(self) -> None:
        ops = _make_ops()
        ops.damping.rayleigh(ratio=0.05, f_i=1.0, f_j=10.0)
        (rec,) = ops._rayleigh_records
        exp = rayleigh_from_ratio(ratio=0.05, f_i=1.0, f_j=10.0)
        assert (rec.alpha_m, rec.beta_k, rec.beta_k_init, rec.beta_k_comm) == exp
        # default 'initial' → β in betaK0, not betaK
        assert rec.beta_k == 0.0
        assert rec.beta_k_init != 0.0

    def test_ratio_form_respects_stiffness_switch(self) -> None:
        ops = _make_ops()
        ops.damping.rayleigh(ratio=0.05, f_i=1.0, f_j=10.0, stiffness="current")
        (rec,) = ops._rayleigh_records
        assert rec.beta_k != 0.0
        assert rec.beta_k_init == 0.0


# --- fail-loud validation --------------------------------------------------

class TestRayleighValidation:
    def test_both_forms_raises(self) -> None:
        ops = _make_ops()
        with pytest.raises(ValueError, match="not both"):
            ops.damping.rayleigh(alpha_m=0.1, ratio=0.05, f_i=1.0, f_j=10.0)

    def test_neither_form_raises(self) -> None:
        ops = _make_ops()
        with pytest.raises(ValueError, match="supply either"):
            ops.damping.rayleigh()

    def test_incomplete_ratio_form_raises(self) -> None:
        ops = _make_ops()
        with pytest.raises(ValueError, match="needs all of"):
            ops.damping.rayleigh(ratio=0.05, f_i=1.0)  # missing f_j


# --- emit ------------------------------------------------------------------

class TestRayleighEmit:
    def test_build_carries_records_into_built_model(self) -> None:
        ops = _make_ops()
        ops.damping.rayleigh(alpha_m=0.1, beta_k=0.01)
        # build() copies the declaration list onto the BuiltModel snapshot.
        assert tuple(ops._rayleigh_records) == (
            RayleighRecord(0.1, 0.01, 0.0, 0.0),
        )

    def test_emit_calls_emitter_rayleigh(self) -> None:
        e = RecordingEmitter()
        _built(RayleighRecord(0.1, 0.01, 0.0, 0.0))._emit_rayleigh(e)
        assert e.calls == [("rayleigh", (0.1, 0.01, 0.0, 0.0), {})]

    def test_emit_preserves_declaration_order(self) -> None:
        e = RecordingEmitter()
        _built(
            RayleighRecord(0.1, 0.0, 0.0, 0.0),
            RayleighRecord(0.2, 0.0, 0.0, 0.0),
        )._emit_rayleigh(e)
        assert [c[1][0] for c in e.calls] == [0.1, 0.2]

    def test_no_records_emits_nothing(self) -> None:
        e = RecordingEmitter()
        _built()._emit_rayleigh(e)
        assert e.calls == []

    def test_tcl_line_format(self) -> None:
        e = TclEmitter()
        e.rayleigh(0.1, 0.01, 0.0, 0.0)
        lines = [ln for ln in e.lines() if "rayleigh" in ln]
        assert lines == ["rayleigh 0.1 0.01 0.0 0.0"]

    def test_py_line_format(self) -> None:
        e = PyEmitter()
        e.rayleigh(0.1, 0.01, 0.0, 0.0)
        lines = [ln for ln in e.lines() if "rayleigh" in ln]
        assert len(lines) == 1
        assert "rayleigh(" in lines[0]
        assert "0.1" in lines[0] and "0.01" in lines[0]
