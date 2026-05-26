"""apeGmsh.mesh._compose — Compose facade scaffold (Phase 3B.1 / ADR 0038).

The :class:`Compose` facade is a session-level entry point that lands the
shell of ADR 0038's ``g.compose(...)`` API: input validation, the
``compose_inspect`` / ``compose_list`` companion helpers, the
:class:`ComposedModule` handle, and the typed exception hierarchy.

The merge engine itself — tag-offset reservation, namespace prefix
sweep, record rewrite + verifier — is intentionally **deferred** to
Phase 3B.2.  Calling :meth:`Compose.compose` here raises
:class:`NotImplementedError` after the input gates pass; ``inspect`` and
``list`` are fully functional because they only read H5 metadata or walk
the current broker's ``fem.composed_from``.

Cross-references
----------------
* ADR 0038 §"g.compose() signature" — the entry-point contract.
* ADR 0038 §"Companion helpers (v1)" — inspect / list shape.
* ADR 0038 §"Tag-collision verifier" — the typed errors defined here.
* Phase 3A.1 substrate (PR #361):
  :class:`apeGmsh._kernel.records._compose.ComposeRecord` +
  :class:`apeGmsh._kernel.record_sets.ComposeSet` carry the provenance
  this facade will produce in Phase 3B.2 and inspects today.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .._kernel.records._compose import ComposeRecord

if TYPE_CHECKING:
    from .._core import apeGmsh
    from .FEMData import FEMData


# ---------------------------------------------------------------------------
# Exception hierarchy (ADR 0038 §"Tag-collision verifier")
# ---------------------------------------------------------------------------


class ComposeError(Exception):
    """Base for all compose-time errors per ADR 0038."""


class ComposeLabelError(ComposeError, ValueError):
    """Invalid ``label=`` per ADR 0038 §"g.compose() signature" line 94.

    Raised when ``label`` is empty, carries the namespace separator
    ``.``, the depth-boundary separator ``/``, whitespace, or starts /
    ends with ``_`` (the reserved-prefix convention).
    """


class ComposeAnchorError(ComposeError, ValueError):
    """``anchor=`` combined with a non-zero ``translate=`` per ADR 0038
    §"g.compose() signature" line 104.

    ``anchor`` is sugar that resolves to a translate; the two are
    mutually exclusive."""


class ComposeCapacityError(ComposeError, ValueError):
    """Source span exceeds the configured reservation cap per ADR 0038
    §"Tag-collision verifier" check 5.

    Raised by the merge engine in Phase 3B.2 when an explicit
    ``compose_size_per_module=N`` is smaller than the source's actual
    tag span.  The exception type lives in 3B.1 so callers writing
    forward-compatible try/excepts can catch it today.
    """


class ComposeDepthExceededError(ComposeError, ValueError):
    """Nested-compose depth exceeds ``max_compose_depth`` per ADR 0038
    §"Namespace rule".

    Raised by the merge engine in Phase 3B.2; defined here so the
    typed-error surface for compose-time failures is complete.
    """


class ComposeNamespaceCollisionError(ComposeError, ValueError):
    """Post-rewrite PG-name collision per ADR 0038 §"Tag-collision
    verifier" check 4.

    Raised by the verifier in Phase 3B.2; defined here so callers can
    write forward-compatible exception handlers.
    """


class ComposeFilterWarning(UserWarning):
    """One-line warning per filtered-with-warning record kind per
    compose call per ADR 0038 §"Merge semantics".

    Emitted by the merge engine in Phase 3B.2 for the stages /
    time-series / load-patterns kinds.  Defined here so the warning
    class lives with its sibling errors.
    """


# ---------------------------------------------------------------------------
# ComposedModule — live handle to one composed source module
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComposedModule:
    """Live handle to one composed source module in the host session.

    Wraps a :class:`ComposeRecord` provenance entry plus an optional
    back-reference to the host :class:`FEMData` so the handle can later
    introspect the broker (PG inventory, label inventory, record counts
    contributed by this module).

    Phase 3B.1 ships the handle's identity surface (``label`` /
    ``source_path`` / ``translate`` / ``rotate`` / ``partition_rank``);
    the introspection methods (:meth:`pgs`, :meth:`labels`,
    :meth:`record_counts`) are stubbed pending the Phase 3B.2 merge
    engine that populates the ``module_label`` parallel datasets they
    walk.
    """

    record: "ComposeRecord"
    _fem: "FEMData | None" = field(default=None, repr=False, compare=False)

    # ── Identity passthroughs ───────────────────────────────────

    @property
    def label(self) -> str:
        """Namespace label assigned at compose time."""
        return self.record.label

    @property
    def source_path(self) -> str:
        """Path of the source ``model.h5`` that contributed this module."""
        return self.record.source_path

    @property
    def translate(self) -> tuple[float, float, float]:
        """XYZ translation applied at compose time."""
        return self.record.translate

    @property
    def rotate(self) -> tuple[float, float, float, float] | None:
        """Optional axis-angle rotation applied at compose time."""
        return self.record.rotate

    @property
    def partition_rank(self) -> int | None:
        """Layer-2 partition-rank hint per ADR 0038 §"Rank model"."""
        return self.record.partition_rank

    # ── Introspection (stubbed until Phase 3B.2) ────────────────

    def pgs(self) -> tuple[str, ...]:
        """PG names contributed by this module.

        Lands in Phase 3B.2 — needs the ``module_label`` parallel
        dataset populated by the merge engine.
        """
        raise NotImplementedError(
            "ComposedModule.pgs() needs the module_label parallel "
            "dataset populated by the merge engine; lands in Phase 3B.2."
        )

    def labels(self) -> tuple[str, ...]:
        """Label names contributed by this module.

        Lands in Phase 3B.2 — needs the ``module_label`` parallel
        dataset populated by the merge engine.
        """
        raise NotImplementedError(
            "ComposedModule.labels() needs the module_label parallel "
            "dataset populated by the merge engine; lands in Phase 3B.2."
        )

    def record_counts(self) -> dict[str, int]:
        """Per-record-kind counts contributed by this module.

        Lands in Phase 3B.2 — needs the ``module_label`` parallel
        dataset populated by the merge engine.
        """
        raise NotImplementedError(
            "ComposedModule.record_counts() needs the module_label "
            "parallel dataset populated by the merge engine; lands in "
            "Phase 3B.2."
        )


# ---------------------------------------------------------------------------
# Compose — session-level facade
# ---------------------------------------------------------------------------


class Compose:
    """Facade for compose-time model assembly per ADR 0038.

    Single per-session instance, exposed through the three session-level
    entry points :meth:`apeGmsh.compose`, :meth:`apeGmsh.compose_inspect`,
    and :meth:`apeGmsh.compose_list`.

    Phase 3B.1 (this PR) scaffolds the facade — input validation, the
    list / inspect helpers, exception types, the
    :data:`RESERVATION_GRANULARITY` knob, and the :class:`ComposedModule`
    handle.  The merge engine behind :meth:`compose` raises
    :class:`NotImplementedError` pending Phase 3B.2.
    """

    #: Reservation granularity for per-module tag windows per ADR 0038
    #: §"Tag-offset scheme — per-module auto-sizing".  Each compose call
    #: rounds the source's tag-span up to a multiple of this value when
    #: computing the host-side reservation.  Power-of-10 keeps the log
    #: messages human-readable; Phase 3B.2 uses it inside the merge
    #: engine.
    RESERVATION_GRANULARITY: int = 1_000_000

    def __init__(self, session: "apeGmsh") -> None:
        self._session = session

    # ── Public API ────────────────────────────────────────────────

    def compose(
        self,
        source: "str | Path",
        *,
        label: str,
        translate: tuple[float, float, float] = (0.0, 0.0, 0.0),
        rotate: tuple[float, float, float, float] | None = None,
        anchor: str | None = None,
        partition_rank: int | None = None,
        properties: "dict[str, Any] | None" = None,
        max_compose_depth: int = 3,
        compose_size_per_module: int | None = None,
    ) -> ComposedModule:
        """Merge a previously-saved apeGmsh model into the host session.

        Phase 3B.1 (this PR) validates inputs eagerly and raises
        :class:`NotImplementedError` before any H5 read or broker
        mutation; the merge engine ships in Phase 3B.2.

        Parameters
        ----------
        source : str | Path
            Path to the source ``model.h5`` (H5-only in v1 per ADR 0038
            §"g.compose() signature").
        label : str
            Namespace prefix assigned to every imported string-keyed
            record.  Required.  Must be non-empty, contain no ``.``,
            ``/`` or whitespace, and must not start or end with ``_``.
        translate, rotate : tuple
            Rigid-body placement of the module in the host's coordinate
            system.  ``rotate`` is axis-angle ``(x, y, z, theta)``.
        anchor : str | None
            PG-name sugar over ``translate``.  Mutually exclusive with a
            non-zero ``translate`` — see ADR 0038 §"g.compose() signature"
            line 104.
        partition_rank : int | None
            Layer-2 rank hint per ADR 0038 §"Rank model".  ``K >= 0``.
        properties : dict | None
            Free-form provenance dict round-tripped through
            ``/composed_from/{label}/properties`` on the host's next
            ``g.save()``.
        max_compose_depth : int, default 3
            Hard cap on nested-compose depth — raises
            :class:`ComposeDepthExceededError` from the verifier in
            Phase 3B.2.  No-op in 3B.1 (validation only; the engine
            stub fires first).
        compose_size_per_module : int | None
            Explicit reservation-size floor per ADR 0038 §"Tag-offset
            scheme".  ``None`` means "auto-size from the source's
            actual span".  Phase 3B.2 honours the override; 3B.1
            validates only ``> 0``.

        Returns
        -------
        ComposedModule
            Phase 3B.2 returns the live handle; in 3B.1 this method
            raises :class:`NotImplementedError` after validation.

        Raises
        ------
        ComposeLabelError
            ``label=`` violates the lexical rules.
        ComposeAnchorError
            ``anchor=`` combined with a non-zero ``translate=``.
        ValueError
            ``partition_rank < 0`` or ``compose_size_per_module <= 0``.
        NotImplementedError
            Always, after validation, until Phase 3B.2 wires the merge
            engine.
        """
        # Eager input validation — fail before any H5 read so misuse
        # surfaces at call time instead of half-way through the merge.
        self._validate_label(label)
        self._validate_translate_rotate_anchor(translate, anchor)
        self._validate_partition_rank(partition_rank)
        self._validate_compose_size(compose_size_per_module)
        # ``properties`` and ``max_compose_depth`` are exercised by the
        # Phase 3B.2 engine — no 3B.1 surface beyond accepting them.

        raise NotImplementedError(
            "Compose merge engine ships in Phase 3B.2; "
            "this PR (3B.1) scaffolds the facade only. "
            "Phase 3A.1 schema substrate (PR #361) is on main."
        )

    def compose_inspect(self, path: "str | Path") -> dict:
        """Read a module's H5 header without composing it.

        Returns a metadata-only summary — does NOT parse bulk record
        bodies.  ADR 0038 §"Companion helpers (v1)" line 121.

        Keys
        ----
        ``fem_hash`` : str
            ``snapshot_id`` from ``/meta``; empty string when absent.
        ``neutral_schema_version`` : str
            ``neutral_schema_version`` from ``/meta``; empty string
            when absent (e.g. very old files).
        ``tag_span_max`` : int
            ``tag_span_max`` from ``/meta``; ``0`` for pre-2.9.0 files
            that lacked the attribute.
        ``pg_inventory`` : tuple[str, ...]
            Sorted physical-group names.
        ``label_inventory`` : tuple[str, ...]
            Sorted label names.
        ``record_counts`` : dict[str, int]
            Counts for the major record kinds present on disk.
        ``composed_from`` : tuple[ComposeRecord, ...]
            ``ComposeRecord`` entries from ``/composed_from/`` (empty
            for uncomposed sources).
        ``properties`` : dict
            File-level properties slot.  ADR 0038 stores ``properties``
            per-module under each ``/composed_from/{label}/properties/``
            sub-group; the inspect-level entry is reserved for a future
            file-wide annotation surface and is ``{}`` today.
        """
        import h5py  # local import — keeps mesh package import-time light

        p = Path(path)
        with h5py.File(str(p), "r") as f:
            meta_attrs: dict[str, Any] = {}
            if "meta" in f:
                meta_attrs = dict(f["meta"].attrs)

            fem_hash = str(meta_attrs.get("snapshot_id", ""))
            neutral_schema_version = str(
                meta_attrs.get("neutral_schema_version", "")
            )
            tag_span_max = int(meta_attrs.get("tag_span_max", 0))

            pg_inventory = _read_named_group_inventory(f, "physical_groups")
            label_inventory = _read_named_group_inventory(f, "labels")
            record_counts = _read_record_counts(f)

            # ``_read_composed_from`` is the canonical reader for
            # ``/composed_from/`` and tolerates absence by returning ().
            from ._femdata_h5_io import _read_composed_from
            composed_from = _read_composed_from(
                f["composed_from"] if "composed_from" in f else None
            )

        return {
            "fem_hash": fem_hash,
            "neutral_schema_version": neutral_schema_version,
            "tag_span_max": tag_span_max,
            "pg_inventory": pg_inventory,
            "label_inventory": label_inventory,
            "record_counts": record_counts,
            "composed_from": composed_from,
            "properties": {},
        }

    def compose_list(self) -> tuple[ComposedModule, ...]:
        """Composed modules currently on the host session.

        Returns modules in compose-call order (the
        :class:`ComposeSet`'s ascending-label order, which matches the
        compose-order-independent canonicalisation of ADR 0038
        §"Lineage chain extension").  Empty tuple when no modules are
        composed or no FEM has been extracted yet.
        """
        fem = self._current_fem()
        if fem is None:
            return ()

        composed_from = getattr(fem, "composed_from", None)
        if not composed_from:
            return ()

        return tuple(
            ComposedModule(record=rec, _fem=fem) for rec in composed_from
        )

    # ── Defensive accessors ───────────────────────────────────────

    def _current_fem(self) -> "FEMData | None":
        """Best-effort fetch of the host session's current ``FEMData``.

        Returns ``None`` when no FEM has been extracted yet (e.g. the
        session was constructed but never ``begin()``-ed, or
        ``get_fem_data()`` would raise because gmsh has no mesh).
        Used by :meth:`compose_list` to gracefully degrade.
        """
        try:
            return self._session.mesh.queries.get_fem_data()
        except Exception:
            # Intentionally swallow — compose_list is read-only and
            # must not blow up when called pre-mesh.  Real errors
            # surface elsewhere.
            return None

    # ── Validators ────────────────────────────────────────────────

    @staticmethod
    def _validate_label(label: str) -> None:
        """Enforce ADR 0038 §"g.compose() signature" line 94 label rules.

        Required: non-empty string, no ``.`` (namespace separator), no
        ``/`` (depth-boundary separator), no whitespace, no leading or
        trailing ``_`` (reserved-prefix convention).
        """
        if not isinstance(label, str):
            raise ComposeLabelError(
                f"compose label must be a string, got {type(label).__name__}"
            )
        if not label:
            raise ComposeLabelError(
                "compose label must be non-empty per ADR 0038 "
                "§'g.compose() signature'."
            )
        if "." in label:
            raise ComposeLabelError(
                f"compose label {label!r} contains '.' (the namespace "
                "separator); ADR 0038 §'Namespace rule' reserves it."
            )
        if "/" in label:
            raise ComposeLabelError(
                f"compose label {label!r} contains '/' (the "
                "depth-boundary separator); ADR 0038 §'Namespace rule' "
                "reserves it."
            )
        if any(ch.isspace() for ch in label):
            raise ComposeLabelError(
                f"compose label {label!r} contains whitespace."
            )
        if label.startswith("_") or label.endswith("_"):
            raise ComposeLabelError(
                f"compose label {label!r} cannot start or end with '_'."
            )

    @staticmethod
    def _validate_translate_rotate_anchor(
        translate: tuple[float, float, float],
        anchor: str | None,
    ) -> None:
        """Enforce ADR 0038 line 104: ``anchor=`` and a non-zero
        ``translate=`` are mutually exclusive.
        """
        if anchor is None:
            return
        # Anchor is set — translate must be the identity.
        if any(float(x) != 0.0 for x in translate):
            raise ComposeAnchorError(
                f"compose() got anchor={anchor!r} together with a "
                f"non-zero translate={translate}; per ADR 0038 "
                "§'g.compose() signature' line 104 the two are "
                "mutually exclusive."
            )

    @staticmethod
    def _validate_partition_rank(partition_rank: int | None) -> None:
        """Enforce ADR 0038 §"Layer 2" line 420: ``K >= 0``.

        Phase 3B.1 surfaces a plain :class:`ValueError` because the
        constraint is a simple integer-range check; no compose-specific
        semantic context applies.  Callers catching :class:`ValueError`
        (which :class:`ComposeError` subclasses share) still see it.
        """
        if partition_rank is None:
            return
        if not isinstance(partition_rank, int) or isinstance(
            partition_rank, bool
        ):
            raise ValueError(
                f"compose(partition_rank=...) must be an int or None, "
                f"got {type(partition_rank).__name__}"
            )
        if partition_rank < 0:
            raise ValueError(
                f"compose(partition_rank={partition_rank}) must be "
                ">= 0 per ADR 0038 §'Rank model — Layer 2'."
            )

    @staticmethod
    def _validate_compose_size(compose_size_per_module: int | None) -> None:
        """Enforce ``compose_size_per_module > 0`` when supplied."""
        if compose_size_per_module is None:
            return
        if (
            not isinstance(compose_size_per_module, int)
            or isinstance(compose_size_per_module, bool)
        ):
            raise ValueError(
                "compose(compose_size_per_module=...) must be an int "
                "or None, got "
                f"{type(compose_size_per_module).__name__}"
            )
        if compose_size_per_module <= 0:
            raise ValueError(
                "compose(compose_size_per_module=...) must be > 0; "
                f"got {compose_size_per_module}."
            )


# ---------------------------------------------------------------------------
# Helpers used by compose_inspect
# ---------------------------------------------------------------------------


def _read_named_group_inventory(f: Any, group_name: str) -> tuple[str, ...]:
    """Return sorted names of a named-index group (PG / labels) or ()."""
    if group_name not in f:
        return ()
    parent = f[group_name]
    names: list[str] = []
    for key in parent.keys():
        sub = parent[key]
        if not hasattr(sub, "attrs"):
            continue
        name_attr = sub.attrs.get("name", key)
        names.append(
            name_attr.decode("utf-8")
            if isinstance(name_attr, (bytes, bytearray))
            else str(name_attr)
        )
    return tuple(sorted(names))


def _read_record_counts(f: Any) -> dict[str, int]:
    """Count rows in the major record kinds present on the file.

    Probes optional groups with ``in`` per the h5py optional-child
    ``.get()`` hazard (project_h5py_optional_child_get_hazard).
    """
    counts: dict[str, int] = {}

    if "nodes" in f and "ids" in f["nodes"]:
        counts["nodes"] = int(f["nodes/ids"].shape[0])
    else:
        counts["nodes"] = 0

    elements_total = 0
    if "elements" in f:
        for type_name in f["elements"].keys():
            sub = f["elements"][type_name]
            if hasattr(sub, "keys") and "ids" in sub:
                elements_total += int(sub["ids"].shape[0])
    counts["elements"] = elements_total

    for kind, dataset in (
        ("constraints", "constraints"),
        ("loads", "loads"),
        ("masses", "masses"),
    ):
        total = 0
        if dataset in f:
            node = f[dataset]
            if hasattr(node, "shape"):
                # Top-level dataset (e.g. /masses, /loads).
                total = int(node.shape[0])
            elif hasattr(node, "keys"):
                # Sub-grouped (e.g. /constraints/{kind} datasets).
                for child in node.keys():
                    sub = node[child]
                    if hasattr(sub, "shape"):
                        total += int(sub.shape[0])
        counts[kind] = total

    return counts
