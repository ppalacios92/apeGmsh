"""P4 — standardized column/beam generators + fluent BarBuilder (ADR 0066 §8)."""
from __future__ import annotations

import pytest

from apeGmsh import apeGmsh
from apeGmsh._kernel.defs.rebar import (
    Bar, BarBuilder, BarLayout, Cage, Hook, Stirrup, TieLayout,
)


def test_column_perimeter_bars_and_densified_ties():
    with apeGmsh(model_name="gen_col") as g:
        cage = g.rebar.column(
            section=("rect", 0.5, 0.5), height=3.0, cover=0.04,
            longitudinal=BarLayout(n_x=3, n_y=3, db=0.025),
            ties=TieLayout(db=0.01, spacing=0.2, hinge_spacing=0.1,
                           hinge_length=0.5))
        # 3×3 perimeter = 2·3 + 2·3 − 4 = 8 bars, all vertical, full height
        assert len(cage.bars) == 8
        for b in cage.bars:
            p0, p1 = b.path.points
            assert p0[2] == 0.0 and p1[2] == pytest.approx(3.0)
            assert p0[0] == p1[0] and p0[1] == p1[1]
        # ties densified in the end hinge zones → more than the uniform count
        zs = sorted(s.path.points[0][2] for s in cage.stirrups)
        assert len(zs) > round(3.0 / 0.2)                 # > uniform
        gaps = [b - a for a, b in zip(zs, zs[1:])]
        assert min(gaps) == pytest.approx(0.1, abs=1e-6)  # hinge_spacing present
        assert max(gaps) == pytest.approx(0.2, abs=1e-6)  # regular spacing present


def test_column_uniform_ties_when_no_hinge():
    with apeGmsh(model_name="gen_col_uni") as g:
        cage = g.rebar.column(
            section=("rect", 0.4, 0.4), height=2.0, cover=0.04,
            longitudinal=BarLayout(n_x=2, n_y=2, db=0.02),
            ties=TieLayout(db=0.01, spacing=0.25))
        assert len(cage.bars) == 4                         # 4 corner bars
        zs = sorted(s.path.points[0][2] for s in cage.stirrups)
        gaps = [round(b - a, 9) for a, b in zip(zs, zs[1:])]
        assert set(gaps) == {0.25}                         # all uniform


def test_beam_top_bottom_bars_and_yz_stirrups():
    with apeGmsh(model_name="gen_beam") as g:
        cage = g.rebar.beam(
            section=("rect", 0.3, 0.5), length=4.0, cover=0.04,
            top=BarLayout(n_x=2, db=0.02), bottom=BarLayout(n_x=3, db=0.02),
            stirrups=TieLayout(db=0.01, spacing=0.2))
        assert len(cage.bars) == 5                         # 2 top + 3 bottom
        tops = [b for b in cage.bars if b.role == "top"]
        bots = [b for b in cage.bars if b.role == "bottom"]
        assert len(tops) == 2 and len(bots) == 3
        # top bars sit higher (z) than bottom bars; both run along x
        assert tops[0].path.points[0][2] > bots[0].path.points[0][2]
        for b in cage.bars:
            p0, p1 = b.path.points
            assert p0[0] == 0.0 and p1[0] == pytest.approx(4.0)
        # stirrups are rings in the y-z plane at x-stations (constant x)
        s0 = cage.stirrups[0]
        xs = {round(p[0], 9) for p in s0.path.points}
        assert len(xs) == 1                                # constant x → y-z ring


def test_fluent_bar_builder_equivalent_to_l1():
    with apeGmsh(model_name="gen_fluent") as g:
        built = (g.rebar.bar(db=0.025, material="rebar")
                 .through([(0, 0, 0), (0, 0, 3.0)])
                 .hook_end(Hook.standard_90())
                 .as_("L1"))
        assert isinstance(built, Bar)
        assert built.name == "L1"
        assert built.end_hook is not None and built.end_hook.angle == 90.0
        assert built.db == 0.025
        # an abandoned builder is inert (no Bar, nothing emitted)
        b = g.rebar.bar(db=0.02, material="rebar")
        assert isinstance(b, BarBuilder)


def test_builder_requires_points():
    with apeGmsh(model_name="gen_fluent2") as g:
        with pytest.raises(ValueError):
            g.rebar.bar(db=0.02, material="rebar").build()


def test_column_cage_places_embedded_end_to_end():
    with apeGmsh(model_name="gen_col_place") as g:
        vol = g.model.geometry.add_box(0, 0, 0, 0.5, 0.5, 3.0)
        g.physical.add_volume([vol], name="Col")
        cage = g.rebar.column(
            section=("rect", 0.5, 0.5), height=3.0, cover=0.05,
            longitudinal=BarLayout(n_x=2, n_y=2, db=0.025),
            ties=TieLayout(db=0.01, spacing=0.5))
        g.rebar.place(cage, into="Col", coupling="embedded", perfect=1.0e8)
        # one embedded tie per cage member (4 bars + tie rings)
        n_members = len(cage.bars) + len(cage.stirrups)
        assert len(g.reinforce.reinforce_defs) == n_members
