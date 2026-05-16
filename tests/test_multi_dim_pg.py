"""
Multi-dim physical groups are NOT supported.

A physical-group name maps to exactly one Gmsh dimension.  This is
enforced at every creation chokepoint:

* ``g.physical.add()`` (and its add_* shorthands) — the programmatic path
* the ModelViewer's ``_write_group()`` — the GUI path

and every consumer fails loud (never silently truncates) if a legacy
model nonetheless carries one PG name at several dims.

Multi-dim *labels* (Tier 1, ``g.labels``) remain supported — that is a
separate concept and is intentionally untouched here.
"""
import gmsh
import numpy as np
import pytest

from apeGmsh import apeGmsh
from apeGmsh.core._helpers import resolve_to_dimtags
from apeGmsh.viewers.core.selection import _write_group


# =====================================================================
# Creation ban — g.physical.add() (programmatic chokepoint)
# =====================================================================

def test_add_same_name_other_dim_raises():
    """add_surface after add_volume with the same name is rejected."""
    with apeGmsh(model_name="ban_v_then_s", verbose=False) as g:
        g.model.geometry.add_box(0, 0, 0, 1, 1, 1)
        g.model.sync()
        g.physical.add_volume([1], name="Mixed")
        with pytest.raises(ValueError, match="single dimension|not supported"):
            g.physical.add_surface([1], name="Mixed")


def test_add_same_name_other_dim_raises_reverse():
    """Order-independent: add_volume after add_surface also rejected."""
    with apeGmsh(model_name="ban_s_then_v", verbose=False) as g:
        g.model.geometry.add_box(0, 0, 0, 1, 1, 1)
        g.model.sync()
        g.physical.add_surface([1], name="Mixed")
        with pytest.raises(ValueError, match="single dimension|not supported"):
            g.physical.add_volume([1], name="Mixed")


def test_add_same_name_same_dim_still_upserts():
    """Sanity: same name at the SAME dim still appends (upsert intact)."""
    with apeGmsh(model_name="upsert_ok", verbose=False) as g:
        g.model.geometry.add_box(0, 0, 0, 1, 1, 1)
        g.model.geometry.add_box(2, 0, 0, 1, 1, 1)
        g.model.sync()
        g.physical.add_volume([1], name="Body")
        g.physical.add_volume([2], name="Body")  # append, not a new PG
        assert set(g.physical.entities("Body")) == {1, 2}


def test_dim_tags_method_removed():
    """The multi-dim escape hatch is gone — guard against reintroduction."""
    with apeGmsh(model_name="no_dim_tags", verbose=False) as g:
        assert not hasattr(g.physical, "dim_tags")


# =====================================================================
# Single-dim still works (no regression, no merge overhead)
# =====================================================================

def test_entities_single_dim_resolves_without_dim():
    with apeGmsh(model_name="single_ok", verbose=False) as g:
        g.model.geometry.add_box(0, 0, 0, 1, 1, 1)
        g.model.sync()
        g.physical.add_volume([1], name="Only")
        assert g.physical.entities("Only") == [1]


def test_fem_single_dim_name_unchanged():
    """fem.nodes.get(pg=) for a single-dim PG: name == (dim, tag)."""
    with apeGmsh(model_name="fem_single", verbose=False) as g:
        g.model.geometry.add_box(0, 0, 0, 1, 1, 1)
        g.model.sync()
        g.physical.add_volume([1], name="Only")
        g.mesh.sizing.set_global_size(0.5)
        g.mesh.generation.generate(3)
        fem = g.mesh.queries.get_fem_data()
        ids_by_name = fem.nodes.physical.node_ids("Only")
        ids_by_tuple = fem.nodes.physical.node_ids((3, 1))
        assert np.array_equal(
            np.asarray(ids_by_name, dtype=np.int64),
            np.asarray(ids_by_tuple, dtype=np.int64),
        )


# =====================================================================
# Legacy / raw multi-dim PG (bypassing add()) — fail loud, not silent
# =====================================================================

@pytest.fixture
def g_legacy_multi_pg():
    """Simulate a legacy model: a multi-dim PG written via raw gmsh,
    bypassing g.physical.add()'s guard."""
    with apeGmsh(model_name="legacy_multi", verbose=False) as g:
        g.model.geometry.add_box(0, 0, 0, 1, 1, 1)
        g.model.sync()
        # Raw gmsh — deliberately reproduce the now-forbidden state.
        t3 = gmsh.model.addPhysicalGroup(3, [1])
        gmsh.model.setPhysicalName(3, t3, "Mixed")
        t2 = gmsh.model.addPhysicalGroup(2, [1])
        gmsh.model.setPhysicalName(2, t2, "Mixed")
        yield g


def test_entities_legacy_multi_dim_raises(g_legacy_multi_pg):
    with pytest.raises(ValueError, match="multiple dimensions|not supported"):
        g_legacy_multi_pg.physical.entities("Mixed")


def test_resolve_to_dimtags_legacy_multi_dim_raises(g_legacy_multi_pg):
    with pytest.raises(ValueError, match="multiple dimensions|not supported"):
        resolve_to_dimtags(
            "Mixed", default_dim=3, session=g_legacy_multi_pg,
        )


# =====================================================================
# ModelViewer GUI chokepoint — _write_group() invariant
# =====================================================================

def test_write_group_rejects_mixed_dims():
    with apeGmsh(model_name="viewer_ban", verbose=False) as g:
        g.model.geometry.add_box(0, 0, 0, 1, 1, 1)
        g.model.sync()
        with pytest.raises(ValueError, match="single dimension|not supported"):
            _write_group("Mixed", [(3, 1), (2, 1)])


def test_write_group_rejection_preserves_existing_group():
    """A rejected multi-dim write must NOT delete the prior valid PG."""
    with apeGmsh(model_name="viewer_preserve", verbose=False) as g:
        g.model.geometry.add_box(0, 0, 0, 1, 1, 1)
        g.model.sync()
        _write_group("Keep", [(3, 1)])            # valid single-dim
        with pytest.raises(ValueError):
            _write_group("Keep", [(3, 1), (2, 1)])  # rejected
        # The original single-dim group is still intact.
        assert g.physical.entities("Keep") == [1]
