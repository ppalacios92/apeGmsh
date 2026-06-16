"""Unit tests for the engine-free FD core (`apeGmsh.sensitivity._fd`)."""
from __future__ import annotations

import math

from apeGmsh.sensitivity import FDSensitivity


def test_central_difference_exact_on_quadratic() -> None:
    fd = FDSensitivity(lambda p: p[0] ** 2)          # f'(3) = 6
    assert math.isclose(fd.gradient([3.0])[0], 6.0, rel_tol=1e-7)


def test_gradient_vector_multiparam() -> None:
    fd = FDSensitivity(lambda p: p[0] ** 2 + 3.0 * p[1])   # grad = [2x, 3]
    g = fd.gradient([4.0, 10.0])
    assert math.isclose(g[0], 8.0, rel_tol=1e-6)
    assert math.isclose(g[1], 3.0, rel_tol=1e-6)


def test_forward_scheme_reuses_base_solve() -> None:
    fd = FDSensitivity(lambda p: p[0] ** 2 + p[1] ** 2, scheme="forward")
    fd.gradient([1.0, 1.0])
    assert fd.n_solves == 3                            # 1 base + 1 per param


def test_cache_avoids_resolves() -> None:
    fd = FDSensitivity(lambda p: p[0] ** 2)
    fd.gradient([2.0])
    n1 = fd.n_solves
    fd.gradient([2.0])
    assert fd.n_solves == n1                           # all cache hits


def test_step_study_plateau_monotone_improvement() -> None:
    fd = FDSensitivity(lambda p: p[0] ** 3)            # f'(1) = 3
    rows = fd.step_study([1.0], rel_steps=(1e-1, 1e-2, 1e-3))
    errs = [abs(g - 3.0) for _, g in rows]
    assert errs[0] > errs[1] > errs[2]


def test_unknown_scheme_raises() -> None:
    fd = FDSensitivity(lambda p: p[0])
    try:
        fd.gradient([1.0], scheme="bogus")
        assert False, "expected ValueError"
    except ValueError:
        pass
