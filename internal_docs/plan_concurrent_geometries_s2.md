# Plan — Concurrent geometries S2 (ADR 0058)

**Status:** Ready to implement (2026-06-11). Prereqs merged or open:
ADR 0058 (#622), S0 kind registry (#623), S1 scene seam (#625).

S1 left exactly one lie in the system: `director.scene_for(geometry)`
returns the same scene for every geometry. S2 makes it true — real
per-geometry `FEMSceneData` instances — and then lets more than one
render. Everything below is sequenced so the viewport change (S2b) is
the *last* thing that moves.

**Memory decision (measured at S1, ADR open question 3):** plain deep
copies. A 23k-node / 124k-tet scene is ~7 MB and `grid.copy(deep=True)`
runs in ~2 ms; a 1M-cell model extrapolates to ~70 MB / ~20 ms per
geometry. No copy-on-write.

## Core architectural decision

**Actor-per-scene, visibility flips, never re-attach.** Each
materialized geometry scene owns its substrate fill + wireframe actors,
added to the plotter once at materialization. "Which geometry renders"
is actor *visibility*, not actor churn:

- S2a (active-only preserved): exactly the active geometry's substrate
  actors are visible; switching geometry = flip two actor pairs + the
  existing DEFORM/GATE pump. No diagram re-attach, no dataset swap.
- S2b (concurrent): visibility = `geometry.visible` (new flag).

Rejected alternative: a single rendered actor whose dataset is swapped
to the active scene's grid — it makes the active geometry special
forever and forces re-pointing machinery S2b would immediately delete.

## S2a — per-geometry scenes + actor switching (active-only rendering)

### Scene materialization

- `ResultsDirector` gains `_scenes: dict[geom_id, FEMSceneData]`.
  `bind_plotter(scene=...)` seeds `{boot_geom.id: scene}` (the boot
  scene keeps its already-built actors). `scene_for(geom)` materializes
  lazily on first miss; `unbind_plotter` clears the dict.
- Materialization = `clone_scene(bound_scene)` helper in
  `scene/fem_scene.py`: deep-copy `grid` (reset points to
  `reference_points` — clones are born undeformed), share the
  immutable index arrays (`node_ids`, `node_id_to_idx`,
  `cell_to_element_id`, `element_id_to_cell`, `cell_dim`,
  `model_diagonal`), copy `reference_points`, leave
  `actor/pick_engine/element_visibility/opacity_controller` None.
  The viewer (not the director) fills the render-side fields — the
  director must stay importable headless; expose a
  `director.on_scene_materialized: Callable[[geom, scene], None] | None`
  hook the viewer sets at `show()`.
- Geometry removal (`GEOMETRY_REMOVED` payload): viewer removes that
  scene's actors; director drops the dict entry. Duplicate: nothing —
  the clone materializes lazily.

### Viewer hook — what materialization wires (the 11 consumers)

Disposition of every `self._scene` consumer category (seam map from
the S1 session; line refs pre-S1 drift slightly):

| consumer | disposition |
|---|---|
| substrate fill + wireframe actors (`results_viewer` ~590/609) | **per-scene** — extract the add_mesh block into `_add_substrate_actors(scene)`; called at show() for boot scene and from the materialization hook; visibility per the render rule |
| `ElementVisibility` (~315) | **per-scene** (wraps the grid's ghost array); dispatcher wiring (~1025) repeats per scene |
| `OpacityController` (~566) | **per-actor** — register the new actors with the existing controller; per-geometry `display_opacity` already exists on `Geometry` |
| pick engine (~310) | **active-only in S2a** — invisible actors aren't pickable; S2c registers all + disambiguates |
| dim filter (~1226) + stage activation masks (~1290) | **view-global state, re-applied per scene**: loop materialized scenes on change; apply current state at materialization |
| node cloud (~634/751/1457) | **stays active-only** — it's an editing aid, not model state; under concurrency it follows the active geometry (decision, not deferral) |
| deform id→row lookup (~815) | shared — every scene indexes the same model (S1 already states this) |
| status line (~1364), node/element label overlays (~2027/2061), probe radius (~2240), cell-extract pick path (~2358) | **active scene** — `self._scene` becomes a property returning `director.scene_for(geometries.active)`; these read it unchanged |

The `self._scene = property` move is the trick that keeps the blast
radius small: every "display-level" consumer keeps compiling and is
automatically right, because in S2a the active scene *is* the display.

### Switching behavior

`GEOMETRY_ACTIVE_CHANGED` already runs DEFORM + GATE. Add one
RENDER-lane subscriber: flip substrate-actor visibility (old active
off, new active on; materialize on demand), re-sync node cloud against
the new active scene, re-apply label overlays if visible. The DEFORM
pump needs **zero changes** — S1's `_render_geometries()` loop +
`scene_for` already do the right thing once scenes differ.

### Tests (S2a)

- Seam: `scene_for(geom_a) is not scene_for(geom_b)`; clone shares
  index arrays, owns points; born undeformed.
- Offscreen GL (local-only, qt-marked — the gallery pattern from
  memory works on this machine): open viewer, add geometry B with
  deform on, switch active A→B→A; assert actor visibility flips and
  `B.scene.grid.points` carries B's deform while A's stays reference.
- Existing 1426-test suite stays green (S2a preserves active-only).

## S2b — concurrent rendering

- `Geometry.visible: bool = True` (new field; session schema additive,
  old sessions load `visible = (geometry is active)` — ADR ruling).
  Owner = `GeometryManager.set_visible()` → new
  `GEOMETRY_VISIBILITY_CHANGED` dispatcher row `{DEFORM, GATE}`
  (ADR 0056: owner-fired; outline geometry eye becomes this flag —
  today's eye drives the `saved_visibility` composition snapshot,
  which gets retired for geometry rows).
- `_render_geometries()` returns visible geometries (one-line change —
  S1 built the loop for this).
- GATE: a layer shows iff `layer.is_visible AND composition gate AND
  owning_geometry.visible`. (Today's gate hides everything outside the
  *active* geometry — replace that test with the visible test.)
- Substrate actor visibility = `geometry.visible AND geometry.show_mesh`.
- Scalar bars: per-diagram (unchanged); when >1 geometry visible,
  prefix bar titles with the geometry name (ADR ruling). Implement in
  `_scalar_bar_support` title resolution — needs the owning geometry's
  name threaded or queried via `geometry_for_layer`.
- STEP pump: `registry.update_to_step` already hits every visible
  attached diagram — correct under concurrency.
- Stage interaction: per-geometry `stage_id` pin is **S3**, not here.
  In S2b every geometry reads the active stage (documented limitation).

### Tests (S2b)

- Two geometries visible, different deform scales → both substrate
  grids at their own configuration in one render (offscreen
  screenshot or actor-visibility + points assertions).
- Gate truth table: (layer ∧ composition ∧ geometry) visibility.
- Old-session restore maps `visible = is-active`.

## S2c — picking disambiguation

- Register every visible scene's actors with the pick engine;
  actor→`(geom_id, scene)` map resolves cell→element against the hit
  scene's `cell_to_element_id`.
- Pick IR (ADR 0045/0047): additive `geometry_id` field; selection log
  and pick reporting carry it. Backends without the field keep working
  (additive widening, ADR 0047 precedent).

## Explicitly out of scope

Per-geometry `stage_id` pin, spatial `offset`, ghost preset,
duplicate-with-layers (all S3); `DeformedShapeDiagram` retirement +
exemption-list deletion (S4); mesh-viewer parity (never in this ADR).

## Suggested PR cut

1. **PR: S2a** (scenes + switching; behavior-preserving) — the bulk.
2. **PR: S2b** (visible flag + concurrent gate + scalar-bar prefix) —
   the user-visible flip, small once S2a lands.
3. **PR: S2c** (picking) — independent of S2b's UI, needs S2a.
