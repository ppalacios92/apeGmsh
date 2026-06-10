# Plan — ADR 0055 P2.3: staged replay to tcl / py (`_replay_staged_into`)

**Goal:** `OpenSeesModel.build("tcl"|"py")` re-emits a staged archive's deck
(today it fails loud). This is the **completeness-proof** slice: a recording-
emitter oracle asserts the replayed call stream equals the bridge's original
`BuiltModel.emit` stream, which is the strongest evidence P2.1/P2.2 captured
the staged program faithfully. `build("h5")`/`to_h5` already round-trip
(P2.2 echo); `build("live")` stays fail-loud (`LiveOpsEmitter.stage_open`
raises). Partitioned staged stays fail-loud (Phase 5).

**Design authority:** `decisions/0055-staged-h5-archival.md`; grounded on the
bridge's ACTUAL staged emit, not the stale `staged-analysis.md`.

## Live-source ground truth (verified 2026-06-10, post #585/#586 main)

`BuiltModel.emit` (`apesees.py:668`) global order, then per-stage:
1. `model(ndm, ndf)`
2. nodes — **all FEM nodes EXCEPT `node_owner_stage`** (`apesees.py:1024` skip)
3-4. pre_element materials/sections/series — **skip analysis-chain primitives when staged** (`:1037`)
5. geomTransf fan-out
6. elements — **all EXCEPT `element_owner_stage`** (`:1076` skip); tags pre-allocated across global+stage
7. global `_emit_fixes`/`_emit_masses`/`_emit_regions`/`_emit_rayleigh`/`_emit_damping_attach`/`_emit_modal_damping`
7b. `emit_mp_constraints` (claimed skipped) · 7b' reinforce · 7c auto-handler
7d. global `initial_stress` (**empty in staged** — every record `.add()`'d to a stage; defensive-only)
8. patterns + recorders (claimed skipped) via `emit_pattern_spec`/`emit_recorder_spec`
9. **staged:** `_emit_stages_flat` (`apesees.py:1469`)

`_emit_stages_flat` per-stage order (the replay target):
`stage_open(name)` → `set_time`/`set_creep` → owned nodes (`_emit_node_with_inferred_ndf`) → owned elements (`spec._emit`, tags from `element_plan`) → `remove_sp`/`remove_element` → stage `fix`/`mass` → `_emit_stage_regions` → `emit_stage_mp_constraints` → support-HOLD pattern (`pattern_open(Plain,…)` + `sp_hold` per flagged dof + `pattern_close`) → `domain_change` → stage `rayleigh`/`damping_attach` → stage `initial_stress` (global helper + addToParameter) → `activate_absorbing` → analysis chain (`constraints…analysis`) → stage patterns (`emit_pattern_spec`) → stage recorders (`emit_recorder_spec`) → `pre_analyze_reset`→`reset()` → `analyze(steps, dt)` → `stage_close()`.

**Key archive invariant (why this is tractable):** P2.1 REDIRECTED every
stage-scoped call into the stage bucket, so a staged archive's GLOBAL zones
(`_fixes`/`_masses`/`_patterns`/`_recorders`/`_analysis_attrs`/`_analyze_call`)
already contain ONLY genuinely-global records. The **only** global zones that
still carry stage content are `nodes` (all FEM nodes) and `element_meta` (the
complete pool — it IS the `fem_eid→ops_tag` map). So the replay's only
filtering job is **skip stage-owned node/element tags from the global emit**.

## Design

### `_replay_staged_into(emitter, *, stages, **flat_kwargs)` — new in compose.py
Sibling of `_replay_into`. Steps:

1. **Upfront guards:** raise `NotImplementedError` if the target emitter is a
   `LiveOpsEmitter` (its `stage_open` raises — fail clean, not mid-replay);
   the partitioned branch is gated by the caller (OpenSeesModel has no
   partition info on the read side beyond the neutral `/partitions` zone —
   confirm whether a staged+partitioned archive can even exist: P2.1 `h5()`
   refused partitioned staged, so a partitioned staged ARCHIVE never exists;
   assert-and-document rather than branch).
2. **Global prefix:** call `_replay_into` with `nodes` and `elements`
   **pre-filtered** to drop stage-owned tags (new `skip_node_tags` /
   `skip_element_tags` params on `_replay_into`, defaulting empty so the flat
   path is unchanged). All other global sequences pass through as-is (already
   global-only). `analysis_attrs={}`/`analyze_call=None` for staged → no
   global chain emitted (matches the bridge).
3. **Per stage** (registration order), re-drive the `_emit_stages_flat` order
   above from `StageRecordRO`:
   - owned nodes: `(tag → fem coords, nodes_ndf[tag] elide-on-equal)` →
     `emitter.node(...)` (reuse `_emit_node_with_inferred_ndf` semantics).
   - owned elements: look up each `owned_element_id` in a `tag → ElementRecord`
     map built from the GLOBAL `_elements` pool (connectivity rehydrated the
     same way `_populate_emitter` does for global elements) → `set_element_nodes`
     + `set_current_fem_element_id` + `emitter.element(type, tag, *args)`.
   - stage fix/mass/regions/MP/HOLD/rayleigh/initial_stress/activate_absorbing/
     chain/patterns/recorders/removals — replay the StageRecordRO records
     VERBATIM (resolved tags; NOT re-resolved through `emit_*_spec`, which
     would re-run PG fan-out the archive already expanded).
   - **chain_attrs int-recovery:** before `_replay_analysis_chain`, coerce
     float-valued args that are integral back to `int` (NormDispIncr reads
     back `(1e-4, 50.0, 0.0, 2.0)`; `OPS_GetIntInput` rejects floats and the
     tcl deck bytes drift). Apply `is_integer()` recovery to the `*_args`
     tuples.
   - hook-wrap: `emit_initial_stress_global` registers `step_hook_ramp`; the
     stage's `analyze` then auto-wraps. `stage_close` clears the hook flag, so
     wrap is per-stage iff that stage has initial_stress — verify tcl/py
     `stage_close` resets `_step_hooks_registered`.

### `_replay_into` gains `skip_node_tags` / `skip_element_tags` (additive)
Empty defaults → flat path byte-identical. Staged replay passes the owned-tag
unions.

### `OpenSeesModel._populate_emitter` — dispatch
Replace the staged `NotImplementedError` (added in P2.2) with: if `_stages`,
route to `_replay_staged_into` (tcl/py); keep the Live upfront-raise. Thread
`_elements` (global pool, for owned lookup), `_nodes_ndf`, `_fem`.

## Open questions for the gate-1 panel (pressure-test these)
1. **HOLD series persistence** — the support pattern's `Constant` series is
   bridge-registered; is it in `/opensees/time_series` so the global prefix
   declares it before the stage's `pattern_open` references its tag? (P2.2
   reader-forward-compat skeptic raised this.) If NOT persisted, replay emits
   a dangling series ref.
2. **Owned-element connectivity** — does `_load_elements` populate
   `ElementRecord.connectivity` for the tcl/py path, or does `_populate_emitter`
   rehydrate it from the FEM? Owned-element lookup must get the same
   connectivity the global emit would.
3. **Node-pair owned elements** (`fem_eid < 0`) — can a stage own a node-pair
   element? Its connectivity comes from `inline_connectivity`, not the FEM.
4. **emit_index** — `_emit_stages_flat` uses FIXED slot order; within the
   regions pool, is stored order (region_seq ascending) sufficient, or does
   any cross-slot interleaving need the emit_index?
5. **Oracle tag normalization** — region/parameter tags diverge across
   round-trip (freshly allocated). The oracle must normalize tag POSITIONS,
   not values. Which arg positions are tags vs values per call?
6. **Global initial_stress + stages mixed** — can a staged build also have a
   global initial_stress bucket, and if so does the (absent) global analyze
   leave its hooks unfired? (Bridge `:1147` is "defensive-only".)
7. **`numberer_runtime_fallback`** — the one chain attr `_replay_analysis_chain`
   drops (backlog); does any staged chain carry it?

## Verify (load-bearing)
- **Recording-oracle**: replay-from-archive call stream == original
  `BuiltModel.emit` stream (normalized name/arity, tag positions normalized),
  for 2-stage + kitchen-sink + **mixed-initial-stress** (one stage with, one
  without) fixtures. `step_hook_ramp` precedes `analyze` per stage iff that
  stage has initial_stress.
- tcl/py deck structural equality: `stage_open`/`stage_close` delimiters,
  per-stage `loadConst`+`wipeAnalysis` boundaries, owned topology inside the
  stage block, hook-wrapped analyze loops.
- `build("tcl")`/`build("py")` no longer raise; `build("live")` still raises.
- stage `s.region` + `s.damping` fixture survives (flat `_replay_into` drops
  region/rayleigh; staged MUST NOT).
- `model_hash` unaffected (replay is a deck path, not a write path).

## Gate-1 resolutions (run wf_278f77e8 — go-with-plan-edits; these SUPERSEDE the "Design" buckets)

The plan's "replay StageRecordRO VERBATIM" bucket was too coarse — it conflates THREE
replay strategies. Corrected per-stage replay (`_replay_staged_into`), exact slot order:

1. `stage_open(name)`
2. `set_time` / `set_creep` (presence-gated)
3. **owned nodes** — verbatim from `(tag → fem coords, nodes_ndf elide-on-equal)`
4. **owned elements** — look up each `owned_element_id` in the **REHYDRATED** pool
   `{rec.tag: rec for rec in self._rehydrate_element_connectivity(self._elements)}`
   (raw `_elements` has `connectivity=()` + no conn prefix in args — keying the raw pool
   emits node-less element lines). The global-prefix `skip_element_tags` filter operates on
   the **same rehydrated list** so global + owned re-emits share byte-identical conn+args.
5. `remove_sp` / `remove_element` — verbatim
6. stage `fix` / `mass` — verbatim
7. stage `regions` — verbatim `region(tag, *args)` in stored (region_seq) order
8. **stage MP constraints** (FATAL fix) — NOT `emit_stage_mp_constraints` (needs build-side
   ConstraintRecord + fresh tags, absent on read). Emit directly from the 4 resolved RO
   record types in the **bridge sub-order**: `rigid_links` (`rigidLink(kind,master,slave)`)
   → `equal_dofs` (`equalDOF(master,slave,*dofs)`) → `rigid_diaphragms`
   (`rigidDiaphragm(perp_dir,master,*slaves)`; kinematic already folded onto
   RigidDiaphragmRecord at write) → `embedded_nodes` (`element('ASDEmbeddedNodeElement',…)`).
   Phantom-producing kinds (tied_contact/mortar/distributing) are unreachable — `set_stage_records`
   fails loud on them at write.
9. **HOLD patterns** (HIGH fix — slot 10, BEFORE domain_change) — `patterns` split by
   `sp_holds` presence: `hold = [p for p in patterns if p.sp_holds]`. Emit
   `pattern_open("Plain", p.tag, *p.args)` + `sp_hold(node,dof)` per pair + `pattern_close()`.
   The `role="hold"` attr is NOT read back; `sp_holds`-presence is the discriminant. Guard the
   degenerate empty-`sp_holds` case so it's not mistaken for a load pattern.
10. `domain_change()` — **iff `ro.domain_changed`** (replay the captured bool, do NOT recompute the gate)
11. stage `rayleigh` — verbatim `rayleigh(*coeffs)`; damping_attach rides in `regions`
12. **stage `initial_stress`** (re-run helper) — `emit_initial_stress_global` +
    `emit_initial_stress_addtoparameter` with the **SHARED** allocator (see below)
13. **`activate_absorbing`** (FATAL fix — re-run helper, NOT verbatim) — rebuild
    `ActivateAbsorbingRecord` from the declarative `(pg, elements)` pairs and call
    `emit_activate_absorbing(records, emitter, fem, fem_eid_to_ops_tag=…, tags=<shared>)`
14. stage analysis chain — `_replay_analysis_chain` (now with int-recovery, see below)
15. **load patterns** (slot 16, AFTER chain) — `load = [p for p in patterns if not p.sp_holds]`,
    replay verbatim (loads/sps)
16. stage `recorders` — verbatim
17. `pre_analyze_reset` → `reset()` (presence-gated)
18. `analyze(steps, dt)`
19. `stage_close()`

**Cross-cutting fixes:**
- **Shared TagAllocator** (FATAL) — ONE `TagAllocator()` at the top of `_replay_staged_into`,
  threaded through every stage's `emit_initial_stress_global` / `_addtoparameter` /
  `emit_activate_absorbing` (the bridge reuses one `tags` across all stages; a per-stage/per-call
  allocator restarts parameter counters and diverges).
- **Int-recovery in shared `_replay_analysis_chain`** (HIGH) — apply `is_integer()→int` to the
  `*_args` tuples INSIDE `_replay_analysis_chain` (compose.py), benefiting both flat + staged
  (NormDispIncr reads back `(1e-4, 50.0, 0.0, 2.0)`; `OPS_GetIntInput` rejects floats).
- **`_replay_into` skip-sets** operate on the rehydrated element list.

**Oracle design (HIGH fixes):**
- **Apples-to-apples precondition** — staged-mode bridge GLOBAL pass still runs
  `_emit_regions`/`_emit_rayleigh`/`_emit_damping_attach`/`emit_mp_constraints`/reinforce/auto-handler
  with NO `_replay_into` counterpart. Every oracle fixture MUST have zero global
  region/rayleigh/MP/reinforce/auto-handler/pg-filtered-recorder, with an explicit assertion those
  global zones are empty (else the completeness oracle silently passes comparing two equally-incomplete
  streams).
- **Element-order normalization** — the rehydrated pool iterates alphabetically by type token, the
  bridge by spec-registration order. Oracle groups both streams by `(type, tag)` before comparing
  (OpenSees is order-insensitive once nodes precede), OR fixtures use one element type per pool.
- **Tag-position normalization** — parameter/region tags diverge across round-trip (freshly
  allocated). Normalize tag POSITIONS, not values; normalize numerics identically on both streams.

**Open-question resolutions:** #1 HOLD `Constant` series IS persisted (registered `timeSeries.Constant`
primitive → time_series zone) ✓. #2/#3 owned-element connectivity via rehydrated pool (covers node-pair
`fem_eid<0` via inline_connectivity). #4 fixed slot order — emit_index canNOT reconstruct cross-slot
position. #5 shared allocator + position-normalization. #6 (MEDIUM) global+staged initial_stress: the
global hook-wrap leaks into stage-0's analyze identically on bridge AND replay (oracle matches) — add a
mixed fixture and DROP the "iff that stage has initial_stress" Verify invariant (replay faithfully
reproduces the bridge; document, don't "fix" the bridge here). #7 `numberer_runtime_fallback` not
present in staged chains (route it through `_replay_analysis_chain` anyway — cheap, backlog item).

## Out of scope (→ P2.4 / Phase 5)
Partitioned staged replay; test inversion; viewer-consume.
