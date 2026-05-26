"""Tag-collision verifier — ADR 0038 §"Tag-collision verifier".

A pure-Python primitive that asserts five properties on a proposed
compose merge **after** the tag-rewrite pass and **before** the
merged records are committed to the host broker:

1. No imported tag lands outside its module's reservation window
   (i.e., into the host's tag range or into a sibling's range).
2. No two modules' reservation ranges overlap.
3. Every constraint reference resolves inside the owning module's
   reservation window (cross-module references are forbidden in v1).
4. No physical-group name collides after `{label}.` namespacing
   with an already-existing host PG.
5. Source tag span fits within the configured reservation size
   (only fires under an explicit ``compose_size_per_module=N``
   override smaller than the source's actual span).

Checks 1-4 raise :class:`PartTagCollisionError` or
:class:`ComposeInvariantError` (check 3 specifically); check 5
raises :class:`ComposeCapacityError`.  All five fail-loud at
compose time — silent corruption of the host broker is the worst
outcome we are avoiding.

The verifier operates on **pure Python data**: synthetic test
inputs construct ``ReservationRecord`` and ``ImportedRecords``
instances directly without touching gmsh, openseespy, or any
network-side broker.  This decouples the verifier from
implementation churn in the actual record dataclasses and keeps
the test surface fast.

ADR 0038 §"Tag-collision verifier" pins the contract.  The
verifier is reused beyond compose: any future operation that
merges records into a shared tag space (e.g., session merging in
v2) should call this primitive too.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from ._compose_errors import (
    ComposeCapacityError,
    ComposeInvariantError,
    PartTagCollisionError,
)


# ---------------------------------------------------------------------------
# Data shapes the verifier consumes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReservationRecord:
    """One module's reserved tag window in the host's tag namespace.

    Parameters
    ----------
    label : str
        Module label (the value passed to ``g.compose(label=...)``).
    base : int
        Lower bound of the reserved window (inclusive).
    size : int
        Window length.  Must be strictly positive.

    The reserved range is the half-open interval ``[base, base+size)``.
    Per ADR 0038's auto-sizing formula, ``base`` and ``size`` are
    both rounded up to the ``RESERVATION_GRANULARITY`` of the
    ``Compose`` facade (default ``1_000_000``).
    """

    label: str
    base: int
    size: int

    def __post_init__(self) -> None:
        if self.size <= 0:
            raise ValueError(
                f"ReservationRecord {self.label!r}: size must be > 0 "
                f"(got {self.size})."
            )
        if self.base < 0:
            raise ValueError(
                f"ReservationRecord {self.label!r}: base must be >= 0 "
                f"(got {self.base})."
            )

    @property
    def upper(self) -> int:
        """Exclusive upper bound of the reserved window."""
        return self.base + self.size

    def contains(self, tag: int) -> bool:
        """Return ``True`` when ``tag`` is inside the reservation."""
        return self.base <= tag < self.upper


@dataclass(frozen=True)
class ConstraintReference:
    """One tag-reference field on an imported constraint record.

    Parameters
    ----------
    kind : str
        The constraint record's kind (e.g. ``"embedded"``,
        ``"equalDOF"``, ``"rigid_link"``).  Used for error
        messages only.
    field_name : str
        The dataclass field that holds the tag (e.g.
        ``"master_node"``, ``"host_element_tag"``,
        ``"slave_nodes[3]"``).  Used for error messages only.
    tag : int
        The (already-rewritten) tag value the field points at.
    """

    kind: str
    field_name: str
    tag: int


@dataclass(frozen=True)
class ImportedRecords:
    """A module's contribution to the host broker after rewrite.

    Parameters
    ----------
    tags : Sequence[int]
        Every tag the module imports — nodes, elements, materials,
        sections, integration rules, etc.  All values are
        post-rewrite (offset already applied).
    pg_names : Sequence[str]
        The module's local physical-group names, BEFORE the
        ``{label}.`` namespace prefix is applied.  The verifier
        applies the prefix itself when checking against
        ``host_pg_names`` so callers don't have to pre-stringify.
    constraint_refs : Sequence[ConstraintReference]
        Every tag-reference field on every imported constraint
        record, post-rewrite.  See ADR 0038 §"Tag-reference
        rewrite checklist" for the full set of fields.
    source_span : int or None
        Source's ``(max_tag - min_tag + 1)``.  Required for
        check 5; ``None`` skips check 5 (caller did not pass
        ``compose_size_per_module=N`` override).
    """

    tags: Sequence[int] = field(default_factory=tuple)
    pg_names: Sequence[str] = field(default_factory=tuple)
    constraint_refs: Sequence[ConstraintReference] = field(
        default_factory=tuple
    )
    source_span: int | None = None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def tag_collision_verify(
    *,
    reservations: Sequence[ReservationRecord],
    host_pg_names: Iterable[str],
    module_imports: Mapping[str, ImportedRecords],
    compose_size_per_module: int | None = None,
) -> None:
    """Run the five ADR 0038 verifier checks on a proposed merge.

    Parameters
    ----------
    reservations : Sequence[ReservationRecord]
        One reservation per module the host has accepted.  Must
        include a record for every key in ``module_imports``.
    host_pg_names : Iterable[str]
        Every PG name currently in the host (before merge).
    module_imports : Mapping[str, ImportedRecords]
        Each module's post-rewrite contribution, keyed by module
        label.  Empty mapping is a valid no-op input — checks 1,
        2, 3, 5 trivially pass; check 4 still runs against
        ``reservations`` (but with no imports it cannot fire).
    compose_size_per_module : int or None
        Explicit reservation-size cap passed by the caller.
        ``None`` means "auto-sized" — check 5 is skipped because
        the auto-sizing scheme guarantees fit by construction.

    Raises
    ------
    PartTagCollisionError
        Check 1 (imported tag outside reservation), check 2
        (overlapping reservations), or check 4 (PG-name collision
        after namespacing) failed.
    ComposeInvariantError
        Check 3 (cross-module constraint reference) failed.
    ComposeCapacityError
        Check 5 (source span exceeds explicit cap) failed.

    Notes
    -----
    The checks run in a fixed order — 2, then 5, then 1, 3, 4 —
    chosen so structural failures (overlapping reservations,
    over-capacity reservations) are surfaced before content
    failures (tags pointing at the wrong reservation).  Each
    check is implemented as a single-purpose helper for direct
    unit-test addressability.
    """
    res_by_label: dict[str, ReservationRecord] = {
        r.label: r for r in reservations
    }

    # Structural checks first — these don't depend on the imports.
    _check2_reservations_disjoint(reservations)

    if compose_size_per_module is not None:
        _check5_source_span_fits(
            module_imports=module_imports,
            cap=compose_size_per_module,
        )

    # Content checks — require both reservations and imports.
    host_pg_set = set(host_pg_names)
    for mod_label, records in module_imports.items():
        if mod_label not in res_by_label:
            raise PartTagCollisionError(
                f"module {mod_label!r}: no reservation record "
                f"provided to the verifier (have: "
                f"{sorted(res_by_label)!r})."
            )
        reservation = res_by_label[mod_label]
        _check1_imported_tags_in_reservation(mod_label, records, reservation)
        _check3_constraint_refs_in_reservation(
            mod_label, records, reservation
        )
        _check4_pg_namespace_disjoint(mod_label, records, host_pg_set)


# ---------------------------------------------------------------------------
# Per-check helpers — each addressable individually from tests.
# ---------------------------------------------------------------------------


def _check1_imported_tags_in_reservation(
    mod_label: str,
    records: ImportedRecords,
    reservation: ReservationRecord,
) -> None:
    """Check 1 — every imported tag lands inside the reservation.

    A tag outside the reservation means either (a) the offset
    rewrite missed a field (cover-set bug — see ADR 0038
    §"Tag-reference rewrite checklist") or (b) the source carried
    a cross-module reference that the rewriter could not resolve.
    Either way: fail loud.
    """
    for tag in records.tags:
        if not reservation.contains(tag):
            raise PartTagCollisionError(
                f"module {mod_label!r}: imported tag {tag} falls "
                f"outside reservation [{reservation.base}, "
                f"{reservation.upper}). Likely cause: tag-rewrite "
                f"cover-set drift (ADR 0038)."
            )


def _check2_reservations_disjoint(
    reservations: Sequence[ReservationRecord],
) -> None:
    """Check 2 — no two reservations overlap.

    The auto-sizing formula guarantees disjointness by
    construction, but the verifier double-checks the actual
    extents in case the offset formula is ever changed.  This is
    an O(n^2) sweep — fine for the realistic module count
    (single digits to low tens in v1).
    """
    res = list(reservations)
    for i, a in enumerate(res):
        for b in res[i + 1:]:
            # Half-open intervals [a.base, a.upper) and
            # [b.base, b.upper) overlap iff
            # a.base < b.upper AND b.base < a.upper.
            if a.base < b.upper and b.base < a.upper:
                raise PartTagCollisionError(
                    f"reservation overlap: module {a.label!r} "
                    f"[{a.base}, {a.upper}) overlaps module "
                    f"{b.label!r} [{b.base}, {b.upper})."
                )


def _check3_constraint_refs_in_reservation(
    mod_label: str,
    records: ImportedRecords,
    reservation: ReservationRecord,
) -> None:
    """Check 3 — every constraint reference resolves inside the
    owning module's reservation window.

    Cross-module references between sibling composes are
    forbidden in v1 (ADR 0038 INV-2).  A reference outside the
    reservation means either the rewrite missed a field
    (cover-set bug) or the module's source H5 carried such a
    cross-module reference.
    """
    for ref in records.constraint_refs:
        if not reservation.contains(ref.tag):
            raise ComposeInvariantError(
                f"module {mod_label!r}: constraint {ref.kind!r} "
                f"field {ref.field_name!r} references tag "
                f"{ref.tag} outside reservation "
                f"[{reservation.base}, {reservation.upper}). "
                f"Cross-module references are forbidden in v1 "
                f"(ADR 0038 INV-2)."
            )


def _check4_pg_namespace_disjoint(
    mod_label: str,
    records: ImportedRecords,
    host_pg_names: set[str],
) -> None:
    """Check 4 — no PG-name collision after namespacing.

    The namespace prefix prevents this by construction in the
    typical case.  Separator alternation (the `.` <-> `/` rule,
    ADR 0038 INV-3) eliminates the cross-module-PG-collision
    class structurally.  Check 4 catches only the rare case
    where a host author literally named a PG with a
    ``{compose_label}.`` prefix matching an actual compose label.
    """
    for pg in records.pg_names:
        prefixed = f"{mod_label}.{pg}"
        if prefixed in host_pg_names:
            raise PartTagCollisionError(
                f"module {mod_label!r}: namespaced PG name "
                f"{prefixed!r} collides with an existing host "
                f"physical group. Rename the host PG or the "
                f"compose label to resolve."
            )


def _check5_source_span_fits(
    module_imports: Mapping[str, ImportedRecords],
    cap: int,
) -> None:
    """Check 5 — source span fits the explicit reservation cap.

    Only runs when the caller passed
    ``compose_size_per_module=N``.  Without an override, the
    auto-sizing scheme computes ``size`` from the source's actual
    span and check 5 is correct by construction.
    """
    for mod_label, records in module_imports.items():
        if records.source_span is None:
            # Caller did not declare a source span for this
            # module — skip the comparison for it.  The
            # corresponding reservation must still fit the
            # imports, which check 1 enforces.
            continue
        if records.source_span > cap:
            raise ComposeCapacityError(
                f"module {mod_label!r}: source tag span "
                f"{records.source_span} exceeds configured "
                f"compose_size_per_module={cap}. Increase the "
                f"override or remove it to let the auto-sizing "
                f"scheme compute the window size."
            )
