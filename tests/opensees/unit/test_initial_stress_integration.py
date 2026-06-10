"""End-to-end integration test for ``apeSees.initial_stress`` (Phase SSI-1).

Wires a tiny 1-element 2D quad mesh through the apeSees bridge and
verifies the emitted Tcl + Python deck shape.  Does NOT run OpenSees
itself — that's covered by the acceptance test that runs against the
Ladruno binary (see ``tests/opensees/integration/`` once it exists).

The test uses ``ElasticIsotropic`` as a stand-in for
``ASDPlasticMaterial3D`` so the emit pipeline can be exercised
without an ASDPlasticMaterial3D source dep — ``addToParameter`` is
emitted symbolically in either case (the actual response is only
evaluated by OpenSees at analyze time).
"""
from __future__ import annotations

import os

import pytest

from apeGmsh.opensees.apesees import apeSees
from tests.opensees.fixtures.fem_stub import (
    FEMStub,
    _ElementGroupView,
    _ElementsStub,
    _NodesStub,
)


def _make_single_quad_fem() -> FEMStub:
    """One 4-node quad, nodes laid out as a unit square in XY."""
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
            "Right":  [2, 3],
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


def _build_ops_with_initial_stress(tmp_path):
    """Construct an apeSees bridge with one quad + one initial_stress
    directive.  Returns (ops, tcl_path, py_path)."""
    fem = _make_single_quad_fem()
    ops = apeSees(fem, default_orientation=None)
    ops.model(ndm=2, ndf=2)

    # 3D continuum material — ElasticIsotropic stands in for any
    # ASDPlasticMaterial3D that exposes commitStressIncrementXX.
    mat = ops.nDMaterial.ElasticIsotropic(E=1.0e6, nu=0.3, rho=0.0)
    ops.element.FourNodeQuad(
        pg="Rock",
        thickness=1.0,
        material=mat,
        plane_type="PlaneStrain",
    )
    ops.fix(pg="Left", dofs=(1, 0))
    ops.fix(pg="Bottom", dofs=(0, 1))

    # Analysis chain — minimal, valid combinations.
    ops.constraints.Plain()
    ops.numberer.RCM()
    ops.system.UmfPack()
    ops.test.NormDispIncr(tol=1.0e-4, max_iter=50)
    ops.algorithm.Newton()
    ops.integrator.LoadControl(dlam=0.1)
    ops.analysis.Static()

    # The phase SSI-1 entry point.
    ops.initial_stress(
        name="rock_insitu",
        pg="Rock",
        sigma_xx=-6300.0,
        sigma_yy=-6300.0,
        sigma_zz=-6300.0,
        ramp_steps=10,
    )

    tcl_path = str(tmp_path / "deck.tcl")
    py_path = str(tmp_path / "deck.py")
    return ops, tcl_path, py_path


def test_initial_stress_tcl_emit_shape(tmp_path) -> None:
    ops, tcl_path, _ = _build_ops_with_initial_stress(tmp_path)
    ops.tcl(tcl_path, analyze_steps=10, analyze_dt=0.1)

    with open(tcl_path, "r", encoding="utf-8") as f:
        text = f.read()

    # 1. Topology: nodes + element present.  The element tag is
    # allocated from the per-kind "element" counter, which is
    # SEEDED by the primitive's own registration — so the element
    # fan-out tag is typically ``primitive_tag + 1``, not 1.  Just
    # check shape, not the exact tag.
    assert "model BasicBuilder -ndm 2 -ndf 2" in text
    assert "node 1" in text
    assert any(
        ln.startswith("element quad ") for ln in text.splitlines()
    )

    # 2. Material declared.
    assert "nDMaterial ElasticIsotropic 1" in text

    # 3. Dispatcher boilerplate emitted exactly once.
    assert text.count(
        "# apeSees per-step hook dispatcher (Phase SSI-1)"
    ) == 1
    assert "set _apesees_before_step_hooks {}" in text
    assert "proc _apesees_call_before_step {}" in text

    # 4. Parameter declarations (three: XX, YY, ZZ).
    # We don't hardcode the tag numbers because the allocator order
    # could change — but at minimum there must be three "parameter N"
    # lines.
    param_lines = [ln for ln in text.splitlines() if ln.startswith("parameter ")]
    assert len(param_lines) == 3, (
        f"expected 3 parameter declarations, got {param_lines}"
    )

    # 5. Per-stress proc body emitted with the right name.
    assert "proc rock_insitu {}" in text
    assert "set rock_insitu_state(count) [expr {$rock_insitu_state(count) + 1}]" in text
    # n_steps_to_full == ramp_steps == 10 (lambda_install default 1.0).
    assert "set _factor [expr {$rock_insitu_state(count) / 10.0}]" in text
    # Target == sigma * lambda_install == -6300.0 * 1.0.
    assert "-6300.0" in text

    # 6. lappend registration.
    assert "lappend _apesees_before_step_hooks rock_insitu" in text

    # 7. addToParameter — one per (parameter, element) for each of
    # XX/YY/ZZ.  With one element, that's 3 addToParameter lines.
    add_lines = [
        ln for ln in text.splitlines() if ln.startswith("addToParameter ")
    ]
    assert len(add_lines) == 3, (
        f"expected 3 addToParameter lines (1 element × 3 components), "
        f"got {add_lines}"
    )
    # Verify each component is represented.
    assert any("commitStressIncrementXX" in ln for ln in add_lines)
    assert any("commitStressIncrementYY" in ln for ln in add_lines)
    assert any("commitStressIncrementZZ" in ln for ln in add_lines)

    # 8. Analyze loop is hook-wrapped (because initial_stress
    # registered a step hook), and uses dt=0.1.
    assert (
        "for {set _apesees_i 0} {$_apesees_i < 10} {incr _apesees_i} {"
        in text
    )
    assert "_apesees_call_before_step" in text
    assert "analyze 1 0.1" in text
    assert "_apesees_call_after_step" in text


def test_initial_stress_py_emit_shape(tmp_path) -> None:
    ops, _, py_path = _build_ops_with_initial_stress(tmp_path)
    ops.py(py_path, analyze_steps=10, analyze_dt=0.1)

    with open(py_path, "r", encoding="utf-8") as f:
        text = f.read()

    assert "import openseespy.opensees as ops" in text
    assert "ops.model('basic', '-ndm', 2, '-ndf', 2)" in text
    assert "ops.nDMaterial('ElasticIsotropic', 1," in text

    # Dispatcher.
    assert text.count("# apeSees per-step hook dispatcher (Phase SSI-1)") == 1
    assert "_apesees_before_step_hooks: list = []" in text
    assert "def _apesees_call_before_step()" in text

    # Parameter declarations + per-stress function + lappend.
    assert "ops.parameter(" in text
    assert "def rock_insitu()" in text
    assert "_apesees_before_step_hooks.append(rock_insitu)" in text

    # addToParameter per element / component (3 lines for 1 element).
    add_lines = [
        ln.strip() for ln in text.splitlines()
        if ln.strip().startswith("ops.addToParameter(")
    ]
    assert len(add_lines) == 3
    joined = "\n".join(add_lines)
    assert "'commitStressIncrementXX'" in joined
    assert "'commitStressIncrementYY'" in joined
    assert "'commitStressIncrementZZ'" in joined

    # Hook-wrapped analyze loop.
    assert "for _apesees_i in range(10):" in text
    assert "ops.analyze(1, 0.1)" in text


def test_initial_stress_emit_order_is_correct(tmp_path) -> None:
    """parameter declarations MUST come before any addToParameter
    referencing them — OpenSees errors otherwise."""
    ops, tcl_path, _ = _build_ops_with_initial_stress(tmp_path)
    ops.tcl(tcl_path, analyze_steps=10)
    with open(tcl_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    first_param = next(
        i for i, ln in enumerate(lines) if ln.startswith("parameter ")
    )
    first_addto = next(
        i for i, ln in enumerate(lines) if ln.startswith("addToParameter ")
    )
    assert first_param < first_addto


def test_initial_stress_validates_inputs(tmp_path) -> None:
    """Construction-time validation: name shape, ramp_steps, lambda_install."""
    fem = _make_single_quad_fem()
    ops = apeSees(fem, default_orientation=None)
    ops.model(ndm=2, ndf=2)

    with pytest.raises(ValueError, match="exactly one of pg= or elements="):
        ops.initial_stress(
            name="bad", sigma_xx=-100, sigma_yy=-100, sigma_zz=-100,
            ramp_steps=1,
        )

    with pytest.raises(ValueError, match="exactly one of pg= or elements="):
        ops.initial_stress(
            name="bad", pg="Rock", elements=[1],
            sigma_xx=-100, sigma_yy=-100, sigma_zz=-100, ramp_steps=1,
        )

    with pytest.raises(ValueError, match="ramp_steps must be >= 1"):
        ops.initial_stress(
            name="bad", pg="Rock",
            sigma_xx=-100, sigma_yy=-100, sigma_zz=-100,
            ramp_steps=0,
        )

    with pytest.raises(ValueError, match=r"lambda_install must be in \(0, 1\]"):
        ops.initial_stress(
            name="bad", pg="Rock",
            sigma_xx=-100, sigma_yy=-100, sigma_zz=-100,
            ramp_steps=1, lambda_install=1.5,
        )

    with pytest.raises(ValueError, match="must be a valid Tcl identifier"):
        ops.initial_stress(
            name="123bad",  # starts with digit
            pg="Rock", sigma_xx=-100, sigma_yy=-100, sigma_zz=-100,
            ramp_steps=1,
        )

    with pytest.raises(ValueError, match="name= must be non-empty"):
        ops.initial_stress(
            name="", pg="Rock",
            sigma_xx=-100, sigma_yy=-100, sigma_zz=-100, ramp_steps=1,
        )


def test_initial_stress_lambda_install_scales_target_in_emit(tmp_path) -> None:
    """target_value passed to step_hook_ramp = sigma * lambda_install."""
    fem = _make_single_quad_fem()
    ops = apeSees(fem, default_orientation=None)
    ops.model(ndm=2, ndf=2)
    mat = ops.nDMaterial.ElasticIsotropic(E=1e6, nu=0.3, rho=0.0)
    ops.element.FourNodeQuad(
        pg="Rock", thickness=1.0, material=mat,
    )
    ops.fix(pg="Left", dofs=(1, 0))
    ops.constraints.Plain()
    ops.numberer.RCM()
    ops.system.UmfPack()
    ops.test.NormDispIncr(tol=1e-4, max_iter=50)
    ops.algorithm.Newton()
    ops.integrator.LoadControl(dlam=0.1)
    ops.analysis.Static()
    ops.initial_stress(
        name="half_install",
        pg="Rock",
        sigma_xx=-6300.0, sigma_yy=-6300.0, sigma_zz=-6300.0,
        ramp_steps=10,
        lambda_install=0.5,
    )
    tcl_path = str(tmp_path / "deck.tcl")
    ops.tcl(tcl_path)
    with open(tcl_path, "r", encoding="utf-8") as f:
        text = f.read()
    # Target value = sigma * lambda_install = -6300 * 0.5 = -3150.
    # The ramp proc multiplies _factor by this target.
    assert "-3150.0" in text
    # The raw -6300 should NOT appear as the ramp target (the proc
    # uses the SCALED target).
    assert "set _cur [expr {-6300.0 * $_factor}]" not in text


def test_no_initial_stress_means_no_hook_wrap(tmp_path) -> None:
    """If no initial_stress is registered, the analyze loop carries no
    hook-dispatcher wrapping (the fail-loud per-increment loop itself is
    always present)."""
    fem = _make_single_quad_fem()
    ops = apeSees(fem, default_orientation=None)
    ops.model(ndm=2, ndf=2)
    mat = ops.nDMaterial.ElasticIsotropic(E=1e6, nu=0.3, rho=0.0)
    ops.element.FourNodeQuad(
        pg="Rock", thickness=1.0, material=mat,
    )
    ops.fix(pg="Left", dofs=(1, 0))
    ops.constraints.Plain()
    ops.numberer.RCM()
    ops.system.UmfPack()
    ops.test.NormDispIncr(tol=1e-4, max_iter=50)
    ops.algorithm.Newton()
    ops.integrator.LoadControl(dlam=0.1)
    ops.analysis.Static()
    tcl_path = str(tmp_path / "deck.tcl")
    ops.tcl(tcl_path, analyze_steps=5)
    with open(tcl_path, "r", encoding="utf-8") as f:
        text = f.read()
    # No dispatcher, no hook calls (the fail-loud per-increment loop is
    # always present, but carries no hook wrapping).
    assert "_apesees_call_before_step" not in text
    assert "_apesees_call_after_step" not in text
    assert "parameter " not in text  # space after to avoid matching "parameters"
    # rc-checked per-increment analyze loop, never a bare ``analyze 5``.
    assert "analyze 5" not in text
    assert "for {set _apesees_i 0} {$_apesees_i < 5}" in text
    assert "[analyze 1]" in text
