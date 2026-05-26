"""Error types for ADR 0038 `g.compose()` model composition.

These exceptions surface at compose time when the tag-collision
verifier or the namespace/reservation machinery detects a violation
of the merge contract.  They are intentionally narrow — one error
class per failure mode, with a clear `__str__` that names the
offending module label and the colliding identifier.

The verifier (`_tag_collision_verifier.tag_collision_verify`) and
the future Compose facade (`mesh/_compose.py`, ADR 0038 Phase 3)
both raise from this module.  Keeping the exception types in
``core/`` instead of ``mesh/`` lets the verifier — which is a
reusable primitive — be imported by both call sites without
introducing a layering cycle.

ADR 0038 §"Tag-collision verifier" pins the contract.
"""
from __future__ import annotations


class PartTagCollisionError(RuntimeError):
    """Raised when the tag-collision verifier detects a tag-space
    or namespace overlap that would corrupt the host broker.

    Raised by checks 1, 2, and 4 of the verifier:

    - Check 1: an imported tag lands outside the module's reservation
      window (typically into the host's tag range).
    - Check 2: two modules' reservation windows overlap.
    - Check 4: a namespaced physical-group name collides with an
      existing host PG.

    The message names the offending module label and the colliding
    identifier so callers can fix the source H5 or the host author's
    PG-naming choice.
    """


class ComposeCapacityError(RuntimeError):
    """Raised when an explicit ``compose_size_per_module=N`` override
    is smaller than the source's actual tag span.

    Verifier check 5.  Only fires under the explicit override —
    without an override, the auto-sizing scheme computes a window
    that fits the source by construction.

    The message names the source's span and the configured cap so
    callers can either widen the override or remove it to let the
    auto-sizing scheme do its job.
    """


class ComposeInvariantError(RuntimeError):
    """Raised when a constraint reference resolves outside the
    owning module's reservation window.

    Verifier check 3.  This means either the tag-rewrite cover-set
    missed a field (an implementation bug — see ADR 0038
    §"Tag-reference rewrite checklist") or the source H5 carried a
    cross-module reference between sibling composes (forbidden in
    v1 — see ADR 0038 INV-2).

    The message names the offending module label, the constraint
    kind, the field that holds the bad reference, and the
    out-of-range tag value.
    """
