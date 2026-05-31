"""ADR 0045 S5-tiebreak — highest-active-dim-wins pick (model/BREP viewer).

Two headless layers, no renderer:
  * ``coincident_stack`` — the pure resolution (a face hit -> [volume, face],
    head = the default selection = highest active dim).
  * ``EntityRegistry.volumes_of_face`` — the adjacency accessor the resolution
    consumes.

The default pick is correct regardless of which coincident actor the picker
returns. (The Tab "select other" cycle through the stack is deferred to a
follow-up — Qt focus traversal swallows the Tab key, which needs a viewport
eventFilter + GPU verification.)
"""
from __future__ import annotations

import pytest

from apeGmsh.viewers.core.pick_tiebreak import coincident_stack


# ---------------------------------------------------------------------
# coincident_stack — pure resolution
# ---------------------------------------------------------------------

def _vof(mapping):
    """Build a volumes_of_face callable from a plain dict."""
    return lambda dt: mapping.get((int(dt[0]), int(dt[1])), [])


def test_face_hit_routes_to_volume_first():
    stack = coincident_stack((2, 5), [0, 1, 2, 3], _vof({(2, 5): [(3, 9)]}))
    assert stack == [(3, 9), (2, 5)]          # volume first, face second


def test_face_hit_volume_dim_inactive_keeps_face():
    # dim 3 not active -> no routing, just the face.
    stack = coincident_stack((2, 5), [1, 2], _vof({(2, 5): [(3, 9)]}))
    assert stack == [(2, 5)]


def test_face_hit_face_dim_inactive_keeps_only_volume():
    # Narrowed to volumes (dim 2 inactive): only the volume survives.
    stack = coincident_stack((2, 5), [3], _vof({(2, 5): [(3, 9)]}))
    assert stack == [(3, 9)]


def test_free_surface_has_no_volume():
    stack = coincident_stack((2, 5), [2, 3], _vof({}))
    assert stack == [(2, 5)]


def test_internal_face_lists_both_volumes_sorted_then_face():
    stack = coincident_stack(
        (2, 5), [2, 3], _vof({(2, 5): [(3, 12), (3, 7)]}),
    )
    assert stack == [(3, 7), (3, 12), (2, 5)]


def test_volume_hit_is_its_own_head():
    stack = coincident_stack((3, 9), [2, 3], _vof({}))
    assert stack == [(3, 9)]


def test_edge_hit_passthrough():
    stack = coincident_stack((1, 4), [0, 1, 2, 3], _vof({(2, 5): [(3, 9)]}))
    assert stack == [(1, 4)]


def test_inactive_hit_dim_yields_empty():
    # Defensive: picker gate normally prevents this, but a dim-2 hit with
    # neither 2 nor 3 active resolves to nothing.
    assert coincident_stack((2, 5), [0, 1], _vof({(2, 5): [(3, 9)]})) == []


def test_no_duplicate_when_volume_equals_nothing():
    # A face whose only owner is inactive collapses to just the face.
    stack = coincident_stack((2, 5), [2], _vof({(2, 5): [(3, 9)]}))
    assert stack == [(2, 5)]


# ---------------------------------------------------------------------
# EntityRegistry adjacency accessor
# ---------------------------------------------------------------------

def test_registry_volumes_of_face_roundtrip():
    from apeGmsh.viewers.core.entity_registry import EntityRegistry

    reg = EntityRegistry()
    assert reg.volumes_of_face((2, 5)) == []        # default empty
    reg.set_face_to_volume({(2, 5): [(3, 9)], (2, 6): [(3, 9), (3, 10)]})
    assert reg.volumes_of_face((2, 5)) == [(3, 9)]
    assert reg.volumes_of_face((2, 6)) == [(3, 9), (3, 10)]
    assert reg.volumes_of_face((2, 99)) == []       # unknown face
    # Returns a copy — caller can't mutate internal state.
    got = reg.volumes_of_face((2, 5))
    got.append((3, 0))
    assert reg.volumes_of_face((2, 5)) == [(3, 9)]


def test_registry_volumes_of_face_feeds_coincident_stack():
    """The accessor is exactly the callable coincident_stack expects."""
    from apeGmsh.viewers.core.entity_registry import EntityRegistry

    reg = EntityRegistry()
    reg.set_face_to_volume({(2, 5): [(3, 9)]})
    stack = coincident_stack((2, 5), [0, 1, 2, 3], reg.volumes_of_face)
    assert stack == [(3, 9), (2, 5)]


def test_default_pick_is_volume_in_both_hit_directions():
    """Bulletproofing the primary behavior: whether the picker resolves the
    boundary click to the dim=2 face or the dim=3 volume actor, the head of
    the stack (the default selection) is the owning volume."""
    vof = _vof({(2, 5): [(3, 9)]})
    # Face-actor hit -> volume is head.
    assert coincident_stack((2, 5), [0, 1, 2, 3], vof)[0] == (3, 9)
    # Volume-actor hit -> already the volume.
    assert coincident_stack((3, 9), [0, 1, 2, 3], vof)[0] == (3, 9)
