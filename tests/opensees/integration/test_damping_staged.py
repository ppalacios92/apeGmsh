"""Stage-bound damping — ``s.damping.*`` (ADR 0053, D5).

Stage damping mirrors the flat ``ops.damping.*`` surface but resolves
inside the owning stage's block (after ``domainChange``), so the
``rayleigh`` / ``region -damp`` lines bind the stage's domain. The
Damping *object* definition still emits once, pre-element. Modal damping
is intentionally not staged.

Driven through ``ops.build().emit(RecordingEmitter())`` so the stage
scope (between ``stage_open`` / ``stage_close``) is inspectable, plus a
deck-level Tcl assertion and a live transient.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from apeGmsh.opensees import apeSees
from apeGmsh.opensees.emitter.recording import RecordingEmitter

from tests.opensees.fixtures.fem_stub import make_two_column_frame


def _full_chain(ops: apeSees) -> dict[str, object]:
    return {
        "test":        ops.test.NormDispIncr(tol=1e-6, max_iter=20),
        "algorithm":   ops.algorithm.Newton(),
        "integrator":  ops.integrator.LoadControl(dlam=0.1),
        "constraints": ops.constraints.Plain(),
        "numberer":    ops.numberer.RCM(),
        "system":      ops.system.UmfPack(),
        "analysis":    ops.analysis.Static(),
    }


def _frame() -> apeSees:
    fem = make_two_column_frame()
    ops = apeSees(cast("object", fem))
    ops.model(ndm=3, ndf=6)
    transf = ops.geomTransf.Linear(vecxz=(1.0, 0.0, 0.0))
    ops.element.elasticBeamColumn(
        pg="Cols", transf=transf,
        A=0.01, E=200e9, Iz=1e-4, Iy=1e-4, G=80e9, J=1e-4,
    )
    return ops


def _stage_spans(rec: RecordingEmitter) -> list[tuple[int, int]]:
    """(open_idx, close_idx) for each stage in the recorded call stream."""
    spans: list[tuple[int, int]] = []
    open_i: int | None = None
    for i, (name, _a, _k) in enumerate(rec.calls):
        if name == "stage_open":
            open_i = i
        elif name == "stage_close" and open_i is not None:
            spans.append((open_i, i))
            open_i = None
    return spans


def _call_indices(rec: RecordingEmitter, name: str) -> list[int]:
    return [i for i, (n, _a, _k) in enumerate(rec.calls) if n == name]


# --- stage rayleigh --------------------------------------------------------

def test_stage_rayleigh_emits_inside_stage_block() -> None:
    ops = _frame()
    with ops.stage(name="dyn") as s:
        s.damping.rayleigh(alpha_m=0.1, beta_k=0.01)
        s.analysis(**_full_chain(ops))
        s.run(n_increments=1)
    rec = RecordingEmitter()
    ops.build().emit(rec)
    (span,) = _stage_spans(rec)
    (ray_i,) = _call_indices(rec, "rayleigh")
    assert span[0] < ray_i < span[1]


def test_global_and_stage_rayleigh_coexist() -> None:
    # Global rayleigh binds the (pre-stage) global elements; stage
    # rayleigh binds inside the stage block. Two distinct lines, one
    # outside and one inside the stage span.
    ops = _frame()
    ops.damping.rayleigh(alpha_m=0.05)            # global
    with ops.stage(name="dyn") as s:
        s.damping.rayleigh(alpha_m=0.1, beta_k=0.01)   # stage
        s.analysis(**_full_chain(ops))
        s.run(n_increments=1)
    rec = RecordingEmitter()
    ops.build().emit(rec)
    (span,) = _stage_spans(rec)
    ray = _call_indices(rec, "rayleigh")
    assert len(ray) == 2
    outside = [i for i in ray if not (span[0] < i < span[1])]
    inside = [i for i in ray if span[0] < i < span[1]]
    assert len(outside) == 1 and len(inside) == 1
    assert outside[0] < span[0]  # global emits before the stage


# --- stage damping objects -------------------------------------------------

def test_stage_uniform_object_global_attach_in_stage() -> None:
    ops = _frame()
    with ops.stage(name="dyn") as s:
        s.damping.uniform(ratio=0.03, freq_lower=0.5, freq_upper=10.0, on="Cols")
        s.analysis(**_full_chain(ops))
        s.run(n_increments=1)
    rec = RecordingEmitter()
    ops.build().emit(rec)
    (span,) = _stage_spans(rec)
    # The damping object DEFINITION emits once, pre-element (outside the
    # stage span); the region -damp attach emits inside the stage.
    (damp_i,) = _call_indices(rec, "damping")
    assert damp_i < span[0]
    region_calls = [
        i for i, (n, a, _k) in enumerate(rec.calls)
        if n == "region" and "-damp" in a
    ]
    assert region_calls and all(span[0] < i < span[1] for i in region_calls)


def test_two_stages_damping_regions_get_distinct_tags() -> None:
    ops = _frame()
    with ops.stage(name="s1") as s:
        s.damping.uniform(ratio=0.03, freq_lower=0.5, freq_upper=10.0, on="Cols")
        s.analysis(**_full_chain(ops))
        s.run(n_increments=1)
    with ops.stage(name="s2") as s:
        s.damping.uniform(ratio=0.05, freq_lower=0.5, freq_upper=10.0, on="Cols")
        s.analysis(**_full_chain(ops))
        s.run(n_increments=1)
    rec = RecordingEmitter()
    ops.build().emit(rec)
    region_tags = [
        int(a[0]) for (n, a, _k) in rec.calls
        if n == "region" and "-damp" in a
    ]
    assert len(region_tags) == 2
    assert region_tags[0] != region_tags[1]


def test_stage_modal_is_rejected() -> None:
    ops = _frame()
    with ops.stage(name="dyn") as s:
        with pytest.raises(NotImplementedError, match="modal"):
            s.damping.modal(0.05, modes=3)
        s.analysis(**_full_chain(ops))
        s.run(n_increments=1)


# --- deck-level + live -----------------------------------------------------

def test_stage_rayleigh_in_tcl_deck(tmp_path: Path) -> None:
    ops = _frame()
    with ops.stage(name="dyn") as s:
        s.damping.rayleigh(alpha_m=0.1, beta_k=0.01)
        s.analysis(**_full_chain(ops))
        s.run(n_increments=1)
    out = tmp_path / "deck.tcl"
    ops.tcl(str(out))
    lines = [ln.strip() for ln in out.read_text(encoding="utf-8").splitlines()]
    assert any(ln == "rayleigh 0.1 0.01 0.0 0.0" for ln in lines)


def _subprocess_python() -> str | None:
    import os
    import sys
    venv = os.environ.get("OPENSEES_VENV")
    if venv:
        cand = (
            os.path.join(venv, "Scripts", "python.exe")
            if os.name == "nt" else os.path.join(venv, "bin", "python")
        )
        if os.path.exists(cand):
            return cand
    return sys.executable


def _has_openseespy(python_bin: str) -> bool:
    import subprocess
    return subprocess.run(
        [python_bin, "-c", "import openseespy.opensees"],
        capture_output=True, check=False,
    ).returncode == 0


_PY = _subprocess_python()


@pytest.mark.subprocess
@pytest.mark.skipif(
    _PY is None or not _has_openseespy(_PY),
    reason="openseespy not available in subprocess python",
)
def test_staged_rayleigh_deck_runs(tmp_path: Path) -> None:
    # Staged models can't run through the in-process LiveOpsEmitter, so
    # emit the staged py deck (it carries its own per-stage analyze loop)
    # and run it via openseespy in a subprocess — proves the in-stage
    # rayleigh line parses and the staged transient executes.
    fem = make_two_column_frame()
    ops = apeSees(cast("object", fem))
    ops.model(ndm=3, ndf=6)
    transf = ops.geomTransf.Linear(vecxz=(1.0, 0.0, 0.0))
    ops.element.elasticBeamColumn(
        pg="Cols", transf=transf,
        A=0.01, E=200e9, Iz=1e-4, Iy=1e-4, G=80e9, J=1e-4,
    )
    ops.fix(pg="Base", dofs=(1, 1, 1, 1, 1, 1))
    ops.mass(pg="Top", values=(1.0, 1.0, 1.0, 0.0, 0.0, 0.0))
    ts = ops.timeSeries.Linear()
    with ops.stage(name="dyn") as s:
        s.damping.rayleigh(ratio=0.05, f_i=1.0, f_j=10.0)
        with s.pattern(series=ts) as p:
            p.load(node=2, forces=(100.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        s.analysis(
            test=ops.test.NormDispIncr(tol=1e-8, max_iter=20),
            algorithm=ops.algorithm.Linear(),
            integrator=ops.integrator.Newmark(gamma=0.5, beta=0.25),
            constraints=ops.constraints.Transformation(),
            numberer=ops.numberer.Plain(),
            system=ops.system.BandGeneral(),
            analysis=ops.analysis.Transient(),
        )
        s.run(n_increments=3, dt=0.01)

    deck = tmp_path / "staged.py"
    ops.py(str(deck), run=False)
    text = deck.read_text(encoding="utf-8")
    assert "rayleigh(" in text  # the in-stage line is in the deck

    import subprocess
    assert _PY is not None
    proc = subprocess.run(
        [_PY, str(deck)], capture_output=True, text=True,
        check=False, cwd=tmp_path,
    )
    assert proc.returncode == 0, (
        f"staged deck returned {proc.returncode}.\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
