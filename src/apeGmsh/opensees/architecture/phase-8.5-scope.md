# Phase 8.5 — Broker-side neutral-zone writers in `model.h5`

**Status:** Scoping (May 2026).  Drafted in parallel with the
[Phase 8.4 scope](phase-8.4-scope.md); 8.4 and 8.5 are independent
and can land in either order.

This phase makes the **broker** (`FEMData`) write the neutral-zone
groups in `model.h5` — the groups the master plan
([phase-8-untangle.md §3](phase-8-untangle.md)) puts at the root
without an `/opensees/` prefix.  After this phase, `model.h5` is
self-sufficient: a viewer can render the geometry without
instantiating an OpenSees deck.

This phase is **additive** — it adds new groups and a new entry
point.  It is not breaking on its own.  (8.4 is the breaking
half of the model.h5 reshuffle; 8.5 fills out the neutral half.)

## 1. The change

### 1a. Groups added

Seven new neutral-zone groups under the root, plus an extension to
the existing `/elements/{type}` group (currently bridge-written;
broker takes over):

| Path | Owner | Source-of-truth on `FEMData` | Status today |
|---|---|---|---|
| `/nodes` | broker | `fem.nodes` (`NodeComposite`) | absent in `model.h5` |
| `/elements/{type}` | broker | `fem.elements` (`ElementComposite`) | bridge writes today; broker takes ownership |
| `/physical_groups` | broker | derived from PG membership on `fem.nodes` / `fem.elements` | absent |
| `/labels` | broker | derived from label membership on `fem.nodes` / `fem.elements` | absent |
| `/constraints/{kind}` | broker | `fem.nodes.constraints` + `fem.elements.constraints` | absent |
| `/loads/{kind}` | broker | `fem.nodes.loads` + `fem.elements.loads` | absent |
| `/masses` | broker | `fem.nodes.masses` (`MassSet`) | absent |

The OpenSees-resolved `/bcs/fix` and `/bcs/mass` (currently at root,
moves to `/opensees/bcs` in 8.4) are NOT touched by 8.5 — those are
solver-resolved enrichment, not solver-neutral broker state.

### 1b. New entry point

```python
fem = g.mesh.queries.get_fem_data(dim=3)
fem.to_h5("model.h5")     # writes neutral zone only
```

`FEMData.to_h5(path)` — new public method.  Writes the seven groups
above plus `/meta` (re-using the meta attrs the bridge already
writes; defaults populated from `fem.snapshot_id`,
`fem.info.ndm` etc.).  Does NOT write any `/opensees/` content;
absent enrichment is the right "no solver" signal.

The bridge's `apeSees(fem).h5(path)` continues to be the way to
get a fully enriched file — internally it will call
`fem.to_h5(path)` for the neutral zone, then write its own
`/opensees/` enrichment.  Same file format either way.

### 1c. Symmetric record-compound-dtype helper

Master plan §3 specifies that every record-set group
(`/constraints/{kind}`, `/loads/{kind}`, `/masses`, `/bcs/fix`,
`/bcs/mass`, `/patterns/{name}/loads`) shares the same outer
compound shape so the viewer can use one reader:

```
target_kind   vlen utf-8     "node" | "element" | "pg"
target        vlen utf-8     tag (str) or pg name
payload_kind  vlen utf-8     record subtype (e.g. "rigid_beam",
                              "point_load", "lumped")
payload       compound       subtype-specific typed fields
```

A helper, e.g. `mesh/_record_h5.py::make_record_dtype(payload_dtype)`,
returns the 4-field compound for any payload dtype.  Every
record-set writer (broker-side or bridge-side) calls through it so
the contract holds without duplication.

### 1d. Source-side surface

| File | What changes |
|---|---|
| `src/apeGmsh/mesh/FEMData.py` | Add `to_h5(path)` public method.  ~15 lines (mostly delegation to a new helper). |
| `src/apeGmsh/mesh/_femdata_h5_io.py` (NEW) | The actual neutral-zone writer.  Mirrors the existing `_femdata_native_io.py` pattern (which writes a `/model/` SUB-group inside results files — see §2 below). |
| `src/apeGmsh/mesh/_record_h5.py` (NEW) | The symmetric-record-compound-dtype helper + per-kind payload dtypes. |
| `src/apeGmsh/opensees/emitter/h5.py` | (a) Stop writing `/elements/{type}` directly (broker owns that group now). (b) Optionally call `fem.to_h5(path)` internally to populate the neutral zone before writing `/opensees/...`.  See §3 flavors. |
| `src/apeGmsh/opensees/emitter/h5_reader.py` | Add typed accessors for the new neutral-zone groups: `nodes()`, `elements()` (already exists — adjust shape), `physical_groups()`, `labels()`, `constraints()`, `loads()`, `masses()`. |
| `src/apeGmsh/opensees/architecture/h5-schema.md` | Document the neutral zone (per-group sections + the symmetric compound dtype). |

### 1e. Test-side surface

| File | What changes |
|---|---|
| `tests/opensees/h5/test_h5_emitter.py` | The bridge-only writer tests should still pass (since 8.5 doesn't change /opensees/ paths).  The `/elements/...` literal-path assertions need updating if the broker's `/elements/{type}` shape differs from the bridge's. |
| `tests/opensees/h5/fixtures.py` | Fixtures may grow `/nodes`, `/physical_groups`, etc. in their `expected_groups` lists if the bridge's `apeSees(fem).h5(...)` flow now invokes the broker writer. |
| `tests/mesh/test_femdata_to_h5.py` (NEW) | Round-trip the neutral zone: build a FEMData, call `to_h5`, re-open, assert each group's shape + content. |
| `tests/mesh/test_record_h5_dtype.py` (NEW) | Unit-test the symmetric compound dtype helper for all payload kinds. |

The existing `tests/test_results_femdata_native_roundtrip.py` and
the ~10 `to_native_h5` mock stubs in `tests/test_results_*` are NOT
affected — those exercise `_femdata_native_io.py` (the `/model/`
sub-group writer used by Results), which 8.5 leaves alone.

### 1f. Doc-side surface

| File | What changes |
|---|---|
| `architecture/h5-schema.md` | Per-group sections for each new neutral group; symmetric-compound-dtype contract section. |
| `architecture/viewer-integration.md` | The neutral zone is the viewer's primary substrate post-8.7; document the new accessors. |
| `architecture/phase-8-untangle.md` | Mark Phase 8.5 as landed once the implementation PR ships; refresh §6 acceptance criteria. |

## 2. Coexistence with `_femdata_native_io.py`

`mesh/_femdata_native_io.py` already exists (421 lines) and writes
a FEMData snapshot under a `/model/` sub-group — but inside
**results files**, not as a standalone `model.h5`.  Used by
`results/writers/_native.py:134` to embed the producing geometry
alongside the response data so a results consumer can rebuild the
mesh without a separate file.

The master plan ([§7 Q2](phase-8-untangle.md)) explicitly addresses
this: "Different layout, different consumer, NOT a duplicate of
`fem.to_h5(path)`. Keep both."

So the plan is:

| File | Writes to | Consumer |
|---|---|---|
| `_femdata_native_io.py::write_fem_to_h5(fem, group)` | `<results_file>.h5/model/...` (sub-group inside an open results file) | Results-side embedded snapshot |
| `_femdata_h5_io.py::write_fem_h5(fem, path)` (NEW) | `<path>.h5/{nodes,elements,...}` (root of a fresh model.h5) | Viewer / external tooling |

They share dataclass shapes (Nodes, Elements) but emit at different
roots.  We could refactor to share a common low-level writer down
the road, but for 8.5 we keep them separate — `_femdata_native_io`
is mature and not breaking; touching it is out of scope.

## 3. Design tension

There are three real choices to make in 8.5; none is the kind of
deep architectural fork that 8.3b's Flavor 1 vs. 2 was, but each
needs a deliberate call.

### Choice 1 — Where do the bridge's element-args go?

The current `/elements/{type}` group (h5.py:1051) holds OpenSees-
specific metadata: `args` numeric array, `str_args` string array,
`__deviation__` annotations, the `type` attr.  Broker takes over
the group in 8.5 — the broker's version holds only neutral data
(`ids`, `connectivity`).  Where do the bridge's args go?

- **A. `/opensees/element_meta/{type}/{args, str_args}`** — bridge
  writes its OpenSees-specific element metadata under a new
  `/opensees/` subpath.  Clean separation; broker owns
  `/elements/{type}`, bridge owns `/opensees/element_meta/{type}`.
  *Recommended.*
- **B. Co-locate under `/elements/{type}/args`** — broker writes
  `ids`/`connectivity`; bridge appends `args`/`str_args` to the
  same group.  Simpler file shape but couples the two writers
  (bridge must run after broker; partial ownership of one group).
- **C. Drop the bridge's element-args entirely.**  If nothing
  reads them, delete.  Audit: `recording.py` and `tcl.py` may
  reference them via the `_ElementRecord.args` Python field, but
  the H5 datasets themselves are written in case a downstream
  consumer wants them — actual reader of `/elements/{type}/args`
  is unclear today.  Worth checking before deletion.

### Choice 2 — Should `apeSees(fem).h5(path)` invoke `fem.to_h5(path)` internally?

Two flows:

- **A. Composed flow** — `apeSees(fem).h5(path)` opens the file,
  delegates the neutral zone to a helper that mirrors
  `fem.to_h5(path)`, then writes its `/opensees/...`.  One file
  produced; identical layout whether the user calls `apeSees.h5`
  or `fem.to_h5`.  *Recommended.*
- **B. Two-step flow** — user calls `fem.to_h5(path)` first, then
  `apeSees(fem).h5(path, mode="a")` appends `/opensees/...`.
  Cleaner API contract per method but requires user discipline
  for the order.  Awkward for the common "I just want one file"
  case.

### Choice 3 — Compound payload shape: per-kind dtype vs. opaque blob?

The master plan's "same compound shape" guidance is interpretable
two ways:

- **A. Per-kind payload dtype (typed).**  Each `/constraints/{kind}`
  dataset has its own compound dtype where the `payload` field is a
  per-kind nested compound.  `/constraints/rigid_beam` has
  `payload = (master:int, slave:int, dofs:vlen-int, offset:(3,)f64)`;
  `/constraints/equal_dof` has `payload = (master:int, slave:int,
  dofs:vlen-int)`.  Outer 4-field shape uniform; payload typed per
  kind.  *Recommended — h5dump-friendly, viewer reads with one
  function but per-kind decoders.*
- **B. Opaque vlen-bytes payload.**  The `payload` field is a
  vlen-bytes blob; readers parse per `payload_kind`.  Most uniform
  outer shape (every dataset truly identical), but loses HDF5's
  introspection benefit.

Recommendation: ship A.  More typing work in the dtype helper but
the file stays inspectable with `h5dump`.

### Recommendation summary

- Choice 1: A (`/opensees/element_meta/{type}`).
- Choice 2: A (`apeSees.h5` composes `fem.to_h5` + `/opensees/`
  in one call).
- Choice 3: A (typed per-kind payload compounds).

All three are the "more code, more correct" answer and follow the
same minimum-viable-change instinct as 8.3b / 8.4.

## 4. Phase 8.5 sub-commits

Four-to-six commit shape, depending on how Choice 1 lands:

### Commit 1 — `_record_h5.py`: symmetric compound dtype helper

Add `mesh/_record_h5.py` with `make_record_dtype(payload_dtype)`
and per-kind payload dtype factories
(`constraint_payload_dtype("rigid_beam")` etc.).  Pure helper +
unit test (`test_record_h5_dtype.py`).  No callers yet.

### Commit 2 — `_femdata_h5_io.py`: neutral-zone writer

Add `mesh/_femdata_h5_io.py` with `write_fem_h5(fem, path)`.
Implements the seven new groups + `/meta`.  Uses the helper from
commit 1 for record-set datasets.  Add `FEMData.to_h5(path)` public
method delegating to it.  New test
`tests/mesh/test_femdata_to_h5.py` round-trips a representative
FEMData.

### Commit 3 — Reader accessors for the neutral zone

Extend `emitter/h5_reader.py` with typed accessors for the seven
new groups (`nodes()`, `physical_groups()`, `labels()`,
`constraints()`, `loads()`, `masses()`; adjust `elements()` shape
if needed).  Update existing tests.

### Commit 4 — Bridge integration: `apeSees.h5(path)` composes the neutral zone

Modify `emitter/h5.py` so `apeSees(fem).h5(path)` invokes the
neutral-zone writer first, then writes its `/opensees/...`.  Stop
writing `/elements/{type}` directly — that group is now broker-
owned.

### Commit 5 — Bridge element-args relocation

Move the OpenSees-specific element metadata (`args`, `str_args`,
`__deviation_*`) from the bridge's now-deleted `/elements/{type}`
writer to `/opensees/element_meta/{type}` (Choice 1, Flavor A).
Update tests and docs.

### Commit 6 — Doc rewrite: `h5-schema.md` + `viewer-integration.md` neutral zone

Per-group sections for `/nodes`, `/elements/{type}`,
`/physical_groups`, `/labels`, `/constraints/{kind}`,
`/loads/{kind}`, `/masses`.  Symmetric compound dtype contract
section.  Refresh `viewer-integration.md` to point the geometry
panels at the broker zone.

(Commits 4 + 5 can ship together if the element-args relocation
diff stays small; keep separate if it grows.)

## 5. Verification gates (per commit)

Same as previous Phase-8 PRs:

- `mypy --strict src/apeGmsh/`
- `ruff check src/apeGmsh/ tests/`
- `pytest -m "not live and not subprocess" --ignore=tests/acad --continue-on-collection-errors`

Each commit's verification: no new errors / regressions relative
to the pre-PR baseline.  Re-measure at PR-open time.

Special checks for this phase:

- `fem.to_h5(path)` produces a file that `h5_reader.open` can
  read; `validate()` returns empty.
- Round-trip: every record on a representative FEMData survives
  `write → read → reconstruct` with bit-identical fields (modulo
  numpy's float64 representation).
- `apeSees(fem).h5(path)` after commit 4 produces a file with
  both neutral and `/opensees/...` zones populated.
- Existing `_femdata_native_io.py` `/model/` writer untouched;
  `tests/test_results_femdata_native_roundtrip.py` still passes.

## 6. Open questions for the implementing session

1. **`schema_version` interaction with 8.4.**  If 8.5 lands BEFORE
   8.4, schema is `1.1.0` and the additive new groups are a
   `1.2.0` minor bump.  If 8.5 lands AFTER 8.4, schema is `2.0.0`
   already and the additive new groups are a `2.1.0` minor bump.
   Both are correct per the schema-version contract; the
   implementer just bumps to whichever the current major-tagged
   minor is.

2. **`/elements/{type}` rename vs. retention.**  Bridge currently
   uses `element_group_name(type_token)` which converts e.g.
   `forceBeamColumn` → `forceBeamColumn` (identity in most cases).
   Broker doesn't have a "type token" concept — it has GMSH element
   type names (`triangle3`, `quad4`, `tet4`, …).  Are the two
   namespaces compatible (e.g. `tet4` for the broker matches what
   the bridge would have written for a 4-node tet element type)?
   If not, who wins?  Recommendation: broker wins — bridge
   adapts its element-meta keying to match.

3. **Empty-FEMData handling.**  `fem.to_h5(path)` on a FEMData
   with no constraints / no loads / no masses: write empty
   datasets, omit the groups entirely, or write the groups with
   zero-row datasets?  Recommendation: omit empty groups (matches
   bridge's behaviour for `/bcs`, `/recorders`, `/analysis` —
   absence means "user did not declare this").

4. **Composite-aware vs. flat record iteration.**  The broker has
   `fem.nodes.constraints.by_kind("rigid_beam")` etc.  The writer
   could iterate by sub-composite (NodeConstraintSet,
   SurfaceConstraintSet) and infer `target_kind="node"` /
   `"element"` from the source, or it could collapse everything
   into a single flat list with explicit `target_kind` per record.
   Recommendation: iterate per sub-composite — preserves
   provenance and matches how the in-memory shape lives.

5. **Performance.**  Large meshes (>1M nodes) may need chunked /
   compressed writes for `/nodes/coords` and per-PG membership
   datasets.  Recommendation: defer compression to a follow-up;
   ship 8.5 with default contiguous writes, profile if it becomes
   a problem.

6. **Backward-compat shim for existing `apeSees.h5(path)` callers.**
   No callers exist outside the emitter test suite (audit
   confirmed in 8.4 scope §1b).  No shim needed.

## 7. Out of scope (defer to later phases)

- **`/opensees/tag_map`** — Phase 8.6 (additive).
- **Viewer migration off `FEMData` / `solvers`** — Phase 8.7,
  consumes the post-8.5 schema.
- **Ordering vs. Phase 8.4** — independent; either order works
  per §6 Q1.
- **`_femdata_native_io.py` consolidation** — different consumer
  (Results-side embedded snapshot), keep separate per master plan
  §7 Q2.
- **Compression / chunking for large meshes** — defer per §6 Q5.
- **A second solver writing its own enrichment zone** —
  the namespace makes room for it but the actual plug-in is its
  own project.

## 8. Risk assessment

The master plan ([phase-8-untangle.md §5](phase-8-untangle.md))
rated 8.5 as **medium risk** because of the new writer-code
volume.  The audit on current `main` confirms:

- ~3 new files (`_femdata_h5_io.py`, `_record_h5.py`, plus
  optional `_record_h5_payloads.py`); ~600–800 lines of new
  writer code.
- 1 existing file modified (`emitter/h5.py`) — drops one writer
  method (`_write_elements`), gains a delegation to the broker.
- Reader gets ~7 new typed accessors.
- Test suite gets 2 new files.

Re-rated as **medium**: the new code volume is real, but every
piece is mechanical and the contract (master plan §3) is explicit.
Effort is dominated by getting the symmetric compound dtype right
across all five record kinds, plus the doc rewrite.

## References

- [phase-8-untangle.md](phase-8-untangle.md) — master plan
- [phase-8.4-scope.md](phase-8.4-scope.md) — companion scope doc
  (the breaking half of the model.h5 reshuffle)
- [h5-schema.md](h5-schema.md) — current schema (will be extended)
- [viewer-integration.md](viewer-integration.md) — viewer contract
  (will be extended)
- [decisions/0011-h5-as-fourth-emit-target.md](decisions/0011-h5-as-fourth-emit-target.md)
  — original ADR for `model.h5`
- [phase-8.3b-scope.md](phase-8.3b-scope.md) — recorder cluster
  relocation, the doc this one mirrors structurally
