# Plan — Concurrent geometries S3 (ADR 0058)

**Status:** Ready to implement (2026-06-12). Prereqs all merged:
ADR 0058 (#622), S0 kind registry (#623), S1 scene seam (#625),
S2a per-geometry scenes (#629), S2b concurrent rendering (#636),
S2c picking disambiguation (#647).

S2 made geometries real scene instances that render concurrently and
pick unambiguously. S3 makes them *useful side by side*: a per-geometry
spatial **offset** so two instances can sit next to each other, an
optional **stage_id pin** so one geometry can show stage A while the
viewport scrubs stage B, the **reference-ghost preset** (the most
common FEM-viewer ask), and **duplicate-with-layers** so a comparison
view is one gesture, not a rebuild. As ruled in the ADR, the time
cursor stays **director-global** — per-geometry step cursors were
explicitly rejected; the pin is a *stage* pin whose step is derived
from the one global cursor.

**Memory decision (carried from S2):** plain deep copies, no COW. S3
adds no per-geometry arrays beyond what S2a already copies — offset is
a 3-tuple on `Geometry`, never a baked point array.

## Core architectural decision 1 — offset is a pump-time term, never a transform, never baked state

**Ruling: the offset is applied inside the DEFORM pump as a rigid
translation added to the computed points — `pts = reference_points +
offset + scale·field` — and `FEMSceneData.reference_points` stays the
pristine model baseline.** Offset is geometry state (`Geometry.offset`),
not scene state.

Why not an actor-level transform (`SetPosition` / user matrix)? It
breaks the S2c invariant that **world coordinates == grid coordinates**:

- every pick path (KD-tree node snap, `extract_cells` highlight, box
  projection in `results_pick._build_box_result`) would need a
  world→local conversion keyed on the hit actor's transform, and every
  overlay (probe marker, labels, highlight) the inverse;
- diagram actors are backend-owned (ADR 0042) — there is no per-geometry
  actor enumeration to transform; we'd need a new backend capability
  plus a registry walk, and `sync_substrate_points` consumers (line-force
  local axes, glyph anchors, fiber clouds) recompute geometry *from*
  points, so half of them must receive translated points anyway.

Why not bake the offset into `reference_points` at mutation time? Then
"reference" stops meaning *model reference*: `clone_scene` copies it,
the boot scene's `self._reference_points` alias drifts, and the session
restore / un-offset path must subtract deltas instead of recomputing.
One field, one meaning: `reference_points` = model; `offset` = geometry.

Pump semantics change (the only contract touch):
`_compute_deformed_pts(geom, step)` returns **non-None whenever deform
is enabled OR `geom.offset != (0,0,0)`** — for a deform-off offset
geometry it returns `reference + offset`. The `None` fast-path
(`grid.points = reference.copy()`, diagrams told "back to reference")
is preserved exactly for zero-offset geometries, so every existing
behavior and test is untouched at offset zero. Diagrams cannot tell
offset from deformation — which is precisely the PR #620 contract:
every rendering diagram already proved it re-positions against whatever
points it is handed.

### Consumer disposition under the pump-baked offset

| consumer | disposition |
|---|---|
| substrate fill + wireframe | share `scene.grid` — follow `grid.points` automatically, **zero change** |
| diagrams (`sync_substrate_points(deformed_pts, scene)`) | receive offset points through the one hook — **zero change** (PR #620 contract) |
| DEFORM `None` fast-path (`results_viewer._pump_deform`) | fires only for deform-off **and** zero-offset; otherwise the pump assigns the computed points |
| node cloud (`_sync_node_cloud`) | active-only editing overlay; the pump already passes the active geometry's points. Its `None` branch (boot `self._reference_points`) now only fires at zero offset → stays correct |
| picking (S2c `_actor_scenes` / `scene_resolver`) | world == grid coords — **zero change**. `scene.node_tree` (KD-tree, cached) is invalidated on offset change (RENDER-lane subscriber) so node snaps don't use a stale frame; per-step deform staleness is pre-existing and out of scope |
| box pick | projects `grid.points` → offset-correct automatically |
| node / element label overlays | read the active scene's `grid.points` when rebuilt; the offset event's RENDER-lane subscriber rebuilds them when visible (mirrors `_sync_substrate_visibility`) |
| probe / local-axes overlays | S2c use-time scene resolution reads `grid.points` → correct, **zero change** |
| element pick highlight / cell extract | extracts from the hit scene's grid → correct |
| scalar reads (contours, slabs) | keyed by node/element ID, not coordinates → unaffected |
| stage-activation / dim-filter masks | per-cell, coordinate-free → unaffected |
| camera | bounds widen; no work (user reframes) |
| `reference_points` | **unchanged** — stays the pristine model baseline |

Rejected alternative recorded for the ADR trail: actor transforms (above)
and baked `reference_points` (above).

## Core architectural decision 2 — stage pin = clamp the global cursor into the pinned stage

**Ruling: a geometry pinned to stage S shows S's state at
`clamp(cursor, 0, n_steps(S) − 1)`, where `cursor` is the director's
one global step index mapped onto S.** Concretely, a new director
helper owns the mapping (it owns the combined-mode boundaries):

```python
director.local_step_for_stage(stage_id) -> int
# single-stage mode: clamp(self._step_index, 0, n_steps(S) - 1)
# combined mode:     clamp(global - boundary_start(S), 0, n_steps(S) - 1)
```

Consequences: equal-length stages compare *step-by-step* (mode shapes,
repeated load protocols); when the active stage is longer the pinned
geometry holds at its end-of-history (the "stage A final configuration
vs stage B evolving" use case falls out for free); and in combined
mode a pinned geometry plays its stage's segment and freezes outside
it — construction playback with one frame locked. The rejected
alternative — always freeze at the pinned stage's last captured step —
is strictly less expressive (it is the clamp's behavior whenever the
cursor is past the pinned range) and makes equal-length comparison
impossible.

What the pin scopes (three read paths, one rule — *pinned-or-active*):

1. **Substrate deform** — `_read_deform_field` gains a `stage_id`
   parameter; `_compute_deformed_pts` passes
   `geom.stage_id or director.stage_id` and the clamped step.
2. **The geometry's diagrams** — mirror the S2b `bar_prefix_resolver`
   stamping precedent exactly: `bind_plotter` forwards a
   `stage_pin_resolver(diagram) -> Optional[str]` (owning geometry's
   pin) to the registry, which stamps it on each diagram at
   attach/add. `Diagram._scoped_results()` resolves
   `spec.stage_id or stamped_pin` — an explicit per-diagram
   `spec.stage_id` still wins (ADR: the two pins compose).
   `ReactionsDiagram._scoped_results` (defensive override) gets the
   same fallback — refactor the effective-stage lookup into one base
   helper `Diagram._effective_stage_id()` so the two can't drift.
   The STEP pump becomes pin-aware: the full path loops
   `registry.diagrams()` pushing `local_step_for_stage(pin)` for
   diagrams of pinned geometries, the raw step otherwise (the
   layer-scoped path resolves its one owner the same way).
3. **Per-scene stage-activation masks** — `_sync_stage_layers` /
   `_materialize_scene` currently mirror the *active* stage's
   `LAYER_STAGE` mask onto every scene; they become per-geometry:
   mask for `geom.stage_id or current stage`.
   `StageActivationController` gains `mask_for_stage_id(sid)`
   (parameterized sibling of `current_mask()` — it already holds the
   name map).

**Events and re-attach (ADR 0056 rules).** State lives on `Geometry`
(`stage_id: Optional[str] = None`), so the owner mutator is
`GeometryManager.set_stage_pin(geom_id, stage_id)` firing a new
granular kind `GEOMETRY_STAGE_PIN_CHANGED` (payload geom_id; added to
`_GRANULAR_GEOMETRY_KINDS` for omnibus dedup). Matrix row:
`{STEP, DEFORM}` — GATE is untouched (layer visibility doesn't depend
on the pin) and the mask resync + render ride a RENDER-lane subscriber.
A pin change ALSO requires re-attaching that geometry's diagrams
(stage scoping is resolved at attach: cached step-0 data, ranges —
same reason `set_stage` calls `reattach_all`). Use the
GEOMETRY_REMOVED precedent: the **director registers a typed
GeometryManager observer at `__init__`** (typed observers registered
before the viewer's dispatcher bridge run first), and on
`GEOMETRY_STAGE_PIN_CHANGED` re-attaches only that geometry's attached
diagrams (filtered `_pump_restack` walk via `registry.backend` +
`_scene_for_diagram`). Pumps then run against fresh attachments —
no new dispatcher primitive, no ordering hack.

Documented limitation (not a defect): the Inspector/details panel's
`read_at_pick` keeps reading the active stage. The pick carries
`geometry_id` (S2c) so a future pin-aware read is mechanical; out of
S3 to keep the slice tight. The shift-click time-history snap (the
third S2c deferral) IS made pin-aware here — see S3b.

## Core architectural decision 3 — ghost preset is a GeometryManager verb that creates an EMPTY geometry

**Ruling: `GeometryManager.add_reference_ghost(geom_id)` — a preset
verb on the manager, composing its own mutators; the ghost is
substrate-only (empty compositions) and does NOT use
duplicate-with-layers.** One click produces:

- a new geometry named `"<src> (reference)"`, `visible=True`,
  `deform_enabled=False`, `show_mesh=True`, `show_nodes=False`,
  `display_opacity=GHOST_OPACITY` (module constant, 0.3),
  `offset` and `stage_id` **copied from the source** (the ghost sits
  on the source's frame, in the source's stage context);
- the **source stays active** — the ghost is decoration, not an
  editing target (plain `duplicate` keeps its make-active behavior;
  the preset restores the active pointer);
- **no compositions / layers** — a dimmed reference doesn't want the
  source's contours doubled on top of it. If the user wants layers on
  the ghost, that's duplicate-with-layers + manual deform-off — a
  different gesture for a different intent.

Why the manager and not a viewer function: it is pure state
composition (testable headless, no Qt/plotter), the manager already
owns display state like `display_opacity`, and ADR 0056 wants call
sites calling owner mutators — the outline's context-menu action just
calls the verb inside `dispatcher.gesture_batch()` so the N internal
mutator fires coalesce to one pump + render.

Two notes on existing ghosts:

- **`DeformedShapeDiagram`'s undeformed wireframe ghost**
  (`_runtime_show_undeformed` runtime state, `show_reference` style) —
  **coexists, untouched.** Its retirement is S4's whole job (kind →
  create-geometry sugar + session migration + exemption-list
  deletion). S3 ships the replacement primitive; S4 swaps consumers.
- **Wireframe-only styling** — the ADR's preset sketch says
  "wireframe, dimmed", but `Geometry` has no fill/wireframe split
  (`show_mesh` drives the pair). v1 ghosts are *dimmed* (opacity 0.3
  on fill + wireframe), which reads correctly and occludes less; a
  per-geometry `substrate_style` field is a cheap additive follow-up
  if users ask. Not in S3.

## Core architectural decision 4 — duplicate-with-layers is a director verb that replays the session-restore recipe

**Ruling: `ResultsDirector.duplicate_geometry(geom_id)` — the manager's
`duplicate()` stays the state-only primitive (now also copying `offset`
+ `stage_id`); the director composes it with diagram reconstruction
from each layer's `DiagramSpec`, reusing the exact `_apply_session`
recipe** (`kind_def(spec.kind).diagram_class(spec, results)`, plus
`tag_map=` for `section_cut`). The director is the right owner: it
holds the registry, the bound `Results`, the tag map, and the
geometries — the manager can't construct diagrams and shouldn't learn
how.

Per-layer flow, wrapped in `dispatcher.session_batch()`:

1. `new_geom = geometries.duplicate(geom_id)` (state clone, clone
   becomes active — matching today's duplicate UX).
2. For each source composition: `new_geom.compositions.add(name=...)`;
   for each layer `d`: rebuild `cls(d.spec, results)`, record
   **composition membership first** (`add_layer`), **then**
   `registry.add(...)` — so attach resolves the clone's scene through
   the registry's `scene_resolver` (`geometry_for_layer` hits), not
   the active-geometry fallback. (Wrong-scene attach would be benign —
   clones share cells and the next DEFORM re-points everything — but
   correct-by-construction beats benign.)
3. Restore the clone's active-composition pointer by position.
4. Layers that fail to rebuild (`NoDataError`, unknown kind) are
   skipped and counted — same fail-soft as session restore.

Explicitly **NOT copied** (same rule as session save/restore — *what's
in the spec round-trips, what isn't doesn't*): runtime overrides not
reflected into the spec (`DeformedShapeDiagram._runtime_show_undeformed`,
runtime scale tweaks, live color-map edits), probe/pick state and
highlights, per-scene `ElementVisibility` manual hides (clones are born
unhidden; view-global dim/stage layers re-apply at materialization),
selection log entries. No new copying machinery — if a field should
survive duplication, the fix is "put it in the spec", which also fixes
session restore.

The outline's existing geometry-row **Duplicate** action routes to the
director verb (ADR: "upgrades `GeometryManager.duplicate()` from
'deform state only' to duplicate-with-layers" — the user-facing
gesture upgrades; the manager primitive keeps its narrow contract).

## S3a — per-geometry offset

Touch points:

- `diagrams/_geometries.py` — `Geometry.offset: tuple[float, float, float]
  = (0.0, 0.0, 0.0)`; owner mutator `GeometryManager.set_offset(geom_id,
  offset)` (length-3 validate, float-coerce, no-op on equal, fires
  `GEOMETRY_OFFSET_CHANGED`); `duplicate()` copies it.
- `diagrams/_dispatch.py` — `GEOMETRY_OFFSET_CHANGED` kind; matrix row
  `{DEFORM}`; add to `_GRANULAR_GEOMETRY_KINDS`; docstring table row.
- `results_viewer.py` — `_compute_deformed_pts` adds the offset term +
  the non-None-when-offset rule; `_pump_deform`'s reference branch
  unchanged (it only fires at zero offset now); RENDER-lane subscriber
  on `GEOMETRY_OFFSET_CHANGED`: invalidate that scene's `node_tree`,
  rebuild label overlays if visible, `_apply_geometry_display` not
  needed (no visibility change).
- `ui/_geometry_settings_panel.py` — offset row (three spinboxes, model
  units), `_reflect` + `_fire_offset` → `set_offset` (mirrors the
  scale field's wiring). **Lands last** (viewport-visible change).
- `diagrams/_session.py` — `GeometrySnapshot.offset` (default zero),
  schema **v6**, serialize/deserialize; `results_viewer` session
  capture + `_apply_session` restore via the mutator (order vs other
  fields irrelevant). Legacy sessions read `(0,0,0)`.

Tests (headless unless marked; harness = `tests/viewers/
test_scene_instances_s2{a,b,c}.py` patterns — GeometryManager +
SimpleNamespace director stubs, `NativeWriter` fixture, bound-method
`__get__` tricks):

- mutator: fires `GEOMETRY_OFFSET_CHANGED` with geom_id payload;
  no-op on same value; validates length; `duplicate` copies offset.
- matrix: row is `{DEFORM}`; granular fire suppresses the omnibus.
- pump: two geometries, B offset `(1,2,3)` deform-off → B's
  `grid.points == reference + offset`, A's untouched; B's stub diagram
  received non-None offset points via `sync_substrate_points`; offset
  back to zero → `None` fast-path restored (stub sees None).
- deform + offset compose: `reference + offset + scale·field`.
- node_tree invalidation: cached tree dropped after offset change.
- box pick (S2c stub backend): offset geometry's nodes found at offset
  positions.
- session: v6 round-trip; legacy JSON (no field) loads zero offset.
- qt-marked offscreen (S2c `test_pick_on_second_geometry...` pattern —
  QTimer drive + assertions dict): two visible geometries, B offset →
  grids separated by the offset vector; node pick on B's actor snaps
  to the offset coordinate and carries B's geometry_id.

## S3b — per-geometry stage pin

Touch points:

- `diagrams/_geometries.py` — `Geometry.stage_id: Optional[str] = None`
  (None = follow the active stage); `GeometryManager.set_stage_pin`;
  `duplicate()` copies it.
- `diagrams/_dispatch.py` — `GEOMETRY_STAGE_PIN_CHANGED`, row
  `{STEP, DEFORM}`, granular set, docstring row.
- `diagrams/_director.py` — `local_step_for_stage(stage_id)` (clamp;
  combined-mode boundary window); typed observer registered at
  `__init__` (next to `_drop_scene_for_geometry`): pin change →
  re-attach that geometry's attached diagrams; `bind_plotter` grows
  `stage_pin_resolver` forwarding (S2b `bar_prefix_resolver` pattern).
- `diagrams/_registry.py` — stamp `_stage_pin_resolver` at
  bind/add/reattach (mirror `_stamp_bar_prefix`).
- `diagrams/_base.py` — `Diagram._effective_stage_id()` =
  `spec.stage_id or stamped pin`; `_scoped_results` uses it;
  `diagrams/_reactions.py` override uses the same helper.
- `results_viewer.py` — `_read_deform_field(field, step, stage_id)`;
  `_compute_deformed_pts` resolves pinned-or-active stage + clamped
  step; `_pump_step` pushes per-diagram effective steps;
  `_sync_stage_layers` + `_materialize_scene` apply per-geometry
  masks; RENDER-lane subscriber on the pin event (mask resync via the
  same `_sync_stage_layers`).
- `data/_stage_activation.py` — `StageActivationController.
  mask_for_stage_id(sid)`.
- shift-click time-history (S2c deferral, placed here):
  `director.read_history(node_id, component, stage_id=None)` param;
  `_open_time_history` resolves the pick's `geometry_id` → owner pin.
- `ui/_geometry_settings_panel.py` — stage-pin combo ("Follow active
  stage" + real stages from `director.stages()`, combined excluded).
  **Lands last.**
- `diagrams/_session.py` — `GeometrySnapshot.stage_id` (default None),
  schema **v7**; `_apply_session` sets the pin **after** the
  composition/layer loop (so the director's reattach observer fires
  against recorded membership, once, instead of churning).

Tests:

- mutator + event + matrix row + duplicate-copies-pin (headless).
- `local_step_for_stage`: clamp within/beyond range; combined-mode
  boundary window (stub director state).
- two-stage `NativeWriter` fixture (S2c fixture pattern, two
  `begin_stage` blocks with distinguishable displacement fields):
  pinned geometry B warps from stage 1's field while the director sits
  on stage 2; unpinning re-follows the active stage.
- `_effective_stage_id`: spec pin wins over geometry pin; no pin =
  None; ReactionsDiagram path included.
- pin-change reattach: stub diagrams count detach/attach — only the
  pinned geometry's attached diagrams cycle.
- STEP pump: pinned geometry's diagram receives the clamped step,
  unpinned receives the raw step.
- stage-activation: pinned geometry's scene holds the pinned stage's
  `LAYER_STAGE` mask across an active-stage change (compare
  `ElementVisibility` hidden masks, headless).
- session: v7 round-trip; legacy loads None.
- qt-marked offscreen: two geometries, B pinned to stage "grav" while
  the active stage scrubs — B's `grid.points` stay at the pinned
  field; A follows the cursor.

## S3c — reference-ghost preset + duplicate-with-layers

Touch points:

- `diagrams/_geometries.py` — `GHOST_OPACITY = 0.3`;
  `GeometryManager.add_reference_ghost(geom_id)` per decision 3
  (compose duplicate → rename → deform off → show_nodes off →
  display_opacity → restore source active).
- `diagrams/_director.py` — `duplicate_geometry(geom_id)` per
  decision 4 (session-restore recipe, membership-then-registry order,
  `session_batch` wrap, fail-soft skip count returned).
- `ui/_outline_tree.py` — geometry-row context menu: "Duplicate"
  routes to `director.duplicate_geometry`; new "Add reference ghost"
  action → manager verb inside `gesture_batch`. **Lands last.**
- no session changes — a ghost is an ordinary geometry after creation
  (no linkage field, by design: rename-safe, independently deletable,
  no source-deletion lifecycle questions).

Tests:

- ghost preset (headless): new geometry named `"<src> (reference)"`,
  deform off, visible, `display_opacity == GHOST_OPACITY`,
  `show_nodes` off, offset + pin copied, compositions empty, source
  still active; ghost of a ghost gets a unique name.
- duplicate-with-layers (headless, stub registry/backend + real
  GeometryManager): clone has same composition names/order; rebuilt
  diagrams are distinct instances with equal `(kind, selector, style,
  stage_id)` specs; registry grew by the layer count; clone's layers
  attach against the clone's scene (scene_resolver assertion);
  runtime overrides not copied (DeformedShape clone has default
  `_runtime_show_undeformed`); failing spec skipped, rest land.
- section_cut layer duplicates through the tag_map path.
- qt-marked offscreen: deformed geometry + "Add reference ghost" →
  two substrate pairs visible, ghost at reference (points equal
  reference + source offset), dimmed; duplicate-with-layers on a
  contour geometry → two contour layers, scalar-bar titles carry the
  geometry-name prefix (S2b rule).

## Explicitly out of scope

- **S4**: `DeformedShapeDiagram` retirement, kind → create-geometry
  sugar, session migration of `deformed_shape` specs, deletion of the
  contract-guard exemption list.
- **Mesh-viewer parity** — never in this ADR.
- **Multi-geometry box picking** (S2c deferral, ruled out of S3 too):
  a box over overlapping scenes returns duplicate node/element ids
  with ambiguous attribution, and the pick IR carries ONE
  `geometry_id` per result — widening it to a list is a real IR
  change with no driving use case; S3a offsets *reduce* overlap and
  make active-scene box picks usable. Revisit on demand.
- **GP-marker geometry attribution** (S2c deferral): cosmetic —
  GP picks resolve element ids scene-independently via the inventory
  callback; the future fix is stamping the owner geom id at
  `register_actor` time. Not needed by any S3 feature.
- Pin-aware Inspector/details `read_at_pick` (documented limitation,
  mechanical follow-up via the pick's `geometry_id`).
- Per-geometry step cursor (ADR-rejected), cross-geometry scalar-range
  coupling (ADR v1 ruling), wireframe-only ghost styling
  (`substrate_style` field — additive follow-up), COW memory.

## Suggested PR cut

1. **PR: S3a offsets** — pump term + event + node-tree invalidation +
   session v6 + panel UI last. Behavior-preserving at offset zero;
   existing suite stays green untouched.
2. **PR: S3b stage pin** — the bulk: manager field, director helper +
   reattach observer, resolver stamping, pin-aware STEP/DEFORM/masks,
   time-history, session v7, panel combo last. Independent of S3a
   (touches disjoint state; both rebase clean).
3. **PR: S3c ghost preset + duplicate-with-layers** — needs S3a + S3b
   merged (the preset copies offset + pin); manager/director verbs +
   tests first, outline menu actions last.
