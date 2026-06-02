"""End-to-end deck test for ``ops.damping.rayleigh`` (ADR 0053, D1).

Builds a real (stub-fem) frame, declares global Rayleigh damping, and
asserts the ``rayleigh`` line lands in the generated Tcl *and* openseespy
decks.  No openseespy required — pure emit.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from apeGmsh.opensees import apeSees

from tests.opensees.fixtures.fem_stub import make_two_column_frame


def _frame_with_rayleigh(**rayleigh_kwargs: Any) -> apeSees:
    fem = make_two_column_frame()
    ops = apeSees(cast("object", fem))
    ops.model(ndm=3, ndf=6)
    transf = ops.geomTransf.Linear(vecxz=(1.0, 0.0, 0.0))
    ops.element.elasticBeamColumn(
        pg="Cols", transf=transf,
        A=0.01, E=200e9, Iz=1e-4, Iy=1e-4, G=80e9, J=1e-4,
    )
    ops.fix(pg="Base", dofs=(1, 1, 1, 1, 1, 1))
    ops.damping.rayleigh(**rayleigh_kwargs)
    return ops


def _deck(ops: apeSees, tmp_path: Path, suffix: str) -> str:
    out = tmp_path / f"deck.{suffix}"
    getattr(ops, suffix)(str(out))
    return out.read_text(encoding="utf-8")


def test_raw_rayleigh_line_in_tcl_deck(tmp_path: Path) -> None:
    ops = _frame_with_rayleigh(alpha_m=0.1, beta_k=0.01)
    lines = [
        ln for ln in _deck(ops, tmp_path, "tcl").splitlines()
        if ln.strip().startswith("rayleigh")
    ]
    assert lines == ["rayleigh 0.1 0.01 0.0 0.0"]


def test_raw_rayleigh_line_in_py_deck(tmp_path: Path) -> None:
    ops = _frame_with_rayleigh(alpha_m=0.1, beta_k=0.01)
    lines = [
        ln for ln in _deck(ops, tmp_path, "py").splitlines()
        if "rayleigh(" in ln
    ]
    assert len(lines) == 1
    assert "0.1" in lines[0] and "0.01" in lines[0]


def test_ratio_form_initial_default_lands_in_betaK0(tmp_path: Path) -> None:
    # initial default → β in the 3rd slot (betaK0); the 2nd slot (betaK,
    # current tangent) stays zero — the nonlinear-safe choice (ADR 0053).
    ops = _frame_with_rayleigh(ratio=0.05, f_i=1.0, f_j=10.0)
    line = next(
        ln for ln in _deck(ops, tmp_path, "tcl").splitlines()
        if ln.strip().startswith("rayleigh")
    )
    _, alpha, beta_k, beta_k0, beta_kc = line.split()
    assert float(alpha) > 0.0
    assert float(beta_k) == 0.0
    assert float(beta_k0) > 0.0
    assert float(beta_kc) == 0.0
