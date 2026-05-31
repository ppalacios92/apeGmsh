"""ADR 0048/0049 PR-2 — ``/opensees/nodes_ndf`` persistence + round-trip.

Builds a real broker-backed model (so the neutral zone exists and the writer
runs), confirms the effective per-node ndf is persisted in the opensees zone,
and proves a ``from_h5 -> to_h5`` re-emit is byte-identical (the automatic
``model_hash`` fold stays stable). No openseespy needed — ``ops.h5`` composes
the archive without running an analysis.
"""
from __future__ import annotations

from pathlib import Path

import h5py

from apeGmsh import apeGmsh
from apeGmsh.opensees import apeSees
from apeGmsh.opensees.emitter import h5_reader
from apeGmsh.opensees.opensees_model import OpenSeesModel


def _build_tet_box_model(g: apeGmsh, out: Path) -> None:
    """A homogeneous tet box (one nDMaterial, ndf=3) emitted to *out*."""
    g.model.geometry.add_box(0, 0, 0, 1, 1, 1, label="body")
    g.physical.add_volume("body", name="body")
    g.mesh.sizing.set_global_size(1.0)
    g.mesh.generation.generate(3)
    fem = g.mesh.queries.get_fem_data()
    ops = apeSees(fem)
    ops.model(ndm=3, ndf=3)
    ops.element.FourNodeTetrahedron(
        pg="body",
        material=ops.nDMaterial.ElasticIsotropic(E=30e9, nu=0.2),
    )
    ops.h5(str(out))


def _read_model_hash(path: Path) -> str:
    with h5py.File(str(path), "r") as f:
        return f["meta/lineage"].attrs["model_hash"]


def test_nodes_ndf_persisted_with_effective_values(tmp_path: Path) -> None:
    out = tmp_path / "m.h5"
    with apeGmsh(model_name="m") as g:
        _build_tet_box_model(g, out)

    with h5_reader.open(str(out)) as model:
        assert model.validate() == []
        nd = model.nodes_ndf()
        assert nd is not None and len(nd) > 0
        # homogeneous tet (nDMaterial, ndf=3) → every node's effective ndf is 3
        assert set(nd.values()) == {3}


def test_nodes_ndf_roundtrip_hash_stable(tmp_path: Path) -> None:
    a = tmp_path / "a.h5"
    b = tmp_path / "b.h5"
    with apeGmsh(model_name="rt") as g:
        _build_tet_box_model(g, a)

    om = OpenSeesModel.from_h5(str(a))
    om.to_h5(str(b))

    # /opensees/nodes_ndf re-emits byte-identically → values match and the
    # model_hash (which folds the whole opensees zone) is stable, with no
    # lineage drift warning.
    with h5_reader.open(str(a)) as ma, h5_reader.open(str(b)) as mb:
        assert ma.nodes_ndf() == mb.nodes_ndf()
    assert _read_model_hash(a) == _read_model_hash(b)
    assert om.lineage.warnings == ()
