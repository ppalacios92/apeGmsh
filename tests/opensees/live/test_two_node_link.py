"""Live smoke: a ``TwoNodeLink`` spring assembles and runs through
openseespy, producing the expected static stiffness response.

Gated by the ``live`` marker.

A single elastic link spring (stiffness ``k`` on local dir 1) between a
fixed node and a free node, loaded along the link axis, gives a tip
displacement of exactly ``F / k`` — confirming the element emits a
valid deck and assembles its stiffness.
"""
from __future__ import annotations

from typing import cast

import pytest

from apeGmsh.opensees import apeSees

openseespy = pytest.importorskip("openseespy.opensees")

from apeGmsh.opensees.element.zero_length import (  # noqa: E402
    ZeroLengthMatDir,
)
from apeGmsh.opensees.emitter.live import LiveOpsEmitter  # noqa: E402

from tests.opensees.fixtures.fem_stub import (  # noqa: E402
    make_two_node_beam,
)


@pytest.mark.live
def test_two_node_link_static_stiffness_F_over_k() -> None:
    # make_two_node_beam: node 1 @(0,0,0) fixed, node 2 @(0,0,1) →
    # the link axis is global Z, so its local x (dir 1) is along Z.
    fem = make_two_node_beam()
    ops = apeSees(cast("object", fem))  # type: ignore[arg-type]
    ops.model(ndm=3, ndf=3)

    k = 1.0e6
    F = 1.0e3
    expected = F / k  # 1e-3

    spring = ops.uniaxialMaterial.ElasticMaterial(E=k)
    ops.element.TwoNodeLink(
        pg="Cols",
        mat_dirs=(ZeroLengthMatDir(material=spring, dof=1),),
    )

    ops.fix(pg="Base", dofs=(1, 1, 1))
    ops.fix(nodes=(2,), dofs=(1, 1, 0))  # free along Z (the link axis)

    ts = ops.timeSeries.Linear()
    with ops.pattern.Plain(series=ts) as p:
        p.load(node=2, forces=(0.0, 0.0, F))

    ops.constraints.Plain()
    ops.numberer.Plain()
    ops.system.BandGeneral()
    ops.test.NormDispIncr(tol=1e-10, max_iter=10)
    ops.algorithm.Linear()
    ops.integrator.LoadControl(dlam=1.0)
    ops.analysis.Static()

    emitter = LiveOpsEmitter(wipe=True)
    ops.build().emit(emitter)
    assert emitter.analyze(steps=1) == 0

    assert emitter.ops.nodeDisp(2, 3) == pytest.approx(expected, rel=1e-6)
