"""
Typed ``damping`` objects (ADR 0053, D3).

Each class is a ``@dataclass(frozen=True, kw_only=True, slots=True)`` mirroring
the OpenSees ``damping <Type> $tag ...`` command. The matching
:class:`apeGmsh.opensees._internal.ns.damping._DampingNS` methods take the same
kwargs, ``_register`` the primitive, and record a ``region -damp`` attachment.

These are frequency-band viscous dissipators (Yuli Huang et al., 2020-2022) —
**not** Rayleigh. They are inert until attached to elements via a region.

The four registered OpenSees types (verified against
``OpenSeesDampingCommands.cpp``):

  * :class:`Uniform`  — constant ζ across a frequency band
    (``damping Uniform $tag $zeta $freq1 $freq2``)
  * :class:`SecStif`  — committed-stiffness-proportional
    (``damping SecStif $tag $beta``)
  * :class:`URD`      — piecewise ζ(f) over N≥2 ``(freq, zeta)`` points
    (``damping URD $tag $N $f1 $z1 ... $fN $zN``)
  * :class:`URDbeta`  — piecewise β(f) over N≥2 ``(freq, beta)`` points
    (``damping URDbeta $tag $N $fc1 $b1 ... $fcN $bN``)

**Time window** — all types accept ``activate_time`` / ``deactivate_time``
(``-activateTime`` / ``-deactivateTime``) so the object can be switched off
during a quasi-static gravity stage and on for the dynamic phase; without
windowing a damping object dissipates from t=0 and corrupts the initial state.

**Scale factor** — all types accept ``factor`` (an ``ops.timeSeries.*``
object) emitted as ``-factor $tsTag``. The bridge emits ``-factor`` on both
backends (the Tcl-only ``-fact`` alias would break an openseespy deck —
``OpenSeesDampingCommands.cpp:71``). The series is a primitive dependency, so
its ``timeSeries`` line is emitted before the ``damping`` line.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .._internal.tag_resolution import resolve_tag
from .._internal.types import Damping, Primitive, TimeSeries

if TYPE_CHECKING:
    from ..emitter.base import Emitter


__all__ = ["Uniform", "SecStif", "URD", "URDbeta"]


def _window_args(
    activate_time: float | None,
    deactivate_time: float | None,
) -> list[float | str]:
    """Trailing ``-activateTime`` / ``-deactivateTime`` flags (ADR 0053).

    Emitted only when set — OpenSees defaults are ``0.0`` / ``1e20``.
    """
    args: list[float | str] = []
    if activate_time is not None:
        args += ["-activateTime", activate_time]
    if deactivate_time is not None:
        args += ["-deactivateTime", deactivate_time]
    return args


def _factor_args(
    emitter: "Emitter",
    factor: TimeSeries | None,
) -> list[int | str]:
    """Trailing ``-factor $tsTag`` flag (ADR 0053).

    Emitted only when a series is set; the tag is resolved against the
    emitter (the series is declared as a dependency so it already has one).
    Always ``-factor`` — never the Tcl-only ``-fact`` alias.
    """
    if factor is None:
        return []
    return ["-factor", resolve_tag(emitter, factor)]


@dataclass(frozen=True, kw_only=True, slots=True)
class Uniform(Damping):
    """``damping Uniform $tag $zeta $freq1 $freq2 [-activateTime ta]
    [-deactivateTime td] [-factor ts]`` — constant damping ratio ``zeta``
    across the band ``[freq1, freq2]`` (Hz).

    ``zeta`` is the **physical target ratio** — OpenSees applies the
    internal factor of two; do not pre-divide (ADR 0053).
    """

    zeta: float
    freq1: float
    freq2: float
    activate_time: float | None = None
    deactivate_time: float | None = None
    factor: TimeSeries | None = None

    def __post_init__(self) -> None:
        if self.zeta < 0.0:
            raise ValueError(f"Uniform: zeta must be >= 0, got {self.zeta!r}")
        if self.freq1 <= 0.0 or self.freq2 <= 0.0:
            raise ValueError(
                "Uniform: freq1/freq2 must be positive (Hz), got "
                f"freq1={self.freq1!r}, freq2={self.freq2!r}"
            )
        if self.freq2 <= self.freq1:
            raise ValueError(
                "Uniform: freq2 must be > freq1, got "
                f"freq1={self.freq1!r}, freq2={self.freq2!r}"
            )

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        emitter.damping(
            "Uniform", tag, self.zeta, self.freq1, self.freq2,
            *_window_args(self.activate_time, self.deactivate_time),
            *_factor_args(emitter, self.factor),
        )

    def dependencies(self) -> tuple[Primitive, ...]:
        return () if self.factor is None else (self.factor,)


@dataclass(frozen=True, kw_only=True, slots=True)
class SecStif(Damping):
    """``damping SecStif $tag $beta [-activateTime ta] [-deactivateTime td]
    [-factor ts]`` — committed (secant) stiffness-proportional damping.

    (OpenSees also accepts the ``SecStiff`` spelling; the bridge emits the
    ``SecStif`` form, which both the Tcl and openseespy parsers accept.)
    """

    beta: float
    activate_time: float | None = None
    deactivate_time: float | None = None
    factor: TimeSeries | None = None

    def __post_init__(self) -> None:
        if self.beta < 0.0:
            raise ValueError(f"SecStif: beta must be >= 0, got {self.beta!r}")

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        emitter.damping(
            "SecStif", tag, self.beta,
            *_window_args(self.activate_time, self.deactivate_time),
            *_factor_args(emitter, self.factor),
        )

    def dependencies(self) -> tuple[Primitive, ...]:
        return () if self.factor is None else (self.factor,)


@dataclass(frozen=True, kw_only=True, slots=True)
class URD(Damping):
    """``damping URD $tag $N $f1 $z1 ... $fN $zN [-activateTime ta]
    [-deactivateTime td] [-factor ts]`` — user-defined piecewise damping
    ratio ζ(f) interpolated over ``N`` ``(freq, zeta)`` points (Yuli Huang's
    "URD" — Unconditionally-stable Rayleigh-like Damping).

    Parameters
    ----------
    points
        Tuple of ``(freq, zeta)`` pairs (Hz, physical ratio), strictly
        ascending in frequency. At least 2 points are required (OpenSees
        ``URDDamping`` needs ``N >= 2``).
    """

    points: tuple[tuple[float, float], ...]
    activate_time: float | None = None
    deactivate_time: float | None = None
    factor: TimeSeries | None = None

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError(
                "URD: needs at least 2 (freq, zeta) points, got "
                f"{len(self.points)}"
            )
        freqs = [f for f, _ in self.points]
        for f, z in self.points:
            if f <= 0.0:
                raise ValueError(f"URD: freq must be positive (Hz), got {f!r}")
            if z < 0.0:
                raise ValueError(f"URD: zeta must be >= 0, got {z!r}")
        if any(b <= a for a, b in zip(freqs, freqs[1:])):
            raise ValueError(
                f"URD: freqs must be strictly ascending, got {freqs!r}"
            )

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        pairs: list[float] = []
        for f, z in self.points:
            pairs += [f, z]
        emitter.damping(
            "URD", tag, len(self.points), *pairs,
            *_window_args(self.activate_time, self.deactivate_time),
            *_factor_args(emitter, self.factor),
        )

    def dependencies(self) -> tuple[Primitive, ...]:
        return () if self.factor is None else (self.factor,)


@dataclass(frozen=True, kw_only=True, slots=True)
class URDbeta(Damping):
    """``damping URDbeta $tag $N $fc1 $b1 ... $fcN $bN [-activateTime ta]
    [-deactivateTime td] [-factor ts]`` — user-defined piecewise
    stiffness-proportional coefficient β(f) over ``N`` ``(freq, beta)``
    points.

    Parameters
    ----------
    points
        Tuple of ``(freq, beta)`` pairs, strictly ascending in frequency.
        ``freq`` is in Hz — OpenSees multiplies by 2π internally
        (``OpenSeesDampingCommands.cpp:348``). At least 2 points are
        required (``N >= 2``).
    """

    points: tuple[tuple[float, float], ...]
    activate_time: float | None = None
    deactivate_time: float | None = None
    factor: TimeSeries | None = None

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError(
                "URDbeta: needs at least 2 (freq, beta) points, got "
                f"{len(self.points)}"
            )
        freqs = [f for f, _ in self.points]
        for f, b in self.points:
            if f <= 0.0:
                raise ValueError(
                    f"URDbeta: freq must be positive (Hz), got {f!r}"
                )
            if b < 0.0:
                raise ValueError(f"URDbeta: beta must be >= 0, got {b!r}")
        if any(b <= a for a, b in zip(freqs, freqs[1:])):
            raise ValueError(
                f"URDbeta: freqs must be strictly ascending, got {freqs!r}"
            )

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        pairs: list[float] = []
        for f, b in self.points:
            pairs += [f, b]
        emitter.damping(
            "URDbeta", tag, len(self.points), *pairs,
            *_window_args(self.activate_time, self.deactivate_time),
            *_factor_args(emitter, self.factor),
        )

    def dependencies(self) -> tuple[Primitive, ...]:
        return () if self.factor is None else (self.factor,)
