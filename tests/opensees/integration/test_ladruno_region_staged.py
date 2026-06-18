"""ADR 0064 — a region-filtered Ladruno inside a stage.

A stage-bound Ladruno claimed via ``s.recorder(...)`` rides the same
``emit_recorder_spec`` → ``materialize`` → ``_emit`` pipeline as the
flat path, so its auto-emitted ``region`` line lands inside the owning
stage's ``stage_open`` … ``stage_close`` bracket and the ``recorder
ladruno ... -R <tag>`` declaration references it. This pins that the
inherited ``FilterableRecorder`` machinery works under staging (flat,
unpartitioned).
"""
from __future__ import annotations

from apeGmsh.opensees.apesees import apeSees
from apeGmsh.opensees.emitter.recording import RecordingEmitter

from tests.opensees.fixtures.fem_stub import (
    FEMStub,
    _ElementGroupView,
    _ElementsStub,
    _NodesStub,
)


def _make_two_quad_fem_stub() -> FEMStub:
    return FEMStub(
        nodes=_NodesStub(
            ids=[1, 2, 3, 4, 5, 6],
            coords=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.0, 1.0, 0.0),
                (0.0, 1.0, 0.0),
                (1.0, 2.0, 0.0),
                (0.0, 2.0, 0.0),
            ],
            node_pgs={
                "Rock": [1, 2, 3, 4],
                "Fill": [3, 4, 5, 6],
                "Base": [1, 2],
                "FillTop": [5, 6],
            },
        ),
        elements=_ElementsStub(
            elem_pgs={
                "Rock": _ElementGroupView(ids=(1,), connectivity=((1, 2, 3, 4),)),
                "Fill": _ElementGroupView(ids=(2,), connectivity=((4, 3, 5, 6),)),
            },
        ),
    )


def _chain(ops: apeSees) -> dict[str, object]:
    return {
        "test":        ops.test.NormDispIncr(tol=1e-4, max_iter=50),
        "algorithm":   ops.algorithm.Newton(),
        "integrator":  ops.integrator.LoadControl(dlam=0.1),
        "constraints": ops.constraints.Plain(),
        "numberer":    ops.numberer.RCM(),
        "system":      ops.system.UmfPack(),
        "analysis":    ops.analysis.Static(),
    }


def test_stage_bound_ladruno_filter_materializes_region_in_stage() -> None:
    fem = _make_two_quad_fem_stub()
    ops = apeSees(fem, default_orientation=None)
    ops.model(ndm=2, ndf=2)
    mat = ops.nDMaterial.ElasticIsotropic(E=1e6, nu=0.3, rho=0.0)
    ops.element.FourNodeQuad(pg="Rock", thickness=1.0, material=mat)
    ops.fix(pg="Base", dofs=(1, 1))

    with ops.stage(name="probe") as s:
        s.recorder(ops.recorder.Ladruno(
            file="run.ladruno",
            nodal_responses=("displacement",),
            nodes_pg="Rock",
        ))
        s.analysis(**_chain(ops))
        s.run(n_increments=2)

    rec = RecordingEmitter()
    ops.build().emit(rec)

    names = [c[0] for c in rec.calls]
    region_calls = [c for c in rec.calls if c[0] == "region"]
    lad_calls = [
        c for c in rec.calls if c[0] == "recorder" and c[1][0] == "ladruno"
    ]

    # Exactly one region + one ladruno recorder, both inside a stage block.
    assert len(region_calls) == 1
    assert len(lad_calls) == 1
    assert "stage_open" in names
    region_idx = rec.calls.index(region_calls[0])
    stage_open_idx = names.index("stage_open")
    assert region_idx > stage_open_idx, "region must materialize in-stage"

    # The recorder's -R references the auto-emitted region tag.
    region_tag = int(region_calls[0][1][0])
    lad_args = lad_calls[0][1]
    assert "-R" in lad_args
    assert lad_args[lad_args.index("-R") + 1] == region_tag

    # Region carries the resolved Rock node ids.
    region_args = region_calls[0][1]
    assert "-node" in region_args
    node_idx = region_args.index("-node")
    assert sorted(
        int(x) for x in region_args[node_idx + 1: node_idx + 5]
    ) == [1, 2, 3, 4]
