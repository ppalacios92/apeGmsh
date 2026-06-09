# Plan — ADR 0055 Phase 2: non-partitioned staged-model H5 archival

**Goal:** ground the lineage chain for **non-partitioned staged** models — make
`apeSees.h5()` succeed on a staged build, persist `/opensees/stages/` declaratively,
and round-trip it back through `OpenSeesModel.from_h5 → build` byte-stable. This
satisfies the `model=` requirement on every `Results.from_*` constructor
(ADR 0020 INV-1), which is the actual thing blocking staged-results viewing.

**Design authority:** `decisions/0055-staged-h5-archival.md`. This doc is the
*execution breakdown*, **hardened by an adversarial panel (2026-06-09, run wf_457d56d4)**
that returned `stop-rethink` on the first draft and caught 4 fatal + 5 high defects.
All plan-changing findings are folded in below; verdict after edits = **go**.

**Scope confirmed (2026-06-09):**
- Phase 2 = **non-partitioned only**. Partitioned staged stays fail-loud (Phase 5).
- **Chain + feedstock only.** Viewer stage-aware *consumption* is a later slice.

## Live-fact reconciliation (verified against source; ADR text is stale)
- Schema bump **2.17.0 → 2.18.0**. Single source = `emitter/h5.py:337` (`SCHEMA_VERSION`). (ADR's 2.15→2.16 was Phase 1.)
- **The staged `h5()` guard is the single check at `apesees.py ~5690`** (method def `h5` at ~5616). Verify exact line at code time.
- **`apesees.py ~5223/5310/5361/5434` are LIVE-EXECUTION guards** (analyze / eigen / critical_time_step / analyze_explicit) — they **must stay raising**. Do NOT touch them. (ADR's 5493/5502 citations are stale — ignore.)
- `BuiltModel.stage_records` exists (`apesees.py:535`) and **carries the resolved per-stage sub-records** (`fix_records`/`mass_records`/`support_records`/`activate_absorbing_records`/`activated_pgs`/…), iterated at `apesees.py:859-868`. The writer reads these directly (it still needs the bm **tag resolver** to map `id(spec)→tag`).
- `StageRecord` has **NO `owned_element_ids`/`owned_node_ids` fields** — only `activated_pgs` (`build.py:1018`). The writer must DERIVE owned ids (see P2.1).
- `StageRecord.activate_absorbing_records` (`build.py:1095`) emits at `apesees.py:1704` (flat, **after initial_stress, before the analysis chain**). Must be persisted + replayed.
- Tri-state reality: `pre_analyze_reset` is plain `bool=False` (`build.py:1089`, two-state); `set_creep_on` is `bool|None` (`1088`, tri-state); only `set_time`/`dt` are `float|None`.
- `is_partitioned(fem)` → `build.py:3099` (reads `fem.partitions`; `/partitions` round-trips). `_emit_stages_partitioned` (`apesees.py ~2184-2520`) has **zero raises** — partitioned-staged is NOT fail-loud at the emit path; the **only** fail-loud boundary is the `h5()` guard.
- `_replay_into` → `compose.py:247` (note: flat replay **deliberately drops** region/rayleigh/damping, `compose.py:386-391`, and emits **patterns before chain**). `_replay_staged_into`/`StageRecordRO` are net-new.
- `schema_version.py` lives at `opensees/_internal/`, not `emitter/`.

## Invariants (corrected from the ADR by the panel)
1. **Do NOT re-derive ownership at replay** — persist `owned_element_ids`/`owned_node_ids` per stage. The **writer** derives them once via `compute_stage_ownership(stage_records, elements, fem)` + join `id(spec)→bm.tag_for[id]`, writes **sorted ascending** `int64` (else two fresh builds drift the hash while `from_h5→to_h5` stays stable, masking it).
2. **Tri-state, corrected:** `set_time`/`dt` → NaN-sentinel (`float|None`). `set_creep_on` → `int8` {-1,0,1}. `pre_analyze_reset` → single `int64` 0/1 (no `_present` companion). Round-trip test per kind incl. omit-vs-emit.
3. **Pin constraint compound dofs to the GLOBAL ndf envelope on BOTH sides** — writer pads `width=max(self._ndf, max(len(r.dofs)))`; `StageRecordRO` keeps the padded width on read (never strip zeros), else `_dtype_tag` drifts. Test the full `from_h5→to_h5→from_h5` cycle.
4. **`element_tag_map` re-validation (re-specified):** persist `/opensees/element_tag_map` (`int64` pair) from the writer's allocation plan. On read, compare it against `(rec.fem_eid → rec.tag)` reconstructed from rehydrated `ElementRecord`s (broker `/elements`) — **NOT** by re-running `allocate_element_tags` (impossible: no primitives post-rehydrate). Drift test = direct `h5py` mutation of the dataset → assert `from_h5`/replay raises.
5. **Stage patterns fully-resolved, replayed verbatim** — never re-run `emit_pattern_spec` at replay.
6. **Producer hard-floor** — once 2.18.0 ships, every file (incl. vanilla) stamps 2.18.0; a 2.17 reader REFUSES it. State as hard floor.
7. **Declarative store-and-echo** — region refs by name, initial-stress by field set, analysis chain by value.
8. **H5 persistence is side-channel, NOT replay** (the fatal-#2 fix) — see P2.1.

---

## Slices (each = own PR, `--base main`)

### P2.0 — Schema/version bump (smallest, lands first)
- Bump `emitter/h5.py:337` `SCHEMA_VERSION` 2.17.0 → **2.18.0**; add a 2.18.0 History bullet (`/opensees/stages` + `/opensees/element_tag_map`, both fold into `model_hash`, ADR 0023 window, hard-floor sentence inv#6). `MODEL_HASH_EXCLUDED_CHILDREN` **unchanged**.
- **Enumerate the dependent edits** (panel high-sev): `tests/fixtures/schema.py:8-9` (`OPENSEES_CURRENT`→'2.18.0', `OPENSEES_PRIOR_MINOR`→'2.17.0'); the hardcoded `== "2.17.0"` asserts in `test_h5_damping.py` + `test_h5_names_sidecar.py` (prefer converting to `import OPENSEES_CURRENT`); version-stamp asserts in `test_h5_partitions.py` / `test_h5_schema_compat.py`.
- **Verify:** vanilla write byte-identical; `model_hash` unchanged for vanilla; **targeted `tests/opensees/h5` + `test_h5_schema_compat` green**.

### P2.1 — Writer + non-partitioned guard relax (folded per panel finding #9)
**Mechanism (fatal-#2 fix, stated explicitly):** H5 staged persistence is **side-channel**, mirroring Phase 1's `set_initial_stress_records`:
- Add `H5Emitter.set_stage_records(stage_records, resolver)` + `_write_stages(f)` that persists **directly from the `StageRecord`s** (like `_write_regions`/`_write_dampings`/`_write_partitions`), called **last** in `write_opensees_into`, with **early-return before `create_group('stages')` when empty** (vanilla byte-identity).
- **Suppress the in-band leak:** `apeSees.h5`'s `bm.emit` drives `_emit_stages_flat`, whose in-band fix/mass/region/pattern/recorder/chain calls would pollute the GLOBAL H5 buffers and leave the last stage's `_analysis_attrs`/`_analyze_call` set → `_write_analysis` (`h5.py:2508`) emits a **phantom global `/opensees/analysis`**. Fix: make `H5Emitter` stage-aware — `stage_open`/`stage_close` flip an `_in_stage` flag; in-band per-stage Protocol calls are **dropped while `_in_stage`** (authoritative copy is in the side-channel `StageRecord`s); **skip `_write_analysis` when `stage_records` present**.
- **Owned-id derivation (inv#1):** run `compute_stage_ownership` → `{id(spec)→stage_idx}`/`{node_id→stage_idx}`, join `id(spec)→bm.tag_for` for element tags + resolve node tags, persist per-stage `int64` **sorted ascending**. Emit `/opensees/element_tag_map` from the same plan.
- **Per `stage_{idx:03d}`:** `name`, `n_increments`; tri-state per inv#2; `activated_pgs` ordered vlen-str verbatim; `owned_element_ids`/`owned_node_ids` int64 sorted; inline chain `(token,*args)`; sub-tables incl. **`activate_absorbing_records`** (fatal-#3) at the after-initial-stress slot, `support`(+pattern presence), `stage_constraint`(global-ndf width inv#3), `remove_sp`/`remove_element`, per-stage `initial_stress`.
- **Guard relax:** lift the `apesees.py ~5690` `h5()` guard for **non-partitioned only** — new condition `if self._stage_records and is_partitioned(self._fem): raise`. Live-exec guards untouched.
- **Verify:** 2-stage flat fixture group shape; **assert NO global `/opensees/analysis` child**; vanilla early-return; narrower-than-ndf width re-emit-stable; a stage with `s.activate_absorbing()` persists.

### P2.2 — Reader: `StageRecordRO` + `OpenSeesModel.stages()`
- Add `StageRecordRO` to `typed_records.py` (value form; chain `(token,args)`; **constraint dofs kept at persisted padded width** inv#3; includes `activate_absorbing`).
- `OpenSeesModel._stages` + `.stages()`; `_load_stages` walks `stage_NNN` zero-padded; **read-time self-consistency fail-loud** (stage_open/close pairing). Legacy absence → empty tuple (the `nodes_ndf` pattern). `from_compose_buffers` populates `_stages`. **`_populate_emitter_h5` routes via `set_stage_records`, NOT `_replay_staged_into`** (fatal-#2).
- **Verify:** `from_h5` `.stages()` matches; **full `from_h5→to_h5→from_h5` hash-stable** (incl. narrower-than-ndf); malformed → fail loud; pre-2.18 → empty → flat.

### P2.3 — Replay (tcl/py only): `_replay_staged_into`
- New free function sibling of `_replay_into`, **for tcl/py emit only** (H5 uses the side-channel). **Branch on `is_partitioned` → RAISE for partitioned** (Phase 5). **Add an upfront read-side guard: raise when `_stages` non-empty AND target emitter is Live** (LiveOpsEmitter.stage_open raises — fail clean, not deep in replay; panel high-sev #6).
- `build()` + `_populate_emitter` (tcl/py) route here when `_stages` non-empty. **Ground the per-stage order on `_emit_stages_flat` (`apesees.py ~1520-1758`), NOT the stale `staged-analysis.md`:** emit global prefix, then per stage `stage_open → set_time/set_creep → owned nodes/elements (by stored tag) → remove_sp/remove_element → fix/mass/region → stage MP constraints → support HOLD → domain_change → rayleigh/damping_attach → initial_stress → activate_absorbing → **chain → patterns → recorders** (chain BEFORE patterns, opposite of flat `_replay_into`) → pre_analyze_reset → analyze → stage_close`. No claim sets rehydrated. Support-HOLD: one shared Constant series tag + per-stage Plain tag via a deterministic allocator.
- `element_tag_map` re-validation per inv#4.
- **Verify (load-bearing):** recording-emitter oracle = normalized `(name, arity, kwargs)` sequence equality with **re-allocated tag positions normalized** (region/parameter tags diverge, `compose.py:307-317`), replay vs original `BuiltModel.emit`, for flat + staged fixtures; **`step_hook_ramp` before `analyze` PER STAGE iff that stage has initial_stress** (flag resets per `stage_close`) — add a **mixed-stage fixture** (one with, one without). `model_hash` stability: `from_h5→to_h5` identical; **two fresh builds match** (multi-stage non-trivial ownership); staged ≠ one-stage-removed. Add a **stage-bound `s.region` + `s.damping`** fixture (flat `_replay_into` drops those — staged must NOT).

### P2.4 — Test inversion + partitioned fail-loud + suite
- **`test_h5_staged_fail_loud.py` has exactly two tests** (one non-partitioned staged-raise + vanilla smoke) — there is **no partitioned-raise case to "keep"**. Convert the staged-raise into a **non-partitioned staged ROUND-TRIP success** test; **ADD a new multi-partition staged fixture asserting `ops.h5` still raises** (partitioned-staged fail-loud is currently untested). Keep vanilla smoke + assert no `/opensees/stages` after vanilla write. Make the recording-oracle a mandatory gate.
- **Verify:** full `tests/opensees/h5` + `tests/opensees` targeted green.

---

## Explicitly out of Phase 2
Partitioned staged + partitioned-HOLD → **Phase 5** · viewer stage-aware consume → later slice · `g.compose()` FILTER+warn → **Phase 3** (ADR 0038:169) · `ops.domain_capture` `bridge=None` ndf → **Phase 4** (ADR 0048) · per-stage modal damping / live staged emit (keep raising).

## Risk note
Largest byte-canonical-drift surface in the persistence layer. The single most
important guard is the `model_hash`-stability test (two fresh builds + full
`from_h5→to_h5→from_h5`); build it in P2.3 and keep it green at every later slice.
Refresh all line anchors against source at code time — many in the ADR have drifted.
