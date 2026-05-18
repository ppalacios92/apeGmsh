# API Flow Atlas

An interactive, single-page map of how apeGmsh's public methods route data
through the library. Pick any action and the package map highlights the
exact path it takes, while the side panel annotates **what is handed off at
each hop**.

**Scope:** the whole library at **public-entry-API depth** — every
user-callable method traced as its own flow. Model-building (`model`,
`parts`, `physical`, `labels`, `sections`, `mesh`, `mesh_selection`),
the **FEMData / resolution** pipeline (`constraints` / `loads` /
`masses` → `fem.nodes` / `fem.elements`, plus `.select()` chains), the
**OpenSees bridge** (`apeSees(fem)` + typed primitives + emitters),
**Results** post-processing (constructors, composites, slabs, plot),
**cuts / sweeps / drift**, **ground motions**, the **viewers** (public
entry points only), `viz`, and the public **FEM-theory** helpers.
Internal Qt/VTK widgets and private reader/writer plumbing are not
expanded — hops that leave into them are flagged.

`905 methods · 96 packages · 294 hops`, driven entirely by
[`flows.json`](flows.json).

[Open the Atlas full-screen :material-open-in-new:](atlas.html){ .md-button .md-button--primary target="_blank" rel="noopener" }

!!! tip "Best viewed full-screen"
    The Atlas is a full-viewport app (index · package map · step panel).
    The inline preview below works, but the **Open full-screen** button
    above gives it the room it needs.

<iframe
  src="atlas.html"
  title="apeGmsh API Flow Atlas"
  loading="lazy"
  style="width:100%; height:80vh; min-height:620px; border:1px solid var(--md-default-fg-color--lightest); border-radius:8px; background:#0e1116;">
</iframe>

## How to read it

- **Left — index:** every method, grouped by composite. Search with `/`,
  or click a node in the map to filter the index to everything that routes
  through it.
- **Center — package map:** faint by default. Selecting a method lights
  only its path, numbers the packages in call order, and labels the active
  hop with the data passed. Drag to pan, wheel to zoom.
- **Right — step panel:** the ordered hops. Each card shows the action and
  a highlighted **“passes / hands off”** box (the cross-method data
  contract), then the method's inputs / outputs / reads / writes and its
  `src/…:line`. Two-stage pipelines are traced end to end (e.g.
  `g.constraints.tie` → defs → resolver → records → `fem.elements`).
- Deep-link a method with `#<method-id>`; `↑`/`↓` step through hops;
  `Esc` clears.

## Maintaining the data

[`flows.json`](flows.json) is the source of truth. The Atlas fetches it
at runtime when the site is served, so edits appear on refresh. The page
also keeps an embedded copy so it still works when opened directly from
disk (`file://`, where browsers block local `fetch`). After editing
`flows.json`, refresh that embedded fallback:

```bash
python docs/api-flows/_embed.py
```

The helper is idempotent and re-validates the JSON (schema keys,
referential integrity, embedded-copy round-trip) on every run.
