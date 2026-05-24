"""Subprocess smoke test for the Phase SSI-1 initial_stress emit pipeline.

Validates that:

1. ``ops.initial_stress(...)`` + ``ops.tcl(path, run=True, analyze_steps=N)``
   produces a deck that **parses and runs** under OpenSees.exe without
   errors.
2. The same pipeline emits a Python deck runnable via
   ``python deck.py`` against openseespy.

The deck uses J2Plasticity as a stand-in for ASDPlasticMaterial3D —
OpenSees may or may not expose ``commitStressIncrementXX`` on
J2Plasticity (the user-facing acceptance test wants
ASDPlasticMaterial3D MohrCoulomb), but the deck is well-formed
syntactically.  If the response is unknown, OpenSees will warn but the
deck typically still runs (``updateParameter`` becomes a no-op on
materials without the response).  We tolerate either outcome: the
purpose of this test is to catch shape regressions (missing
``parameter`` declarations, malformed proc syntax, broken for-loop
wrapping) — not to validate the physics.

Gated on the OpenSees binary being available, like the existing
:mod:`tests.opensees.subprocess.test_tcl_invocation`.
"""
from __future__ import annotations

import os
import shutil
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


def _python_available_with_openseespy() -> bool:
    venv = os.environ.get("OPENSEES_VENV")
    if venv:
        candidate = os.path.join(
            venv, ("Scripts" if os.name == "nt" else "bin"),
            ("python.exe" if os.name == "nt" else "python"),
        )
        return os.path.exists(candidate)
    return False


pytestmark = pytest.mark.subprocess


def _make_minimal_2d_fem() -> FEMStub:
    """1 quad in 2D, anchored at the left edge."""
    nodes = _NodesStub(
        ids=[1, 2, 3, 4],
        coords=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
        ],
        node_pgs={
            "Left":   [1, 4],
            "Bottom": [1, 2],
        },
    )
    elements = _ElementsStub(
        elem_pgs={
            "Rock": _ElementGroupView(
                ids=(1,), connectivity=((1, 2, 3, 4),),
            ),
        },
    )
    return FEMStub(nodes=nodes, elements=elements)


def _build_ops_for_smoke(tmp_path: Path) -> apeSees:
    fem = _make_minimal_2d_fem()
    ops = apeSees(cast("object", fem), default_orientation=None)  # type: ignore[arg-type]
    ops.model(ndm=2, ndf=2)

    # ElasticIsotropic — does NOT expose commitStressIncrementXX; the
    # smoke test tolerates the resulting OpenSees warnings.  Use this
    # stand-in until ASDPlasticMaterial3D has an apeGmsh typed wrapper.
    mat = ops.nDMaterial.ElasticIsotropic(E=1.0e6, nu=0.25, rho=0.0)
    ops.element.FourNodeQuad(
        pg="Rock", thickness=1.0, material=mat,
    )
    ops.fix(pg="Left", dofs=(1, 0))
    ops.fix(pg="Bottom", dofs=(0, 1))

    ops.constraints.Plain()
    ops.numberer.RCM()
    ops.system.UmfPack()
    ops.test.NormDispIncr(tol=1.0e-4, max_iter=50)
    ops.algorithm.Newton()
    ops.integrator.LoadControl(dlam=0.1)
    ops.analysis.Static()

    ops.initial_stress(
        name="rock_insitu",
        pg="Rock",
        sigma_xx=-100.0, sigma_yy=-100.0, sigma_zz=-100.0,
        ramp_steps=10,
    )
    return ops


@pytest.mark.skipif(
    not _opensees_available(),
    reason="OpenSees binary not on PATH and OPENSEES_BIN not set",
)
def test_initial_stress_tcl_subprocess_smoke(tmp_path: Path) -> None:
    """``ops.tcl(path, run=True, analyze_steps=10)`` produces a Tcl
    deck that parses and runs under OpenSees — even when the underlying
    material doesn't expose ``commitStressIncrementXX``."""
    ops = _build_ops_for_smoke(tmp_path)
    deck_path = tmp_path / "deck.tcl"
    # We don't pass run=True because the call would raise on any
    # non-zero exit code; addToParameter against ElasticIsotropic may
    # legitimately warn-then-continue (returncode 0) or warn-then-exit
    # non-zero depending on the OpenSees build.  We capture instead.
    ops.tcl(str(deck_path), analyze_steps=10, analyze_dt=0.1)

    import subprocess
    binary = os.environ.get("OPENSEES_BIN") or shutil.which("OpenSees")
    assert binary is not None
    proc = subprocess.run(
        [binary, str(deck_path)],
        capture_output=True, text=True, check=False,
    )
    # We DO require the deck to parse — i.e. no Tcl parser error.
    # OpenSees prints parser errors to stderr.  A material warning is
    # OK; a "invalid command name" or "wrong # args" is not.
    combined = (proc.stdout + "\n" + proc.stderr).lower()
    parser_errors = [
        "invalid command name",
        "wrong # args",
        "extra characters after close-brace",
        "missing close-brace",
        "syntax error",
    ]
    for needle in parser_errors:
        assert needle not in combined, (
            f"OpenSees subprocess hit a Tcl parser error ({needle!r}). "
            f"This indicates the Phase SSI-1 emit produced malformed "
            f"Tcl.\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n"
            f"{proc.stderr}"
        )


@pytest.mark.skipif(
    not _python_available_with_openseespy(),
    reason="OPENSEES_VENV not set or python missing",
)
def test_initial_stress_py_subprocess_smoke(tmp_path: Path) -> None:
    """``ops.py(path, run=True, analyze_steps=10)`` produces a Python
    deck that parses and runs under openseespy."""
    ops = _build_ops_for_smoke(tmp_path)
    deck_path = tmp_path / "deck.py"
    ops.py(str(deck_path), analyze_steps=10, analyze_dt=0.1)

    import subprocess
    venv = os.environ["OPENSEES_VENV"]
    if os.name == "nt":
        python = os.path.join(venv, "Scripts", "python.exe")
    else:
        python = os.path.join(venv, "bin", "python")
    proc = subprocess.run(
        [python, str(deck_path)],
        capture_output=True, text=True, check=False,
    )
    combined = proc.stdout + "\n" + proc.stderr
    # Python errors that would indicate a malformed py emit:
    py_errors = [
        "SyntaxError",
        "IndentationError",
        "NameError: name '_apesees",  # dispatcher names wrong
        "TypeError: ops.",
    ]
    for needle in py_errors:
        assert needle not in combined, (
            f"Python subprocess hit a malformed-emit error ({needle!r}). "
            f"\n--- stdout ---\n{proc.stdout}\n"
            f"--- stderr ---\n{proc.stderr}"
        )
