# MP per-record tag tracking — next-session scope

**Status:** Planning doc, not yet started. Created 2026-05-26 as a follow-up
to PR [#343](https://github.com/nmorabowen/apeGmsh/pull/343) (Phase
SSI-2.E mechanical verbs) and PR [#344](https://github.com/nmorabowen/apeGmsh/pull/344)
(PR-2 deferral docs).

The deferral entry that motivates this work lives at
[`_DEFERRED.md`](_DEFERRED.md) §"MP per-record tag tracking — enabling
refactor for `s.remove_mp` and future swap verbs".

---

## 1. What this is

Today, `_internal/build.py::emit_mp_constraints` and its per-kind helpers
(`_emit_rigid_links`, `_emit_equal_dofs`, `_emit_rigid_diaphragms`,
`_emit_kinematic_couplings`) emit anonymous OpenSees commands — there is
no apeGmsh-side stable handle on the resulting MP record after emit. Only
`_emit_surface_couplings` (ASDEmbeddedNodeElement) allocates and persists
a per-record element tag, because that path goes through the `element`
parser.

Consequence: every future "mutate an MP after the fact" verb is
currently blocked at the apeGmsh-emit layer, **even though OpenSees
itself supports the mutation**. That's why this work pays off: it's a
mechanical lift that unlocks a whole class of future verbs without
committing to any specific consumer.

Concrete consumers that this lift enables (none required to merge — the
point is to do the plumbing on its own merits):

- `s.remove_mp(name=)` / per-kind `s.remove_equal_dof(name=)` etc. —
  formally deferred in [`_DEFERRED.md`](_DEFERRED.md) with stated
  trigger ("real SSI deck with reusable temporary shoring that can't be
  served by `s.remove_element` on the host PG").
- Hypothetical `s.swap_mp(name=, …)` — substitute one MP for another
  mid-run (relevant for damper/spring substitutions in nonlinear time
  history).
- H5 round-trip identity for MP constraints — today's
  `/opensees/constraints/{equalDOF,rigidLink,rigidDiaphragm,kinematic_coupling}`
  compound dtypes carry the `name` column but no `tag` column. Adding
  one tightens round-trip parity for the `OpenSeesModel` read-side
  broker (ADR 0019).

---

## 2. Why this is the next move (and why we waited)

The May 2026 four-agent critique pass (architecture invariants, API
consistency, OpenSees semantics, use-case skeptic) on the proposed PR 2
verbs converged on **DEFER all three** because no real consumer needed
them today. But the **architecture-invariants critic explicitly called
out the MP-tag-tracking gap as a worthwhile enabling refactor**,
independent of any verb that consumes it. Quote from the critique
report:

> Independent of any immediate consumer, the per-record tag-identity
> gap in the MP emit fan-out is a worthwhile target for opportunistic
> landing. This blocks every future "mutate an MP after the fact"
> verb, not just `s.remove_mp` — also any hypothetical `s.swap_mp` or
> `s.update_mp_stiffness`.

That makes this the right "side-track that IS worth a follow-up PR"
(my note from the synthesis): small, mechanical, pays down architecture
debt without committing to a controversial verb.

**Cost estimate (rough):** 1-2 days code + tests; H5 schema bump
opensees 2.7.0 → 2.8.0 per ADR 0023.

---

## 3. Critical OpenSees-source finding that changes the design

The deferral entry in `_DEFERRED.md` proposed threading
`tags.allocate("MPconstraint")` through each per-kind emit helper. After
reading the OpenSees Tcl convenience-command source, **the right path
is different and significantly simpler**.

### What I assumed

- apeGmsh allocates an MP tag via `TagAllocator`.
- apeGmsh emits a raw `MP_Constraint $tag $rNode $cNode $matrix
  $cDOFs $rDOFs` command, bypassing the `equalDOF` / `rigidLink`
  convenience wrappers.

### What's actually true

`TclCommand_addEqualDOF_MP` at
`SRC/runtime/commands/modeling/constraint.cpp:435-502` does the
following:

1. Constructs `MP_Constraint *theMP = new MP_Constraint(RnodeID,
   CnodeID, Ccr, rcDOF, rcDOF);` — at line 492.
2. The `MP_Constraint` constructor at
   `SRC/domain/constraints/MP_Constraint.cpp:236` uses
   `DomainComponent(nextTag++, CNSTRNT_TAG_MP_Constraint)` — line 238 —
   so OpenSees auto-allocates the MP tag from an internal static
   counter at construction time. apeGmsh has no way to override this.
3. **CRITICAL: line 500 — `Tcl_SetObjResult(interp,
   Tcl_NewIntObj(theMP->getTag()));`** — the `equalDOF` Tcl command
   RETURNS the auto-allocated tag via the Tcl result. The user (or
   apeGmsh-emitted deck) can capture it with `set tag [equalDOF
   $rNode $cNode 1 2 3]`.

### The implication

apeGmsh **doesn't need to allocate MP tags at all**. The right pattern
is to capture OpenSees' auto-allocated tag at emit time into a
deck-local variable, keyed by the apeGmsh-side `name=`:

```tcl
# emitted by apeGmsh — equalDOF returns the auto-tag
set _ape_mp_lining_anchor_tag [equalDOF 7 12 1 2 3]
# ... later, in a different stage ...
remove mp -tag $_ape_mp_lining_anchor_tag
```

```python
# Py emitter equivalent (if openseespy mirrors the Tcl return)
_ape_mp_lining_anchor_tag = ops.equalDOF(7, 12, 1, 2, 3)
# ... later ...
ops.remove("mp", "-tag", _ape_mp_lining_anchor_tag)
```

This is a much lighter lift than the original plan. No `TagAllocator`
extension; no new `kind="MPconstraint"` counter; no risk of the
apeGmsh-side tag drifting from the OpenSees-side tag.

### Open verification items for the next session

- [ ] Confirm `ops.equalDOF(...)` in openseespy actually returns the
  tag as `int`. If openseespy drops the return value (just calls into
  C++ without forwarding `getTag()`), the Py emitter needs a fallback
  — most likely `ops.getMPtags()` followed by an order-based read.
  Worth checking `openseespywin/opensees.pyi` or the openseespy
  source.
- [ ] Confirm `rigidLink` and `rigidDiaphragm` Tcl commands at
  `SRC/runtime/commands/domain/rigid_links.cpp` ALSO return their MP
  tags (or set of tags for rigidDiaphragm which creates many MPs at
  once). If they don't, we either patch the Tcl wrappers OR fall
  back to a getMPtags()-diff approach.
- [ ] Decide what `LiveOpsEmitter` does. Likely:
  `_ape_mp_<name>_tag = self._ops.equalDOF(...)` and stash on
  `self._mp_name_to_tag: dict[str, int]`. Same idea, in-process.

---

## 4. Scope

### In scope

- Per-kind emit helpers in
  [`src/apeGmsh/opensees/_internal/build.py`](../_internal/build.py)
  (`_emit_equal_dofs`, `_emit_rigid_links`, `_emit_rigid_diaphragms`,
  `_emit_kinematic_couplings`) — each emits a `set _ape_mp_<name>_tag
  [equalDOF …]` (Tcl) or `_ape_mp_<name>_tag = ops.equalDOF(…)` (Py)
  capture line per record. The mp_constraint_comment line still emits
  for human-readability.
- New emitter Protocol method
  [`emitter/base.py`](../emitter/base.py)::`Emitter` —
  `mp_constraint_capture(name: str, tag_expr: str | int)` or similar.
  Per-emitter dialect handles the Tcl `set $name [...]` / Py
  `name = ...` / Live in-memory dict pattern.
- `RecorderRecord`-style record extension on the bridge to store a
  `name → captured_tag_variable` map per scope (global, per-stage),
  exposed via a `bridge.mp_tag_for(name)` read accessor for downstream
  verbs like `s.remove_mp`. The map is built up as emit progresses; the
  Live emitter materializes real `int` tags, the Tcl/Py emitters
  materialize Tcl-variable / Python-name strings.
- H5 schema: bump opensees `2.7.0 → 2.8.0` (additive minor per ADR
  0023). Add a `tag` column to the compound dtypes under
  `/opensees/constraints/{equalDOF,rigidLink,rigidDiaphragm,
  kinematic_coupling}`. For the schema, `tag` is **the integer the
  Live emitter recorded** OR `-1` sentinel for Tcl/Py text decks
  where the tag is only known at deck-execution time.
- `OpenSeesModel.from_h5(...)` read side adds a `mp_tags()` accessor
  returning `dict[name, int | None]` (None when the file was written
  from a Tcl/Py-only build).
- Tests: unit + h5 round-trip + integration.

### Out of scope (explicitly)

- Any `s.remove_mp` / `s.swap_mp` verb. Those stay deferred until a
  real consumer surfaces (per the [`_DEFERRED.md`](_DEFERRED.md)
  trigger). This work is purely the enabling plumbing.
- ASDEmbeddedNodeElement / `tie` / `distributing` — those already
  allocate per-record tags via the `element` parser path. No change.
- `tied_contact` / `mortar` — already deferred independently (ADR
  0034 §5a-ext); not affected by this lift.
- Tag-tracking in the partitioned path for foreign-node replication —
  ADR 0027's tag-determinism contract already covers this; the
  per-record name → tag map is per-rank in the cross-partition case
  but the cross-rank tag identity is OpenSees-side, not apeGmsh-side.
  Worth a tripwire check (see §7) but probably no work.

---

## 5. File map

| Concern | File | Notes |
|---|---|---|
| Per-kind emit (Tcl/Py/Live capture) | [`_internal/build.py`](../_internal/build.py)::`emit_mp_constraints` + 4 `_emit_*` helpers | Each helper grows a "name + capture" emit line per record. |
| Bridge-side `name → tag-expr` map | [`apesees.py`](../apesees.py)::`apeSees._mp_name_to_tag_expr: dict[str, str \| int]` | Populated during build; read by future `s.remove_mp` verbs. Live emitter stores `int`; Tcl/Py emitters store Tcl-var / Py-var-name strings. |
| Protocol method | [`emitter/base.py`](../emitter/base.py)::`Emitter` | One new method (probably `mp_constraint_capture(name, tag_expr_or_value)`). |
| Tcl emit | [`emitter/tcl.py`](../emitter/tcl.py) | `set _ape_mp_<name>_tag [equalDOF …]` — but watch out for name sanitization since Tcl variable names have restrictions (alphanumeric + underscore). |
| Py emit | [`emitter/py.py`](../emitter/py.py) | `_ape_mp_<name>_tag = ops.equalDOF(…)`. Same sanitization rules. |
| Live emit | [`emitter/live.py`](../emitter/live.py) | Real `int` capture into `self._mp_name_to_tag: dict[str, int]`. Note: openseespy return value verification needed (§3 open items). |
| H5 schema bump | [`emitter/h5.py`](../emitter/h5.py) + [`emitter/h5_reader.py`](../emitter/h5_reader.py) | Add `tag` column to MP compound dtypes; bump opensees zone 2.7.0 → 2.8.0. Two-version reader window applies per ADR 0023. |
| Recording emit | [`emitter/recording.py`](../emitter/recording.py) | New `("mp_constraint_capture", (name, tag_expr), {})` tuple for test introspection. |
| OpenSeesModel read | [`opensees_model.py`](../opensees_model.py) | New `mp_tags() -> dict[str, int \| None]` accessor. None on Tcl/Py-only files where the tag isn't known. |

---

## 6. Schema migration (ADR 0023 application)

- `SCHEMA_VERSION` in [`emitter/h5.py`](../emitter/h5.py) bumps
  **2.7.0 → 2.8.0** (additive minor — the `tag` column is added with
  a default of `-1` for legacy files in the reader's back-compat
  window).
- Two-version reader window: a reader at 2.8.x accepts 2.8.* and
  2.7.* with `tag` defaulting to `-1`. The reader policy lives in
  [`_internal/schema_version.py`](../_internal/schema_version.py).
- The neutral zone (`NEUTRAL_SCHEMA_VERSION` at 2.6.0) and results
  zone (`RESULTS_SCHEMA_VERSION` at 1.1.0) do NOT bump — this is a
  pure opensees-zone change.
- Cuts / sweeps / transforms schemas are unaffected.

---

## 7. Test plan

Unit:

- New `tests/opensees/unit/test_mp_tag_capture.py`:
  - Per-kind: assert that emitting an `equalDOF` / `rigidLink` /
    `rigidDiaphragm` / `kinematic_coupling` record with a `name=`
    produces a corresponding capture line preceding the emit, and that
    `bridge._mp_name_to_tag_expr[name]` is populated post-build.
  - Anonymous records (no `name=`) should NOT produce a capture line
    (the capture is opt-in to keep deck noise minimal).
  - Per-emitter shape: Tcl produces `set _ape_mp_<name>_tag [...]`,
    Py produces `_ape_mp_<name>_tag = ops...`, Recording captures
    the tuple.
- Live test (gated on openseespy availability — same
  `@pytest.mark.live` marker as `test_live_stage_open_raises`):
  - Emit an `equalDOF` with `name=`, drive it through `LiveOpsEmitter`,
    then assert `bridge._mp_name_to_tag` carries the real tag matching
    `ops.getMPtags()`.

H5 round-trip:

- New `tests/opensees/h5/test_h5_mp_tag_column.py`:
  - Write a fixture with named `equalDOF` / `rigidLink` /
    `rigidDiaphragm` / `kinematic_coupling` records; read back and
    assert the `tag` column is populated (with `-1` on Tcl/Py-only
    builds, with the real int on Live builds).
  - Schema-version check: a 2.7.0 fixture (legacy, no `tag` column)
    reads cleanly with `tag` defaulting to `-1` and a one-shot
    DeprecationWarning. A 2.5.x or older fixture raises
    `SchemaVersionError` per the two-version window.

Integration:

- Extend `tests/opensees/integration/test_emit_partitioned_mp_constraint_replication.py`
  (or add a new file) to assert the capture line emits on the SAME
  rank as the underlying constraint (per ADR 0027 INV-4 fan-out
  rules). Cross-rank tag identity is OpenSees-side; apeGmsh only
  needs to ensure the variable name is consistent.

Existing tests to NOT break:

- All 145 stage tests
- All 34 SSI-2.E tests from PR #343
- The four-agent critique didn't surface anything; this is a
  mechanical lift.

---

## 8. Tripwires

- **Tcl variable-name sanitization.** `name=` from
  `g.constraints.equal_dof(name=...)` is user-supplied and might
  contain hyphens / dots / spaces. The Tcl variable name we emit
  (`_ape_mp_<sanitized_name>_tag`) must be a legal Tcl identifier.
  Reuse the existing `_sanitize_raw_token` helper in
  [`_internal/build.py:1448`](../_internal/build.py) (search for it).
  Also: Py emitter names must follow the same rule (Python identifier
  syntax is similar but stricter on leading digit). Sanitize in ONE
  place and pass the sanitized string through.
- **openseespy return-value drift.** If `ops.equalDOF(...)` returns
  `None` on some openseespy build, the live capture path silently
  loses the tag. Defensive: fall back to `ops.getMPtags()` and
  diff against the pre-emit snapshot. Test this on at least one
  openseespy version.
- **`rigidDiaphragm` creates N MPs from one command.** Look at
  `RigidDiaphragm.cpp` to see how many MP_Constraints it spawns
  (likely one per constrained node, so N-1 for a master + N
  constrained). The capture line either gets a LIST of tags or we
  pick a representative. The simpler choice: store only the FIRST
  tag and document that `rigidDiaphragm` removal is "remove mp
  $masterNodeTag" (cascade-by-master).
- **`_DEFERRED.md` synchronization.** When this PR lands, update
  the "MP per-record tag tracking" deferral entry to ✅ SHIPPED.
  Also update `_DEFERRED.md` §"`s.remove_mp(name=)`" to remove the
  "apeGmsh-side blocker #1: no per-record MP tag tracking" sub-bullet
  — that blocker is gone, but the architectural-concern blocker (#2,
  UN-CLAIM as a fourth pattern) remains.
- **Partitioned path interaction.** Cross-partition MP constraints
  (ADR 0027) replicate the MP command on every rank that has the
  constrained node — each rank's OpenSeesMP process will allocate
  its OWN tag because the static `nextTag` counter is per-process.
  Per-rank tag values DIVERGE. This is fine for `remove mp -tag`
  because the removal also emits per-rank, and each rank uses its
  own captured variable. But it means the H5 schema's `tag` column
  CAN'T be a single int for cross-partition MPs — it has to be
  per-rank. Either: (a) store the first-rank tag as the canonical
  one and accept that cross-rank actions need re-capture, or (b)
  store a list-of-(rank, tag) pairs (schema gets ugly). Lean (a).
- **Stale per-stage emit ordering.** PR #343's SSI-2.E removals
  emit BEFORE stage-bound new BCs (the "atomic-replace" design).
  If a future `s.remove_mp(name=)` consumes
  `bridge._mp_name_to_tag_expr[name]`, the variable must already be
  bound at the point of `remove mp` emission. Today's MP
  emission happens BEFORE per-stage emit (in `emit_mp_constraints`
  which runs in the global pre-stage block, or in
  `emit_stage_mp_constraints` for stage-claimed MPs). For
  global-pool MPs claimed by a stage, the capture happens in the
  stage block — and a LATER stage would see the variable in scope.
  Lock this in a test that emits an `equalDOF` in stage 1 and
  attempts to reference its captured tag in stage 2 (even if
  there's no actual remove verb yet, exercise the variable
  visibility).

---

## 9. Open design questions

- **Q1: Capture for anonymous records too?** A user who writes
  `g.constraints.equal_dof(...)` without `name=` gets an anonymous
  record. Do we (a) skip capture entirely (no deck noise, no
  removability), (b) auto-generate a name (`_anon_<hash>`), or (c)
  capture into a list rather than a named variable? Lean (a) — keep
  the opt-in shape consistent with the rest of apeGmsh.
- **Q2: H5 `tag` column type for Tcl/Py text decks.** When the user
  emits `ops.tcl("model.tcl")` and then `ops.h5("model.h5")`
  separately (without running the deck), what goes in the `tag`
  column? Options: `-1` sentinel, `None` (h5 needs an explicit
  representation — nullable int), or "the Tcl variable name as a
  string". Lean `-1` sentinel + the variable name as a SEPARATE
  string column `tag_var` ("captured into Tcl `$_ape_mp_foo_tag`").
- **Q3: Per-stage vs global scope.** If `g.constraints.equal_dof(name="foo")`
  is claimed by stage 2 (via `s.equal_dof(name="foo")`), the capture
  line emits INSIDE stage 2's block. A `s.remove_mp(name="foo")` in
  stage 3 needs the variable to still be in Tcl/Py scope. Tcl
  variable scoping: by default `set` creates global scope, so this
  works as long as we don't wrap in a `proc {}`. Verify against
  the existing dispatcher boilerplate (Phase SSI-1).
- **Q4: Should the bridge expose a public `bridge.mp_tag_for(name)`
  method now**, even with no consumer? The deferral note in
  `_DEFERRED.md` says "do it on its own merits." Exposing a
  read-only accessor with a clear contract makes future consumers
  trivial. Lean yes — but mark it experimental (rename-without-
  warning prefix `_`) until a real consumer pins the signature.

---

## 10. References

- PR [#343](https://github.com/nmorabowen/apeGmsh/pull/343) — Phase
  SSI-2.E (mechanical between-stage Domain mutators) — the parent
  feature.
- PR [#344](https://github.com/nmorabowen/apeGmsh/pull/344) — PR-2
  deferral docs — captures the four-agent critique that flagged
  this refactor as opportunistic.
- ADR [0022](decisions/0022-mp-constraint-emission-fanout.md) — the
  current MP-emission fan-out shape that this refactor extends.
- ADR [0023](decisions/0023-per-zone-schema-versioning.md) — per-zone
  schema policy; opensees 2.7.0 → 2.8.0 bump rules.
- ADR [0019](decisions/0019-opensees-model-read-side-broker.md) —
  `OpenSeesModel` read-side broker that gains `mp_tags()`.
- ADR [0034](decisions/0034-stage-bound-bcs-and-recorders.md) §5a —
  CLAIM-by-name for MP constraints; the relevant scope+name
  vocabulary this refactor preserves.
- [`_DEFERRED.md`](_DEFERRED.md) §"MP per-record tag tracking" — the
  entry this scope-doc operationalizes.
- OpenSees source citations (versioned C++ — current as of 2026-05):
  - `SRC/runtime/commands/modeling/constraint.cpp:435-502` —
    `TclCommand_addEqualDOF_MP`, the Tcl-side wrapper that
    `Tcl_SetObjResult`s the auto-allocated tag at line 500.
  - `SRC/domain/constraints/MP_Constraint.cpp:236-260` — the
    `MP_Constraint` constructor; `nextTag++` at line 238 is the
    auto-tag source.
  - `SRC/domain/domain/Domain.cpp:1265` — `Domain::removeMP_Constraint(int tag)`.
  - `SRC/domain/domain/Domain.cpp:1286` — `Domain::removeMP_Constraints(int nodeTag)` (cascade-by-constrained-node).
  - `SRC/tcl/commands.cpp:6223-6247` — Tcl-side `remove mp` parser
    (two forms: `remove mp $nodeTag` and `remove mp -tag $tag`).
  - `SRC/runtime/commands/domain/rigid_links.cpp` — to verify
    rigidLink / rigidDiaphragm Tcl return-value behavior (open
    item §3).
