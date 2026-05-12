"""Integration tests for ``ops.recorder.declare(...)`` end-to-end emit.

Phase 9 commit 3a wires the bridge to:

1. Construct a :class:`RecorderDeclaration` from the namespace method,
   capturing the bridge's ``ndm``/``ndf`` (D8) and expanding canonical
   shorthand at declaration time.
2. Fan out the declaration to one ``emitter.recorder(...)`` call per
   ``(ops_token, target_set)`` group at emit time via
   :func:`emit_recorder_spec`.

These tests cover the ``"nodes"`` category end-to-end through
:class:`RecordingEmitter`. Other categories raise
``NotImplementedError`` in commit 3a (covered by separate stub tests).

Equivalence test: declaring ``ops.recorder.declare(nodes="displacement",
pg="Top")`` produces the same nodal recorder vocabulary as
manually emitting ``ops.recorder.Node(file=..., response="disp",
nodes=(2,), dofs=(1, 2, 3))`` — modulo file path naming, the OpenSees
``recorder Node`` shape is equivalent.
"""
from __future__ import annotations

from typing import cast

import pytest

from apeGmsh.opensees import apeSees
from apeGmsh.opensees.emitter.recording import RecordingEmitter
from apeGmsh.opensees.recorder import (
    RecorderDeclaration,
    RecorderRecord,
)

from tests.opensees.fixtures.fem_stub import make_two_node_beam


# ---------------------------------------------------------------------------
# Namespace declare() — registration + shorthand expansion + D8 binding
# ---------------------------------------------------------------------------


class TestDeclareRegistration:
    def test_declare_returns_RecorderDeclaration(self) -> None:
        fem = make_two_node_beam()
        ops = apeSees(cast("object", fem))
        ops.model(ndm=3, ndf=6)
        decl = ops.recorder.declare(nodes="displacement", pg="Top")
        assert isinstance(decl, RecorderDeclaration)

    def test_declare_registers_on_bridge(self) -> None:
        fem = make_two_node_beam()
        ops = apeSees(cast("object", fem))
        ops.model(ndm=3, ndf=6)
        decl = ops.recorder.declare(nodes=("displacement_x",), pg="Top")
        # The bridge holds the declaration with an allocated tag
        assert ops.tag_for(decl) is not None

    def test_declare_captures_bridge_ndm_ndf(self) -> None:
        # Phase 9 D8: bridge state is the source of truth for ndm/ndf
        fem = make_two_node_beam()
        ops = apeSees(cast("object", fem))
        ops.model(ndm=2, ndf=3)
        decl = ops.recorder.declare(nodes="displacement", pg="Top")
        assert decl.ndm == 2
        assert decl.ndf == 3

    def test_declare_expands_shorthand_immediately(self) -> None:
        # "displacement" shorthand expands to per-axis canonicals at
        # declaration time, clipped by bridge's ndm.
        fem = make_two_node_beam()
        ops = apeSees(cast("object", fem))
        ops.model(ndm=3, ndf=6)
        decl = ops.recorder.declare(nodes="displacement", pg="Top")
        assert decl.records[0].components == (
            "displacement_x", "displacement_y", "displacement_z",
        )

    def test_declare_expands_shorthand_clipped_to_ndm_2d(self) -> None:
        fem = make_two_node_beam()
        ops = apeSees(cast("object", fem))
        ops.model(ndm=2, ndf=3)
        decl = ops.recorder.declare(nodes="displacement", pg="Top")
        # 2D clips to (x, y) only
        assert decl.records[0].components == (
            "displacement_x", "displacement_y",
        )

    def test_declare_accepts_canonical_tuple(self) -> None:
        fem = make_two_node_beam()
        ops = apeSees(cast("object", fem))
        ops.model(ndm=3, ndf=6)
        decl = ops.recorder.declare(
            nodes=("displacement_x", "reaction_force_y"),
            pg="Top",
        )
        assert decl.records[0].components == (
            "displacement_x", "reaction_force_y",
        )

    def test_declare_without_model_raises(self) -> None:
        fem = make_two_node_beam()
        ops = apeSees(cast("object", fem))
        # No ops.model() call → declare should raise
        with pytest.raises(RuntimeError, match="ops.model"):
            ops.recorder.declare(nodes="displacement", pg="Top")

    def test_declare_named(self) -> None:
        fem = make_two_node_beam()
        ops = apeSees(cast("object", fem))
        ops.model(ndm=3, ndf=6)
        decl = ops.recorder.declare(
            nodes="displacement", pg="Top", name="roof_kinematics",
        )
        assert decl.name == "roof_kinematics"


# ---------------------------------------------------------------------------
# End-to-end emit through RecordingEmitter
# ---------------------------------------------------------------------------


class TestDeclareEmit:
    def test_nodes_pg_emit_produces_one_recorder_call(self) -> None:
        """A single 'displacement' declaration on a 3D model produces
        one ``recorder Node ... -dof 1 2 3 disp`` call."""
        fem = make_two_node_beam()
        ops = apeSees(cast("object", fem))
        ops.model(ndm=3, ndf=6)
        ops.recorder.declare(
            nodes="displacement", pg="Top", dt=0.01, name="run1",
        )

        bm = ops.build()
        rec = RecordingEmitter()
        bm.emit(rec)

        recorder_calls = [c for c in rec.calls if c[0] == "recorder"]
        assert len(recorder_calls) == 1, (
            f"expected 1 recorder call, got {len(recorder_calls)}: "
            f"{recorder_calls}"
        )

        name, args, _ = recorder_calls[0]
        assert name == "recorder"
        assert args[0] == "Node"
        # Args: "-file", <path>, "-dT", 0.01, "-time", "-node", 2,
        #       "-dof", 1, 2, 3, "disp"
        assert "-file" in args
        assert "-dT" in args
        # dt was 0.01
        dt_idx = args.index("-dT")
        assert args[dt_idx + 1] == 0.01
        assert "-time" in args
        assert "-node" in args
        node_idx = args.index("-node")
        # PG "Top" = node 2
        assert args[node_idx + 1] == 2
        assert "-dof" in args
        dof_idx = args.index("-dof")
        # Three DOFs (1, 2, 3) for displacement in 3D
        assert args[dof_idx + 1 : dof_idx + 4] == (1, 2, 3)
        # Last positional arg is the ops token
        assert args[-1] == "disp"

    def test_nodes_2d_emit_clips_to_two_dofs(self) -> None:
        fem = make_two_node_beam()
        ops = apeSees(cast("object", fem))
        ops.model(ndm=2, ndf=3)
        ops.recorder.declare(nodes="displacement", pg="Top")

        bm = ops.build()
        rec = RecordingEmitter()
        bm.emit(rec)

        recorder_calls = [c for c in rec.calls if c[0] == "recorder"]
        assert len(recorder_calls) == 1
        _, args, _ = recorder_calls[0]
        dof_idx = args.index("-dof")
        # 2D clips to DOFs (1, 2) — no z displacement
        assert args[dof_idx + 1 : dof_idx + 3] == (1, 2)

    def test_two_token_components_emit_two_calls(self) -> None:
        """``displacement_x + reaction_force_y`` route through different
        ops tokens (disp vs reaction) → two recorder calls."""
        fem = make_two_node_beam()
        ops = apeSees(cast("object", fem))
        ops.model(ndm=3, ndf=6)
        ops.recorder.declare(
            nodes=("displacement_x", "reaction_force_y"),
            pg="Top",
        )

        bm = ops.build()
        rec = RecordingEmitter()
        bm.emit(rec)

        recorder_calls = [c for c in rec.calls if c[0] == "recorder"]
        assert len(recorder_calls) == 2

        ops_tokens = sorted(args[-1] for _, args, _ in recorder_calls)
        assert ops_tokens == ["disp", "reaction"]

    def test_same_token_components_collapse_to_one_call(self) -> None:
        """``displacement_x + displacement_y`` share the 'disp' token →
        one recorder call with two -dofs."""
        fem = make_two_node_beam()
        ops = apeSees(cast("object", fem))
        ops.model(ndm=3, ndf=6)
        ops.recorder.declare(
            nodes=("displacement_x", "displacement_y"),
            pg="Top",
        )

        bm = ops.build()
        rec = RecordingEmitter()
        bm.emit(rec)

        recorder_calls = [c for c in rec.calls if c[0] == "recorder"]
        assert len(recorder_calls) == 1
        _, args, _ = recorder_calls[0]
        assert args[-1] == "disp"
        dof_idx = args.index("-dof")
        assert args[dof_idx + 1 : dof_idx + 3] == (1, 2)

    def test_ids_selector_emit(self) -> None:
        fem = make_two_node_beam()
        ops = apeSees(cast("object", fem))
        ops.model(ndm=3, ndf=6)
        # Explicit IDs instead of pg=
        ops.recorder.declare(nodes="displacement", ids=(1, 2))

        bm = ops.build()
        rec = RecordingEmitter()
        bm.emit(rec)

        recorder_calls = [c for c in rec.calls if c[0] == "recorder"]
        assert len(recorder_calls) == 1
        _, args, _ = recorder_calls[0]
        node_idx = args.index("-node")
        assert args[node_idx + 1 : node_idx + 3] == (1, 2)


# ---------------------------------------------------------------------------
# Deferred categories (3b+) raise descriptive NotImplementedError
# ---------------------------------------------------------------------------


class TestDeclareDeferredCategories:
    def test_element_record_emit_raises(self) -> None:
        # Constructing the record bypasses the namespace
        # (which only exposes nodes= in 3a). This proves the
        # build.py dispatch handles unsupported categories
        # gracefully with a useful error.
        fem = make_two_node_beam()
        ops = apeSees(cast("object", fem))
        ops.model(ndm=3, ndf=6)

        decl = RecorderDeclaration(
            records=(
                RecorderRecord(
                    category="elements",
                    components=("nodal_resisting_force_x",),
                    ids=(1,),
                ),
            ),
        )
        ops.register(decl)

        bm = ops.build()
        rec = RecordingEmitter()
        with pytest.raises(NotImplementedError, match="commit 3b"):
            bm.emit(rec)

    def test_fiber_record_emit_raises_with_domain_capture_hint(self) -> None:
        fem = make_two_node_beam()
        ops = apeSees(cast("object", fem))
        ops.model(ndm=3, ndf=6)

        decl = RecorderDeclaration(
            records=(
                RecorderRecord(
                    category="fibers",
                    components=("fiber_stress",),
                    ids=(1,),
                ),
            ),
        )
        ops.register(decl)

        bm = ops.build()
        rec = RecordingEmitter()
        with pytest.raises(NotImplementedError, match="DomainCapture"):
            bm.emit(rec)
