"""
Typed ``system`` primitives — Phase 3C.

Each class is a ``@dataclass(frozen=True, kw_only=True, slots=True)``
mirroring the OpenSees Tcl ``system <Type>`` command. The matching
:class:`apeGmsh.opensees._internal.ns.analysis._SystemNS` methods take
no parameters (the seven core variants ship as flag-only) and call
``self._bridge._register(Cls())``.

Linear-system solvers are singletons in OpenSees (no tag in the
command). The ``tag`` parameter to :meth:`_emit` is consumed by the
allocator but not rendered.

OpenSees command shapes::

    system BandGeneral
    system BandSPD
    system ProfileSPD
    system SProfileSPD
    system UmfPack
    system Mumps
    system SparseGeneral
    system SparseSYM
    system FullGeneral
    system Diagonal
    system MPIDiagonal
    system ParallelProfileSPD

``Diagonal`` is the solver paired with explicit time integration
(``CentralDifference`` / the Ladruno ``ExplicitBathe`` family): it
inverts a lumped, diagonal mass matrix element-wise. It cannot solve a
coupled stiffness system, so it is **not** valid for static / implicit
analysis. ``MPIDiagonal`` / ``ParallelProfileSPD`` are parallel-only —
they require an OpenSees build with ``_PARALLEL_INTERPRETERS`` (e.g.
``OpenSeesMP``); emission works anywhere but a serial run errors.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .._internal.types import LinearSystem, Primitive

if TYPE_CHECKING:
    from ..emitter.base import Emitter


__all__ = [
    "BandGeneral",
    "BandSPD",
    "ProfileSPD",
    "SProfileSPD",
    "UmfPack",
    "Mumps",
    "SparseGeneral",
    "SparseSYM",
    "FullGeneral",
    "Diagonal",
    "MPIDiagonal",
    "ParallelProfileSPD",
]


# ---------------------------------------------------------------------------
# BandGeneral — banded, general (non-symmetric)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class BandGeneral(LinearSystem):
    """``system BandGeneral`` — banded general (non-symmetric) solver."""

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        emitter.system("BandGeneral")

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# BandSPD — banded, symmetric positive-definite
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class BandSPD(LinearSystem):
    """``system BandSPD`` — banded symmetric-positive-definite solver."""

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        emitter.system("BandSPD")

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# ProfileSPD — variable-bandwidth (skyline) symmetric positive-definite
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class ProfileSPD(LinearSystem):
    """``system ProfileSPD`` — skyline symmetric-positive-definite solver."""

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        emitter.system("ProfileSPD")

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# UmfPack — direct sparse LU (UMFPACK)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class UmfPack(LinearSystem):
    """``system UmfPack`` — direct sparse LU via UMFPACK."""

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        emitter.system("UmfPack")

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# Mumps — multifrontal massively-parallel sparse direct solver
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class Mumps(LinearSystem):
    """``system Mumps`` — multifrontal massively-parallel sparse solver."""

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        emitter.system("Mumps")

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# SparseGeneral — generic sparse general (SuperLU-backed)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class SparseGeneral(LinearSystem):
    """``system SparseGeneral`` — generic sparse general solver."""

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        emitter.system("SparseGeneral")

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# FullGeneral — dense, non-symmetric (small-system fallback)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class FullGeneral(LinearSystem):
    """``system FullGeneral`` — dense general solver (small systems only)."""

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        emitter.system("FullGeneral")

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# SProfileSPD — single-precision skyline symmetric positive-definite
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class SProfileSPD(LinearSystem):
    """``system SProfileSPD`` — single-precision skyline SPD solver."""

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        emitter.system("SProfileSPD")

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# SparseSYM — symmetric sparse direct solver
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class SparseSYM(LinearSystem):
    """``system SparseSYM`` — symmetric sparse direct solver."""

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        emitter.system("SparseSYM")

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# Diagonal — direct diagonal solver (explicit time integration)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class Diagonal(LinearSystem):
    """``system Diagonal`` — direct diagonal solver.

    The system paired with explicit time integration
    (``CentralDifference`` / Ladruno ``ExplicitBathe`` family): it
    inverts a lumped, diagonal mass matrix element-wise, with no global
    factorization. It only uses the diagonal of the assembled matrix, so
    it is **not** valid for static / implicit analysis (a coupled
    stiffness solve will fail to converge).
    """

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        emitter.system("Diagonal")

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# MPIDiagonal — parallel diagonal solver
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class MPIDiagonal(LinearSystem):
    """``system MPIDiagonal`` — distributed diagonal solver.

    Parallel counterpart of :class:`Diagonal` for explicit runs under
    ``OpenSeesMP``. Only available in OpenSees builds with
    ``_PARALLEL_INTERPRETERS``; a serial build falls back to the plain
    diagonal solver. Emission works on any build.
    """

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        emitter.system("MPIDiagonal")

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# ParallelProfileSPD — distributed skyline symmetric positive-definite
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class ParallelProfileSPD(LinearSystem):
    """``system ParallelProfileSPD`` — distributed skyline SPD solver.

    Parallel counterpart of :class:`ProfileSPD`. Only available in
    OpenSees builds with ``_PARALLEL_INTERPRETERS`` (e.g.
    ``OpenSeesMP``); emit-only against a serial ``OpenSees.exe`` will
    error at runtime.
    """

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        _ = tag
        emitter.system("ParallelProfileSPD")

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()
