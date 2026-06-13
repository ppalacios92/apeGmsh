# Plan — Concurrent geometries S4 (ADR 0058)

**Status:** Ready to implement (2026-06-13). The ADR close-out. Prereqs
all merged: S0 kind registry (#623), S1 scene seam (#625), S2a/b/c
(#629/#636/#647), S3a/b/c (offsets, stage pin, ghost preset +
duplicate-with-layers). `GeometryManager.add_reference_ghost` and
`ResultsDirector.duplicate_geometry` already exist on main.

S3 shipped the *replacement primitives*: the reference ghost
(`add_reference_ghost`, `GHOST_OPACITY=0.3`,
`src/apeGmsh/viewers/diagrams/_geometries.py:235`) is the inverse-preset
that produces a deform-off dimmed wireframe geometry, and a deform-on
geometry is what `set_deformation(...)` already makes. S4 is the *swap*:
retire `DeformedShapeDiagram`, delete the now-empty contract-test
exemption, and make legacy sessions carrying a `deformed_shape` spec
load cleanly.

**Almost certainly ONE PR.** The work is a delete + a guard-unlocking +
a session no-op. No new state, no new event, no schema bump. Commit
sequence below.

## Why this is a plan and not a blind delete

Two sharp edges, both ruled here from the source:

1. The contract-test exemption deletion makes
   `test_deform_follow_contract.py`'s walk **unconditional** — get the
   exact mechanism right or the guard silently keeps exempting
   something.
2. A legacy session with a `deformed_shape` spec must still load. The
   existing fail-soft restore path already drops unknown kinds — so the
   question is whether "drop + log" is sufficient or whether to
   auto-convert. Decided below from `_apply_session` /
   `deserialize_session` behavior.

---

## Ruling 1 — what replaces it (capability-neutral check: PASS)

`DeformedShapeDiagram` does exactly two things
(`src/apeGmsh/viewers/diagrams/_deformed_shape.py`):

* **warps its own copy** of the substrate by `base + scale·disp`
  (`_warped_points`, reading `style.components` =
  `displacement_x/_y/_z` at the global step) and emits a solid
  *deformed* `MeshLayer`;
* renders an **optional undeformed wireframe ghost**
  (`_runtime_show_undeformed` / `style.show_undeformed`,
  `undeformed_color` `#888`, `undeformed_opacity` 0.25) behind it.

Both are covered by the S1–S3 model:

| DeformedShapeDiagram behavior | Replacement |
|---|---|
| warped deformed mesh | a **geometry with deform on** (`set_deformation(enabled=True, field=..., scale=...)`) — the DEFORM pump warps its `scene.grid.points` directly (`results_viewer._read_deform_field`, `:949`) |
| undeformed wireframe ghost | the **S3c reference-ghost preset** — `add_reference_ghost` clones the source deform-off, `display_opacity=GHOST_OPACITY`, dimmed (the ADR's "inverse preset") |
| "deformed overlay on the reference mesh" (both at once) | **two geometries**: one deform-on + its reference ghost, rendered concurrently (S2b `visible`) |
| per-step re-warp, scale tweak | geometry `deform_scale` + the per-geometry DEFORM pump (S2/S3) |

**One field-name mapping wrinkle (not a gap):** the diagram reads the
explicit component tuple `style.components`
(`displacement_x/_y/_z`); geometry deform reads a **base field name**
and appends `_x/_y/_z` itself (`_read_deform_field`, `:955`). The
canonical default maps cleanly (`displacement_{x,y,z}` → base
`"displacement"`). The replacement primitives already exist and are
field-name-agnostic — there is **no capability lost**. The only thing
that does not survive is a `DeformedShapeStyle` built on a
*non-suffixed / mixed* component set (e.g. `("velocity_x",
"displacement_y")`) — a configuration with no UI to create it (the Add
Diagram dialog only ever emits default-component styles) and no known
user. Documented as a non-defect; the migration (Ruling 3) handles it
by dropping such specs fail-soft, same as any unconvertible spec.

**Wireframe-vs-dimmed cosmetic note (carried from S3c, not reopened):**
the old ghost is a true *wireframe*; the S3c ghost is *dimmed fill +
wireframe* (opacity 0.3). S3c already ruled this an acceptable
substitute (reads correctly, occludes less); a per-geometry
`substrate_style` field is the additive follow-up if users ask. Out of
S4.

## Ruling 2 — exemption deletion (the contract goes unconditional)

The sole exemption today
(`tests/viewers/test_deform_follow_contract.py:31`):

```python
_EXEMPT: dict[str, str] = {
    "DeformedShapeDiagram": "renders its own warp from the displacement field",
}
```

`test_every_rendering_diagram_overrides_sync_substrate_points` walks
every `Diagram` subclass under `apeGmsh.viewers.diagrams` and asserts
each one overrides `sync_substrate_points` *unless its name is in
`_EXEMPT`*. Once `DeformedShapeDiagram` is deleted, `_EXEMPT` is empty.

**Decision: delete the `_EXEMPT` dict and the skip branch entirely**, so
the contract is structurally unconditional — *every* discovered diagram
must override the hook, no exemption mechanism remains to grow back
(this is the ADR Part 3 promise: "no exemption mechanism exists to grow
back"). Concretely:

* delete the `_EXEMPT` literal and its docstring paragraph (the
  module docstring's "A diagram may be exempted ONLY if…" sentence);
* in `test_every_rendering_diagram_overrides_sync_substrate_points`,
  drop `if cls.__name__ in _EXEMPT: continue`;
* delete `test_exempt_list_is_live` (it only guards the now-gone dict).

`test_discovery_sees_the_diagram_family` stays unchanged (its pinned
set — Contour/Fiber/LayerStack/LineForce/SpringForce — never included
DeformedShape).

**Verified no non-DeformedShape reliance:** `_EXEMPT` has exactly one
entry; grep of the test confirms nothing else reads it. Every other
rendering diagram already overrides `sync_substrate_points` (that is
what keeps the suite green today), so emptying the exemption asserts
nothing new about them — it only removes the one escape hatch.

## Ruling 3 — session migration = **drop + log** (no schema bump)

A legacy session JSON carries `deformed_shape` in its flat
`diagrams[]` list, referenced by a composition's `layer_indices`. Trace
the load path on main:

1. `deserialize_spec` (`_session.py:162`) calls `style_class_for(kind)`;
   once the kind is unregistered this returns `None` → `deserialize_spec`
   raises `KeyError`.
2. `deserialize_session` (`:347`) wraps each spec in `try/except: continue`
   — the `deformed_shape` spec is **silently dropped from `diagrams`**.
3. `_apply_session` (`results_viewer.py:2405`) builds `restored_layers`
   index-aligned to `session.diagrams`; a dropped spec simply isn't in
   that list, and any composition `layer_index` pointing past it is
   guarded by `if 0 <= idx < len(restored_layers)` + `if d is not None`
   (`:2477`). **The hierarchy restores intact minus the retired layer.**

So fail-soft drop is **already the behavior** the moment the kind leaves
the registry — no migration code is strictly required. The only gap is
*visibility*: today it's silent.

**Decision: drop + one explanatory log, no auto-convert, no schema bump.**

* Keep it drop-not-convert because (a) the replacement is a *geometry*,
  not a layer — auto-spawning a geometry from inside the per-spec layer
  loop would cross-cut the geometry-snapshot loop that runs after it and
  muddy index alignment; (b) the field-name mapping is lossy for
  non-default component sets (Ruling 1); (c) "what's in the spec
  round-trips, what isn't doesn't" — the user's *saved geometry deform
  state* (if they had a deform-on geometry) already round-trips via
  `GeometrySnapshot`; the `deformed_shape` *layer* was the legacy
  mechanism being retired, and a viewer reopened post-S4 will simply not
  show that one layer. The user re-adds it as deform-on + "Add reference
  ghost" — two clicks, the new idiom.
* Make the drop **visible**: add a recognized-but-retired branch so the
  log says *why* rather than "unknown kind". Two clean options — pick
  the lighter:
  - **(preferred)** in `deserialize_spec`, special-case
    `kind == "deformed_shape"` to raise a typed/worded `KeyError`
    ("retired in ADR 0058 S4 — re-add as a deform-on geometry + Add
    reference ghost"), so the existing `except: continue` still drops it
    but a debug log (if added) reads clearly; OR
  - count retired-kind drops in `_apply_session` alongside `n_skipped`
    and `report(...)` a one-line note.
  Either is ~5 lines. **No `SESSION_SCHEMA_VERSION` bump** — the on-disk
  shape is unchanged; we're removing a readable kind, which the format
  already tolerates (missing/unreadable specs degrade by design,
  `_session.py:50` "missing fields read as defaults").

**Reserve the kind string?** No live registration, but keep
`"deformed_shape"` *recognized as retired* in the one
`deserialize_spec` branch above so the log is specific. That string is
not re-registered and is not a `DiagramKindDef` — it exists only as a
migration-recognition literal.

## Ruling 4 — removal scope (the delete list)

**Delete:**

* `src/apeGmsh/viewers/diagrams/_deformed_shape.py` — the whole module
  (class + `@register_diagram_kind` decorator, so it leaves the
  registry).
* `DeformedShapeStyle` — `src/apeGmsh/viewers/diagrams/_styles.py:419`
  (no other diagram references it; grep-verified). Remove its `__init__`
  export too.
* `__init__.py` (`diagrams/`): the `from ._deformed_shape import
  DeformedShapeDiagram` import (`:9`), and the `DeformedShapeDiagram` /
  `DeformedShapeStyle` `__all__` entries (`:40/:41`) + the
  `DeformedShapeStyle` re-export (`:23`). Fix the package docstring line
  (`:4`) that name-drops it.
* `ui/_add_diagram_dialog.py`: nothing to delete structurally — it reads
  `all_kinds()`, so unregistering removes the combo entry automatically.
  **Verify** the dialog has no `deformed_shape`-specific branch (grep:
  it does not; only `section_cut` is special-cased). The dialog's
  generic `kind_entry.diagram_class(spec, …)` path simply never sees the
  kind again.
* `ui/_diagram_settings_tab.py`: the `_dispatch_kind_panel` branch
  `elif kind == "deformed_shape": self._build_deformed_panel(d)`
  (`:801`) and the `_build_deformed_panel` method itself (the scale
  slider + show-undeformed toggle, reading `_runtime_show_undeformed`
  `:1277`). No diagram of that kind can exist post-S4, so the panel is
  dead.
* `results/demo.py:72-81` — the `DeformedShapeDiagram` / `_spec` /
  `registry.add` block. Replace with the new idiom
  (`geometries.set_deformation(...)` on the boot geometry, optionally
  `add_reference_ghost`) **or** drop the deform line from the demo if it
  over-complicates it — demo is illustrative, keep it minimal.
* Tests that *construct* it — `test_deformed_diagram.py` (delete; its
  subject is gone), and the `DeformedShape`/`deformed_shape` references
  in `test_add_diagram_dialog.py`, `test_add_diagram_dialog_topology.py`,
  `test_diagram_kind_registry.py`, `test_diagram_topology.py`,
  `test_inplace_mutation.py`, `test_diagrams_perf_audit.py`,
  `test_style_presets.py`, `test_session_persistence.py`,
  `test_scene_instances_s3c.py`, `_render_screenshots.py`. Audit each:
  if the test merely *includes* deformed_shape in an "every kind" sweep,
  drop that kind from the expectation; if it's deformed-shape-specific,
  delete the case. (`test_scene_instances_s3c.py` references it only in
  the "runtime overrides not copied" assertion of duplicate-with-layers
  — replace with another runtime-override example or drop that sub-
  assertion.)

**Keep:**

* `_kinds.py` `register_diagram_kind` / `in_catalog` machinery — generic,
  unrelated. Drop only the `deformed_shape` example mention in its
  docstring (`:67`).
* `_kind_catalog.py` — `deformed_shape` is already *absent* from the
  catalog (`in_catalog=False`); the docstring notes (`:19`, `:231`)
  cite it as the canonical opt-out example. Either update those mentions
  to `section_cut` (still a valid `in_catalog=False` example) or leave
  them as historical ADR-0058 references — cosmetic, low-priority; do
  the rename to avoid a dangling name.
* The `"deformed_shape"` string in `deserialize_spec` (Ruling 3
  migration-recognition literal) — the only place the name survives in
  source.
* `_base.py:65` / `:238` — docstrings using `deformed_shape` /
  `DeformedShape` as examples; swap to `contour` so no dangling
  reference (cosmetic).
* The two ADR-0056 mentions of `_runtime_show_undeformed`
  (`0056-...md:51/:127`) — historical decision text, **do not edit**
  (ADRs are immutable records). ADR 0058 itself is updated to
  Status: Accepted (see PR cut).

## Ruling 5 — PR cut (one PR)

**PR: S4 — retire DeformedShapeDiagram (ADR 0058 close-out).**

Commit sequence (each leaves the suite green):

1. **Delete the diagram + style + exports.** Module, `DeformedShapeStyle`,
   `__init__` import/`__all__`. The contract test goes RED here (exemption
   names a class that no longer exists → `test_exempt_list_is_live`
   fails) — fixed in commit 2, same PR.
2. **Unlock the contract.** Delete `_EXEMPT` + the skip branch +
   `test_exempt_list_is_live`; the walk is now unconditional and green.
3. **Prune the UI + demo + remaining tests.** `_diagram_settings_tab`
   panel branch + method, `demo.py` block, the test-sweep references and
   `test_deformed_diagram.py`. Cosmetic docstring swaps
   (`_base`, `_kinds`, `_kind_catalog`).
4. **Session migration log.** The `deserialize_spec` retired-kind branch
   (Ruling 3) + a focused test: a session JSON containing a
   `deformed_shape` spec restores its other layers intact and drops the
   retired one fail-soft (no raise, hierarchy preserved). No schema bump.
5. **ADR 0058 → Accepted.** Flip the Status header; one line noting S4
   shipped and the contract is unconditional.

Tests to add/confirm:
* contract guard runs unconditionally and passes (commit 2).
* `style_class_for("deformed_shape") is None` and
  `kind_def("deformed_shape") is None` (registry clean).
* legacy-session restore drops the retired spec, keeps siblings
  (commit 4) — model on `test_session_persistence.py`'s round-trip
  fixtures.
* full `tests/viewers` suite green; mypy baseline not raised.

## Explicitly out of scope

* Wireframe-only ghost styling (`substrate_style` field) — S3c additive
  follow-up, not reopened.
* Auto-converting a legacy `deformed_shape` spec into a spawned deform-on
  geometry (Ruling 3 rejected it: lossy field mapping, cross-cuts the
  snapshot loop, no driving use case).
* Mesh-viewer parity — never in this ADR.
* Any change to the per-geometry DEFORM pump / scene model (S1–S3 own
  it; S4 only deletes a consumer).
