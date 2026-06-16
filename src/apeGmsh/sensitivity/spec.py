"""Typed specs for the sensitivity driver — `Param` and `Response`.

`Param` names a parameter and its base value (optionally bounds for `solve`).
`Response` names the scalar the driver differentiates: a `Results` node selector
(`pg`/`label`/`node`) + `component` + a time `reduce` rule. `reduce_response` is
the pure NumPy reducer that turns a `(T, N)` slab into one scalar — engine-free
and unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

_REDUCERS = ("peak", "rms", "mean_abs", "last", "at_time")


@dataclass(frozen=True, kw_only=True, slots=True)
class Param:
    """A scalar parameter the model exposes (a damping knob, stiffness, mass...).

    The driver passes the current ``{name: value}`` mapping to the user's
    ``build(ops, params)`` callable, which applies it (e.g.
    ``ops.damping.rayleigh(ratio=params["xi"], ...)``). ``lower``/``upper`` are
    used only by :meth:`Sensitivity.solve`.
    """

    name: str
    value: float
    lower: Optional[float] = None
    upper: Optional[float] = None


@dataclass(frozen=True, kw_only=True, slots=True)
class Response:
    """The scalar response to differentiate, as a `Results` query + time reduce.

    Selectors mirror ``results.nodes.get`` (`pg`/`label`; `node` is an explicit
    id). ``component`` is a DOF-aware name (e.g. ``"displacement_x"``).
    ``reduce`` collapses the time axis per node, then the worst (max) node is
    taken so a PG-wide response is one number:

    - ``peak``    : ``max|v|`` over time
    - ``rms``     : ``sqrt(mean(v^2))`` over time
    - ``mean_abs``: ``mean|v|`` over time
    - ``last``    : value at the final step
    - ``at_time`` : value at the step nearest ``at_time``
    """

    component: str
    pg: Optional[str] = None
    label: Optional[str] = None
    node: Optional[int] = None
    reduce: str = "peak"
    at_time: Optional[float] = None
    absolute: bool = True

    def __post_init__(self) -> None:
        if self.reduce not in _REDUCERS:
            raise ValueError(
                f"reduce={self.reduce!r} not one of {_REDUCERS}"
            )
        if self.reduce == "at_time" and self.at_time is None:
            raise ValueError("reduce='at_time' requires at_time=")


def reduce_response(
    values: "np.ndarray",
    time: "np.ndarray",
    response: Response,
) -> float:
    """Collapse a ``(T, N)`` time x node slab to one scalar per `response`.

    Reduces along the time axis per node, then takes the worst (max) node.
    """
    v = np.asarray(values, dtype=float)
    if v.ndim == 1:
        v = v.reshape(-1, 1)
    if v.size == 0:
        raise ValueError("empty response slab — check the node selector")
    a = np.abs(v) if response.absolute else v

    if response.reduce == "peak":
        per_node = a.max(axis=0)
    elif response.reduce == "rms":
        per_node = np.sqrt((v ** 2).mean(axis=0))
    elif response.reduce == "mean_abs":
        per_node = np.abs(v).mean(axis=0)
    elif response.reduce == "last":
        per_node = a[-1, :]
    elif response.reduce == "at_time":
        t = np.asarray(time, dtype=float)
        idx = int(np.argmin(np.abs(t - float(response.at_time))))
        per_node = a[idx, :]
    else:  # pragma: no cover - guarded in __post_init__
        raise ValueError(f"unknown reduce {response.reduce!r}")

    return float(np.max(per_node))
