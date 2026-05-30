"""S5 acceptance — EntityRegistry.set_dim_pickable (volume-click pass-through).

Headless: stub actors record SetPickable; assert the fan-out toggles every
actor of a dim (fill / wire / node / silhouette) and only that dim. The
actual ray-pass-through-to-volume needs a GPU + eyeball; this locks the
pickability gating logic the fix rests on.
"""
from __future__ import annotations

from apeGmsh.viewers.core.entity_registry import EntityRegistry


class _StubActor:
    def __init__(self) -> None:
        self.pickable: bool | None = None

    def SetPickable(self, v) -> None:
        self.pickable = bool(v)


def _reg_dim_with_all_actors(reg, dim):
    fill, wire, node, sil = (_StubActor() for _ in range(4))
    reg.register_dim(dim, mesh=object(), actor=fill, cell_to_dt={0: (dim, 1)})
    reg.register_wire(dim, object(), wire)
    reg.register_node_cloud(dim, object(), node)
    reg.set_silhouette(dim, sil, {})
    return fill, wire, node, sil


def test_set_dim_pickable_toggles_every_actor_of_the_dim() -> None:
    reg = EntityRegistry()
    fill, wire, node, sil = _reg_dim_with_all_actors(reg, 3)

    reg.set_dim_pickable(3, False)
    assert [a.pickable for a in (fill, wire, node, sil)] == [False] * 4

    reg.set_dim_pickable(3, True)
    assert [a.pickable for a in (fill, wire, node, sil)] == [True] * 4


def test_set_dim_pickable_only_affects_that_dim() -> None:
    reg = EntityRegistry()
    f2, *_ = _reg_dim_with_all_actors(reg, 2)
    f3, *_ = _reg_dim_with_all_actors(reg, 3)

    # Volumes-only: dim 2 non-pickable, dim 3 pickable (the pass-through).
    reg.set_dim_pickable(2, False)
    reg.set_dim_pickable(3, True)
    assert f2.pickable is False
    assert f3.pickable is True


def test_set_dim_pickable_unknown_dim_is_noop() -> None:
    reg = EntityRegistry()
    reg.set_dim_pickable(2, False)   # no actors registered → no error
