"""Subprocess runtime test for ADR 0052 slice 1 — ``s.support`` HOLD.

Builds a 2-stage single-quad model via apeSees, emits the Tcl deck,
runs it on the Ladruno OpenSees binary, and verifies the *runtime*
HOLD-vs-ANCHOR asymmetry that the ADR is about:

  Stage 1 pushes the free top-right node to a displacement ``d`` via a
  nodal load.  ``loadConst`` freezes that load as the constant baseline.
  Stage 2 then constrains that node's X DOF:

  * ``s.support`` (HOLD) — pins it at its CURRENT position ``d`` with
    zero initial force: the node STAYS at ``d``.
  * ``s.fix`` (ANCHOR) — drives it back to ``t = 0``: the node SNAPS
    toward 0 (the frozen load is now reacted by the support).

This proves the emitted ``sp ... [nodeDisp ...] -const`` deck actually
behaves as designed, not just that it has the right text.

Gated on the OpenSees binary being available.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import cast

import pytest

from apeGmsh.opensees import apeSees

from tests.opensees.fixtures.fem_stub import (
    FEMStub,
    _ElementGroupView,
    _ElementsStub,
    _NodesStub,
)


def _opensees_available() -> bool:
    return bool(os.environ.get("OPENSEES_BIN") or shutil.which("OpenSees"))


pytestmark = [
    pytest.mark.subprocess,
    pytest.mark.skipif(
        not _opensees_available(),
        reason="OpenSees binary not on PATH and OPENSEES_BIN not set",
    ),
]


def _make_single_quad_fem() -> FEMStub:
    return FEMStub(
        nodes=_NodesStub(
            ids=[1, 2, 3, 4],
            coords=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.0, 1.0, 0.0),
                (0.0, 1.0, 0.0),
            ],
            # Bottom edge fully fixed; top edge free.
            node_pgs={"Bottom": [1, 2], "TopRight": [3]},
        ),
        elements=_ElementsStub(
            elem_pgs={
                "Block": _ElementGroupView(
                    ids=(1,), connectivity=((1, 2, 3, 4),),
                ),
            },
        ),
    )


def _full_chain(ops: apeSees) -> dict[str, object]:
    return {
        "test":        ops.test.NormDispIncr(tol=1e-8, max_iter=50),
        "algorithm":   ops.algorithm.Newton(),
        "integrator":  ops.integrator.LoadControl(dlam=0.1),
        "constraints": ops.constraints.Transformation(),
        "numberer":    ops.numberer.Plain(),
        "system":      ops.system.FullGeneral(),
        "analysis":    ops.analysis.Static(),
    }


def _build_deck(stage2_kind: str) -> apeSees:
    """2-stage quad: stage 1 pushes node 3 in +X; stage 2 either HOLDs
    or ANCHORs node 3's X DOF.  ``stage2_kind`` in {"support", "fix"}."""
    fem = _make_single_quad_fem()
    ops = apeSees(cast("object", fem), default_orientation=None)  # type: ignore[arg-type]
    ops.model(ndm=2, ndf=2)
    mat3d = ops.nDMaterial.ElasticIsotropic(E=2.0e5, nu=0.0, rho=0.0)
    mat2d = ops.nDMaterial.PlaneStrain(base=mat3d)
    ops.element.FourNodeQuad(
        pg="Block", thickness=1.0, material=mat2d, plane_type="PlaneStrain",
    )
    ops.fix(pg="Bottom", dofs=(1, 1))

    # Stage 1: ramp a +X point load on node 3 to full → node 3 drifts.
    with ops.stage(name="push") as s:
        ts = ops.timeSeries.Linear()
        with s.pattern(series=ts) as p:
            p.load(node=3, forces=(1.0e3, 0.0))
        s.analysis(**_full_chain(ops))
        s.run(n_increments=10, dt=0.1)

    # Stage 2: constrain node 3's X DOF — HOLD vs ANCHOR.
    with ops.stage(name="lock") as s:
        if stage2_kind == "support":
            s.support(nodes=[3], dofs=(1, 0))
        else:
            s.fix(nodes=[3], dofs=(1, 0))
        s.analysis(**_full_chain(ops))
        s.run(n_increments=5, dt=0.1)

    return ops


def _emit_with_recorder(ops: apeSees, tmp_path: Path) -> tuple[Path, Path]:
    """Emit the Tcl deck, post-pend a node-3 X-disp recorder before the
    first stage banner so it captures both stages."""
    deck = tmp_path / "deck.tcl"
    ops.tcl(str(deck))
    disp_out = tmp_path / "disp.out"
    disp_posix = str(disp_out).replace("\\", "/")
    text = deck.read_text()
    text = text.replace(
        "# === Stage: push ===",
        f"recorder Node -file {disp_posix} -time -node 3 -dof 1 disp\n"
        "# === Stage: push ===",
        1,
    )
    deck.write_text(text)
    return deck, disp_out


def _run(deck: Path) -> None:
    binary = os.environ.get("OPENSEES_BIN") or shutil.which("OpenSees")
    assert binary is not None
    proc = subprocess.run(
        [binary, str(deck)], capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, (
        f"OpenSees exit {proc.returncode}\n"
        f"--- stdout (tail) ---\n"
        f"{chr(10).join(proc.stdout.splitlines()[-40:])}\n"
        f"--- stderr (tail) ---\n"
        f"{chr(10).join(proc.stderr.splitlines()[-40:])}"
    )


def _disp_rows(disp_out: Path) -> list[float]:
    assert disp_out.exists(), "recorder produced no output"
    rows = [
        float(ln.split()[1])
        for ln in disp_out.read_text().splitlines()
        if ln.strip()
    ]
    # 10 stage-1 steps + 5 stage-2 steps.
    assert len(rows) == 15, f"expected 15 disp rows, got {len(rows)}"
    return rows


def test_support_holds_deformed_position(tmp_path: Path) -> None:
    """HOLD: node 3 stays at its stage-1 drifted position through
    stage 2 (zero initial force, no snap)."""
    ops = _build_deck("support")
    deck, disp_out = _emit_with_recorder(ops, tmp_path)
    _run(deck)
    rows = _disp_rows(disp_out)
    d_stage1 = rows[9]   # node 3 X-disp after stage 1
    d_final = rows[14]   # after stage 2 (HOLD)
    assert d_stage1 > 1e-4, (
        f"stage 1 should have pushed node 3 to a positive drift; "
        f"got {d_stage1:.3e}"
    )
    # HOLD preserves the deformed position: final ≈ stage-1 value.
    assert abs(d_final - d_stage1) < 1e-6 * max(1.0, abs(d_stage1)) + 1e-9, (
        f"HOLD should preserve node 3 at d={d_stage1:.6e}, "
        f"but it moved to {d_final:.6e}"
    )


def test_fix_snaps_to_reference(tmp_path: Path) -> None:
    """ANCHOR: the same node, fixed in stage 2 instead, snaps back
    toward t=0 — the contrast that makes HOLD meaningful."""
    ops = _build_deck("fix")
    deck, disp_out = _emit_with_recorder(ops, tmp_path)
    _run(deck)
    rows = _disp_rows(disp_out)
    d_stage1 = rows[9]
    d_final = rows[14]
    assert d_stage1 > 1e-4
    # ANCHOR drives node 3 back to its reference position.
    assert abs(d_final) < 1e-6 * max(1.0, abs(d_stage1)) + 1e-9, (
        f"fix should snap node 3 back to ~0, but it is at {d_final:.6e}"
    )
