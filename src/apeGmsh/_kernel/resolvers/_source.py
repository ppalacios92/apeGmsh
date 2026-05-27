"""Resolver source adapter — Phase 3B.2d / ADR 0038.

The :class:`ResolverSource` Protocol abstracts the small surface that
session composites (``g.loads`` / ``g.masses`` / ``g.constraints``)
use to look up node tags, coordinates, and PG / label resolutions
while building :class:`~apeGmsh._kernel.records` instances.

Two concrete implementations ship in this module:

* :class:`GmshSource` — wraps a live gmsh session (build phase).  All
  queries route to ``gmsh.model.*`` plus the composites' existing
  resolution helpers.
* :class:`FEMDataSource` — wraps a :class:`FEMData` snapshot
  (chain phase).  Queries are answered out of the in-memory broker
  with no gmsh state required.

The Protocol is intentionally narrow — it covers only the lookup
operations the chain-phase shim retrofit (Phase 3B.2d step 3) needs to
resolve a constraint / load / mass def directly into a record using
the broker as the source of truth.  Wider operations (face areas,
edge tributaries, element connectivity walks) remain on the existing
:class:`apeGmsh._kernel.resolvers._load_resolver.LoadResolver` and
sibling resolvers — those are pure mesh math and don't need the source
abstraction.

Future work
-----------
As more chain-phase shim paths get retrofitted, additional methods can
be added here as needed — keep the Protocol minimal.  Foreign-format
adapters (LS-DYNA d3plot, xDMF, Exodus) that round-trip via
:class:`FEMData` get :class:`FEMDataSource` for free.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Protocol, runtime_checkable

import numpy as np

if TYPE_CHECKING:
    from apeGmsh.mesh.FEMData import FEMData


@runtime_checkable
class ResolverSource(Protocol):
    """Adapter contract for chain-phase constraint / load / mass resolution.

    Methods return numpy arrays of int64 node IDs (and parallel coord
    arrays where applicable) so the consuming code can index into the
    broker's record-set machinery without any gmsh dependency.

    All methods are name-resolution-aware: pass either a label name
    (Tier 1), a physical-group name (Tier 2), or a concrete container
    that already resolves to nodes.
    """

    def node_ids(self) -> np.ndarray:
        """All node ids in the model (int64 ndarray)."""
        ...

    def node_coords(self) -> np.ndarray:
        """All node coordinates as an ``(N, 3)`` float64 ndarray.

        Indexed parallel to :meth:`node_ids`.
        """
        ...

    def nodes_for(self, target: str) -> np.ndarray:
        """Resolve a target name to a set of node ids.

        ``target`` is the label/PG name passed by the user.  Resolution
        order matches the rest of the API: label (Tier 1) → physical
        group (Tier 2).  Returns an int64 ndarray.

        Raises
        ------
        KeyError
            When the name resolves to neither a label nor a PG, and is
            not a known mesh-selection container either.
        """
        ...

    def has_target(self, target: str) -> bool:
        """``True`` when ``target`` resolves to something in the source.

        Cheap pre-check used by validators that want to surface a clear
        error message before kicking off the full resolution.
        """
        ...


class FEMDataSource:
    """:class:`ResolverSource` backed by a :class:`FEMData` snapshot.

    Used by the chain-phase shim retrofit to resolve constraint / load /
    mass defs into records without touching gmsh — every lookup is
    answered out of the broker's named-group / label / node arrays.

    Construction is cheap (just stashes the ``FEMData`` reference); the
    object is otherwise stateless.  Pass a fresh instance per shim call
    so the source always reflects the latest chain head.
    """

    __slots__ = ("_fem",)

    def __init__(self, fem: "FEMData") -> None:
        self._fem = fem

    # -- ResolverSource methods ------------------------------------

    def node_ids(self) -> np.ndarray:
        return np.asarray(self._fem.nodes.ids, dtype=np.int64)

    def node_coords(self) -> np.ndarray:
        return np.asarray(self._fem.nodes.coords, dtype=np.float64)

    def nodes_for(self, target: str) -> np.ndarray:
        """Walk the broker's name → entity machinery to resolve nodes.

        Looks up ``target`` first in the node-side labels, then the
        node-side physical groups, then the element-side labels / PGs
        (gathering every node touching the resolved elements).  This
        mirrors the live-gmsh ``resolve_to_dimtags`` Tier 1 → Tier 2
        ordering.
        """
        fem = self._fem

        # Tier 1 — labels on node side.
        from apeGmsh._kernel._label_prefix import add_prefix
        prefixed = add_prefix(target)

        for entry in fem.nodes.labels._groups.values():
            entry_name = entry.get("name", "")
            if entry_name in (target, prefixed):
                ids = entry.get("node_ids")
                if ids is not None:
                    return np.asarray(ids, dtype=np.int64)

        # Tier 1 — labels on element side: gather nodes from
        # connectivity of resolved elements.
        for entry in fem.elements.labels._groups.values():
            entry_name = entry.get("name", "")
            if entry_name in (target, prefixed):
                eids = entry.get("element_ids")
                if eids is not None:
                    return self._nodes_from_element_ids(
                        np.asarray(eids, dtype=np.int64)
                    )

        # Tier 2 — physical groups on node side.
        for entry in fem.nodes.physical._groups.values():
            entry_name = entry.get("name", "")
            if entry_name == target:
                ids = entry.get("node_ids")
                if ids is not None:
                    return np.asarray(ids, dtype=np.int64)

        # Tier 2 — physical groups on element side.
        for entry in fem.elements.physical._groups.values():
            entry_name = entry.get("name", "")
            if entry_name == target:
                eids = entry.get("element_ids")
                if eids is not None:
                    return self._nodes_from_element_ids(
                        np.asarray(eids, dtype=np.int64)
                    )

        raise KeyError(
            f"FEMDataSource: target {target!r} resolves to neither a "
            f"label (Tier 1) nor a physical group (Tier 2) in the "
            f"current FEMData chain head."
        )

    def has_target(self, target: str) -> bool:
        """``True`` when :meth:`nodes_for` would succeed without raising."""
        try:
            self.nodes_for(target)
            return True
        except KeyError:
            return False

    # -- Internal helpers ------------------------------------------

    def _nodes_from_element_ids(self, eids: np.ndarray) -> np.ndarray:
        """Collect the union of node ids referenced by the given elements.

        Walks every element-type group in the broker's element
        composite; for each group whose ids overlap ``eids`` it pulls
        the corresponding connectivity rows and unions their nodes.
        Returns int64 ndarray (sorted, no duplicates).
        """
        fem = self._fem
        eids_set = set(int(x) for x in eids)
        out: set[int] = set()
        for code, grp in fem.elements._groups.items():
            grp_ids = np.asarray(grp.ids, dtype=np.int64)
            mask = np.array(
                [int(t) in eids_set for t in grp_ids], dtype=bool,
            )
            if not mask.any():
                continue
            conn = np.asarray(grp.connectivity, dtype=np.int64)[mask]
            for row in conn:
                out.update(int(n) for n in row)
        return np.array(sorted(out), dtype=np.int64)


class GmshSource:
    """:class:`ResolverSource` backed by the live gmsh session.

    Build-phase callers wrap their session in this adapter and pass it
    to the chain-phase router so the same code path works for both
    phases.  In practice the build-phase shims continue using their
    existing resolution helpers directly (no behaviour change); this
    adapter exists so future code that needs to be source-agnostic can
    consume the Protocol uniformly.

    Construction is cheap.  Queries are evaluated lazily.
    """

    __slots__ = ("_session",)

    def __init__(self, session) -> None:
        self._session = session

    # -- ResolverSource methods ------------------------------------

    def node_ids(self) -> np.ndarray:
        import gmsh
        tags, _coords, _ = gmsh.model.mesh.getNodes()
        return np.asarray(tags, dtype=np.int64)

    def node_coords(self) -> np.ndarray:
        import gmsh
        _tags, coords, _ = gmsh.model.mesh.getNodes()
        return np.asarray(coords, dtype=np.float64).reshape(-1, 3)

    def nodes_for(self, target: str) -> np.ndarray:
        """Use the central :func:`resolve_to_dimtags` helper + gmsh mesh
        queries to collect node tags.
        """
        import gmsh
        from apeGmsh.core._helpers import resolve_to_dimtags

        dts = resolve_to_dimtags(
            target, default_dim=3, session=self._session,
        )
        if not dts:
            raise KeyError(
                f"GmshSource: target {target!r} resolves to no entities."
            )

        out: set[int] = set()
        for d, t in dts:
            tags, _coords = gmsh.model.mesh.getNodesForPhysicalGroup(d, t) \
                if False else (np.array([], dtype=np.int64), None)
            # Use getNodes on the dim/tag (covers entity nodes, not PG):
            ntags, _ = gmsh.model.mesh.getNodes(dim=d, tag=t, includeBoundary=True)[:2]
            out.update(int(n) for n in ntags)
        return np.array(sorted(out), dtype=np.int64)

    def has_target(self, target: str) -> bool:
        try:
            self.nodes_for(target)
            return True
        except Exception:
            return False


def make_source(session_or_fem) -> ResolverSource:
    """Pick the right :class:`ResolverSource` for the given argument.

    Convenience constructor used by the chain-phase router — accepts
    either an :class:`apeGmsh` session or a :class:`FEMData` snapshot
    and returns the matching adapter.  Discriminates by attribute
    presence (FEMData has ``.nodes`` + ``.elements`` composites;
    session has ``.mesh`` plus ``.model``).
    """
    # FEMData carries ``.composed_from`` and ``.elements._groups`` —
    # session carries ``.mesh`` + ``.model``.  Use ``composed_from`` as
    # the discriminator since it is the most cohesive FEMData-only
    # attribute introduced in 2.9 schema.
    if hasattr(session_or_fem, "composed_from") and not hasattr(
        session_or_fem, "_compose_facade",
    ):
        return FEMDataSource(session_or_fem)
    return GmshSource(session_or_fem)
