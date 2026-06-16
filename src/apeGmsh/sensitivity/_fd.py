"""Black-box finite-difference gradient core (engine-agnostic).

`FDSensitivity` holds a scalar `forward(values) -> float` callable and computes
its gradient by re-running with perturbed parameters. It MEMOIZES evaluations
(each is typically a full transient solve — the expensive thing) so repeated
gradients and the step-plateau sweep don't re-solve identical models, and COUNTS
solves (`n_solves`) for honest cost accounting.

This module has NO apeGmsh/OpenSees dependency — it is pure Python and is the
substance validated upstream in the Ladruno OpenSees fork (PR #241). The apeGmsh
coupling lives in `driver.py`.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

_DEFAULT_STEPS: Tuple[float, ...] = (1e-1, 3e-2, 1e-2, 3e-3, 1e-3, 3e-4)


class FDSensitivity:
    """Finite-difference gradient of a scalar response.

    Parameters
    ----------
    forward
        ``callable(values) -> float`` — the forward solve; returns the scalar
        response to differentiate.
    rel_step
        Default relative perturbation; per-component step ``h_i = rel_step*|x_i|``,
        floored by ``abs_floor`` so zero components still get a step.
    scheme
        ``"central"`` (2 solves/param, O(h^2)) or ``"forward"`` (1 solve/param,
        O(h), reuses the base solve across components).
    abs_floor
        Minimum absolute step.
    cache
        Memoize ``forward`` by rounded-parameter key (default ``True``).

    Attributes
    ----------
    n_solves
        Count of ACTUAL ``forward`` calls (cache hits excluded).
    """

    def __init__(
        self,
        forward: Callable[[Sequence[float]], float],
        *,
        rel_step: float = 1e-2,
        scheme: str = "central",
        abs_floor: float = 1e-10,
        cache: bool = True,
        round_key: int = 12,
    ) -> None:
        self.forward = forward
        self.rel_step = rel_step
        self.scheme = scheme
        self.abs_floor = abs_floor
        self.round_key = round_key
        self._cache: Optional[Dict[Tuple[float, ...], float]] = {} if cache else None
        self.n_solves = 0

    # -- internals -------------------------------------------------------
    def _eval(self, x: Sequence[float]) -> float:
        x = list(map(float, x))
        key = tuple(round(v, self.round_key) for v in x) if self._cache is not None else None
        if key is not None and key in self._cache:
            return self._cache[key]
        self.n_solves += 1
        val = float(self.forward(x))
        if key is not None:
            self._cache[key] = val
        return val

    def _h(self, xi: float, rel_step: float) -> float:
        h = rel_step * abs(xi)
        return h if h >= self.abs_floor else self.abs_floor

    # -- public ----------------------------------------------------------
    def reset_cache(self) -> None:
        if self._cache is not None:
            self._cache.clear()
        self.n_solves = 0

    def gradient(
        self,
        x0: Sequence[float],
        *,
        rel_step: Optional[float] = None,
        scheme: Optional[str] = None,
    ) -> List[float]:
        """``d(response)/d(x)`` at ``x0``. Uncached cost: central -> ``2*len(x0)``,
        forward -> ``len(x0)+1``."""
        rel_step = self.rel_step if rel_step is None else rel_step
        scheme = self.scheme if scheme is None else scheme
        x0 = list(map(float, x0))
        n = len(x0)
        grad = [0.0] * n

        if scheme == "forward":
            f0 = self._eval(x0)

        for i in range(n):
            h = self._h(x0[i], rel_step)
            if scheme == "central":
                xp = list(x0); xp[i] += h
                xm = list(x0); xm[i] -= h
                grad[i] = (self._eval(xp) - self._eval(xm)) / (2.0 * h)
            elif scheme == "forward":
                xp = list(x0); xp[i] += h
                grad[i] = (self._eval(xp) - f0) / h
            else:
                raise ValueError(f"unknown scheme {scheme!r}")
        return grad

    def step_study(
        self,
        x0: Sequence[float],
        *,
        comp: int = 0,
        rel_steps: Sequence[float] = _DEFAULT_STEPS,
    ) -> List[Tuple[float, float]]:
        """Sweep the FD step for one component to expose the trust plateau.
        Returns ``[(rel_step, central_fd_gradient_component), ...]``. The flat
        region is the reliable estimate; growth at large step = truncation,
        growth at tiny step = round-off."""
        out: List[Tuple[float, float]] = []
        for r in rel_steps:
            g = self.gradient(x0, rel_step=r, scheme="central")[comp]
            out.append((r, g))
        return out
