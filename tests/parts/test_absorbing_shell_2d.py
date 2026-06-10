"""End-to-end tests for ``g.parts.add_absorbing_shell_2d`` (ADR 0054, AB-5).

Bring-your-own-box 2D entry: the user's axis-aligned rectangular surface gets
a one-element absorbing skin welded onto its L/R/B truncation edges, then the
shared classify → PG → transfinite tail.  Mirrors ``test_absorbing_shell.py``.
"""
from __future__ import annotations

import gmsh
import numpy as np
import pytest

from apeGmsh import apeGmsh

# 40 x 30 box, element_size 10 -> nx=4, ny=3 (same grid as the turnkey tests).
NX, NY = 4, 3
EXPECTED = {"L": NY, "R": NY, "B": NX, "BL": 1, "BR": 1}
SOIL_QUAD = NX * NY
SKIN_QUAD = sum(EXPECTED.values())


def _pg_element_count(name: str, dim: int = 2) -> int:
    for d, tag in gmsh.model.getPhysicalGroups(dim):
        if gmsh.model.getPhysicalName(d, tag) == name:
            total = 0
            for ent in gmsh.model.getEntitiesForPhysicalGroup(d, tag):
                _types, etags, _ = gmsh.model.mesh.getElements(d, ent)
                total += sum(len(t) for t in etags)
            return total
    return 0


def _make_box(g, label="soilbox"):
    g.model.geometry.add_rectangle(0.0, -30.0, 0.0, 40.0, 30.0, label=label)
    g.physical.add(2, label, name=label)


class TestHappyPath:
    def test_distribution_and_soil_pg(self):
        g = apeGmsh(model_name="shell2d_dist", verbose=False)
        g.begin()
        try:
            _make_box(g)
            res = g.parts.add_absorbing_shell_2d(box="soilbox", element_size=10.0)
            assert res.ndm == 2
            # The user's PG is reported, no duplicate soil PG created.
            assert res.soil_pg == "soilbox"
            assert set(res.skin_pgs) == set(EXPECTED)
            g.mesh.generation.generate(dim=2)
            assert _pg_element_count(res.soil_pg) == SOIL_QUAD
            for btype, expected in EXPECTED.items():
                assert _pg_element_count(res.skin_pgs[btype]) == expected, btype
            assert _pg_element_count(res.skin_all_pg) == SKIN_QUAD
        finally:
            g.end()

    def test_conformal_no_duplicate_nodes(self):
        g = apeGmsh(model_name="shell2d_conf", verbose=False)
        g.begin()
        try:
            _make_box(g)
            g.parts.add_absorbing_shell_2d(box="soilbox", element_size=10.0)
            g.mesh.generation.generate(dim=2)
            tags, xyz, _ = gmsh.model.mesh.getNodes()
            xyz = np.asarray(xyz).reshape(-1, 3)
            assert len(np.unique(np.round(xyz, 5), axis=0)) == len(tags)
        finally:
            g.end()

    def test_faces_subset(self):
        g = apeGmsh(model_name="shell2d_faces", verbose=False)
        g.begin()
        try:
            _make_box(g)
            res = g.parts.add_absorbing_shell_2d(
                box="soilbox", element_size=10.0, faces=("L", "B"),
            )
            # R dropped: no R panel, no BR corner.
            assert set(res.skin_pgs) == {"L", "B", "BL"}
            g.mesh.generation.generate(dim=2)
            assert _pg_element_count(res.skin_pgs["L"]) == NY
            assert _pg_element_count(res.skin_pgs["B"]) == NX
        finally:
            g.end()

    def test_layered(self):
        g = apeGmsh(model_name="shell2d_layers", verbose=False)
        g.begin()
        try:
            _make_box(g)
            res = g.parts.add_absorbing_shell_2d(
                box="soilbox", element_size=10.0,
                layers=[(10.0, 1), (20.0, 2)],
            )
            assert res.n_layers == 2
            assert set(res.skin_pgs_by_layer[0]) == {"L", "R"}
            assert set(res.skin_pgs_by_layer[1]) == {"L", "R", "B", "BL", "BR"}
            g.mesh.generation.generate(dim=2)
            assert _pg_element_count("soil_layer0") == 4
            assert _pg_element_count("soil_layer1") == 8
        finally:
            g.end()


class TestGuards:
    def test_rotated_box_rejected(self):
        g = apeGmsh(model_name="shell2d_rot", verbose=False)
        g.begin()
        try:
            g.model.geometry.add_rectangle(
                0.0, 0.0, 0.0, 40.0, 30.0, angles_deg=(0.0, 0.0, 20.0),
                label="rot",
            )
            with pytest.raises(ValueError, match="axis-aligned"):
                g.parts.add_absorbing_shell_2d(box="rot", element_size=10.0)
        finally:
            g.end()

    def test_non_flat_box_rejected(self):
        g = apeGmsh(model_name="shell2d_flat", verbose=False)
        g.begin()
        try:
            # A rectangle standing in the XZ plane: y-extent 0, z-extent 30.
            g.model.geometry.add_rectangle(
                0.0, 0.0, 0.0, 40.0, 30.0, plane="xz", label="wall",
            )
            with pytest.raises(ValueError, match="z = const"):
                g.parts.add_absorbing_shell_2d(box="wall", element_size=10.0)
        finally:
            g.end()

    def test_layers_sum_mismatch_rejected(self):
        g = apeGmsh(model_name="shell2d_sum", verbose=False)
        g.begin()
        try:
            _make_box(g)
            with pytest.raises(ValueError, match="y-extent"):
                g.parts.add_absorbing_shell_2d(
                    box="soilbox", element_size=10.0, layers=[(10.0, 1)],
                )
        finally:
            g.end()

    def test_bad_faces_rejected(self):
        g = apeGmsh(model_name="shell2d_badface", verbose=False)
        g.begin()
        try:
            _make_box(g)
            with pytest.raises(ValueError, match="faces"):
                g.parts.add_absorbing_shell_2d(
                    box="soilbox", element_size=10.0, faces=("F",),  # 3D-only
                )
        finally:
            g.end()
