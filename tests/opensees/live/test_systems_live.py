"""Live runs of the newly-added ``system`` solvers.

Gated by the ``live`` marker (skips without ``openseespy``). Each test
drives a solver in its appropriate regime and asserts a clean solve:

* ``Diagonal`` — explicit transient with lumped mass (its only valid
  regime; it cannot solve a coupled stiffness matrix).
* ``SProfileSPD`` / ``SparseSYM`` — implicit static cantilever; the tip
  displacement matches the ``BandGeneral`` reference.

The parallel-family solvers (``MPIDiagonal`` / ``ParallelProfileSPD``)
are not exercised here — they need an ``OpenSeesMP`` build.
"""
from __future__ import annotations

from typing import cast

import pytest

from apeGmsh.opensees import apeSees

openseespy = pytest.importorskip("openseespy.opensees")

from apeGmsh.opensees.emitter.live import LiveOpsEmitter  # noqa: E402

from tests.opensees.fixtures.fem_stub import (  # noqa: E402
    make_two_node_beam,
)


def _cantilever(ops: apeSees) -> None:
    ops.model(ndm=3, ndf=6)
    transf = ops.geomTransf.Linear(vecxz=(1.0, 0.0, 0.0))
    ops.element.elasticBeamColumn(
        pg="Cols", transf=transf,
        A=0.01, E=200e9, Iz=1e-4, Iy=1e-4, G=80e9, J=1e-4,
    )
    ops.fix(pg="Base", dofs=(1, 1, 1, 1, 1, 1))
    ts = ops.timeSeries.Linear()
    with ops.pattern.Plain(series=ts) as p:
        p.load(node=2, forces=(1000.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    ops.constraints.Plain()
    ops.numberer.Plain()
    ops.test.NormDispIncr(tol=1e-9, max_iter=10)
    ops.algorithm.Linear()
    ops.integrator.LoadControl(dlam=1.0)
    ops.analysis.Static()


@pytest.mark.parametrize("system_name", ["SProfileSPD", "SparseSYM"])
@pytest.mark.live
def test_implicit_solver_static_cantilever(system_name: str) -> None:
    expected = 1000.0 * 1.0**3 / (3.0 * 200e9 * 1e-4)

    ops = apeSees(cast("object", make_two_node_beam()))  # type: ignore[arg-type]
    ops.model(ndm=3, ndf=6)
    transf = ops.geomTransf.Linear(vecxz=(1.0, 0.0, 0.0))
    ops.element.elasticBeamColumn(
        pg="Cols", transf=transf,
        A=0.01, E=200e9, Iz=1e-4, Iy=1e-4, G=80e9, J=1e-4,
    )
    ops.fix(pg="Base", dofs=(1, 1, 1, 1, 1, 1))
    ts = ops.timeSeries.Linear()
    with ops.pattern.Plain(series=ts) as p:
        p.load(node=2, forces=(1000.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    ops.constraints.Plain()
    ops.numberer.Plain()
    getattr(ops.system, system_name)()
    ops.test.NormDispIncr(tol=1e-9, max_iter=10)
    ops.algorithm.Linear()
    ops.integrator.LoadControl(dlam=1.0)
    ops.analysis.Static()

    emitter = LiveOpsEmitter(wipe=True)
    ops.build().emit(emitter)
    assert emitter.analyze(steps=1) == 0
    assert emitter.ops.nodeDisp(2, 1) == pytest.approx(expected, rel=1e-3)


@pytest.mark.live
def test_diagonal_drives_explicit_transient() -> None:
    """``system Diagonal`` solves a lumped-mass explicit transient."""
    ops = apeSees(cast("object", make_two_node_beam()))  # type: ignore[arg-type]
    ops.model(ndm=3, ndf=6)
    transf = ops.geomTransf.Linear(vecxz=(1.0, 0.0, 0.0))
    ops.element.elasticBeamColumn(
        pg="Cols", transf=transf,
        A=0.01, E=200e9, Iz=1e-4, Iy=1e-4, G=80e9, J=1e-4,
    )
    ops.fix(pg="Base", dofs=(1, 1, 1, 1, 1, 1))
    ops.mass(nodes=[2], values=(1.0, 1.0, 1.0, 1.0, 1.0, 1.0))
    ts = ops.timeSeries.Linear()
    with ops.pattern.Plain(series=ts) as p:
        p.load(node=2, forces=(1000.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    ops.constraints.Plain()
    ops.numberer.Plain()
    ops.system.Diagonal()
    ops.test.NormDispIncr(tol=1e-9, max_iter=10)
    ops.algorithm.Linear()
    # CentralDifference is in stock OpenSees, so this needs no fork build.
    ops.integrator.CentralDifference()
    ops.analysis.Transient()

    emitter = LiveOpsEmitter(wipe=True)
    ops.build().emit(emitter)
    assert emitter.analyze(steps=5, dt=1e-4) == 0
    assert emitter.ops.getTime() == pytest.approx(5e-4, rel=1e-6)
