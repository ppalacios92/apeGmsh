"""Regression: FEM extraction must never emit element connectivity that
references a node absent from the mesh (the canonical symptom is node
tag ``0``).

Discovered while building a shell-on-solid model via the Part registry
(PR #474 collateral).  The original report blamed ``g.parts.add`` +
``renumber``, but the true trigger is a **global 3-D recombine**:
``g.mesh.structured.recombine()`` (Gmsh's ``mesh.recombine()``) is a
2-D surface operation.  Running it while 3-D tetrahedra exist deletes
interior nodes and leaves the tets that referenced them pointing at
node ``0`` — independent of Parts or renumber, and visible in the raw
Gmsh connectivity *before* any apeGmsh remap.

Passing that connectivity to OpenSees produces the opaque
``Domain::addElement - ... no Node 0 exists in the domain`` abort.
``_validate_connectivity`` (in ``mesh/_fem_extract.py``) now fails loud
at extraction instead, with a message naming the cause and the
transfinite remedy.
"""
import gmsh
import numpy as np
import pytest


def _has_zero_or_dangling(fem) -> tuple[int, int]:
    """Return (n_zero, n_dangling) across all element groups."""
    node_ids = set(int(x) for x in fem.nodes.ids)
    n_zero = n_dangling = 0
    for grp in fem.elements._groups.values():
        c = grp.connectivity
        n_zero += int((c == 0).sum())
        n_dangling += len(set(int(x) for x in c.ravel()) - node_ids)
    return n_zero, n_dangling


# ---------------------------------------------------------------------------
# Clean path: two non-fragmented Parts extract valid connectivity.
# ---------------------------------------------------------------------------

def test_two_part_nonfragmented_extracts_valid_connectivity(g):
    """Two stacked Parts, NOT fragmented, tet mesh, renumbered — every
    connectivity tag is a real node (no tag 0, nothing dangling)."""
    # Footing (wide, flat) + wall (narrow, tall) sitting on its top —
    # two separate part instances, intentionally NOT fragment_all'd so
    # the interface stays non-conformal (each body keeps its own nodes).
    with g.parts.part("foot"):
        g.model.geometry.add_box(0, 0, 0, 2, 2, 0.5)
    with g.parts.part("wal"):
        g.model.geometry.add_box(0.5, 0.5, 0.5, 1, 1, 2)

    g.mesh.sizing.set_global_size(0.5)
    g.mesh.generation.generate(3)
    g.mesh.partitioning.renumber(dim=3, method="simple", base=1)

    fem = g.mesh.queries.get_fem_data(dim=3)

    ids = np.asarray([int(x) for x in fem.nodes.ids])
    assert ids.min() == 1                       # dense 1-based after renumber
    n_zero, n_dangling = _has_zero_or_dangling(fem)
    assert n_zero == 0, "connectivity contains node tag 0"
    assert n_dangling == 0, "connectivity references a non-existent node"


# ---------------------------------------------------------------------------
# Guard: a mesh corrupted by global 3-D recombine fails loud.
# ---------------------------------------------------------------------------

def test_global_3d_recombine_corruption_fails_loud(g):
    """Global ``recombine()`` on a 3-D tet mesh deletes nodes and leaves
    node-0 tets; extraction must raise instead of passing it downstream.

    Built from plain geometry (no Parts) to prove the guard is about
    connectivity integrity, not the Parts mechanism."""
    g.model.geometry.add_box(0, 0, 0, 2, 2, 0.5, label="foot")
    g.model.geometry.add_box(0.5, 0.5, 0.5, 1, 1, 2, label="wal")

    g.mesh.sizing.set_global_size(0.5)
    g.mesh.structured.set_recombine(2, dim=3)   # flag the wall volume
    g.mesh.generation.generate(3)
    # Global 3-D recombine corrupts the volume mesh; recombine() warns
    # at the source that this is a 2-D op run with 3-D elements present.
    with pytest.warns(UserWarning, match="(?i)recombine.*3-D|3-D.*recombine"):
        g.mesh.structured.recombine()

    # Sanity: the raw Gmsh mesh really is corrupt (node-0 tets present).
    _, _, enodes_l = gmsh.model.mesh.getElements(dim=3, tag=-1)
    raw_zeros = sum(int((np.asarray(en) == 0).sum()) for en in enodes_l)
    assert raw_zeros > 0, "precondition: expected Gmsh to emit node-0 tets"

    with pytest.raises(ValueError) as exc:
        g.mesh.queries.get_fem_data(dim=3)

    msg = str(exc.value).lower()
    assert "node tag 0" in msg
    assert "recombine" in msg


def test_guard_fires_in_renumber_before_extraction(g):
    """``renumber`` extracts raw arrays first, so the guard trips there
    too — the user gets the clear error at the earliest touch point."""
    g.model.geometry.add_box(0, 0, 0, 2, 2, 0.5, label="foot")
    g.model.geometry.add_box(0.5, 0.5, 0.5, 1, 1, 2, label="wal")

    g.mesh.sizing.set_global_size(0.5)
    g.mesh.generation.generate(3)
    with pytest.warns(UserWarning):           # recombine() warns on 3-D mesh
        g.mesh.structured.recombine()

    with pytest.raises(ValueError, match="(?i)recombine"):
        g.mesh.partitioning.renumber(dim=3, method="simple", base=1)
