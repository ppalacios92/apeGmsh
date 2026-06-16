"""Unit tests for the `Sensitivity` driver, using a fake (engine-free) forward."""
from __future__ import annotations

import math

import pytest

from apeGmsh.sensitivity import Param, Sensitivity


def _fake(pm):
    # R(xi, k) = 1/xi + 0.001*k  ->  dR/dxi = -1/xi^2,  dR/dk = 0.001
    return 1.0 / pm["xi"] + 0.001 * pm["k"]


def test_named_gradient_keys_and_values() -> None:
    sens = Sensitivity(_fake, [Param(name="xi", value=0.05), Param(name="k", value=100.0)])
    g = sens.gradient()
    assert set(g) == {"xi", "k"}
    assert math.isclose(g["xi"], -1.0 / 0.05 ** 2, rel_tol=1e-4)
    assert math.isclose(g["k"], 0.001, rel_tol=1e-4)


def test_gradient_at_override_point() -> None:
    sens = Sensitivity(_fake, [Param(name="xi", value=0.05), Param(name="k", value=100.0)])
    g = sens.gradient({"xi": 0.10, "k": 100.0})
    assert math.isclose(g["xi"], -1.0 / 0.10 ** 2, rel_tol=1e-4)


def test_requires_at_least_one_param() -> None:
    with pytest.raises(ValueError):
        Sensitivity(_fake, [])


def test_duplicate_param_names_rejected() -> None:
    with pytest.raises(ValueError):
        Sensitivity(_fake, [Param(name="a", value=1.0), Param(name="a", value=2.0)])


def test_step_study_by_name() -> None:
    sens = Sensitivity(_fake, [Param(name="xi", value=0.05), Param(name="k", value=100.0)])
    rows = sens.step_study("xi", rel_steps=(1e-1, 1e-2, 1e-3))
    target = -1.0 / 0.05 ** 2
    errs = [abs(g - target) for _, g in rows]
    assert errs[0] > errs[-1]                          # plateau improves


def test_solve_1d_calibration() -> None:
    # R(xi) = 1/xi ; target 10 -> xi = 0.1
    sens = Sensitivity(lambda pm: 1.0 / pm["xi"],
                       [Param(name="xi", value=0.05, lower=1e-3, upper=1.0)])
    sol = sens.solve(10.0)
    assert math.isclose(sol["xi"], 0.1, rel_tol=1e-4)


def test_solve_multiparam_not_implemented() -> None:
    sens = Sensitivity(_fake, [Param(name="xi", value=0.05), Param(name="k", value=1.0)])
    with pytest.raises(NotImplementedError):
        sens.solve(1.0)


def test_solve_flat_response_raises() -> None:
    sens = Sensitivity(lambda pm: 42.0, [Param(name="xi", value=0.05)])
    with pytest.raises(ValueError):
        sens.solve(10.0)


def test_from_apesees_constructs_without_engine() -> None:
    # Construction must not import or touch the engine (lazy until forward call).
    from apeGmsh.sensitivity import Param, Response, Sensitivity

    def _build(ops, params):  # pragma: no cover - never called here
        raise AssertionError("build must not run at construction time")

    def _runner(ops, response, steps, dt, capture_path):  # pragma: no cover
        raise AssertionError("runner must not run at construction time")

    sens = Sensitivity.from_apesees(
        fem=object(), build=_build,
        params=[Param(name="xi", value=0.05)],
        response=Response(pg="Roof", component="displacement_x", reduce="peak"),
        steps=10, dt=0.01, runner=_runner,
    )
    assert sens.param_names == ("xi",)


def test_runner_seam_is_injectable() -> None:
    # A fake runner returns a (T, N) history; the forward must reduce it and the
    # gradient must compose — all without a real engine. The fake apeSees stashes
    # the params on a dict so the runner can read them.
    import sys
    import types

    import numpy as np

    from apeGmsh.sensitivity import Param, Response
    from apeGmsh.sensitivity.driver import _ApeSeesForward

    class _FakeOps(dict):
        def build(self):  # noqa: D401
            return None

    fake_mod = types.ModuleType("apeGmsh.opensees")
    fake_mod.apeSees = lambda fem: _FakeOps()
    saved = sys.modules.get("apeGmsh.opensees")
    sys.modules["apeGmsh.opensees"] = fake_mod
    try:
        def _build(ops, params):
            ops.update(params)

        def _runner(ops, response, steps, dt, capture_path):
            return np.array([[0.0], [1.0 / ops["xi"]]]), np.array([0.0, dt])

        fwd = _ApeSeesForward(
            fem=None, build=_build,
            response=Response(node=1, component="displacement_x", reduce="peak"),
            steps=2, dt=0.5, capture_path=None, runner=_runner,
        )
        assert math.isclose(fwd({"xi": 0.05}), 20.0, rel_tol=1e-9)
    finally:
        if saved is None:
            sys.modules.pop("apeGmsh.opensees", None)
        else:
            sys.modules["apeGmsh.opensees"] = saved
