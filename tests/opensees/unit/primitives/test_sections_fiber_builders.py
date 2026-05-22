"""Unit tests for parametric ``Fiber``-section builders.

Today's surface: :func:`apeGmsh.opensees.section.fiber.W_fiber` and
its bridge-side wrapper ``ops.section.W_fiber``.  The builder
encapsulates ~30 lines of :class:`RectPatch` boilerplate for built-up
W shapes — a Cerro Lindo Tier-3 ergonomics ask.
"""
from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

import pytest

from apeGmsh.opensees import apeSees
from apeGmsh.opensees.material.uniaxial import ElasticMaterial
from apeGmsh.opensees.section.fiber import Fiber, RectPatch, W_fiber


class TestWFiberBuilder:
    def test_returns_unregistered_fiber(self) -> None:
        m = ElasticMaterial(E=2e11)
        sec = W_fiber(bf=150e-3, tf=12e-3, hw=160e-3, tw=8e-3, material=m)
        assert isinstance(sec, Fiber)
        # No bridge here — section is not registered.
        assert sec.GJ is None

    def test_produces_three_rect_patches(self) -> None:
        m = ElasticMaterial(E=2e11)
        sec = W_fiber(bf=150e-3, tf=12e-3, hw=160e-3, tw=8e-3, material=m)
        # Three patches: top flange, bottom flange, web.
        assert len(sec.patches) == 3
        assert all(isinstance(p, RectPatch) for p in sec.patches)
        # No straight layers, no individual fibers.
        assert sec.layers == ()
        assert sec.fibers == ()

    def test_patch_geometry_matches_canonical_layout(self) -> None:
        # Use unit dimensions for easy reasoning.
        m = ElasticMaterial(E=2e11)
        sec = W_fiber(bf=10.0, tf=2.0, hw=20.0, tw=1.0, material=m)
        top, bot, web = sec.patches

        # Top flange: y ∈ [10, 12], z ∈ [-5, 5]
        assert top.yI == pytest.approx(10.0)
        assert top.yJ == pytest.approx(12.0)
        assert top.zI == pytest.approx(-5.0)
        assert top.zJ == pytest.approx(5.0)

        # Bottom flange: y ∈ [-12, -10], z ∈ [-5, 5]
        assert bot.yI == pytest.approx(-12.0)
        assert bot.yJ == pytest.approx(-10.0)
        assert bot.zI == pytest.approx(-5.0)
        assert bot.zJ == pytest.approx(5.0)

        # Web: y ∈ [-10, 10], z ∈ [-0.5, 0.5]
        assert web.yI == pytest.approx(-10.0)
        assert web.yJ == pytest.approx(10.0)
        assert web.zI == pytest.approx(-0.5)
        assert web.zJ == pytest.approx(0.5)

    def test_subdivision_counts_propagate(self) -> None:
        m = ElasticMaterial(E=2e11)
        sec = W_fiber(
            bf=10.0, tf=2.0, hw=20.0, tw=1.0, material=m,
            ny_flange=4, nz_flange=12, ny_web=16, nz_web=2,
        )
        top, bot, web = sec.patches
        assert (top.ny, top.nz) == (4, 12)
        assert (bot.ny, bot.nz) == (4, 12)
        assert (web.ny, web.nz) == (16, 2)

    def test_GJ_propagates(self) -> None:
        m = ElasticMaterial(E=2e11)
        sec = W_fiber(
            bf=10.0, tf=2.0, hw=20.0, tw=1.0, material=m, GJ=1.5e9,
        )
        assert sec.GJ == 1.5e9

    def test_all_patches_share_the_material(self) -> None:
        m = ElasticMaterial(E=2e11)
        sec = W_fiber(bf=10.0, tf=2.0, hw=20.0, tw=1.0, material=m)
        for patch in sec.patches:
            assert patch.material is m

    def test_dependencies_returns_single_material(self) -> None:
        # Fiber's dependencies() dedups by material identity — all
        # three patches share ``m``, so dependencies() yields exactly
        # one primitive.
        m = ElasticMaterial(E=2e11)
        sec = W_fiber(bf=10.0, tf=2.0, hw=20.0, tw=1.0, material=m)
        assert sec.dependencies() == (m,)


class TestWFiberValidation:
    @pytest.mark.parametrize(
        "kw,val",
        [
            ("bf", 0.0), ("bf", -1.0),
            ("tf", 0.0), ("tf", -2.0),
            ("hw", 0.0), ("hw", -10.0),
            ("tw", 0.0), ("tw", -1.0),
        ],
    )
    def test_nonpositive_dimension_raises(self, kw: str, val: float) -> None:
        m = ElasticMaterial(E=2e11)
        defaults = {"bf": 10.0, "tf": 2.0, "hw": 20.0, "tw": 1.0}
        defaults[kw] = val
        with pytest.raises(ValueError, match="must be > 0"):
            W_fiber(material=m, **defaults)  # type: ignore[arg-type]

    def test_web_thicker_than_flange_raises(self) -> None:
        m = ElasticMaterial(E=2e11)
        with pytest.raises(ValueError, match="web thickness"):
            W_fiber(bf=10.0, tf=2.0, hw=20.0, tw=15.0, material=m)


class TestWFiberNamespace:
    def _make_ops(self) -> apeSees:
        return apeSees(cast("object", MagicMock(name="FEMData")))  # type: ignore[arg-type]

    def test_namespace_registers_with_bridge(self) -> None:
        ops = self._make_ops()
        m = ops.uniaxialMaterial.ElasticMaterial(E=2e11)
        sec = ops.section.W_fiber(
            bf=150e-3, tf=12e-3, hw=160e-3, tw=8e-3, material=m,
        )
        assert isinstance(sec, Fiber)
        # Per-family namespace: uniaxials start at 1, sections start at 1.
        assert ops.tag_for(m) == 1
        assert ops.tag_for(sec) == 1
        assert len(sec.patches) == 3

    def test_namespace_passes_through_GJ(self) -> None:
        ops = self._make_ops()
        m = ops.uniaxialMaterial.ElasticMaterial(E=2e11)
        sec = ops.section.W_fiber(
            bf=10.0, tf=2.0, hw=20.0, tw=1.0, material=m, GJ=1.0e9,
        )
        assert sec.GJ == 1.0e9
