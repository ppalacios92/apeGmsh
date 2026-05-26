"""Unit tests for the ADR 0038 tag-collision verifier.

These tests construct synthetic ``ReservationRecord`` /
``ImportedRecords`` inputs directly — the verifier is a pure
Python primitive that operates on data, so we exercise every
check in isolation without spinning up a full apeGmsh session,
gmsh, or openseespy.

ADR 0038 §"Tag-collision verifier" is the contract under test.
"""
from __future__ import annotations

import pytest

from apeGmsh.core._compose_errors import (
    ComposeCapacityError,
    ComposeInvariantError,
    PartTagCollisionError,
)
from apeGmsh.core._tag_collision_verifier import (
    ConstraintReference,
    ImportedRecords,
    ReservationRecord,
    tag_collision_verify,
)


# ---------------------------------------------------------------------------
# Check 1 — every imported tag lives inside the reservation window.
# ---------------------------------------------------------------------------


def test_check1_imported_tag_in_host_range_raises():
    """A tag below the reservation base falls in the host's range
    and must fail loud with PartTagCollisionError naming the tag.
    """
    res = ReservationRecord(label="conn_a", base=1_000, size=1_000)
    imports = {
        "conn_a": ImportedRecords(tags=(500,)),  # 500 < 1000 -> host range
    }
    with pytest.raises(PartTagCollisionError, match=r"\b500\b"):
        tag_collision_verify(
            reservations=(res,),
            host_pg_names=(),
            module_imports=imports,
        )


def test_check1_passes_when_imported_tag_in_reservation():
    """Tags strictly inside [base, base+size) pass."""
    res = ReservationRecord(label="conn_a", base=1_000, size=1_000)
    imports = {
        "conn_a": ImportedRecords(tags=(1_000, 1_500, 1_999)),
    }
    tag_collision_verify(
        reservations=(res,),
        host_pg_names=(),
        module_imports=imports,
    )


# ---------------------------------------------------------------------------
# Check 2 — no two reservations may overlap.
# ---------------------------------------------------------------------------


def test_check2_overlapping_reservations_raises():
    """Two reservation windows that share any tag must fail loud."""
    a = ReservationRecord(label="conn_a", base=1_000, size=1_000)
    b = ReservationRecord(label="conn_b", base=1_500, size=1_000)
    with pytest.raises(PartTagCollisionError, match="overlap"):
        tag_collision_verify(
            reservations=(a, b),
            host_pg_names=(),
            module_imports={},
        )


def test_check2_passes_when_disjoint():
    """Adjacent but non-overlapping windows are legal — the upper
    bound is exclusive."""
    a = ReservationRecord(label="conn_a", base=1_000, size=1_000)
    b = ReservationRecord(label="conn_b", base=2_000, size=1_000)
    tag_collision_verify(
        reservations=(a, b),
        host_pg_names=(),
        module_imports={},
    )


# ---------------------------------------------------------------------------
# Check 3 — constraint references must resolve inside the owner.
# ---------------------------------------------------------------------------


def test_check3_cross_module_reference_raises():
    """A constraint in module A that references a tag inside
    module B's reservation is a forbidden cross-module reference
    in v1 — must raise ComposeInvariantError naming the bad tag.
    """
    a = ReservationRecord(label="conn_a", base=1_000, size=1_000)
    b = ReservationRecord(label="conn_b", base=2_000, size=1_000)
    imports = {
        "conn_a": ImportedRecords(
            tags=(1_000, 1_100),
            constraint_refs=(
                ConstraintReference(
                    kind="embedded",
                    field_name="host_element_tag",
                    tag=2_500,  # lives in conn_b's range
                ),
            ),
        ),
    }
    with pytest.raises(ComposeInvariantError, match=r"2500|conn_a"):
        tag_collision_verify(
            reservations=(a, b),
            host_pg_names=(),
            module_imports=imports,
        )


def test_check3_passes_when_references_in_owning_module():
    """Constraint references that fall inside the owning
    module's reservation are the canonical happy path."""
    a = ReservationRecord(label="conn_a", base=1_000, size=1_000)
    imports = {
        "conn_a": ImportedRecords(
            tags=(1_000, 1_100, 1_500),
            constraint_refs=(
                ConstraintReference(
                    kind="equalDOF",
                    field_name="master_node",
                    tag=1_100,
                ),
                ConstraintReference(
                    kind="equalDOF",
                    field_name="slave_nodes[0]",
                    tag=1_500,
                ),
            ),
        ),
    }
    tag_collision_verify(
        reservations=(a,),
        host_pg_names=(),
        module_imports=imports,
    )


# ---------------------------------------------------------------------------
# Check 4 — namespaced PG names must not collide with host PGs.
# ---------------------------------------------------------------------------


def test_check4_pg_name_collision_raises():
    """A host that already has ``conn1.face_top`` cannot accept a
    module composed under ``label="conn1"`` carrying a local PG
    named ``face_top`` — the rewrite would produce a duplicate
    namespaced name.
    """
    res = ReservationRecord(label="conn1", base=1_000, size=1_000)
    imports = {
        "conn1": ImportedRecords(
            pg_names=("face_top",),
        ),
    }
    with pytest.raises(PartTagCollisionError, match="conn1.face_top"):
        tag_collision_verify(
            reservations=(res,),
            host_pg_names=("conn1.face_top",),
            module_imports=imports,
        )


def test_check4_passes_when_namespaces_disjoint():
    """A host PG named ``face_top`` does not collide with a
    composed PG that ends up as ``conn1.face_top`` after the
    namespace prefix is applied."""
    res = ReservationRecord(label="conn1", base=1_000, size=1_000)
    imports = {
        "conn1": ImportedRecords(
            pg_names=("face_top", "weld_zone"),
        ),
    }
    tag_collision_verify(
        reservations=(res,),
        host_pg_names=("face_top", "frame_beam_A"),
        module_imports=imports,
    )


# ---------------------------------------------------------------------------
# Check 5 — explicit ``compose_size_per_module=N`` cap fits.
# ---------------------------------------------------------------------------


def test_check5_source_span_exceeds_explicit_size_raises():
    """Passing ``compose_size_per_module=1000`` with a source
    that spans 1500 tags must raise ComposeCapacityError naming
    both numbers so the caller can widen or remove the cap."""
    res = ReservationRecord(label="conn_a", base=1_000, size=2_000)
    imports = {
        "conn_a": ImportedRecords(
            tags=(1_000, 1_500),
            source_span=1_500,
        ),
    }
    with pytest.raises(ComposeCapacityError, match=r"1500.*1000|1000.*1500"):
        tag_collision_verify(
            reservations=(res,),
            host_pg_names=(),
            module_imports=imports,
            compose_size_per_module=1_000,
        )


def test_check5_no_override_means_no_check5_fire():
    """Without an explicit ``compose_size_per_module``, the
    auto-sizing scheme guarantees fit by construction and
    check 5 is a no-op — even if ``source_span`` is recorded on
    the import records.
    """
    res = ReservationRecord(label="conn_a", base=1_000, size=1_000)
    imports = {
        "conn_a": ImportedRecords(
            tags=(1_000,),
            source_span=999_999_999,  # irrelevant without override
        ),
    }
    tag_collision_verify(
        reservations=(res,),
        host_pg_names=(),
        module_imports=imports,
    )


# ---------------------------------------------------------------------------
# Empty-input no-op — the safety-net path called by fragment_all.
# ---------------------------------------------------------------------------


def test_empty_module_imports_is_no_op():
    """An empty ``module_imports`` mapping with no reservations
    is the canonical no-op input — every check trivially passes.
    This is what ``fragment_all`` calls today (per the stub
    wiring in _parts_fragmentation.py)."""
    tag_collision_verify(
        reservations=(),
        host_pg_names=("frame.beam_A", "frame.col_B"),
        module_imports={},
    )


def test_reservation_without_imports_runs_check2_only():
    """Reservations with no corresponding imports still get
    check 2 run on them — useful when modules have been
    reserved but their record streams haven't been merged yet.
    """
    a = ReservationRecord(label="conn_a", base=1_000, size=1_000)
    b = ReservationRecord(label="conn_b", base=2_000, size=1_000)
    tag_collision_verify(
        reservations=(a, b),
        host_pg_names=(),
        module_imports={},
    )


# ---------------------------------------------------------------------------
# Sanity: imports for an unreserved module fail loud.
# ---------------------------------------------------------------------------


def test_imports_without_reservation_raises():
    """If a caller forgets to register a reservation for a
    module that has imports, the verifier must catch it rather
    than silently skipping — that would mean check 1's range
    test never runs for those imports."""
    imports = {
        "conn_a": ImportedRecords(tags=(1_000,)),
    }
    with pytest.raises(PartTagCollisionError, match="no reservation"):
        tag_collision_verify(
            reservations=(),
            host_pg_names=(),
            module_imports=imports,
        )


# ---------------------------------------------------------------------------
# Regression: ReservationRecord input validation.
# ---------------------------------------------------------------------------


def test_reservation_record_rejects_nonpositive_size():
    """``size`` must be strictly positive — a zero-length window
    cannot hold any tag."""
    with pytest.raises(ValueError, match="size must be > 0"):
        ReservationRecord(label="bad", base=0, size=0)


def test_reservation_record_rejects_negative_base():
    """``base`` must be non-negative — tag space starts at 0."""
    with pytest.raises(ValueError, match="base must be >= 0"):
        ReservationRecord(label="bad", base=-1, size=1_000)


# ---------------------------------------------------------------------------
# Regression: ``fragment_all`` still works with the no-op verifier
# stub call wired in (per ADR 0038 Phase 2 stub at
# _parts_fragmentation.py).  Two overlapping boxes -> 3 volumes,
# same as the existing test_fragment_all_two_parts test in
# tests/test_parts_fragmentation.py.  Re-checked here to catch a
# wiring regression near the verifier import.
# ---------------------------------------------------------------------------


def test_fragment_all_still_works_with_empty_module_imports(g):
    """The Phase 2 stub call inside ``fragment_all`` must be a
    pure no-op — exercising it through a real fragmentation
    operation confirms the import path and call site work and
    that the verifier does not perturb the existing behaviour."""
    import gmsh

    with g.parts.part("a"):
        g.model.geometry.add_box(0, 0, 0, 2, 1, 1)
    with g.parts.part("b"):
        g.model.geometry.add_box(1, 0, 0, 2, 1, 1)

    result = g.parts.fragment_all()
    vols = gmsh.model.getEntities(3)
    assert len(vols) == 3
    assert len(result) == 3
