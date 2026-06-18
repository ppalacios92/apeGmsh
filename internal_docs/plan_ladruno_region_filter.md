# Plan — Ladruno recorder region filter (`-R`)

Implements **ADR 0064**
(`src/apeGmsh/opensees/architecture/decisions/0064-ladruno-recorder-region-filter.md`).

**Goal.** Give the `Ladruno` recorder the same region-targeting surface as
`MPCO` (`nodes=` / `nodes_pg=` / `elements=` / `elements_pg=` → auto-emitted
`region` + `-R $tag`), working in **flat and partitioned** decks, by extracting
the shared filter machinery into a `FilterableRecorder` base. No OpenSees change
(the fork recorder already parses `-R`), no H5 schema bump.

**Verified facts this plan rests on.**
- Fork recorder parses `-R <regionTag>` and filters output — `MPCORecorderLadruno.cpp:1654` (parse), `:457`/`:524` (filter), `:684` (MODEL/SETS). So `-R` is bridge-only work.
- MPCO filter machinery to mirror: `recorder.py` — fields `:421–430`, `__post_init__` guards `:443–491`, `has_filter` `:496`, `resolve_filter_ids` `:511`, `materialize` `:618`, `-R` injection `:719`.
- Ladruno today: `recorder.py:728–833` — no selectors; `_emit` at `:818`; `-G energy` MUST stay last (`:828–832`, parser eats trailing ints).
- Partition path keys on `isinstance(p, MPCO)`: planner `apesees.py:4126`, per-element owner `:3348`, per-node owner `:3376`; emit `_emit_mpco_filter_regions_for_rank` `:4148`; plan dataclass `_PartitionedMPCOPlan`/`materialised_spec` `:353`.
- Staged + flat both flow through `emit_recorder_spec` (`_internal/build.py:2649`) → `materialize` → `_emit`.

**Success criterion (whole task).** A region-filtered `Ladruno` emits a
`region $tag …` line + `recorder ladruno … -R $tag` in flat, staged, and
partitioned decks; MPCO's emitted deck is byte-identical to pre-refactor; full
`tests/opensees` suite green with `-W error::Warning`.

---

## RF0 — Extract `FilterableRecorder` base (behaviour-preserving)

Pure refactor of MPCO. **No Ladruno change yet.** This is the riskiest step
(load-bearing, partition-critical recorder) so it ships and verifies alone.

1. In `recorder.py`, add `class FilterableRecorder(Recorder)` — frozen,
   `kw_only`, `slots` dataclass — carrying:
   - fields: `nodes`, `nodes_pg`, `elements`, `elements_pg`, `_region_tag`
     (verbatim types/defaults from MPCO `:421–430`).
   - methods: `has_filter()`, `resolve_filter_ids()`, `materialize()` moved
     verbatim from MPCO. The `materialize`/`resolve_filter_ids` return type and
     the `BridgeError` messages keep the literal word "MPCO" **only** where they
     already do — replace with `type(self).__name__` so Ladruno errors read
     "Ladruno recorder filter: …".
   - `_validate_filter(self, kind: str)` — the four guards from MPCO
     `__post_init__` `:443–491` (nodes XOR nodes_pg; elements XOR elements_pg;
     node-only + elem_responses; element-only + nodal_responses), with `kind`
     interpolated into each message instead of the literal "MPCO".
   - `_region_args(self, tag, node_ids, elem_ids)` is inline in `materialize`
     already — leave it there.
2. `MPCO(FilterableRecorder)`: drop the lifted fields/methods; keep `file`,
   `nodal_responses`, `elem_responses`, `dT`, `nsteps`. `__post_init__` keeps the
   responses-required + dT/nsteps-exclusive checks, then calls
   `self._validate_filter("MPCO")`. `_emit` unchanged (still injects `-R` at
   `:719`, still emits `"mpco"`).
3. Dataclass-inheritance gotchas (slots + frozen + kw_only): base declares the
   selector fields; subclass declares its own. All fields are `kw_only` so
   ordering across the inheritance boundary is a non-issue. Confirm `slots` base
   + `slots` subclass instantiates (no overlapping `__slots__`); if Python
   complains, the standard fix is the base not redeclaring inherited names —
   verify empirically with `opensees_venv`.

**Verify (gate — do not proceed to RF1 until green):**
- `pytest tests/opensees/unit/primitives/test_recorders.py tests/.../test_ladruno_recorder.py tests/.../test_monitor_recorder.py -q` green.
- **Golden deck.** Emit a representative model containing a filtered MPCO
  (`nodes_pg=` + `elements_pg=`), both flat and partitioned, before and after
  RF0; assert the emitted Tcl is byte-identical. (Reuse the existing MPCO
  filter test fixtures; if none dump a full deck, add a throwaway local diff
  harness — do **not** commit it.)
- `mypy` on `src/apeGmsh/opensees` at-or-below baseline.

---

## RF1 — `Ladruno` inherits the filter + emits `-R`

1. `Ladruno(FilterableRecorder)`: keep `file`, `nodal_responses`,
   `elem_responses`, `dT`, `nsteps`, `energy`. Inherit the four selectors +
   `materialize` + `resolve_filter_ids` + `has_filter` from the base.
2. `__post_init__`: keep the "at least one of nodal/elem/energy" + dT/nsteps
   checks, then `self._validate_filter("Ladruno")`, then the **new** step-4
   guard:
   ```python
   if self.has_filter() and self.energy:
       raise ValueError(
           "Ladruno: a region filter (nodes=/nodes_pg=/elements=/elements_pg=) "
           "cannot be combined with energy=True — -R scopes the value channels "
           "but -G energy is whole-model. Use a separate whole-model Ladruno "
           "for energy, or wait on per-region energy (ADR 0064 deferral)."
       )
   ```
3. `_emit`: insert the `-R` injection **after** the `-T` block and **before**
   the `-G energy` block (the energy flag stays last — `:828`):
   ```python
   if self._region_tag is not None:
       args += ["-R", self._region_tag]
   if self.energy:
       args += ["-G", "energy"]
   ```
   Add the MPCO-style `NotImplementedError` guard at the top of `_emit` for an
   unmaterialised `nodes_pg`/`elements_pg` (bridge-bypass defence).
4. Update the docstring: replace the `:766` "Region filter (`-R`)" *deferred*
   bullet with the shipped behaviour + a worked `nodes_pg=` example; keep the
   per-region-energy bullet but cross-reference ADR 0064 §4. Add the four
   selector params to the Parameters block (mirror MPCO's wording).

**Verify:**
- New unit tests in `test_ladruno_recorder.py`:
  - `nodes_pg=` → emits `region $t -node …` then `recorder ladruno … -R $t`.
  - `elements_pg=` → `-ele …`; explicit `nodes=`/`elements=` paths.
  - arg order: `file, -N, -E, -T, -R $t, -G energy` when both filter + energy…
    **expect `ValueError`** (the guard) — assert the guard fires, and assert the
    no-energy filtered case orders `-R` correctly.
  - asymmetric-filter guards fire with "Ladruno" in the message.
  - whole-model Ladruno (no filter) emits **no** `region` line and **no** `-R`
    (regression: byte-identical to today).
- `pytest … -W error::Warning` green.

---

## RF2 — Partition path widened to the base

1. In `apesees.py`, change the INV-4 gates from `MPCO` to `FilterableRecorder`:
   - `_plan_partitioned_mpco_recorders` `:4126` `if not isinstance(p, MPCO)`.
   - per-element owner predicate `:3348`, per-node owner predicate `:3376`.
   - any other `isinstance(spec, MPCO)` that exists to route **filter/region**
     behaviour (grep `isinstance.*MPCO` in `apesees.py` — there were ~6 hits;
     touch only the ones gating region planning/emit/ownership, **not** any that
     are genuinely MPCO-output-format specific). List each hit + keep/change
     decision in the PR description.
2. Rename `_PartitionedMPCOPlan` → `_PartitionedFilterPlan` and its
   `materialised_spec: "MPCO"` annotation → `"FilterableRecorder"`; update the
   doc-comments (`:325–353`) and the method names
   `_plan_partitioned_mpco_recorders` / `_emit_mpco_filter_regions_for_rank` to
   the recorder-neutral `_filter` spelling **only if** it's a pure local rename
   (these look internal/underscored — confirm no external callers via grep
   before renaming; if they leak, leave the names and just widen the types).

**Verify:**
- Extend the existing partitioned-MPCO recorder e2e test (find it under
  `tests/opensees/**/partition*` or `**/*mpco*partition*`) with a
  partitioned region-filtered **Ladruno**: every owning rank emits its
  per-rank `region $t …` (intersected element set) + `recorder ladruno … -R $t`,
  same tag across ranks.
- MPCO partitioned path regression: byte-identical deck vs RF0 golden.

---

## RF3 — Staged + H5 round-trip + close-out

1. **Staged test.** A region-filtered `Ladruno` inside `ops.stage(...)` via
   `s.recorder` materialises its `region` in the owning stage. Assert the
   `region` line lands in the correct stage block (mirror the MPCO staged test
   if one exists; ADR 0034 path).
2. **H5 self-description.** Confirm (run-verified on the fork build, or
   `@pytest.mark.live`-skipped if the deployed fork lacks the recorder — match
   the existing Ladruno live-skip convention at `recorder.py:732`) that a
   region-filtered `.ladruno` writes `MODEL/SETS` with the region tag and that
   `Results.from_*` reads back only the filtered nodes/elements.
3. **ADR + docs.** Flip ADR 0064 to **Accepted** with PR refs; update the
   `recorder.py` deferral notes (done in RF1 for `-R`; here update the
   per-region-energy note to point at ADR 0064 §4). Update `decisions/README.md`
   row 0064 status. If a recorders guide / skill mentions "Ladruno is
   whole-model only", reconcile it (grep `internal_docs`, `skills/apegmsh`,
   docs).

**Verify:** full `pytest tests/opensees -q -W error::Warning` green; mypy
at-or-below baseline; `decisions/README.md` table renders.

---

## Scope boundaries

- **In:** region filter (`-R`) for value channels on `Ladruno`, flat +
  staged + partitioned; the `FilterableRecorder` extraction; the MPCO golden
  -deck guarantee.
- **Out (deferred, unchanged):** per-region energy (`-G energy <regionTag…>`).
  ADR 0064 §4 reserves the landing — reuse `_region_tag`, flip the RF1 guard to
  emit `-G energy $region_tag`, gate on a run-verified fork `-G energy <tag>`
  path. One follow-up slice.
- **Out:** any change to the fork C++ recorder (it already parses `-R`).

## Risk register

| Risk | Mitigation |
|---|---|
| RF0 refactor silently changes MPCO emit | Golden byte-identical deck gate before RF1; RF0 ships/verifies alone |
| `slots` + inheritance instantiation failure | Empirically verify base/subclass instantiation in RF0; standard fix = base owns selector slots, subclass owns its own |
| Missed `isinstance(…, MPCO)` region gate → partitioned footgun | RF2 greps **all** hits, classifies each keep/change in PR; partitioned Ladruno e2e is the proof |
| `-R` lands after `-G energy` → fork parse error | RF1 forbids filter+energy outright (guard) **and** orders `-R` before `-G`; unit-test the order |
| Deployed fork lacks the recorder for live round-trip | RF3 H5 test `@pytest.mark.live`-skips, matching the existing Ladruno convention |
