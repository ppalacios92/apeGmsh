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


def _build_truss_bar_model(g: apeGmsh, out: Path, *, envelope_ndf: int) -> None:
    """A truss bar emitted with an *envelope_ndf* != the truss's inferred ndf.

    A 3D truss infers per-node ndf=3; declaring the model envelope as 6 makes
    every node's effective ndf (3) DIFFER from the envelope, so the persisted
    ``/opensees/nodes_ndf`` carries genuine non-envelope values — the path the
    homogeneous tet box never exercises.
    """
    a = g.model.geometry.add_point(0.0, 0.0, 0.0)
    b = g.model.geometry.add_point(1.0, 0.0, 0.0)
    line = g.model.geometry.add_line(a, b)
    g.model.sync()
    g.physical.add(1, [line], name="bar")
    g.mesh.sizing.set_global_size(1.0)
    g.mesh.generation.generate(1)
    fem = g.mesh.queries.get_fem_data(dim=1)
    ops = apeSees(fem)
    ops.model(ndm=3, ndf=envelope_ndf)
    ops.element.Truss(
        pg="bar", A=0.01,
        material=ops.uniaxialMaterial.ElasticMaterial(E=200e9),
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


def test_nodes_ndf_mixed_roundtrip_preserves_non_envelope_values(
    tmp_path: Path,
) -> None:
    """A model whose inferred per-node ndf != the envelope must persist the
    real (non-envelope) values and round-trip them through from_h5 -> to_h5
    with a stable model_hash. Guards the non-elided branch the homogeneous
    box can't reach (review #8)."""
    a = tmp_path / "a.h5"
    b = tmp_path / "b.h5"
    with apeGmsh(model_name="mix") as g:
        _build_truss_bar_model(g, a, envelope_ndf=6)

    # Truss in a ndf=6 envelope: every node's effective ndf is 3 (!= 6).
    with h5_reader.open(str(a)) as ma:
        nd = ma.nodes_ndf()
        assert nd is not None and len(nd) > 0
        assert set(nd.values()) == {3}, "non-envelope ndf must be persisted"

    om = OpenSeesModel.from_h5(str(a))
    assert om.ndf == 6                       # envelope round-trips
    om.to_h5(str(b))

    with h5_reader.open(str(a)) as ma, h5_reader.open(str(b)) as mb:
        assert ma.nodes_ndf() == mb.nodes_ndf() == nd
    assert _read_model_hash(a) == _read_model_hash(b)
    assert om.lineage.warnings == ()
