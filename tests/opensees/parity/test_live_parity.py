"""Parity: LiveOpsEmitter vs RecordingEmitter on shared fixtures.

Drives the same model through both emitters; verifies the in-process
state OpenSees holds matches what the recording captured.

Note on element choice: this parity test uses ``elasticBeamColumn``
rather than ``forceBeamColumn``. The Phase-3 ``forceBeamColumn._emit``
uses the older Tcl ``-section secTag n_ip`` form which works in real
OpenSees Tcl but is rejected by modern openseespy (which requires a
``beamIntegration`` tag instead). That is a Phase-3 primitive bug,
not a Phase-4 bridge issue — see the Phase-4 report.
"""
from __future__ import annotations

from typing import cast

import pytest

from apeGmsh.opensees import apeSees

# openseespy is required.
pytest.importorskip("openseespy.opensees")

from apeGmsh.opensees.emitter.live import LiveOpsEmitter  # noqa: E402
from apeGmsh.opensees.emitter.recording import RecordingEmitter  # noqa: E402

from tests.opensees.fixtures.fem_stub import (  # noqa: E402
    make_two_node_beam,
)


def _build_elastic_beam() -> apeSees:
    fem = make_two_node_beam()
    ops = apeSees(cast("object", fem))  # type: ignore[arg-type]
    ops.model(ndm=3, ndf=6)
    transf = ops.geomTransf.Linear(vecxz=(1.0, 0.0, 0.0))
    ops.element.elasticBeamColumn(
        pg="Cols",
        transf=transf,
        A=0.01, E=200e9, Iz=1e-4, Iy=1e-4, G=80e9, J=1e-4,
    )
    ops.fix(pg="Base", dofs=(1, 1, 1, 1, 1, 1))
    return ops


@pytest.mark.live
def test_live_emitter_drives_full_deck_without_error() -> None:
    """The live emitter accepts every primitive _emit produces; no
    openseespy parser errors, no missing positional args."""
    ops = _build_elastic_beam()
    bm = ops.build()
    emitter = LiveOpsEmitter(wipe=True)
    bm.emit(emitter)

    # Verify openseespy actually built the model: 2 nodes, 1 element.
    assert len(emitter.ops.getNodeTags()) == 2
    assert len(emitter.ops.getEleTags()) == 1


@pytest.mark.live
def test_live_emitter_node_tags_match_fem_snapshot() -> None:
    """The fan-out emits nodes from the FEM snapshot; openseespy ends
    up with exactly those tags."""
    rec_ops = _build_elastic_beam()
    rec = RecordingEmitter()
    rec_ops.build().emit(rec)

    live_ops = _build_elastic_beam()
    emitter = LiveOpsEmitter(wipe=True)
    live_ops.build().emit(emitter)

    # Node tags from RecordingEmitter (the node() call's first arg).
    rec_node_tags = sorted(c[1][0] for c in rec.calls if c[0] == "node")
    live_node_tags = sorted(emitter.ops.getNodeTags())
    assert rec_node_tags == live_node_tags == [1, 2]
