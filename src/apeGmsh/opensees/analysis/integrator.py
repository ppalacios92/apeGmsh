"""
Typed ``integrator`` primitives — Phase 3C.

Each class is a ``@dataclass(frozen=True, kw_only=True, slots=True)``
mirroring the OpenSees Tcl ``integrator <Type> ...`` command. The
matching :class:`apeGmsh.opensees._internal.ns.analysis._IntegratorNS`
methods take the same kwargs and call ``self._bridge._register(Cls(...))``.

Integrators are singletons in OpenSees (no tag in the command). The
``tag`` parameter to :meth:`_emit` is consumed by the allocator but
not rendered in the emitted command.

OpenSees command shapes::

    integrator LoadControl          dlam [num_iter [min_lam max_lam]]
    integrator DisplacementControl  node dof dU [num_iter [min_dU max_dU]]
    integrator ArcLength            s alpha
    integrator Newmark              gamma beta
    integrator HHT                  alpha [gamma beta]
    integrator CentralDifference
    integrator ExplicitDifference

The ``min_*`` / ``max_*`` step-bracket parameters on LoadControl and
DisplacementControl are only meaningful in tandem with ``num_iter``;
the dataclasses reject "min/max set but num_iter unset" at
construction.

The three *explicit* integrators :class:`ExplicitBathe`,
:class:`ExplicitBatheLNVD` and :class:`CentralDifferenceLadruno` are
**fork-only** — they require the OpenSees *Ladruno fork* build to
*run*. Emission works on any build (it's just an ``integrator <Type>
...`` line); the fork requirement bites only at ``ops.analyze(...)`` /
``ops.run()``. They share an order-free option grammar
(``-cfl``/``-cflAbort``/``-tangent``/``-recompute N``/``-lump
rowsum|diagonal``/``-verbose``/``-divergence f``); see
:func:`_render_explicit_cfl_options`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from .._internal.types import Integrator, Primitive

if TYPE_CHECKING:
    from ..emitter.base import Emitter


__all__ = [
    "LoadControl",
    "DisplacementControl",
    "ArcLength",
    "Newmark",
    "HHT",
    "CentralDifference",
    "ExplicitDifference",
    "ExplicitBathe",
    "ExplicitBatheLNVD",
    "CentralDifferenceLadruno",
]


# ---------------------------------------------------------------------------
# Shared explicit-integrator option grammar (Ladruno fork)
# ---------------------------------------------------------------------------

Lump = Literal["rowsum", "diagonal"]


def _validate_explicit_cfl_options(
    *,
    who: str,
    recompute: int | None,
    lump: Lump | None,
    divergence: float | None,
) -> None:
    """Validate the shared explicit-integrator option flags.

    Enforces only what the fork C++ itself rejects / treats as an
    authoring slip — no cross-flag coupling (the C++ parser is
    permissive: e.g. ``-cflAbort`` without a ``dt_cr`` source is
    silently inert, not an error).
    """
    if recompute is not None and recompute < 1:
        raise ValueError(
            f"{who}: recompute must be >= 1 (every-N committed steps), "
            f"got {recompute}."
        )
    if lump is not None and lump not in ("rowsum", "diagonal"):
        raise ValueError(
            f"{who}: lump must be 'rowsum' or 'diagonal', got {lump!r}."
        )
    if divergence is not None and divergence <= 0:
        raise ValueError(
            f"{who}: divergence factor must be > 0, got {divergence}."
        )


def _render_explicit_cfl_options(
    args: list[float | int | str],
    *,
    cfl: bool,
    cfl_abort: bool,
    tangent: bool,
    recompute: int | None,
    lump: Lump | None,
    verbose: bool,
    divergence: float | None,
) -> None:
    """Append the shared explicit-integrator flags to ``args`` in a
    fixed, byte-stable canonical order.

    Omitted ``lump`` is left to the fork's per-integrator default
    (RowSum for the Bathe schemes, Diagonal for
    ``CentralDifferenceLadruno``) — we never re-emit a default.
    """
    if cfl:
        args.append("-cfl")
    if cfl_abort:
        args.append("-cflAbort")
    if tangent:
        args.append("-tangent")
    if recompute is not None:
        args += ["-recompute", recompute]
    if lump is not None:
        args += ["-lump", lump]
    if verbose:
        args.append("-verbose")
    if divergence is not None:
        args += ["-divergence", divergence]


# ---------------------------------------------------------------------------
# LoadControl — static, prescribed load-factor increment
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class LoadControl(Integrator):
    """``integrator LoadControl dlam [num_iter [min_lam max_lam]]``.

    Static analysis with a fixed (or adaptively bracketed) load-factor
    increment. ``dlam`` is the nominal increment per step; ``num_iter``
    is the target convergence-iteration count used to scale the
    increment adaptively when supplied.
    """

    dlam: float
    num_iter: int | None = None
    min_lam: float | None = None
    max_lam: float | None = None

    def __post_init__(self) -> None:
        if self.num_iter is not None and self.num_iter < 1:
            raise ValueError(
                f"LoadControl: num_iter must be >= 1, got {self.num_iter}"
            )
        if (self.min_lam is None) != (self.max_lam is None):
            raise ValueError(
                "LoadControl: supply both min_lam and max_lam, or "
                f"neither (got min_lam={self.min_lam!r}, "
                f"max_lam={self.max_lam!r})."
            )
        if self.min_lam is not None and self.num_iter is None:
            raise ValueError(
                "LoadControl: min_lam/max_lam require num_iter to be set."
            )
        if (
            self.min_lam is not None
            and self.max_lam is not None
            and self.min_lam > self.max_lam
        ):
            raise ValueError(
                "LoadControl: min_lam must be <= max_lam, got "
                f"min_lam={self.min_lam}, max_lam={self.max_lam}"
            )

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        args: list[float | int] = [self.dlam]
        if self.num_iter is not None:
            args.append(self.num_iter)
            if self.min_lam is not None:
                assert self.max_lam is not None  # __post_init__ guarantee
                args += [self.min_lam, self.max_lam]
        emitter.integrator("LoadControl", *args)

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# DisplacementControl — static, prescribed displacement increment at one DOF
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class DisplacementControl(Integrator):
    """``integrator DisplacementControl node dof dU
    [num_iter [min_dU max_dU]]``.

    Static analysis driven by a prescribed displacement increment
    ``dU`` at ``node``'s ``dof``-th DOF. ``num_iter`` enables adaptive
    bracketing as in :class:`LoadControl`.
    """

    node: int
    dof: int
    dU: float
    num_iter: int | None = None
    min_dU: float | None = None
    max_dU: float | None = None

    def __post_init__(self) -> None:
        if self.dof < 1:
            raise ValueError(
                f"DisplacementControl: dof must be >= 1, got {self.dof}"
            )
        if self.num_iter is not None and self.num_iter < 1:
            raise ValueError(
                "DisplacementControl: num_iter must be >= 1, "
                f"got {self.num_iter}"
            )
        if (self.min_dU is None) != (self.max_dU is None):
            raise ValueError(
                "DisplacementControl: supply both min_dU and max_dU, or "
                f"neither (got min_dU={self.min_dU!r}, "
                f"max_dU={self.max_dU!r})."
            )
        if self.min_dU is not None and self.num_iter is None:
            raise ValueError(
                "DisplacementControl: min_dU/max_dU require num_iter "
                "to be set."
            )
        if (
            self.min_dU is not None
            and self.max_dU is not None
            and self.min_dU > self.max_dU
        ):
            raise ValueError(
                "DisplacementControl: min_dU must be <= max_dU, got "
                f"min_dU={self.min_dU}, max_dU={self.max_dU}"
            )

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        args: list[float | int] = [self.node, self.dof, self.dU]
        if self.num_iter is not None:
            args.append(self.num_iter)
            if self.min_dU is not None:
                assert self.max_dU is not None  # __post_init__ guarantee
                args += [self.min_dU, self.max_dU]
        emitter.integrator("DisplacementControl", *args)

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# ArcLength — static arc-length method
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class ArcLength(Integrator):
    """``integrator ArcLength s alpha``.

    Arc-length continuation. ``s`` is the arc-length increment per step;
    ``alpha`` weights the load contribution to the arc-length norm.
    """

    s: float
    alpha: float

    def __post_init__(self) -> None:
        if self.s <= 0:
            raise ValueError(
                f"ArcLength: s must be > 0, got {self.s}"
            )

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        emitter.integrator("ArcLength", self.s, self.alpha)

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# Newmark — implicit transient (the standard structural choice)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class Newmark(Integrator):
    """``integrator Newmark gamma beta``.

    The classical Newmark scheme. ``gamma=0.5, beta=0.25`` recovers
    the unconditionally stable average-acceleration variant; the user
    is responsible for selecting parameters consistent with their
    accuracy + stability requirements.
    """

    gamma: float
    beta: float

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        emitter.integrator("Newmark", self.gamma, self.beta)

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# HHT — Hilber-Hughes-Taylor alpha-method
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class HHT(Integrator):
    """``integrator HHT alpha [gamma beta]``.

    Hilber-Hughes-Taylor alpha-method. Supplying ``gamma`` and
    ``beta`` overrides the OpenSees defaults derived from ``alpha``;
    omit both to use the defaults. Either supply both or neither.
    """

    alpha: float
    gamma: float | None = None
    beta: float | None = None

    def __post_init__(self) -> None:
        if (self.gamma is None) != (self.beta is None):
            raise ValueError(
                "HHT: supply both gamma and beta, or neither "
                f"(got gamma={self.gamma!r}, beta={self.beta!r})."
            )

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        if self.gamma is None:
            emitter.integrator("HHT", self.alpha)
        else:
            assert self.beta is not None  # __post_init__ guarantee
            emitter.integrator("HHT", self.alpha, self.gamma, self.beta)

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# CentralDifference — explicit transient (no parameters)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class CentralDifference(Integrator):
    """``integrator CentralDifference`` — explicit central-difference."""

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        emitter.integrator("CentralDifference")

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# ExplicitDifference — explicit transient (no parameters)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class ExplicitDifference(Integrator):
    """``integrator ExplicitDifference`` — explicit difference scheme."""

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        emitter.integrator("ExplicitDifference")

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# ExplicitBathe — explicit Noh-Bathe two-sub-step (Ladruno fork)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class ExplicitBathe(Integrator):
    """``integrator ExplicitBathe p [flags...]`` — **fork-only**.

    The Noh-Bathe two-sub-step explicit scheme (2nd order, controllable
    high-frequency dissipation via ``p``). Requires the OpenSees
    *Ladruno fork* build to run; emission works on any build.

    ``p`` is the sub-step parameter ``∈(0,1)`` (default ``0.54``). The
    option flags enable + tune the critical-time-step (``dt_cr``)
    machinery and per-step diagnostics:

    * ``cfl`` — estimate ``dt_cr`` (queryable via ``criticalTimeStep()``).
    * ``cfl_abort`` — abort if ``dt`` exceeds the Noh-Bathe limit
      (inert unless a ``dt_cr`` source — ``cfl``/``tangent``/``recompute``
      — is also enabled).
    * ``tangent`` — estimate ``dt_cr`` from the current tangent.
    * ``recompute`` — refresh ``dt_cr`` every N committed steps (N >= 1).
    * ``lump`` — element mass lumping for ``dt_cr`` (default RowSum).
    * ``verbose`` — per-step dt/energy reporting.
    * ``divergence`` — abort if kinetic energy grows by this factor.
    """

    p: float = 0.54
    cfl: bool = False
    cfl_abort: bool = False
    tangent: bool = False
    recompute: int | None = None
    lump: Lump | None = None
    verbose: bool = False
    divergence: float | None = None

    def __post_init__(self) -> None:
        if not (0.0 < self.p < 1.0):
            raise ValueError(
                f"ExplicitBathe: p must be in (0, 1), got {self.p}."
            )
        _validate_explicit_cfl_options(
            who="ExplicitBathe",
            recompute=self.recompute,
            lump=self.lump,
            divergence=self.divergence,
        )

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        args: list[float | int | str] = [self.p]
        _render_explicit_cfl_options(
            args,
            cfl=self.cfl,
            cfl_abort=self.cfl_abort,
            tangent=self.tangent,
            recompute=self.recompute,
            lump=self.lump,
            verbose=self.verbose,
            divergence=self.divergence,
        )
        emitter.integrator("ExplicitBathe", *args)

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# ExplicitBatheLNVD — Noh-Bathe + FLAC local non-viscous damping (fork)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class ExplicitBatheLNVD(Integrator):
    """``integrator ExplicitBatheLNVD p alpha [flags...]`` — **fork-only**.

    :class:`ExplicitBathe` plus FLAC local non-viscous damping, for
    dynamic relaxation / quasi-static solving. Requires the *Ladruno
    fork* build to run.

    ``p`` is the sub-step parameter ``∈(0,1)`` (default ``0.54``);
    ``alpha`` is the FLAC local-damping coefficient ``∈[0,1)`` (default
    ``0.80``; ``0`` disables damping). Both are always emitted
    explicitly — the fork reads them as a *pair* of leading numerics, so
    eliding ``alpha`` would shift a following flag into its slot. The
    option flags are identical to :class:`ExplicitBathe`.
    """

    p: float = 0.54
    alpha: float = 0.8
    cfl: bool = False
    cfl_abort: bool = False
    tangent: bool = False
    recompute: int | None = None
    lump: Lump | None = None
    verbose: bool = False
    divergence: float | None = None

    def __post_init__(self) -> None:
        if not (0.0 < self.p < 1.0):
            raise ValueError(
                f"ExplicitBatheLNVD: p must be in (0, 1), got {self.p}."
            )
        if not (0.0 <= self.alpha < 1.0):
            raise ValueError(
                "ExplicitBatheLNVD: alpha (FLAC damping) must be in "
                f"[0, 1), got {self.alpha}."
            )
        _validate_explicit_cfl_options(
            who="ExplicitBatheLNVD",
            recompute=self.recompute,
            lump=self.lump,
            divergence=self.divergence,
        )

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        args: list[float | int | str] = [self.p, self.alpha]
        _render_explicit_cfl_options(
            args,
            cfl=self.cfl,
            cfl_abort=self.cfl_abort,
            tangent=self.tangent,
            recompute=self.recompute,
            lump=self.lump,
            verbose=self.verbose,
            divergence=self.divergence,
        )
        emitter.integrator("ExplicitBatheLNVD", *args)

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# CentralDifferenceLadruno — robust central difference (fork)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class CentralDifferenceLadruno(Integrator):
    """``integrator CentralDifferenceLadruno [flags...]`` — **fork-only**.

    The *Ladruno fork*'s robust central-difference integrator: a correct
    first-step starter, built-in ``dt_cr``, and a ``βK`` guard. Requires
    the fork build to run.

    Takes no positional parameter; the option flags match
    :class:`ExplicitBathe`, except ``lump`` defaults to **Diagonal**
    (diagonal-of-consistent) rather than RowSum when omitted. (The
    dropped *coupled* mode is served by ``NewmarkExplicit 0.5`` — out of
    scope here.)
    """

    cfl: bool = False
    cfl_abort: bool = False
    tangent: bool = False
    recompute: int | None = None
    lump: Lump | None = None
    verbose: bool = False
    divergence: float | None = None

    def __post_init__(self) -> None:
        _validate_explicit_cfl_options(
            who="CentralDifferenceLadruno",
            recompute=self.recompute,
            lump=self.lump,
            divergence=self.divergence,
        )

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        args: list[float | int | str] = []
        _render_explicit_cfl_options(
            args,
            cfl=self.cfl,
            cfl_abort=self.cfl_abort,
            tangent=self.tangent,
            recompute=self.recompute,
            lump=self.lump,
            verbose=self.verbose,
            divergence=self.divergence,
        )
        emitter.integrator("CentralDifferenceLadruno", *args)

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()
