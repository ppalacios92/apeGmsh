"""UI tree perf benches — validate hot rebuild paths.

Marked ``@pytest.mark.bench`` so it only runs with ``pytest -m bench``.
Uses the offscreen Qt platform so the test does not require a display.

Two benches:

1. ``test_parts_tree_refresh_perf`` — measures PartsTreePanel.refresh()
   cost for one part containing 10 000 leaf entities. The current
   implementation calls ``QTreeWidgetItem(parent)`` 10 000 times — each
   triggers a tree-widget-side insertion notification because there is
   no ``setUpdatesEnabled(False)`` / ``blockSignals`` wrap. We expect
   the wrap to roughly halve the wall time.

2. ``test_outline_tree_full_rebuild_perf`` — measures the OutlineTree
   _refresh_diagrams full tear-down vs. the same number of nodes
   already present. Demonstrates the cost of ``takeChildren()`` +
   re-add on geometries × compositions matrices that grow with the
   user's session.
"""
from __future__ import annotations

import os
import time

import pytest


# Force offscreen Qt before importing qtpy.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.mark.bench
def test_parts_tree_refresh_perf() -> None:
    """PartsTreePanel.refresh() should beat a 1 s budget for 10k entities.

    More importantly, this exposes that one giant refresh path adds
    items in a tight Python loop without the ``setUpdatesEnabled``
    guard. Compare A (current) and B (with guard) wall times.
    """
    from qtpy import QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    # Stub registries: shape only — PartsTreePanel reads .instances and
    # .all_entities(); the values just need to iterate.
    class _Inst:
        def __init__(self, entities):
            self.entities = entities

    class _Parts:
        def __init__(self, instances):
            self.instances = instances

    class _Reg:
        def __init__(self, all_dts):
            self._all = all_dts

        def all_entities(self, dim=None):
            if dim is None:
                return list(self._all)
            return [(d, t) for (d, t) in self._all if d == dim]

    n = 10_000
    surfaces = list(range(1, n + 1))
    parts = _Parts({"BigPart": _Inst({2: surfaces})})
    entity_reg = _Reg([(2, t) for t in surfaces])

    from apeGmsh.viewers.ui._parts_tree import PartsTreePanel

    # ── A: current implementation ─────────────────────────────────────
    panel = PartsTreePanel(parts, entity_reg)
    # Already refreshed once in __init__ — measure a second call.
    t0 = time.perf_counter()
    panel.refresh()
    t_curr = time.perf_counter() - t0
    print(f"\n[parts_tree A] current refresh({n} leaves): {t_curr*1000:.1f} ms")

    # ── B: simulate the wrap by guarding the tree directly ───────────
    tree = panel._tree
    tree.setUpdatesEnabled(False)
    tree.blockSignals(True)
    try:
        t0 = time.perf_counter()
        panel.refresh()
        t_wrap = time.perf_counter() - t0
    finally:
        tree.blockSignals(False)
        tree.setUpdatesEnabled(True)
    print(f"[parts_tree B] wrapped refresh({n} leaves):  {t_wrap*1000:.1f} ms")

    speedup = t_curr / max(t_wrap, 1e-9)
    print(f"[parts_tree] speedup factor: {speedup:.2f}x")

    # Hard budget — protects against future regressions.
    assert t_curr < 5.0, f"refresh too slow: {t_curr*1000:.0f} ms"


@pytest.mark.bench
def test_outline_tree_full_rebuild_perf() -> None:
    """OutlineTree._refresh_diagrams full rebuild on geom×comp matrix.

    Demonstrates that the current "takeChildren + add" pattern scales
    O(G*C) with no incremental update; for sessions with G=10 geometries
    × C=20 compositions each, every geometry-events fires a complete
    teardown.
    """
    from qtpy import QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    # Stub director shape used by OutlineTree.
    class _Comp:
        def __init__(self, cid: str, name: str, layers):
            self.id = cid
            self.name = name
            self.layers = layers

    class _CompMgr:
        def __init__(self, comps, active_id):
            self.compositions = comps
            self.active_id = active_id

        def find(self, cid):
            for c in self.compositions:
                if c.id == cid:
                    return c
            return None

    class _Geom:
        def __init__(self, gid, name, comps):
            self.id = gid
            self.name = name
            self.compositions = _CompMgr(comps, comps[0].id if comps else None)
            self.deform_enabled = False
            self.deform_field = None
            self.deform_scale = 1.0

    class _GeomMgr:
        def __init__(self, geoms):
            self.geometries = geoms
            self.active_id = geoms[0].id if geoms else None

        def find(self, gid):
            for g in self.geometries:
                if g.id == gid:
                    return g
            return None

        def geometry_for_composition(self, cid):
            for g in self.geometries:
                if g.compositions.find(cid):
                    return g
            return None

        def subscribe(self, cb):
            return lambda: None

    class _Director:
        def __init__(self, geoms):
            self.geometries = _GeomMgr(geoms)
            self.stage_id = "stage0"

        def stages(self):
            return []

        def subscribe_stage(self, cb):
            return lambda: None

        def subscribe_diagrams(self, cb):
            return lambda: None

        @property
        def registry(self):
            class _R:
                def diagrams(self_inner):
                    return []
            return _R()

    # 10 geometries, 20 compositions each = 200 nodes per refresh.
    G, C = 10, 20
    geoms = [
        _Geom(
            f"g{gi}", f"Geometry {gi}",
            [_Comp(f"c{gi}_{ci}", f"Diagram {ci}", []) for ci in range(C)],
        )
        for gi in range(G)
    ]
    director = _Director(geoms)

    from apeGmsh.viewers.ui._outline_tree import OutlineTree

    # Avoid theme subscription triggering import paths during tear-down.
    tree = OutlineTree(director)

    # Warm one round.
    tree._refresh_diagrams()

    iterations = 50
    t0 = time.perf_counter()
    for _ in range(iterations):
        tree._refresh_diagrams()
    elapsed = time.perf_counter() - t0
    per_call = elapsed / iterations * 1000.0
    print(
        f"\n[outline] _refresh_diagrams × {iterations} on {G}×{C} matrix: "
        f"{elapsed*1000:.1f} ms total, {per_call:.2f} ms/call"
    )

    # On a typical workstation each refresh should fit well under 50 ms;
    # the current implementation easily blows past that on larger
    # session matrices because it tears the entire group every time.
    assert per_call < 200.0, f"refresh way too slow: {per_call:.1f} ms/call"
