"""Unit tests for ``ASDAbsorbingBoundary3D``/``2D`` (ADR 0054, AB-2/AB-5).

Exercises construction/validation, ``_emit`` (with and without base-input time
series), ``dependencies()``, and the bridge-namespace facade — the single
``ops.element.ASDAbsorbingBoundary3D``/``2D`` declarations (material= vs raw
G/v/rho) and the ``ops.element.absorbing_boundary`` fan-over-a-skin
convenience (incl. its 2D/3D dispatch on ``skin.ndm``).
"""
from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

import pytest

from apeGmsh.opensees import apeSees
from apeGmsh.opensees._internal.tag_resolution import (
    set_element_nodes,
    set_tag_resolver,
)
from apeGmsh.opensees._internal.types import Primitive
from apeGmsh.opensees.element.absorbing import (
    ASDAbsorbingBoundary2D,
    ASDAbsorbingBoundary3D,
)
from apeGmsh.opensees.emitter.recording import RecordingEmitter
from apeGmsh.opensees.material.nd import ElasticIsotropic
from apeGmsh.opensees.time_series.time_series import Path


N8 = tuple(range(1, 9))  # 8 node tags
N4 = tuple(range(1, 5))  # 4 node tags (2D quad)


def _stub_bridge() -> apeSees:
    return apeSees(cast("object", MagicMock(name="FEMData")))


def _emit(elem, *, tag, nodes=N8, ts_tags=None) -> RecordingEmitter:
    """Emit ``elem`` with a resolver mapping any attached TimeSeries → tag."""
    ts_tags = ts_tags or {}
    e = RecordingEmitter()

    def _resolve(prim: Primitive) -> int:
        if id(prim) in ts_tags:
            return ts_tags[id(prim)]
        raise KeyError(f"unexpected primitive {prim!r}")

    set_tag_resolver(e, _resolve)
    set_element_nodes(e, nodes)
    elem._emit(e, tag=tag)
    return e


class TestConstructionValidation:
    def test_basic_ok(self) -> None:
        e = ASDAbsorbingBoundary3D(pg="abs_L", G=1351.0, v=0.262, rho=2.4e-9, btype="L")
        assert e.pg == "abs_L"
        assert e.btype == "L"
        assert e.dependencies() == ()

    @pytest.mark.parametrize("btype", ["LR", "FK", "BLR", "FKB"])
    def test_opposite_faces_rejected(self, btype: str) -> None:
        with pytest.raises(ValueError, match="opposite"):
            ASDAbsorbingBoundary3D(pg="p", G=1.0, v=0.25, rho=1.0, btype=btype)

    @pytest.mark.parametrize("btype", ["", "X", "LX", "T"])
    def test_illegal_or_empty_btype_rejected(self, btype: str) -> None:
        with pytest.raises(ValueError):
            ASDAbsorbingBoundary3D(pg="p", G=1.0, v=0.25, rho=1.0, btype=btype)

    def test_repeated_letter_rejected(self) -> None:
        with pytest.raises(ValueError, match="repeats"):
            ASDAbsorbingBoundary3D(pg="p", G=1.0, v=0.25, rho=1.0, btype="LL")

    @pytest.mark.parametrize("G,v,rho", [(-1.0, 0.25, 1.0), (1.0, 0.6, 1.0), (1.0, 0.25, -1.0)])
    def test_bad_props_rejected(self, G, v, rho) -> None:
        with pytest.raises(ValueError):
            ASDAbsorbingBoundary3D(pg="p", G=G, v=v, rho=rho, btype="L")

    def test_base_input_on_non_bottom_rejected(self) -> None:
        ts = Path(values=(0.0, 1.0), dt=0.1)
        with pytest.raises(ValueError, match="bottom"):
            ASDAbsorbingBoundary3D(pg="p", G=1.0, v=0.25, rho=1.0, btype="L", fx=ts)

    def test_base_input_on_bottom_ok(self) -> None:
        ts = Path(values=(0.0, 1.0), dt=0.1)
        e = ASDAbsorbingBoundary3D(pg="p", G=1.0, v=0.25, rho=1.0, btype="BL", fx=ts)
        assert e.dependencies() == (ts,)


class TestEmit:
    def test_emit_plain(self) -> None:
        e = ASDAbsorbingBoundary3D(pg="p", G=1351.0, v=0.262, rho=2.4e-9, btype="LF")
        rec = _emit(e, tag=42)
        assert rec.calls == [
            ("element", ("ASDAbsorbingBoundary3D", 42, *N8, 1351.0, 0.262, 2.4e-9, "LF"), {}),
        ]

    def test_emit_with_fx_on_bottom(self) -> None:
        ts = Path(values=(0.0, 1.0), dt=0.1)
        e = ASDAbsorbingBoundary3D(pg="p", G=10.0, v=0.3, rho=2.0, btype="B", fx=ts)
        rec = _emit(e, tag=5, ts_tags={id(ts): 99})
        assert rec.calls == [
            ("element", ("ASDAbsorbingBoundary3D", 5, *N8, 10.0, 0.3, 2.0, "B", "-fx", 99), {}),
        ]

    def test_emit_wrong_node_count_raises(self) -> None:
        e = ASDAbsorbingBoundary3D(pg="p", G=1.0, v=0.25, rho=1.0, btype="L")
        em = RecordingEmitter()
        set_tag_resolver(em, lambda p: 1)
        set_element_nodes(em, (1, 2, 3, 4))
        with pytest.raises(ValueError, match="expected 8 node tags"):
            e._emit(em, tag=1)


class TestFacade:
    def test_material_derives_G(self) -> None:
        ops = _stub_bridge()
        mat = ElasticIsotropic(E=3410.0, nu=0.262, rho=2.4e-9)
        e = ops.element.ASDAbsorbingBoundary3D(pg="abs_L", btype="L", material=mat)
        assert e.G == pytest.approx(3410.0 / (2.0 * 1.262))
        assert e.v == 0.262
        assert e.rho == 2.4e-9

    def test_raw_props(self) -> None:
        ops = _stub_bridge()
        e = ops.element.ASDAbsorbingBoundary3D(
            pg="abs_R", btype="R", G=1351.0, v=0.262, rho=2.4e-9,
        )
        assert (e.G, e.v, e.rho) == (1351.0, 0.262, 2.4e-9)

    def test_material_and_raw_both_rejected(self) -> None:
        ops = _stub_bridge()
        mat = ElasticIsotropic(E=3410.0, nu=0.262, rho=2.4e-9)
        with pytest.raises(ValueError, match="not both"):
            ops.element.ASDAbsorbingBoundary3D(pg="p", btype="L", material=mat, G=1.0)

    def test_neither_material_nor_raw_rejected(self) -> None:
        ops = _stub_bridge()
        with pytest.raises(ValueError, match="all of"):
            ops.element.ASDAbsorbingBoundary3D(pg="p", btype="L")


class TestConstructionValidation2D:
    def test_basic_ok(self) -> None:
        e = ASDAbsorbingBoundary2D(
            pg="abs_L", G=1351.0, v=0.262, rho=2.4e-9, thickness=1.0, btype="L",
        )
        assert e.pg == "abs_L"
        assert e.btype == "L"
        assert e.thickness == 1.0
        assert e.dependencies() == ()

    @pytest.mark.parametrize("btype", ["LR", "BLR"])
    def test_opposite_faces_rejected(self, btype: str) -> None:
        # "LR" PARSES in OpenSees (both flags set) but the element then
        # sorts/sizes as a single vertical boundary — silently wrong.
        with pytest.raises(ValueError, match="opposite"):
            ASDAbsorbingBoundary2D(
                pg="p", G=1.0, v=0.25, rho=1.0, thickness=1.0, btype=btype,
            )

    @pytest.mark.parametrize("btype", ["", "X", "F", "K", "LF", "BK", "T"])
    def test_illegal_or_empty_btype_rejected(self, btype: str) -> None:
        # F/K are 3D-only letters — illegal on the 2D element.
        with pytest.raises(ValueError):
            ASDAbsorbingBoundary2D(
                pg="p", G=1.0, v=0.25, rho=1.0, thickness=1.0, btype=btype,
            )

    def test_repeated_letter_rejected(self) -> None:
        with pytest.raises(ValueError, match="repeats"):
            ASDAbsorbingBoundary2D(
                pg="p", G=1.0, v=0.25, rho=1.0, thickness=1.0, btype="LL",
            )

    @pytest.mark.parametrize(
        "G,v,rho,t",
        [(-1.0, 0.25, 1.0, 1.0), (1.0, 0.6, 1.0, 1.0),
         (1.0, 0.25, -1.0, 1.0), (1.0, 0.25, 1.0, 0.0),
         (1.0, 0.25, 1.0, -2.0)],
    )
    def test_bad_props_rejected(self, G, v, rho, t) -> None:
        with pytest.raises(ValueError):
            ASDAbsorbingBoundary2D(
                pg="p", G=G, v=v, rho=rho, thickness=t, btype="L",
            )

    def test_base_input_on_non_bottom_rejected(self) -> None:
        ts = Path(values=(0.0, 1.0), dt=0.1)
        with pytest.raises(ValueError, match="bottom"):
            ASDAbsorbingBoundary2D(
                pg="p", G=1.0, v=0.25, rho=1.0, thickness=1.0, btype="R", fy=ts,
            )

    def test_base_input_on_bottom_ok(self) -> None:
        ts = Path(values=(0.0, 1.0), dt=0.1)
        e = ASDAbsorbingBoundary2D(
            pg="p", G=1.0, v=0.25, rho=1.0, thickness=1.0, btype="BR", fx=ts,
        )
        assert e.dependencies() == (ts,)


class TestEmit2D:
    def test_emit_plain_thickness_before_btype(self) -> None:
        # Source-verified arg order: G v rho THICKNESS btype
        # (OPS_ASDAbsorbingBoundary2D parses 4 doubles then the string).
        e = ASDAbsorbingBoundary2D(
            pg="p", G=1351.0, v=0.262, rho=2.4e-9, thickness=2.5, btype="L",
        )
        rec = _emit(e, tag=42, nodes=N4)
        assert rec.calls == [
            ("element",
             ("ASDAbsorbingBoundary2D", 42, *N4, 1351.0, 0.262, 2.4e-9, 2.5, "L"),
             {}),
        ]

    def test_emit_with_fx_on_bottom(self) -> None:
        ts = Path(values=(0.0, 1.0), dt=0.1)
        e = ASDAbsorbingBoundary2D(
            pg="p", G=10.0, v=0.3, rho=2.0, thickness=1.0, btype="B", fx=ts,
        )
        rec = _emit(e, tag=5, nodes=N4, ts_tags={id(ts): 99})
        assert rec.calls == [
            ("element",
             ("ASDAbsorbingBoundary2D", 5, *N4, 10.0, 0.3, 2.0, 1.0, "B",
              "-fx", 99),
             {}),
        ]

    def test_emit_wrong_node_count_raises(self) -> None:
        e = ASDAbsorbingBoundary2D(
            pg="p", G=1.0, v=0.25, rho=1.0, thickness=1.0, btype="L",
        )
        em = RecordingEmitter()
        set_tag_resolver(em, lambda p: 1)
        set_element_nodes(em, N8)
        with pytest.raises(ValueError, match="expected 4 node tags"):
            e._emit(em, tag=1)


class TestFacade2D:
    def test_material_derives_G(self) -> None:
        ops = _stub_bridge()
        mat = ElasticIsotropic(E=3410.0, nu=0.262, rho=2.4e-9)
        e = ops.element.ASDAbsorbingBoundary2D(
            pg="abs_L", btype="L", thickness=1.0, material=mat,
        )
        assert e.G == pytest.approx(3410.0 / (2.0 * 1.262))
        assert e.v == 0.262
        assert e.rho == 2.4e-9
        assert e.thickness == 1.0

    def test_error_messages_say_2d(self) -> None:
        ops = _stub_bridge()
        with pytest.raises(ValueError, match="ASDAbsorbingBoundary2D"):
            ops.element.ASDAbsorbingBoundary2D(pg="p", btype="L", thickness=1.0)


class _StubSkin:
    """Minimal stand-in for AbsorbingSkinResult (only skin_pgs is consumed)."""

    def __init__(self, skin_pgs: dict[str, str]) -> None:
        self.skin_pgs = skin_pgs


class _StubSkin2D(_StubSkin):
    """2D stand-in — carries the ``ndm`` marker the dispatch reads."""

    ndm = 2


class TestAbsorbingBoundaryConvenience:
    def _skin(self) -> _StubSkin:
        # A reduced but representative btype set incl. a bottom + a non-bottom.
        return _StubSkin({
            "L": "abs_L", "R": "abs_R", "B": "abs_B",
            "BL": "abs_BL", "LF": "abs_LF",
        })

    def test_one_spec_per_btype(self) -> None:
        ops = _stub_bridge()
        specs = ops.element.absorbing_boundary(
            skin=self._skin(), G=1351.0, v=0.262, rho=2.4e-9,
        )
        assert len(specs) == 5
        assert {s.btype for s in specs} == {"L", "R", "B", "BL", "LF"}
        assert all(s.fx is None for s in specs)  # no base series given

    def test_base_series_only_on_bottom(self) -> None:
        ops = _stub_bridge()
        ts = Path(values=(0.0, 1.0, 0.0), dt=0.1)
        specs = ops.element.absorbing_boundary(
            skin=self._skin(), material=ElasticIsotropic(E=3410.0, nu=0.262, rho=2.4e-9),
            base_series=ts, base_dirs=("x",),
        )
        by = {s.btype: s for s in specs}
        # Bottom (B-containing) get -fx; side panels don't.
        assert by["B"].fx is ts and by["BL"].fx is ts
        assert by["L"].fx is None and by["R"].fx is None and by["LF"].fx is None
        # No -fy/-fz since only "x" requested.
        assert by["B"].fy is None and by["B"].fz is None

    def test_bad_base_dir_rejected(self) -> None:
        ops = _stub_bridge()
        ts = Path(values=(0.0, 1.0), dt=0.1)
        with pytest.raises(ValueError, match="base_dirs"):
            ops.element.absorbing_boundary(
                skin=self._skin(), G=1.0, v=0.25, rho=1.0,
                base_series=ts, base_dirs=("w",),
            )

    def test_thickness_rejected_for_3d_skin(self) -> None:
        ops = _stub_bridge()
        with pytest.raises(ValueError, match="2D-only"):
            ops.element.absorbing_boundary(
                skin=self._skin(), G=1.0, v=0.25, rho=1.0, thickness=1.0,
            )


class TestAbsorbingBoundaryConvenience2D:
    def _skin(self) -> _StubSkin2D:
        return _StubSkin2D({
            "L": "abs_L", "R": "abs_R", "B": "abs_B",
            "BL": "abs_BL", "BR": "abs_BR",
        })

    def test_dispatches_to_2d_specs(self) -> None:
        ops = _stub_bridge()
        specs = ops.element.absorbing_boundary(
            skin=self._skin(), G=1351.0, v=0.262, rho=2.4e-9, thickness=2.0,
        )
        assert len(specs) == 5
        assert all(isinstance(s, ASDAbsorbingBoundary2D) for s in specs)
        assert {s.btype for s in specs} == {"L", "R", "B", "BL", "BR"}
        assert all(s.thickness == 2.0 for s in specs)

    def test_thickness_required(self) -> None:
        ops = _stub_bridge()
        with pytest.raises(ValueError, match="thickness"):
            ops.element.absorbing_boundary(
                skin=self._skin(), G=1.0, v=0.25, rho=1.0,
            )

    def test_base_series_only_on_bottom(self) -> None:
        ops = _stub_bridge()
        ts = Path(values=(0.0, 1.0, 0.0), dt=0.1)
        specs = ops.element.absorbing_boundary(
            skin=self._skin(),
            material=ElasticIsotropic(E=3410.0, nu=0.262, rho=2.4e-9),
            thickness=1.0, base_series=ts, base_dirs=("x",),
        )
        by = {s.btype: s for s in specs}
        assert by["B"].fx is ts and by["BL"].fx is ts and by["BR"].fx is ts
        assert by["L"].fx is None and by["R"].fx is None
        assert by["B"].fy is None

    def test_z_dir_rejected_for_2d_skin(self) -> None:
        ops = _stub_bridge()
        ts = Path(values=(0.0, 1.0), dt=0.1)
        with pytest.raises(ValueError, match="base_dirs"):
            ops.element.absorbing_boundary(
                skin=self._skin(), G=1.0, v=0.25, rho=1.0, thickness=1.0,
                base_series=ts, base_dirs=("z",),
            )
