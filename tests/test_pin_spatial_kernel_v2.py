"""P3-S — new-idiom spatial regression *successors* (selection-unification v2).

Contract: ``docs/plans/selection-unification-v2.md`` §6.2 P3-S + its
2026-05-19 M-CORRECTION note, and
``selection-unification-v2-p3r-callers.md`` §0 M-CORRECTION-P3S. The in-repo
P3-S charter is ``tests/test_pin_spatial_v2.py:21-25``.

P3-R already froze the *literal* box/sphere/plane + fail-loud-via-``.in_box``
behaviour **green** in ``tests/test_mesh_selection_chain.py`` (``:222-336``,
``:432-449`` — the P3-R rewrites). This file adds ONLY the four
source-proven *successor* gaps, **exclusively via the new idiom**
``g.mesh_selection.select(...)`` — there is deliberately **no**
``from apeGmsh._kernel import spatial`` here: the unified spatial kernel is
exercised *through* the idiom, never imported (M-CORRECTION; the fail-loud
centroid is the per-engine ``MeshSelection._centroid_map_live``, not in
``_kernel/spatial.py`` whose docstring states exactly this).

  * **PIN 1 (Gap D)** element-level ``.coords`` returns the per-engine
    fail-loud centroid *value* (never silent row-0), value-frozen; + a
    ``.coords``-triggered fail-loud regression. The *only* element-``.coords``
    value pin in the suite (the existing ``:432-449`` fail-loud triggers via
    ``.in_box``, never ``.coords``).
  * **PIN 2 (Gap C)** element-centroid ``.on_plane`` frozen as an *id-set*,
    replacing the cardinality-only ``len(chained)==4`` at
    ``test_mesh_selection_chain.py:209`` (closes the §7 silent-drift hole).
  * **PIN 3 (Gap E)** the unified kernel ``|(c-p)·n̂| <= tol`` plane
    *boundary* exercised exactly through the live idiom (``tol`` == the
    on-plane distance), frozen id-sets.
  * **PIN 4 (Gap F)** non-unit / non-axis normal *normalisation* through the
    live idiom, anchored to the existing green ``[2,12,17,25]`` oracle.

ADDITIVE ONLY — zero ``src/`` change, zero edits to existing tests. Every
literal below was captured once on the known-green HEAD tree (the
proof-file / p2g freeze pattern) and is hand-derivable from the
deterministic ``{0,0.5,1}^3`` node lattice / ``{0.25,0.75}^3`` element
centroids (derivation in each test).
"""
from __future__ import annotations

import numpy as np
import pytest

from apeGmsh import apeGmsh


@pytest.fixture
def live():
    """Live 3x3x3 lattice — VERBATIM the proven fixture pattern
    (``tests/test_mesh_selection_chain.py:77-97``): 27 nodes at every
    ``{0,0.5,1}^3``; 8 hex8 cells; centroids the 8 corners of
    ``{0.25,0.75}^3``. Built via the RETAINED idiom (NOT the P3-R-removed
    ``g.mesh_selection.add_nodes``)."""
    g = apeGmsh(model_name="p3s_kernel_cube", verbose=False)
    g.begin()
    try:
        g.model.geometry.add_box(0.0, 0.0, 0.0, 1.0, 1.0, 1.0,
                                 label="box")
        g.physical.add_volume("box", name="Body")
        g.mesh.structured.set_transfinite_box("box", n=3)
        g.mesh.generation.generate(dim=3)
        yield g
    finally:
        g.end()


def _sorted_ids(seq) -> list[int]:
    return sorted(int(x) for x in seq)


# =====================================================================
# PIN 1 — element-level ``.coords`` is the per-engine FAIL-LOUD
# centroid, value-frozen (Gap D).
# =====================================================================

# Centroids of the 4 z==0.25 cells, rows in ``sel.ids`` order [1,2,3,4]
# (the deterministic Gmsh transfinite ordering of this exact fixture).
# Exact dyadic values: a hex8 node-z set is four 0.0 + four 0.5 → mean
# = 0.25 exactly (likewise 0.75); 0.25/0.75 are exact in float64.
_PIN1_CENTROIDS = np.array(
    [[0.25, 0.25, 0.25],
     [0.75, 0.25, 0.25],
     [0.25, 0.75, 0.25],
     [0.75, 0.75, 0.25]],
    dtype=np.float64,
)


def test_pin_element_coords_centroid_frozen(live):
    """``select(level='element').in_box(...).coords`` returns the
    per-engine element CENTROIDS (not node coords, never silent
    row-0), value-frozen.

    Derivation: the half-open box upper-z = 0.75 (the unified
    ``box_mask`` uses ``coords < hi``) excludes every centroid with
    z == 0.75 and keeps the 4 with z == 0.25 → ids ``[1,2,3,4]`` (the
    existing green oracle ``test_mesh_selection_chain.py:248-253``).
    Each such hex8 spans a lower-z octant, so its centroid is an
    ``(x,y) ∈ {0.25,0.75}^2`` corner at ``z == 0.25``; row order
    follows ``sel.ids``.
    """
    ms = live.mesh_selection
    sel = (ms.select(level="element", dim=3)
             .in_box((-1.0, -1.0, -1.0), (2.0, 2.0, 0.75)))
    assert _sorted_ids(sel.ids) == [1, 2, 3, 4]    # existing-oracle re-anchor
    c = sel.coords
    assert c.shape == (4, 3)
    assert c.dtype == np.float64
    # value-frozen centroid array — a silent row-0 substitution or a
    # node-coords/centroid mix-up shifts these by >= 0.25:
    np.testing.assert_array_equal(c, _PIN1_CENTROIDS)
    # structural invariants (the human-readable derivation):
    assert np.all(c[:, 2] == 0.25)                 # every z exactly 0.25
    assert set(np.round(c[:, 0], 6)) == {0.25, 0.75}
    assert set(np.round(c[:, 1], 6)) == {0.25, 0.75}


def test_pin_element_coords_fails_loud_on_unknown_node(live, monkeypatch):
    """Paired regression: a corrupted connectivity id makes element
    ``.coords`` raise the per-engine ``_centroid_map_live`` fail-loud,
    never silently substitute row 0.

    Distinct entry path from ``test_mesh_selection_chain.py:432-449``
    (which triggers the same fail-loud via ``.in_box``) — this proves
    the ``.coords`` accessor *itself* is fail-loud.
    """
    ms = live.mesh_selection
    real = ms._get_mesh_elements

    def _bad(dim):
        eids, conn = real(dim)
        conn = conn.copy()
        conn[0, 0] = 10 ** 9                  # a node id that cannot exist
        return eids, conn

    monkeypatch.setattr(ms, "_get_mesh_elements", _bad)
    sel = ms.select(level="element", dim=3)   # seeding does NOT centroid
    with pytest.raises(KeyError, match="not in the live mesh node set"):
        sel.coords                            # ``.coords`` forces centroid


# =====================================================================
# PIN 2 — element-centroid ``.on_plane`` FROZEN ID-SET (Gap C: replaces
# the cardinality-only ``len(chained)==4`` at
# ``test_mesh_selection_chain.py:209`` — the §7 "never silent drift"
# hole).
# =====================================================================

def test_pin_element_on_plane_centroid_frozen_idset(live):
    """``select(level='element').in_box(all).on_plane(z=0.25,+z,
    tol=0.1)`` frozen as the id-set, not ``len()``.

    Derivation: ``in_box((-1,-1,-1),(2,2,2))`` keeps all 8 (every
    centroid coord ∈ {0.25,0.75} ⊂ [-1,2)). Signed distance of a
    centroid to plane (point=(0,0,0.25), n̂=+z) is ``c_z - 0.25``:
    z==0.25 → 0 ≤ 0.1 (keep); z==0.75 → 0.5 > 0.1 (drop). Kept = the 4
    z==0.25 cells = ``[1,2,3,4]`` (the existing ``:253`` z==0.25
    quartet). A cardinality-preserving centroid corruption (any *other*
    4-cell subset) now fails this assertion — the §7 hole closed.
    """
    ms = live.mesh_selection
    chained = (ms.select(level="element", dim=3)
                 .in_box((-1, -1, -1), (2, 2, 2))
                 .on_plane((0, 0, 0.25), (0, 0, 1), tol=0.1))
    assert _sorted_ids(chained.ids) == [1, 2, 3, 4]


# =====================================================================
# PIN 3 — the unified-kernel ``<= tol`` plane BOUNDARY, exercised
# exactly through the live idiom (Gap E: every existing live
# ``on_plane`` uses tol=1e-9/0.1 vs exact 0/0.5/1.0 coords — never the
# ``<=`` edge).
# =====================================================================

# Frozen from the {0,0.5,1}^3 lattice (captured once on the
# known-green tree): the z==0 plane (9 nodes) and z∈{0,0.5} (18 nodes).
_PIN3_Z0 = [2, 4, 6, 8, 12, 16, 17, 19, 25]
_PIN3_Z0_OR_HALF = [2, 4, 6, 8, 9, 11, 12, 13, 15,
                    16, 17, 19, 21, 22, 23, 24, 25, 27]


def test_pin_on_plane_le_tol_boundary_frozen(live):
    """The unified kernel plane predicate is ``|(c-p)·n̂| <= tol``
    (closed). Node lattice z ∈ {0,0.5,1} ⇒ distances to plane z=0
    (n̂=+z) are EXACTLY {0,0.5,1.0}. At ``tol == 0.5`` the z==0.5 plane
    sits on the ``<=`` edge and is INCLUDED (18 nodes = the z∈{0,0.5}
    planes, 9+9); just below 0.5 it is EXCLUDED (9 nodes = z==0 only);
    just above 0.5 still 18 (z==1 distance 1.0 > tol). A ``<=``→``<``
    kernel regression flips the ``tol==0.5`` set 18→9. Frozen as
    id-sets (not just counts) so no silent drift.
    """
    ms = live.mesh_selection
    on_eq = ms.select().on_plane((0, 0, 0), (0, 0, 1), tol=0.5)
    on_lo = ms.select().on_plane((0, 0, 0), (0, 0, 1), tol=0.4999999)
    on_hi = ms.select().on_plane((0, 0, 0), (0, 0, 1), tol=0.5000001)
    # boundary INCLUDED at tol == distance (closed ``<=``):
    assert _sorted_ids(on_eq.ids) == _PIN3_Z0_OR_HALF
    assert len(on_eq) == 18
    # boundary EXCLUDED just below the edge:
    assert _sorted_ids(on_lo.ids) == _PIN3_Z0
    assert len(on_lo) == 9
    # just above the edge unchanged (z==1 still beyond tol):
    assert _sorted_ids(on_hi.ids) == _PIN3_Z0_OR_HALF
    # the just-below set is a strict subset of the boundary set:
    assert set(_PIN3_Z0) < set(_PIN3_Z0_OR_HALF)


# =====================================================================
# PIN 4 — non-unit / non-axis normal NORMALISATION through the live
# idiom (Gap F: the ``n/||n||`` branch is exercised only on the results
# engine, never the live engine). Anchored to the existing green
# ``[2,12,17,25]`` oracle (``test_mesh_selection_chain.py:222-231``) by
# replicating its EXACT chain prefix and varying ONLY the normal —
# head-caught: ``[2,12,17,25]`` is the half-open-box-prefixed z==0
# *subset*, NOT the full 9-node z==0 plane (a box-less
# ``select().on_plane`` would yield all 9).
# =====================================================================

def test_pin_on_plane_nonunit_normal_frozen(live):
    """``select().in_box((0,0,0),(1,1,1)).on_plane((0,0,0),
    (0,0,100.0),tol=1e-9)`` MUST equal the existing green unit-normal
    oracle ``[2,12,17,25]`` (``test_mesh_selection_chain.py:230-231``):
    the caller normalises ``n/||n||`` ((0,0,100)→(0,0,1)) before the
    unified ``plane_mask``, so a non-unit normal is identical to the
    unit one. The half-open box ``[0,1)^3`` drops the upper
    ``{x|y|z=1}`` shell; ∩ the z==0 plane (tol 1e-9) ⇒ exactly
    ``[2,12,17,25]``. A dropped ``/||n||`` would scale the distances by
    100 and empty/shrink the set.
    """
    ms = live.mesh_selection
    nonunit = (ms.select()
                 .in_box((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
                 .on_plane((0, 0, 0), (0, 0, 100.0), tol=1e-9))
    unit = (ms.select()
              .in_box((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
              .on_plane((0, 0, 0), (0, 0, 1), tol=1e-9))
    assert _sorted_ids(nonunit.ids) == [2, 12, 17, 25]   # existing oracle
    assert _sorted_ids(nonunit.ids) == _sorted_ids(unit.ids)
