"""`Sensitivity` — the apeGmsh finite-difference sensitivity driver.

Two ways to construct it:

- **Core** ``Sensitivity(forward, params)`` — you supply a scalar
  ``forward({name: value}) -> float``. Engine-agnostic, fully unit-testable.
- **apeSees** ``Sensitivity.from_apesees(fem, build=, params=, response=, ...)`` —
  the driver builds the deck via ``apeSees(fem)`` + your ``build(ops, params)``,
  runs a transient with an in-process ``DomainCapture``, reads the scalar back
  through ``Results``, and differentiates it. This is the live-engine adapter.

`gradient` returns the full vector for one or many parameters (cost ``2N`` central
/ ``N+1`` forward solves); `solve` calibrates (inverts) for a scalar target.
"""
from __future__ import annotations

from typing import Callable, List, Mapping, Optional, Sequence, Tuple

from ._fd import FDSensitivity
from .spec import Param, Response, reduce_response

ForwardFn = Callable[[Mapping[str, float]], float]


class Sensitivity:
    """Finite-difference response sensitivity over named parameters."""

    def __init__(
        self,
        forward: ForwardFn,
        params: Sequence[Param],
        *,
        rel_step: float = 1e-2,
        scheme: str = "central",
    ) -> None:
        params = tuple(params)
        if not params:
            raise ValueError("Sensitivity needs at least one Param")
        names = [p.name for p in params]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate Param names: {names}")
        self._params = params
        self._forward_named = forward
        self._fd = FDSensitivity(self._forward_vector, rel_step=rel_step, scheme=scheme)

    # -- introspection ---------------------------------------------------
    @property
    def param_names(self) -> Tuple[str, ...]:
        return tuple(p.name for p in self._params)

    @property
    def x0(self) -> List[float]:
        return [p.value for p in self._params]

    @property
    def n_solves(self) -> int:
        return self._fd.n_solves

    def reset(self) -> None:
        self._fd.reset_cache()

    # -- internals -------------------------------------------------------
    def _forward_vector(self, values: Sequence[float]) -> float:
        mapping = {p.name: float(v) for p, v in zip(self._params, values)}
        return float(self._forward_named(mapping))

    def _vec(self, at: Optional[Mapping[str, float]]) -> List[float]:
        if at is None:
            return self.x0
        return [float(at[p.name]) for p in self._params]

    # -- public ----------------------------------------------------------
    def gradient(
        self,
        at: Optional[Mapping[str, float]] = None,
        *,
        rel_step: Optional[float] = None,
        scheme: Optional[str] = None,
    ) -> Mapping[str, float]:
        """``d(response)/d(param)`` for every parameter, as ``{name: value}``."""
        g = self._fd.gradient(self._vec(at), rel_step=rel_step, scheme=scheme)
        return dict(zip(self.param_names, g))

    def step_study(
        self,
        param: Optional[str] = None,
        *,
        at: Optional[Mapping[str, float]] = None,
        rel_steps: Optional[Sequence[float]] = None,
    ) -> List[Tuple[float, float]]:
        """Step-size sweep for one parameter — ALWAYS check the plateau before
        trusting a gradient. ``param`` defaults to the first."""
        comp = 0 if param is None else self.param_names.index(param)
        kw = {} if rel_steps is None else {"rel_steps": tuple(rel_steps)}
        return self._fd.step_study(self._vec(at), comp=comp, **kw)

    def solve(
        self,
        target: float,
        *,
        tol: float = 1e-6,
        max_iter: int = 50,
        damping: float = 1.0,
    ) -> Mapping[str, float]:
        """Calibrate: find the parameter value(s) where the response equals
        ``target``. Single parameter only — a damped-Newton scalar solve using
        the FD gradient. For multi-parameter calibration feed :meth:`gradient`
        to ``scipy.optimize`` (raised as a clear ``NotImplementedError``)."""
        if len(self._params) != 1:
            raise NotImplementedError(
                "Sensitivity.solve handles ONE parameter; for multi-parameter "
                "calibration feed .gradient() to scipy.optimize.least_squares"
            )
        p = self._params[0]
        x = float(p.value)
        for _ in range(max_iter):
            r = self._forward_vector([x]) - float(target)
            if abs(r) <= tol:
                break
            slope = self._fd.gradient([x])[0]
            if slope == 0.0:
                raise ValueError(
                    f"zero sensitivity at {p.name}={x:g}; response is flat in "
                    "this parameter (cannot invert)"
                )
            x -= damping * r / slope
            if p.lower is not None:
                x = max(x, p.lower)
            if p.upper is not None:
                x = min(x, p.upper)
        return {p.name: x}

    # -- live-engine adapter --------------------------------------------
    @classmethod
    def from_apesees(
        cls,
        fem: object,
        *,
        build: "Callable[..., None]",
        params: Sequence[Param],
        response: Response,
        steps: int,
        dt: float,
        runner: "Optional[RunnerFn]" = None,
        capture_path: Optional[str] = None,
        rel_step: float = 1e-2,
        scheme: str = "central",
    ) -> "Sensitivity":
        """Build a `Sensitivity` whose ``forward`` runs a transient via the
        live ``apeSees`` bridge.

        ``build`` is ``callable(ops, params)`` — given a fresh ``apeSees(fem)``
        and the current ``{name: value}`` mapping, it declares the deck
        (materials, elements, fixities, masses, the damping knob from ``params``,
        and the excitation). The driver runs the transient, reads the response
        time-history, and reduces it per ``response``.

        The run-and-read step is delegated to ``runner`` (default
        :func:`default_apesees_runner`) so the exact transient/capture mechanism
        is a single replaceable seam — swap it if your apeGmsh build differs.
        Requires a live OpenSees engine.
        """
        fwd = _ApeSeesForward(
            fem=fem, build=build, response=response,
            steps=steps, dt=dt, capture_path=capture_path,
            runner=runner or default_apesees_runner,
        )
        return cls(fwd, params, rel_step=rel_step, scheme=scheme)


# Run-and-read seam: (ops, response, steps, dt, capture_path) -> (values, time).
RunnerFn = Callable[[object, Response, int, float, Optional[str]], "Tuple[object, object]"]


def _response_selector(response: Response) -> Mapping[str, object]:
    if response.pg is not None:
        return {"pg": response.pg}
    if response.label is not None:
        return {"label": response.label}
    if response.node is not None:
        return {"ids": (response.node,)}
    raise ValueError("Response needs one of pg=, label=, node=")


def default_apesees_runner(
    ops: object,
    response: Response,
    steps: int,
    dt: float,
    capture_path: Optional[str],
) -> "Tuple[object, object]":
    """Default run-and-read for `Sensitivity.from_apesees`.

    Declares an in-process ``DomainCapture`` for the response node(s), steps the
    transient, then reads the time-history back via ``Results.from_native``.
    Returns ``(values, time)`` arrays for `reduce_response`.

    This is the one engine-coupled seam in the module — it depends on the live
    ``apeSees``/``Results``/``DomainCapture`` API. If a future apeGmsh build
    changes that contract, pass your own ``runner=`` to ``from_apesees`` rather
    than editing the driver. (The deck is already built on ``ops`` by the caller.)
    """
    import os
    import tempfile

    from apeGmsh.results import Results
    from apeGmsh.results.capture.spec import DomainCaptureSpec

    sel = _response_selector(response)
    family = response.component.split("_")[0]
    spec = DomainCaptureSpec(opensees=ops)
    spec.nodes(components=[family], **sel)  # type: ignore[arg-type]

    path = capture_path or os.path.join(
        tempfile.gettempdir(), "apegmsh_sensitivity_capture.h5"
    )
    with ops.domain_capture(spec, path=path) as cap:  # type: ignore[attr-defined]
        cap.begin_stage("sensitivity", kind="transient")
        for _ in range(int(steps)):
            ops.analyze(steps=1, dt=float(dt))  # type: ignore[attr-defined]
            cap.step(t=ops.getTime())  # type: ignore[attr-defined]
        cap.end_stage()

    results = Results.from_native(path, model=ops.build())  # type: ignore[attr-defined]
    slab = results.nodes.get(component=response.component, **sel)  # type: ignore[arg-type]
    return slab.values, slab.time


class _ApeSeesForward:
    """Engine-coupled ``forward({name: value}) -> float`` for `from_apesees`.

    Builds the deck on a fresh ``apeSees(fem)`` via the user ``build`` callable,
    delegates the transient run + response read to ``runner``, and reduces the
    result. Imports the bridge lazily so the sensitivity core stays engine-free.
    """

    def __init__(
        self,
        *,
        fem: object,
        build: "Callable[..., None]",
        response: Response,
        steps: int,
        dt: float,
        capture_path: Optional[str],
        runner: "RunnerFn",
    ) -> None:
        self.fem = fem
        self.build = build
        self.response = response
        self.steps = int(steps)
        self.dt = float(dt)
        self.capture_path = capture_path
        self.runner = runner

    def __call__(self, params_map: Mapping[str, float]) -> float:
        from apeGmsh.opensees import apeSees

        ops = apeSees(self.fem)
        self.build(ops, params_map)
        values, time = self.runner(ops, self.response, self.steps, self.dt, self.capture_path)
        return reduce_response(values, time, self.response)
