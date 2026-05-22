"""
``_SectionNS`` — backs ``ops.section.<Type>(...)``.

Phase 1C populates this with one typed method per OpenSees section.
"""
from __future__ import annotations

from typing import Literal, Mapping

from ...section.aggregator import Aggregator
from ...section.beam import ElasticSection
from ...section.fiber import (
    Fiber,
    FiberPoint,
    RectPatch,
    StraightLayer,
    W_fiber as _build_W_fiber,
)
from ...section.plate import (
    ElasticMembranePlateSection,
    LayeredShell,
    LayeredShellFiberSection,
    ShellLayer,
)
from ..types import Section, UniaxialMaterial
from ._base import _BridgeNamespace


__all__ = ["_SectionNS"]


class _SectionNS(_BridgeNamespace):
    """``ops.section.<Type>(...)`` — Phase 1C population.

    Each method constructs a typed section primitive, registers it
    with the bridge (allocating its tag), and returns the typed
    instance. Per the namespace contract in :mod:`api-design`,
    every signature is fully kw-only with explicit types — no
    ``**kwargs`` (P12).
    """

    # -- Beam-line sections ---------------------------------------------

    def Elastic(
        self,
        *,
        E: float,
        A: float,
        Iz: float,
        Iy: float | None = None,
        G: float | None = None,
        J: float | None = None,
        alphaY: float | None = None,
        alphaZ: float | None = None,
    ) -> ElasticSection:
        """``section Elastic`` — 2-D or 3-D linear-elastic beam section.

        Supplying any of ``Iy`` / ``J`` / ``alphaZ`` selects the 3-D
        variant; in that case ``Iy``, ``G``, and ``J`` are all
        required. See :class:`ElasticSection` for the full contract.
        """
        return self._bridge._register(
            ElasticSection(
                E=E, A=A, Iz=Iz,
                Iy=Iy, G=G, J=J,
                alphaY=alphaY, alphaZ=alphaZ,
            )
        )

    # -- Plate / shell sections -----------------------------------------

    def ElasticMembranePlateSection(
        self,
        *,
        E: float,
        nu: float,
        h: float,
        rho: float = 0.0,
    ) -> ElasticMembranePlateSection:
        """``section ElasticMembranePlateSection`` — single-layer plate."""
        return self._bridge._register(
            ElasticMembranePlateSection(E=E, nu=nu, h=h, rho=rho)
        )

    def LayeredShell(
        self,
        *,
        layers: tuple[ShellLayer, ...],
    ) -> LayeredShell:
        """``section LayeredShell`` — stacked nDMaterial layers."""
        return self._bridge._register(LayeredShell(layers=layers))

    def LayeredShellFiberSection(
        self,
        *,
        layers: tuple[ShellLayer, ...],
    ) -> LayeredShellFiberSection:
        """``section LayeredShellFiberSection`` — fiber-based stacked
        layered plate section."""
        return self._bridge._register(
            LayeredShellFiberSection(layers=layers)
        )

    # -- Fiber section ---------------------------------------------------

    def Fiber(
        self,
        *,
        patches: tuple[RectPatch, ...] = (),
        fibers:  tuple[FiberPoint, ...] = (),
        layers:  tuple[StraightLayer, ...] = (),
        GJ: float | None = None,
    ) -> Fiber:
        """``section Fiber`` — block-emit fiber section.

        At least one of ``patches`` / ``fibers`` / ``layers`` must be
        non-empty. See :class:`Fiber` for the full contract and the
        material-tag resolution open question.
        """
        return self._bridge._register(
            Fiber(
                patches=patches,
                fibers=fibers,
                layers=layers,
                GJ=GJ,
            )
        )

    # -- Parametric fiber-section builders ------------------------------

    def W_fiber(
        self,
        *,
        bf: float,
        tf: float,
        hw: float,
        tw: float,
        material: UniaxialMaterial,
        ny_flange: int = 2,
        nz_flange: int = 8,
        ny_web: int = 8,
        nz_web: int = 1,
        GJ: float | None = None,
    ) -> Fiber:
        """``section Fiber`` for a built-up W shape — parametric builder.

        Convenience wrapper around
        :func:`apeGmsh.opensees.section.fiber.W_fiber` that
        auto-registers the resulting :class:`Fiber` with the bridge.
        See the helper docstring for the full geometric contract.
        """
        return self._bridge._register(
            _build_W_fiber(
                bf=bf, tf=tf, hw=hw, tw=tw,
                material=material,
                ny_flange=ny_flange, nz_flange=nz_flange,
                ny_web=ny_web, nz_web=nz_web,
                GJ=GJ,
            )
        )

    # -- Aggregator (composes other sections + uniaxials) ---------------

    def Aggregator(
        self,
        *,
        materials_by_dof: Mapping[
            Literal["P", "Vy", "Vz", "T", "My", "Mz"],
            UniaxialMaterial,
        ],
        base_section: Section | None = None,
    ) -> Aggregator:
        """``section Aggregator`` — DOF-wise uniaxial coupling.

        Maps each entry in ``materials_by_dof`` (DOF code →
        :class:`UniaxialMaterial`) onto a force/moment response code,
        optionally layered on top of ``base_section``.  See
        :class:`apeGmsh.opensees.section.Aggregator` for the full
        contract.
        """
        return self._bridge._register(
            Aggregator(
                materials_by_dof=materials_by_dof,
                base_section=base_section,
            )
        )
