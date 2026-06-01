"""Unit tests for ADR 0051 (BL-4) — two-mode no-mixing guard +
unconsumed-model-load reconciliation warning + ops.ignore_model_loads.

Scope note (matches the shipped BL-4): the masses / g.constraints.bc
mirror reconciliation is DEFERRED to the BRIDGE-1 follow-up round, so
this suite covers only the load / imposed-displacement-case path.

All deck-level; no GPU.
"""
from __future__ import annotations

import warnings
from typing import Any, cast

import pytest

from apeGmsh.opensees.apesees import apeSees, WarnUnconsumedModelLoads
from apeGmsh.opensees._internal.build import BridgeError
from apeGmsh.opensees.emitter.recording import RecordingEmitter

from tests.opensees.fixtures.fem_stub import make_two_column_frame


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _full_chain(ops: apeSees) -> dict[str, object]:
    return {
        "test":        ops.test.NormDispIncr(tol=1e-4, max_iter=50),
        "algorithm":   ops.algorithm.Newton(),
        "integrator":  ops.integrator.LoadControl(dlam=0.1),
        "constraints": ops.constraints.Plain(),
        "numberer":    ops.numberer.RCM(),
        "system":      ops.system.UmfPack(),
        "analysis":    ops.analysis.Static(),
    }


def _frame_ops(fem: Any) -> apeSees:
    ops = apeSees(cast("object", fem), default_orientation=None)
    ops.model(ndm=2, ndf=3)
    t = ops.geomTransf.Linear()
    ops.element.elasticBeamColumn(pg="Cols", transf=t, A=0.01, E=200e9, Iz=1e-4)
    ops.fix(pg="Base", dofs=(1, 1, 1))
    return ops


def _add_stage(ops: apeSees, name: str = "push") -> None:
    with ops.stage(name=name) as s:
        s.analysis(**_full_chain(ops))
        s.run(n_increments=1)


def _emit_recording(ops: apeSees) -> RecordingEmitter:
    rec = RecordingEmitter()
    ops.build().emit(rec)
    return rec


def _emit_asserting_no_unconsumed_warning(ops: apeSees) -> None:
    """Build+emit, turning WarnUnconsumedModelLoads into an error so a
    spurious warning fails the test (the category is ignored by the
    project filter otherwise)."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", WarnUnconsumedModelLoads)
        ops.build().emit(RecordingEmitter())


def _loads(records) -> Any:
    from apeGmsh._kernel.record_sets import NodalLoadSet
    return NodalLoadSet(list(records))


def _sps(records) -> Any:
    from apeGmsh._kernel.record_sets import SPSet
    return SPSet(list(records))


# ---------------------------------------------------------------------------
# 1. No-mixing guard (ADR 0051 §5)
# ---------------------------------------------------------------------------


def test_global_pattern_plus_stage_raises() -> None:
    ops = _frame_ops(make_two_column_frame())
    with ops.pattern.Plain(series=ops.timeSeries.Linear()) as p:
        p.load(node=2, forces=(50.0, 0.0, 0.0))
    _add_stage(ops, "push")

    with pytest.raises(BridgeError) as exc:
        ops.build().emit(RecordingEmitter())
    msg = str(exc.value)
    assert "global" in msg
    assert "Plain" in msg            # names the offending pattern kind
    assert "'push'" in msg           # names the stage
    assert "s.pattern" in msg        # points at the staged alternative


def test_imposed_displacement_plus_stage_raises() -> None:
    """``ops.imposed_displacement`` registers a GLOBAL Plain pattern, so
    combining it with a stage trips the no-mixing guard."""
    ops = _frame_ops(make_two_column_frame())
    ops.imposed_displacement(pg="Top", ux=0.01)
    _add_stage(ops, "push")
    with pytest.raises(BridgeError, match="global ops.pattern"):
        ops.build().emit(RecordingEmitter())


def test_stage_only_patterns_do_not_trip_guard() -> None:
    """A staged model whose only pattern is stage-scoped (s.pattern) is
    valid — it is NOT a global pattern."""
    ops = _frame_ops(make_two_column_frame())
    with ops.stage(name="push") as s:
        with s.pattern(series=ops.timeSeries.Linear()) as p:
            p.load(node=2, forces=(50.0, 0.0, 0.0))
        s.analysis(**_full_chain(ops))
        s.run(n_increments=1)
    rec = _emit_recording(ops)              # must not raise
    assert [c[0] for c in rec.calls].count("pattern_open") == 1


def test_global_pattern_without_stages_is_fine() -> None:
    ops = _frame_ops(make_two_column_frame())
    with ops.pattern.Plain(series=ops.timeSeries.Linear()) as p:
        p.load(node=2, forces=(50.0, 0.0, 0.0))
    rec = _emit_recording(ops)              # must not raise
    assert "stage_open" not in [c[0] for c in rec.calls]


def test_uniform_excitation_global_plus_stage_raises() -> None:
    """The guard catches ANY global pattern class, not just Plain."""
    ops = _frame_ops(make_two_column_frame())
    ops.pattern.UniformExcitation(direction=1, series=ops.timeSeries.Linear())
    _add_stage(ops, "shake")
    with pytest.raises(BridgeError) as exc:
        ops.build().emit(RecordingEmitter())
    assert "UniformExcitation" in str(exc.value)


# ---------------------------------------------------------------------------
# 2. WarnUnconsumedModelLoads (ADR 0051 §7)
# ---------------------------------------------------------------------------


def test_unconsumed_load_case_warns() -> None:
    from apeGmsh._kernel.records._loads import NodalLoadRecord

    fem = make_two_column_frame()
    fem.nodes.loads = _loads([  # type: ignore[attr-defined]
        NodalLoadRecord(node_id=2, force_xyz=(10.0, 0.0, 0.0), pattern="dead"),
    ])
    ops = _frame_ops(fem)
    with pytest.warns(WarnUnconsumedModelLoads, match="'dead'"):
        ops.build().emit(RecordingEmitter())


def test_imported_load_case_is_silent() -> None:
    from apeGmsh._kernel.records._loads import NodalLoadRecord

    fem = make_two_column_frame()
    fem.nodes.loads = _loads([  # type: ignore[attr-defined]
        NodalLoadRecord(node_id=2, force_xyz=(10.0, 0.0, 0.0), pattern="dead"),
    ])
    ops = _frame_ops(fem)
    with ops.pattern.Plain(series=ops.timeSeries.Linear()) as p:
        p.from_model("dead")
    _emit_asserting_no_unconsumed_warning(ops)


def test_imported_via_stage_pattern_is_silent() -> None:
    from apeGmsh._kernel.records._loads import NodalLoadRecord

    fem = make_two_column_frame()
    fem.nodes.loads = _loads([  # type: ignore[attr-defined]
        NodalLoadRecord(node_id=2, force_xyz=(10.0, 0.0, 0.0), pattern="dead"),
    ])
    ops = _frame_ops(fem)
    with ops.stage(name="push") as s:
        with s.pattern(series=ops.timeSeries.Linear()) as p:
            p.from_model("dead")
        s.analysis(**_full_chain(ops))
        s.run(n_increments=1)
    _emit_asserting_no_unconsumed_warning(ops)


def test_ignore_model_loads_silences_warning() -> None:
    from apeGmsh._kernel.records._loads import NodalLoadRecord

    fem = make_two_column_frame()
    fem.nodes.loads = _loads([  # type: ignore[attr-defined]
        NodalLoadRecord(node_id=2, force_xyz=(10.0, 0.0, 0.0), pattern="seismic"),
    ])
    ops = _frame_ops(fem)
    ops.ignore_model_loads("seismic")
    _emit_asserting_no_unconsumed_warning(ops)


def test_prescribed_sp_case_warns_homogeneous_does_not() -> None:
    """A prescribed (non-homogeneous) displacement case is a declared
    case; a homogeneous fix (bc) is NOT a case and never warns."""
    from apeGmsh._kernel.records._loads import SPRecord

    fem = make_two_column_frame()
    fem.nodes.sp = _sps([  # type: ignore[attr-defined]
        SPRecord(node_id=2, dof=1, value=0.01,
                 is_homogeneous=False, pattern="settle"),
        SPRecord(node_id=4, dof=2, value=0.0,
                 is_homogeneous=True, pattern="anchor"),
    ])
    ops = _frame_ops(fem)
    with pytest.warns(WarnUnconsumedModelLoads) as rec:
        ops.build().emit(RecordingEmitter())
    msgs = " ".join(str(w.message) for w in rec)
    assert "'settle'" in msgs        # prescribed -> a case -> warns
    assert "'anchor'" not in msgs    # homogeneous bc -> not a case


def test_multiple_unconsumed_cases_warn_one_each() -> None:
    from apeGmsh._kernel.records._loads import NodalLoadRecord

    fem = make_two_column_frame()
    fem.nodes.loads = _loads([  # type: ignore[attr-defined]
        NodalLoadRecord(node_id=2, force_xyz=(10.0, 0.0, 0.0), pattern="dead"),
        NodalLoadRecord(node_id=4, force_xyz=(0.0, 5.0, 0.0), pattern="live"),
    ])
    ops = _frame_ops(fem)
    with pytest.warns(WarnUnconsumedModelLoads) as rec:
        ops.build().emit(RecordingEmitter())
    cases = {str(w.message).split("'")[1] for w in rec
             if isinstance(w.message, WarnUnconsumedModelLoads)}
    assert cases == {"dead", "live"}


def test_partially_imported_only_warns_the_unconsumed_case() -> None:
    from apeGmsh._kernel.records._loads import NodalLoadRecord

    fem = make_two_column_frame()
    fem.nodes.loads = _loads([  # type: ignore[attr-defined]
        NodalLoadRecord(node_id=2, force_xyz=(10.0, 0.0, 0.0), pattern="dead"),
        NodalLoadRecord(node_id=4, force_xyz=(0.0, 5.0, 0.0), pattern="live"),
    ])
    ops = _frame_ops(fem)
    with ops.pattern.Plain(series=ops.timeSeries.Linear()) as p:
        p.from_model("dead")          # imports "dead", leaves "live"
    with pytest.warns(WarnUnconsumedModelLoads) as rec:
        ops.build().emit(RecordingEmitter())
    msgs = " ".join(str(w.message) for w in rec)
    assert "'live'" in msgs
    assert "'dead'" not in msgs


def test_no_loads_declared_is_silent() -> None:
    ops = _frame_ops(make_two_column_frame())
    with ops.pattern.Plain(series=ops.timeSeries.Linear()) as p:
        p.load(node=2, forces=(50.0, 0.0, 0.0))
    _emit_asserting_no_unconsumed_warning(ops)


# ---------------------------------------------------------------------------
# 3. ops.ignore_model_loads validation
# ---------------------------------------------------------------------------


def test_ignore_model_loads_rejects_empty() -> None:
    ops = _frame_ops(make_two_column_frame())
    with pytest.raises(ValueError, match="non-empty"):
        ops.ignore_model_loads("")


def test_ignore_model_loads_is_idempotent() -> None:
    ops = _frame_ops(make_two_column_frame())
    ops.ignore_model_loads("dead")
    ops.ignore_model_loads("dead")
    assert ops._ignored_model_load_cases == {"dead"}
