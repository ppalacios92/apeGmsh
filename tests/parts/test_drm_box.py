"""End-to-end tests for ``g.parts.add_DRM_box`` and :class:`DRMBox`.

These tests exercise the full geometry → STEP → import → PG-tagging
→ transfinite cascade path against a live OCC kernel.  They are
deliberately not OpenSees-aware — the DRM-box primitive is pure
geometry / mesh setup.
"""
from __future__ import annotations

import math

import gmsh
import pytest

from apeGmsh import DRMBox, DRMBoxResult, apeGmsh


# A small, mesh-friendly default that survives 8 distinct test
# variants — total of 8x8x6 = 384 hex elements per build.  Replaces
# the user's 16x16x30 = 7680-element notebook in the test suite
# (which is verified separately in ``test_user_notebook_reproduction``).
TINY = dict(
    x_inner=(50.0, 4),
    x_layer=(10.0, 1),
    x_outer=(20.0, 1),
    y_inner=(50.0, 4),
    y_layer=(10.0, 1),
    y_outer=(20.0, 1),
    z_top=(20.0, 2),
    z_mid=(20.0, 2),
    z_bottom=(40.0, 2),
)
# Per-axis element totals: X = 1+1+4+1+1 = 8, Y = 8, Z = 2+2+2 = 6.
TINY_TOTAL_HEX = 8 * 8 * 6   # 384


def _element_counts(dim: int) -> dict[str, int]:
    etypes, etags, _ = gmsh.model.mesh.getElements(dim=dim)
    out: dict[str, int] = {}
    for et, tags in zip(etypes, etags):
        name, *_ = gmsh.model.mesh.getElementProperties(et)
        out[name] = out.get(name, 0) + len(tags)
    return out


class TestHappyPath:
    def test_smoke_default_pg_names(self):
        g = apeGmsh(model_name="drm_smoke", verbose=False)
        g.begin()
        try:
            res = g.parts.add_DRM_box(**TINY)
            assert isinstance(res, DRMBoxResult)
            assert res.inner_pg == "inner_box"
            assert res.transition_pg == "transition_box"
            assert res.outer_pg == "outer_box"
            assert res.center == (0.0, 0.0, 0.0)
            assert res.rotation_z == 0.0
            assert set(res.axes) == {"x", "y", "z"}
            # 5x5x3 = 75 sub-volumes on a symmetric layered box
            inst = g.parts.get("drm_box")
            assert len(inst.entities[3]) == 75
        finally:
            g.end()

    def test_mesh_total_hex_count_matches_per_region(self):
        g = apeGmsh(model_name="drm_mesh", verbose=False)
        g.begin()
        try:
            g.parts.add_DRM_box(**TINY)
            g.mesh.generation.generate(dim=3)
            counts = _element_counts(3)
            assert "Hexahedron 8" in counts
            assert counts["Hexahedron 8"] == TINY_TOTAL_HEX
            # No tets — the structured cascade should hex-mesh
            # every sub-volume.
            assert counts.get("Tetrahedron 4", 0) == 0
        finally:
            g.end()

    def test_volume_pg_geometric_semantics(self):
        """Pins the user-notebook geometric semantics of the three
        volume PGs (in_box rule, not max-lateral-rank wrap):

        * ``inner_box`` is the single inner-inner-top sub-volume.
        * ``transition_box`` is the shell inside
          ``[-x_LL,+x_LL] x [-y_LL,+y_LL] x [-(z_top+z_mid), 0]``
          (with ``x_LL = (x_inner+x_layer)/2``) minus ``inner_box``.
        * ``outer_box`` is the rest.

        Regression guard against the original max-lateral-rank
        wrap classifier, which split the column at every Z layer
        and yielded the wrong sub-volume counts (3 / 24 / 48).
        """
        g = apeGmsh(model_name="drm_geom", verbose=False)
        g.begin()
        try:
            res = g.parts.add_DRM_box(**TINY)
            inner_tag = g.physical.get_tag(3, res.inner_pg)
            (inner_vt,) = tuple(g.physical.get_entities(3, inner_tag))
            # inner-inner-top sits laterally at (0, 0) and z-mid at
            # -z_top/2.
            com = g.model.queries.center_of_mass(int(inner_vt), dim=3)
            assert com[0] == pytest.approx(0.0, abs=1e-6)
            assert com[1] == pytest.approx(0.0, abs=1e-6)
            assert com[2] == pytest.approx(-TINY["z_top"][0] / 2, abs=1e-6)

            # Transition AABB: cx ∈ [-x_LL, +x_LL], cy ∈ [-y_LL, +y_LL],
            # cz ∈ [-(z_top + z_mid), 0].
            x_LL = (TINY["x_inner"][0] + TINY["x_layer"][0]) / 2
            y_LL = (TINY["y_inner"][0] + TINY["y_layer"][0]) / 2
            z_LL = TINY["z_top"][0] + TINY["z_mid"][0]
            tol = 1e-6
            trans_tag = g.physical.get_tag(3, res.transition_pg)
            for vt in g.physical.get_entities(3, trans_tag):
                cx, cy, cz = g.model.queries.center_of_mass(int(vt), dim=3)
                assert -x_LL - tol <= cx <= x_LL + tol, (
                    f"trans vol {vt} cx={cx} outside x_LL={x_LL}"
                )
                assert -y_LL - tol <= cy <= y_LL + tol, (
                    f"trans vol {vt} cy={cy} outside y_LL={y_LL}"
                )
                assert -z_LL - tol <= cz <= tol, (
                    f"trans vol {vt} cz={cz} outside z_LL={z_LL}"
                )

            # Every outer sub-volume sits outside at least one of those
            # three bounds (i.e. NOT inside the transition AABB).
            outer_tag = g.physical.get_tag(3, res.outer_pg)
            for vt in g.physical.get_entities(3, outer_tag):
                cx, cy, cz = g.model.queries.center_of_mass(int(vt), dim=3)
                outside = (
                    abs(cx) > x_LL + tol or abs(cy) > y_LL + tol
                    or cz < -z_LL - tol or cz > tol
                )
                assert outside, (
                    f"outer vol {vt} at ({cx},{cy},{cz}) should not "
                    f"lie inside the transition AABB"
                )
        finally:
            g.end()

    def test_volume_pg_partition_is_complete(self):
        g = apeGmsh(model_name="drm_pgs", verbose=False)
        g.begin()
        try:
            res = g.parts.add_DRM_box(**TINY)
            inst = g.parts.get("drm_box")
            all_vols = set(inst.entities[3])
            inner = set(g.physical.get_entities(
                3, g.physical.get_tag(3, res.inner_pg)
            ))
            trans = set(g.physical.get_entities(
                3, g.physical.get_tag(3, res.transition_pg)
            ))
            outer = set(g.physical.get_entities(
                3, g.physical.get_tag(3, res.outer_pg)
            ))
            assert inner.isdisjoint(trans)
            assert inner.isdisjoint(outer)
            assert trans.isdisjoint(outer)
            assert inner | trans | outer == all_vols
            # ``inner_box`` is the single inner-inner-top sub-volume
            # — the geometric "inner box" where an embedded structure
            # sits in the canonical DRM layout.
            assert len(inner) == 1
            # ``transition_box`` is the layer-bounded AABB shell minus
            # the inner cell: (inner | layer)^2 lateral × (top | mid)
            # Z = 9 * 2 = 18, minus the inner cell = 17.
            assert len(trans) == 17
            # ``outer_box`` is everything else (the absorbing region
            # + the inner column below the transition shell).
            assert len(outer) == 75 - 1 - 17
        finally:
            g.end()


class TestRotation:
    def test_rotation_preserves_element_count(self):
        g = apeGmsh(model_name="drm_rot", verbose=False)
        g.begin()
        try:
            res = g.parts.add_DRM_box(**TINY, rotation_z_deg=30.0)
            assert res.rotation_z == pytest.approx(math.radians(30.0))
            g.mesh.generation.generate(dim=3)
            counts = _element_counts(3)
            assert counts.get("Tetrahedron 4", 0) == 0
            assert counts["Hexahedron 8"] == TINY_TOTAL_HEX
        finally:
            g.end()

    def test_rotation_rotates_outer_bbox(self):
        g = apeGmsh(model_name="drm_rot_bb", verbose=False)
        g.begin()
        try:
            g.parts.add_DRM_box(
                **TINY, rotation_z_deg=30.0,
                apply_transfinite=False, tag_line_pgs=False,
            )
            inst = g.parts.get("drm_box")
            # The instance's umbrella bbox expands when rotated.
            # X-extent of the unrotated outer-box is
            # 2 * (50/2 + 10 + 20) = 110.  After a 30° rotation it
            # should be strictly larger.
            assert inst.bbox is not None
            xmin, ymin, _zmin, xmax, ymax, _zmax = inst.bbox
            assert (xmax - xmin) > 110.0
            assert (ymax - ymin) > 110.0
        finally:
            g.end()


class TestTranslation:
    def test_center_shifts_bbox(self):
        g = apeGmsh(model_name="drm_trans", verbose=False)
        g.begin()
        try:
            g.parts.add_DRM_box(
                **TINY, center=(100.0, 200.0, 50.0),
                apply_transfinite=False, tag_line_pgs=False,
            )
            inst = g.parts.get("drm_box")
            assert inst.bbox is not None
            xmin, ymin, zmin, xmax, ymax, zmax = inst.bbox
            cx = 0.5 * (xmin + xmax)
            cy = 0.5 * (ymin + ymax)
            # The DRM-box's lateral centroid sits at the translation
            # ``center`` xy (the inner box is centred laterally).
            assert cx == pytest.approx(100.0, abs=1e-6)
            assert cy == pytest.approx(200.0, abs=1e-6)
            # The Z stack descends from ``cz``: free surface at
            # cz = 50; bottom at cz - (20 + 20 + 40) = -30.
            assert zmax == pytest.approx(50.0, abs=1e-6)
            assert zmin == pytest.approx(-30.0, abs=1e-6)
        finally:
            g.end()


class TestNamingOverrides:
    def test_name_prefix(self):
        g = apeGmsh(model_name="drm_naming", verbose=False)
        g.begin()
        try:
            res = g.parts.add_DRM_box(**TINY, name="alice")
            assert res.inner_pg == "alice_inner_box"
            assert res.transition_pg == "alice_transition_box"
            assert res.outer_pg == "alice_outer_box"
            # Line-PG names also gain the prefix.
            assert res.line_pgs["inner_x"] == "alice_lines_inner_x"
        finally:
            g.end()

    def test_per_pg_override(self):
        g = apeGmsh(model_name="drm_override", verbose=False)
        g.begin()
        try:
            res = g.parts.add_DRM_box(
                **TINY,
                names={
                    "inner_pg": "core",
                    "line_pg_top_z": "top_curves",
                },
            )
            # ``inner_pg`` was overridden directly.
            assert res.inner_pg == "core"
            # Others keep the unprefixed default.
            assert res.transition_pg == "transition_box"
            assert res.outer_pg == "outer_box"
            assert res.line_pgs["top_z"] == "top_curves"
            # Non-overridden line-PG keeps the default.
            assert res.line_pgs["inner_x"] == "lines_inner_x"
        finally:
            g.end()


class TestToggles:
    def test_tag_line_pgs_false_yields_empty_line_pgs(self):
        g = apeGmsh(model_name="drm_no_lines", verbose=False)
        g.begin()
        try:
            res = g.parts.add_DRM_box(**TINY, tag_line_pgs=False)
            assert res.line_pgs == {}
            # And no ``lines_*`` PGs exist in the model.
            for _d, pg_tag in gmsh.model.getPhysicalGroups(dim=1):
                name = gmsh.model.getPhysicalName(1, pg_tag)
                assert not name.startswith("lines_")
        finally:
            g.end()

    def test_tag_line_pgs_true_creates_curve_pgs(self):
        g = apeGmsh(model_name="drm_lines", verbose=False)
        g.begin()
        try:
            res = g.parts.add_DRM_box(**TINY)
            # All 9 expected (region, axis) groups should be present
            # (each is non-empty on this geometry).
            expected = {
                "inner_x", "layer_x", "outer_x",
                "inner_y", "layer_y", "outer_y",
                "top_z", "mid_z", "bottom_z",
            }
            assert set(res.line_pgs) == expected
            # Each PG resolves to at least one curve.
            for key, name in res.line_pgs.items():
                pg_tag = g.physical.get_tag(1, name)
                assert pg_tag is not None, f"line PG {key} missing"
                ents = g.physical.get_entities(1, pg_tag)
                assert len(ents) > 0, f"line PG {key} empty"
        finally:
            g.end()

    def test_line_pgs_classify_by_band_of_their_own_axis(self):
        """Every curve in ``lines_{region}_{axis}`` must span the
        ``axis`` segment named by ``region``.

        This is the contract that makes
        ``set_transfinite_curve('lines_inner_x', n_nodes=nx_inner+1)``
        well-defined — all curves in the PG share the same length.
        A regression to "classify X-aligned edges by Y-band" (or any
        other axis crossing) would put curves of mixed length into a
        single PG and break direct ``set_transfinite_curve`` use.
        """
        g = apeGmsh(model_name="drm_band", verbose=False)
        g.begin()
        try:
            res = g.parts.add_DRM_box(**TINY)
            axis_map = {"x": res.axes["x"], "y": res.axes["y"], "z": res.axes["z"]}
            expected_size = {
                ("x", "inner"): TINY["x_inner"][0],
                ("x", "layer"): TINY["x_layer"][0],
                ("x", "outer"): TINY["x_outer"][0],
                ("y", "inner"): TINY["y_inner"][0],
                ("y", "layer"): TINY["y_layer"][0],
                ("y", "outer"): TINY["y_outer"][0],
                ("z", "top"):    TINY["z_top"][0],
                ("z", "mid"):    TINY["z_mid"][0],
                ("z", "bottom"): TINY["z_bottom"][0],
            }
            for key, pg_name in res.line_pgs.items():
                region, axis_letter = key.rsplit("_", 1)
                pg_tag = g.physical.get_tag(1, pg_name)
                want_size = expected_size[(axis_letter, region)]
                for ctag in g.physical.get_entities(1, pg_tag):
                    bb = gmsh.model.getBoundingBox(1, int(ctag))
                    dx, dy, dz = bb[3]-bb[0], bb[4]-bb[1], bb[5]-bb[2]
                    span = {"x": dx, "y": dy, "z": dz}[axis_letter]
                    assert span == pytest.approx(want_size, abs=1e-6), (
                        f"{pg_name} curve {ctag}: span along {axis_letter} "
                        f"= {span}, expected {want_size} (the {region} "
                        f"segment of axis_{axis_letter}). Classifier is "
                        f"likely crossing axes."
                    )
        finally:
            g.end()

    def test_user_style_per_pg_curve_count_drives_per_axis_total(self):
        """User-style ``set_transfinite_curve('lines_inner_x', n_nodes=N+1)``
        must yield the expected per-axis element total when paired
        with explicit ``setTransfiniteSurface`` / ``setTransfiniteVolume``
        directives on every sub-volume.

        This pins the line-PG semantics: ``lines_inner_x`` curves must
        all share the same X-length so a single n_nodes per PG is the
        right knob.  A classifier regression that mixes lengths into
        one PG would cause adjacent sub-volumes to disagree on shared
        edges and either drop hex elements or fall back to tets.

        ``setTransfiniteAutomatic`` is deliberately NOT used here —
        gmsh overrides per-curve counts inside it from corner mesh
        sizes, which is orthogonal to the classifier contract under
        test.
        """
        g = apeGmsh(model_name="drm_user_style", verbose=False)
        g.begin()
        try:
            res = g.parts.add_DRM_box(**TINY, apply_transfinite=False)
            per_pg_count = {
                "inner_x": TINY["x_inner"][1],
                "layer_x": TINY["x_layer"][1],
                "outer_x": TINY["x_outer"][1],
                "inner_y": TINY["y_inner"][1],
                "layer_y": TINY["y_layer"][1],
                "outer_y": TINY["y_outer"][1],
                "top_z":    TINY["z_top"][1],
                "mid_z":    TINY["z_mid"][1],
                "bottom_z": TINY["z_bottom"][1],
            }
            for key, n_elem in per_pg_count.items():
                g.mesh.structured.set_transfinite_curve(
                    tag=res.line_pgs[key], n_nodes=n_elem + 1,
                )
            inst = g.parts.get("drm_box")
            for vt in inst.entities[3]:
                bnd = gmsh.model.getBoundary(
                    [(3, int(vt))], oriented=False, recursive=False,
                )
                for d, t in bnd:
                    if d == 2:
                        gmsh.model.mesh.setTransfiniteSurface(int(t))
                        gmsh.model.mesh.setRecombine(2, int(t))
                gmsh.model.mesh.setTransfiniteVolume(int(vt))
            g.mesh.generation.generate(dim=3)
            counts = _element_counts(3)
            assert counts.get("Tetrahedron 4", 0) == 0
            assert counts["Hexahedron 8"] == TINY_TOTAL_HEX
        finally:
            g.end()

    def test_apply_transfinite_false_skips_directives(self):
        g = apeGmsh(model_name="drm_no_tf", verbose=False)
        g.begin()
        try:
            g.parts.add_DRM_box(**TINY, apply_transfinite=False)
            # Mesh should still generate, but without the strict
            # 8x8x6 = 384 hex count the transfinite cascade
            # produces.
            g.mesh.generation.generate(dim=3)
            counts = _element_counts(3)
            total = sum(counts.values())
            # Unstructured tet meshes on this geometry produce far
            # more elements than the structured 384.
            assert total != TINY_TOTAL_HEX
        finally:
            g.end()


class TestUserNotebookReproduction:
    """Pin the user's hand-written notebook example to a single call."""

    PARAMS = dict(
        x_inner=(605.0, 10),
        x_layer=(10.0, 1),
        x_outer=(20.0, 2),
        y_inner=(605.0, 10),
        y_layer=(10.0, 1),
        y_outer=(20.0, 2),
        z_top=(50.0, 5),
        z_mid=(50.0, 5),
        z_bottom=(200.0, 20),
    )
    # Per-axis element totals: X = 2+1+10+1+2 = 16, Y = 16, Z = 30.
    EXPECTED_HEX = 16 * 16 * 30

    def test_total_hex_count(self):
        g = apeGmsh(model_name="drm_notebook", verbose=False)
        g.begin()
        try:
            g.parts.add_DRM_box(**self.PARAMS)
            g.mesh.generation.generate(dim=3)
            counts = _element_counts(3)
            assert counts.get("Tetrahedron 4", 0) == 0
            assert counts["Hexahedron 8"] == self.EXPECTED_HEX
        finally:
            g.end()


class TestDRMBoxStandalone:
    """The :class:`DRMBox` Part should also build cleanly on its own."""

    def test_part_session_has_75_volumes(self):
        drm = DRMBox(**TINY)
        with drm:
            drm.build()
            n_vols = len(gmsh.model.getEntities(3))
        try:
            assert n_vols == 75
            assert drm.has_file
        finally:
            drm.cleanup()
