"""Unit tests for the typed ``TwoNodeLink`` element primitive.

Mirrors ``test_elements_zero_length.py``: construction, validation,
``_emit`` shape (with the bare ``-doRayleigh`` flag and optional
``-orient`` / ``-pDelta`` / ``-shearDist`` / ``-mass`` tails),
``dependencies`` dedup, and ``__repr__``.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from apeGmsh.opensees._internal.tag_resolution import (
    set_element_nodes,
    set_tag_resolver,
)
from apeGmsh.opensees._internal.types import Primitive, UniaxialMaterial
from apeGmsh.opensees.element.two_node_link import TwoNodeLink
from apeGmsh.opensees.element.zero_length import ZeroLengthMatDir
from apeGmsh.opensees.emitter.base import Emitter
from apeGmsh.opensees.emitter.recording import RecordingEmitter


@dataclass(frozen=True, kw_only=True, slots=True)
class _FakeMat(UniaxialMaterial):
    name: str

    def _emit(self, emitter: Emitter, tag: int) -> None:
        emitter.uniaxialMaterial("Fake", tag, self.name)

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


def _resolver_from(tags: dict[int, int]) -> object:
    def _resolve(prim: Primitive) -> int:
        return tags[id(prim)]
    return _resolve


class TestTwoNodeLinkConstruction:
    def test_minimal(self) -> None:
        m = _FakeMat(name="x")
        tnl = TwoNodeLink(
            pg="links",
            mat_dirs=(ZeroLengthMatDir(material=m, dof=1),),
        )
        assert tnl.pg == "links"
        assert tnl.orient is None
        assert tnl.p_delta is None
        assert tnl.shear_dist is None
        assert tnl.do_rayleigh is False
        assert tnl.mass is None

    def test_empty_mat_dirs_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            TwoNodeLink(pg="c", mat_dirs=())

    def test_orient_3_tuple_ok(self) -> None:
        m = _FakeMat(name="x")
        tnl = TwoNodeLink(
            pg="c", mat_dirs=(ZeroLengthMatDir(material=m, dof=1),),
            orient=(0.0, 1.0, 0.0),
        )
        assert tnl.orient == (0.0, 1.0, 0.0)

    def test_orient_bad_length_rejected(self) -> None:
        m = _FakeMat(name="x")
        with pytest.raises(ValueError, match="orient must be"):
            TwoNodeLink(
                pg="c", mat_dirs=(ZeroLengthMatDir(material=m, dof=1),),
                orient=(1.0, 0.0),
            )

    def test_pdelta_bad_length_rejected(self) -> None:
        m = _FakeMat(name="x")
        with pytest.raises(ValueError, match="p_delta must be"):
            TwoNodeLink(
                pg="c", mat_dirs=(ZeroLengthMatDir(material=m, dof=1),),
                p_delta=(0.5, 0.5, 0.5),
            )

    def test_shear_dist_bad_length_rejected(self) -> None:
        m = _FakeMat(name="x")
        with pytest.raises(ValueError, match="shear_dist must be"):
            TwoNodeLink(
                pg="c", mat_dirs=(ZeroLengthMatDir(material=m, dof=1),),
                shear_dist=(0.5, 0.5, 0.5),
            )

    def test_negative_mass_rejected(self) -> None:
        m = _FakeMat(name="x")
        with pytest.raises(ValueError, match="mass must be >= 0"):
            TwoNodeLink(
                pg="c", mat_dirs=(ZeroLengthMatDir(material=m, dof=1),),
                mass=-1.0,
            )


class TestTwoNodeLinkDependencies:
    def test_dedup_shared_material(self) -> None:
        a = _FakeMat(name="A")
        b = _FakeMat(name="B")
        tnl = TwoNodeLink(
            pg="c",
            mat_dirs=(
                ZeroLengthMatDir(material=a, dof=1),
                ZeroLengthMatDir(material=b, dof=2),
                ZeroLengthMatDir(material=a, dof=3),
            ),
        )
        assert tnl.dependencies() == (a, b)


class TestTwoNodeLinkEmit:
    def test_minimal_emit(self) -> None:
        m = _FakeMat(name="x")
        tnl = TwoNodeLink(
            pg="c", mat_dirs=(ZeroLengthMatDir(material=m, dof=1),),
        )
        e = RecordingEmitter()
        set_tag_resolver(e, _resolver_from({id(m): 5}))
        set_element_nodes(e, (10, 20))
        tnl._emit(e, tag=42)
        assert e.calls == [
            (
                "element",
                ("twoNodeLink", 42, 10, 20, "-mat", 5, "-dir", 1),
                {},
            ),
        ]

    def test_full_emit_with_bare_rayleigh_flag(self) -> None:
        a = _FakeMat(name="A")
        b = _FakeMat(name="B")
        tnl = TwoNodeLink(
            pg="c",
            mat_dirs=(
                ZeroLengthMatDir(material=a, dof=1),
                ZeroLengthMatDir(material=b, dof=2),
            ),
            orient=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
            p_delta=(0.5, 0.5, 0.5, 0.5),
            shear_dist=(0.5, 0.5),
            do_rayleigh=True,
            mass=2.0,
        )
        e = RecordingEmitter()
        set_tag_resolver(e, _resolver_from({id(a): 11, id(b): 22}))
        set_element_nodes(e, (1, 2))
        tnl._emit(e, tag=50)
        assert e.calls[0][1] == (
            "twoNodeLink", 50, 1, 2,
            "-mat", 11, 22,
            "-dir", 1, 2,
            "-orient", 1.0, 0.0, 0.0, 0.0, 1.0, 0.0,
            "-pDelta", 0.5, 0.5, 0.5, 0.5,
            "-shearDist", 0.5, 0.5,
            "-doRayleigh",          # bare flag, NO value
            "-mass", 2.0,
        )

    def test_do_rayleigh_false_omits_flag(self) -> None:
        m = _FakeMat(name="x")
        tnl = TwoNodeLink(
            pg="c", mat_dirs=(ZeroLengthMatDir(material=m, dof=1),),
            do_rayleigh=False,
        )
        e = RecordingEmitter()
        set_tag_resolver(e, _resolver_from({id(m): 5}))
        set_element_nodes(e, (1, 2))
        tnl._emit(e, tag=3)
        assert "-doRayleigh" not in e.calls[0][1]

    def test_emit_wrong_node_count_raises(self) -> None:
        m = _FakeMat(name="x")
        tnl = TwoNodeLink(
            pg="c", mat_dirs=(ZeroLengthMatDir(material=m, dof=1),),
        )
        e = RecordingEmitter()
        set_tag_resolver(e, _resolver_from({id(m): 1}))
        set_element_nodes(e, (1, 2, 3))
        with pytest.raises(ValueError, match="expected 2 node tags"):
            tnl._emit(e, tag=1)


class TestTwoNodeLinkMisc:
    def test_repr_includes_class_name(self) -> None:
        m = _FakeMat(name="x")
        assert "TwoNodeLink" in repr(
            TwoNodeLink(
                pg="c", mat_dirs=(ZeroLengthMatDir(material=m, dof=1),),
            )
        )
