# Phase 8.6 — Bridge enrichment additions (`/opensees/tag_map`)

**Status:** Scoping (May 2026).  Sits on top of Phase 8.5
([scope doc PR #139](https://github.com/nmorabowen/apeGmsh/pull/139),
[implementation PR #141](https://github.com/nmorabowen/apeGmsh/pull/141))
— the broker neutral zone and `/opensees/element_meta/{type_token}`
are prerequisites.  Additive minor schema bump on top of `2.1.0`.

This phase wires the **FEM ↔ OpenSees element-tag translation** that
the master plan ([phase-8-untangle.md §3](phase-8-untangle.md)) puts
under `/opensees/tag_map/`.  After this phase, a consumer can map an
OpenSees element tag (from MPCO recorder output, log files, etc.)
back to the FEM element ID it was fanned out from — closing the loop
between broker geometry and bridge enrichment.

## 1. The change

### 1a. The mapping

During the bridge's element fan-out
([`_internal/build.py:411`](../_internal/build.py)) the loop knows
both the FEM element ID (``eid``) and the freshly-allocated OpenSees
tag (``ele_tag``):

```python
for eid, node_tags in elements:
    ele_tag = tags.allocate("element")
    set_element_nodes(emitter, node_tags)
    spec._emit(emitter, ele_tag)
```

The bridge currently throws ``eid`` away — only ``ele_tag`` flows
into the H5Emitter via the ``.element(...)`` Protocol call.  Phase
8.6 adds a side channel parallel to ``set_element_nodes`` so the
emitter captures ``(fem_eid, ops_tag)`` per element.

Master plan §3 places the on-disk mapping under
``/opensees/tag_map/``.  This phase fills in that group with the
captured pairs.

### 1b. Side-channel helper

Following the existing ``set_element_nodes`` / ``current_element_nodes``
pattern in
[`_internal/tag_resolution.py`](../_internal/tag_resolution.py):

```python
ATTR_CURRENT_FEM_ELEMENT_ID = "_current_fem_element_id"

def set_current_fem_element_id(emitter: object, fem_eid: int) -> None:
    setattr(emitter, ATTR_CURRENT_FEM_ELEMENT_ID, int(fem_eid))

def current_fem_element_id(emitter) -> int:
    eid = getattr(emitter, ATTR_CURRENT_FEM_ELEMENT_ID, None)
    return -1 if eid is None else int(eid)
```

* Returns ``-1`` as a sentinel when no FEM element ID has been set
  (test scenarios that drive ``.element(...)`` directly without the
  bridge fan-out).
* No Protocol change — opt-in attribute access, same as
  ``set_element_nodes``.

[`_internal/build.py:413`](../_internal/build.py) gets a one-line
addition right after ``set_element_nodes(...)``:

```python
set_element_nodes(emitter, node_tags)
set_current_fem_element_id(emitter, eid)        # new
spec._emit(emitter, ele_tag)
```

### 1c. On-disk shape (design tension — see §3 for flavors)

Either:

* **`/opensees/tag_map/{type_token}/`** with ``ops_tags`` and
  ``fem_eids`` parallel int64 arrays (Flavor A — master plan's
  literal reading), or
* **`/opensees/element_meta/{type_token}/fem_eids`** as a third
  dataset alongside the existing ``ids`` and ``args`` (Flavor B —
  co-locate the per-type tag data).

Both shapes carry the same payload.  §3 recommends Flavor B.

### 1d. Source-side surface

| File | What changes |
|---|---|
| `src/apeGmsh/opensees/_internal/tag_resolution.py` | Add `set_current_fem_element_id` + `current_fem_element_id`; add `ATTR_CURRENT_FEM_ELEMENT_ID` constant; extend `__all__`. ~20 lines. |
| `src/apeGmsh/opensees/_internal/build.py` | One-line addition at the element fan-out site (line 413). |
| `src/apeGmsh/opensees/emitter/h5.py` | `_ElementRecord` gains a `fem_eid: int` field (defaults to ``-1``); `H5Emitter.element(...)` reads the side channel and stores it; writer emits the mapping (per chosen flavor). |
| `src/apeGmsh/opensees/emitter/h5_reader.py` | Add accessor (`tag_map()` for Flavor A; or extend `element_meta_arrays` for Flavor B). |
| Other emitters (`tcl.py`, `py.py`, `live.py`, `recording.py`) | No change — the side channel is opt-in attribute access; emitters that don't read it pay nothing. |

### 1e. Test-side surface

| File | What changes |
|---|---|
| `tests/test_tag_resolution_fem_eid.py` (NEW) | Unit-test the side-channel helper (set / get / sentinel for absent). |
| `tests/test_femdata_to_h5.py` or `tests/test_h5_tag_map.py` (NEW) | Integration: drive `apeSees(fem).h5(path)` with a representative FEMData, verify the on-disk mapping matches the FEM element IDs assigned by the broker. |
| `tests/opensees/h5/test_h5_emitter.py` | Tests that buffer `.element(...)` directly without bridge fan-out should confirm `fem_eid` defaults to ``-1`` (matches the "no FEM context" sentinel). |
| `tests/opensees/h5/fixtures.py` | Fixtures that exercise `.element(...)` may need to call `set_current_fem_element_id` first if we want them to round-trip a non-sentinel FEM ID.  Most likely they keep the default ``-1`` since the fixtures are bridge-only and don't have a broker side. |

### 1f. Doc-side surface

| File | What changes |
|---|---|
| `architecture/h5-schema.md` | New per-group section (Flavor A) or augmented `/opensees/element_meta` section (Flavor B); version history adds `2.1.0 → 2.2.0`. |
| `architecture/viewer-integration.md` | Mention the new accessor / dataset; one paragraph under the element-detail panel since the viewer can now drill from an OpenSees tag back to a FEM element ID. |
| `architecture/phase-8-untangle.md` | Mark Phase 8.6 as landed; refresh §6 acceptance criteria. |

## 2. Source-side audit

The bridge knows ``eid`` at the fan-out call site
([`build.py:411-413`](../_internal/build.py)) but discards it.  No
other code path produces ``.element(...)`` calls — every emit goes
through the fan-out helper.  Direct ``.element(...)`` calls in tests
will simply use the ``-1`` sentinel since they bypass the bridge.

The pre-Phase-8.5 element write at `/elements/{type}` (deleted in
PR #141) had no fem_eid field either — Phase 8.6 introduces the
mapping for the first time.  Pre-existing consumers do not depend on
its presence; pre-8.6 files are valid post-8.6 (the mapping group is
simply absent).

## 3. Design tension

### Choice 1 — On-disk shape

**Flavor A — Standalone `/opensees/tag_map/{type_token}/` group.**

```
/opensees/tag_map/
├── /forceBeamColumn/
│   ├── ops_tags    (N,) int64
│   └── fem_eids    (N,) int64
└── /FourNodeTetrahedron/
    ├── ops_tags
    └── fem_eids
```

* **Pros:** Literal reading of master plan §3.  Clean separation —
  one group dedicated to tag translation.  Adding new mapping
  varieties later (e.g. node-tag mapping if that ever becomes
  necessary) drops cleanly under `/opensees/tag_map/`.
* **Cons:** `ops_tags` duplicates `/opensees/element_meta/{type}/ids`
  exactly.  Two parallel indices for the same per-type data.

**Flavor B — Embed `fem_eids` in `/opensees/element_meta/{type}`.**

```
/opensees/element_meta/
└── /forceBeamColumn/
    ├── ids         (N,) int64           — OpenSees tags
    ├── args        (N, k) float64
    ├── args_str    (N, k) vlen-utf-8     (when any string slot)
    └── fem_eids    (N,) int64           — NEW: parallel to `ids`
```

* **Pros:** Co-located with the data they describe; one less group;
  no duplication of `ids`.  Reader accessor `element_meta_arrays(...)`
  just returns one more numpy array.  Matches the broker's
  `/elements/{gmsh_alias}` shape (broker's `ids` are FEM element IDs
  — Flavor B makes the bridge side carry the FEM IDs by the same name
  but on the bridge-keyed group).
* **Cons:** `/opensees/tag_map/` master-plan path stays unused.  A
  future node-tag mapping (if ever needed) would need a fresh
  location.

**Recommendation: Flavor B.**  Avoids the parallel-index
duplication; one accessor change covers it; matches the symmetry
already established in 8.5 between broker `/elements/{gmsh_alias}`
and bridge `/opensees/element_meta/{type_token}`.  If a node-tag
mapping ever becomes necessary the master plan's `/opensees/tag_map`
slot remains free for that.  The master plan's text predates Phase
8.5's `/opensees/element_meta` — the architectural intent (close the
loop between FEM and OpenSees) is satisfied either way.

### Choice 2 — Sentinel vs. omission for missing fem_eid

When the bridge fans out from a real FEMData every element gets a
fem_eid.  But standalone H5Emitter tests (and recording emitters
driven without the bridge) call `.element(...)` directly with no
side-channel context.  Two ways to encode this:

* **Sentinel `-1`** in the `fem_eids` column for those records, OR
* **Omit `fem_eids` entirely** when the column would be all
  sentinel.

**Recommendation: sentinel `-1`.**  Keeps the column shape uniform
across records, which simplifies the reader.  ``-1`` is an
unambiguous "no FEM context" marker (FEM element IDs are always
positive 1-based ints).

### Choice 3 — Reverse lookup (ops_tag → fem_eid)

Should the reader pre-compute a reverse lookup dict for fast lookup
of an arbitrary OpenSees tag's FEM ID?  Or leave that to consumers?

* **A.** Reader returns raw arrays; consumers build their own dict.
* **B.** Reader exposes `fem_eid_for_ops_tag(type_token, ops_tag)`
  with a cached internal dict.

**Recommendation: A.**  Reader convention so far is "expose raw
datasets, leave consumption to the caller."  A reverse lookup is one
line of caller code (`dict(zip(ops_tags, fem_eids))`); not worth a
new accessor.

### Recommendation summary

* Choice 1: B (embed `fem_eids` under `/opensees/element_meta`).
* Choice 2: sentinel `-1`.
* Choice 3: raw arrays only.

## 4. Sub-commits

Three commits.  Smaller PR than 8.4 / 8.5.

### Commit 1 — Side-channel helper + unit test

Add `set_current_fem_element_id` / `current_fem_element_id` to
[`_internal/tag_resolution.py`](../_internal/tag_resolution.py),
plus `ATTR_CURRENT_FEM_ELEMENT_ID` constant, plus matching unit
test (`tests/test_tag_resolution_fem_eid.py`).  No callers yet.

### Commit 2 — Bridge wires the side channel + emitter captures + writes

1. [`_internal/build.py`](../_internal/build.py) — call
   `set_current_fem_element_id(emitter, eid)` right after
   `set_element_nodes(...)`.
2. [`emitter/h5.py`](../emitter/h5.py) — `_ElementRecord` gains
   `fem_eid: int = -1`; `H5Emitter.element(...)` reads
   `current_fem_element_id(self)` and stores it on the record;
   `_write_element_meta` writes a `fem_eids` int64 dataset alongside
   `ids`.
3. [`emitter/h5_reader.py`](../emitter/h5_reader.py) —
   `element_meta_arrays(type_token)` returns `fem_eids` in its dict
   when present.
4. Tests: extend `test_h5emitter_writes_element_meta_with_args` to
   verify `fem_eids` defaults to sentinel; add a new integration test
   that drives `apeSees(fem).h5(path)` end-to-end and walks
   `/opensees/element_meta/{type_token}/fem_eids`.

### Commit 3 — Doc rewrite

* `architecture/h5-schema.md` — augment the `/opensees/element_meta`
  section to mention `fem_eids`; bump version history `2.1.0 →
  2.2.0`; update the `/meta` example.
* `architecture/viewer-integration.md` — one-paragraph addition to
  the element-detail panel section noting the new round-trip
  capability.
* `architecture/phase-8-untangle.md` — mark 8.6 as landed.

(Commit 3 can fold into commit 2 if the doc churn stays small.)

## 5. Verification gates (per commit)

Same as previous Phase-8 PRs:

* `mypy --strict src/apeGmsh/`
* `ruff check src/apeGmsh/ tests/`
* `pytest -m "not live and not subprocess" --ignore=tests/acad --continue-on-collection-errors`

Re-measure at PR-open time.  Phase 8.6 special checks:

* Side-channel helper's sentinel behaviour: ``current_fem_element_id``
  on a fresh emitter returns ``-1``; after ``set_current_fem_element_id``,
  returns the set value.
* End-to-end: `apeSees(fem).h5(path)` produces
  `/opensees/element_meta/{type_token}/fem_eids` whose i-th entry
  is the FEM element ID that produced the i-th OpenSees tag in
  `ids`.
* Standalone H5Emitter output: `fem_eids` column is all ``-1``
  (sentinel) since no bridge fan-out happened.

## 6. Open questions for the implementing session

1. **Bridge tests that call `.element(...)` directly.**  Confirm
   the sentinel approach (Choice 2) is right.  Inspect the H5
   fixture builders in [`tests/opensees/h5/fixtures.py`](../../../tests/opensees/h5/fixtures.py)
   — they call `.element(...)` without bridge fan-out.  Their on-disk
   `fem_eids` will be a column of ``-1``; that's fine for the
   bridge-only contract, but the fixture's `expected_groups` /
   `element_meta_type_count` entries may need a comment explaining
   the sentinel.

2. **Node-tag mapping?**  apeGmsh today reuses FEM node IDs as
   OpenSees node tags (the bridge calls `ops.node(eid, *coords)` in
   the node fan-out).  A `node_tag_map` would therefore be the
   identity — not worth shipping.  Confirm during implementation;
   if the bridge ever decouples them, Phase 8.6 might want a
   `/opensees/tag_map/nodes` later.  Until then, only elements
   need mapping.

3. **`tcl.py` / `py.py` / `live.py` emitter behavior.**  Confirm
   these emitters don't accidentally read the side-channel attribute
   (they shouldn't — they only use `current_element_nodes`).  If
   any do, evaluate whether to no-op them gracefully or surface the
   FEM ID in their output too (probably no-op, since stream emitters
   don't have a place to put the mapping).

4. **Schema-version interaction.**  Post-8.5 is `2.1.0`; this phase
   is additive → `2.1.0 → 2.2.0`.  Confirm.

5. **Reader accessor naming.**  Flavor B has `fem_eids` join the
   existing `element_meta_arrays(type_token)` dict.  No new top-level
   accessor.  Confirm the naming convention (`fem_eids` not
   `fem_element_ids` or `eids`) — matches the master plan's wording.

## 7. Out of scope (defer to later phases)

* **Viewer migration off FEMData / solvers.**  Phase 8.7.  Phase
  8.6 just makes the data available; consumption is the viewer's
  problem.
* **Delete `solvers/`.**  Phase 8.8.
* **Recipe round-tripping.**  Not addressed by tag_map; if Phase 8.5
  recipes need their own metadata zone, that's a separate scoping.
* **Node-tag mapping.**  See §6 Q2 — not needed today.

## 8. Risk assessment

The master plan rated 8.6 as **low risk** (additive only).  The
audit on current `main` confirms:

* Two new helper functions in `_internal/tag_resolution.py` (~20
  lines).
* One added line in `_internal/build.py`.
* One field added to `_ElementRecord`; one new dataset under
  `/opensees/element_meta/{type}`.
* No breaking change to the Emitter Protocol.
* Schema bump is minor; old readers continue to parse pre-8.6 files
  and ignore the new `fem_eids` dataset in post-8.6 files.

Re-rated as **low**.  Effort is dominated by writing the integration
test that drives a real `FEMData` through `apeSees(fem).h5(path)`
end-to-end and walks the produced mapping.

## References

* [phase-8-untangle.md](phase-8-untangle.md) — master plan;
  `/opensees/tag_map` introduced in §3.
* [phase-8.5-scope.md](phase-8.5-scope.md) — companion scope doc;
  established the `/opensees/element_meta/{type_token}` structure
  Phase 8.6 augments.
* [h5-schema.md](h5-schema.md) — current schema doc (will be
  extended with the new field).
* [viewer-integration.md](viewer-integration.md) — viewer contract
  (will gain the round-trip note).
* [`tests/test_femdata_to_h5.py`](../../../tests/test_femdata_to_h5.py)
  — the representative FEMData builder used by Phase 8.5 tests;
  Phase 8.6 integration tests will reuse this.
