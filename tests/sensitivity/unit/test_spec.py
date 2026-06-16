"""Unit tests for `Param` / `Response` and the pure `reduce_response` reducer."""
from __future__ import annotations

import math

import numpy as np
import pytest

from apeGmsh.sensitivity import Response, reduce_response


def _vals():
    # (T=4, N=1): 0, 0.5, -0.9, 0.3
    return np.array([[0.0], [0.5], [-0.9], [0.3]]), np.array([0.0, 1.0, 2.0, 3.0])


def test_reduce_peak() -> None:
    v, t = _vals()
    r = reduce_response(v, t, Response(component="d", node=1, reduce="peak"))
    assert math.isclose(r, 0.9)


def test_reduce_last() -> None:
    v, t = _vals()
    r = reduce_response(v, t, Response(component="d", node=1, reduce="last"))
    assert math.isclose(r, 0.3)


def test_reduce_at_time() -> None:
    v, t = _vals()
    r = reduce_response(v, t, Response(component="d", node=1, reduce="at_time", at_time=2.0))
    assert math.isclose(r, 0.9)


def test_reduce_rms() -> None:
    v, t = _vals()
    r = reduce_response(v, t, Response(component="d", node=1, reduce="rms"))
    assert math.isclose(r, math.sqrt((0.0 + 0.25 + 0.81 + 0.09) / 4), rel_tol=1e-9)


def test_reduce_multinode_takes_worst() -> None:
    v = np.array([[0.1, -0.4], [0.2, 0.3]])           # worst-node peak = 0.4
    t = np.array([0.0, 1.0])
    r = reduce_response(v, t, Response(component="d", pg="X", reduce="peak"))
    assert math.isclose(r, 0.4)


def test_reduce_empty_raises() -> None:
    with pytest.raises(ValueError):
        reduce_response(np.empty((0, 0)), np.empty((0,)),
                        Response(component="d", node=1, reduce="peak"))


def test_response_bad_reduce_raises() -> None:
    with pytest.raises(ValueError):
        Response(component="d", node=1, reduce="bogus")


def test_response_at_time_requires_time() -> None:
    with pytest.raises(ValueError):
        Response(component="d", node=1, reduce="at_time")
