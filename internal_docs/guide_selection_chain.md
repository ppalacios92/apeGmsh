# The Selection Chain — maintainer invariants

> [!note] Audience
> This is the **maintainer** page for the unified `.select()` idiom
> (the `SelectionChain` family). It documents the load-bearing
> invariants that make the chain import-safe and the legacy selection
> surface untouched. If you only want to *use* `.select()`, read
> [Selection in apeGmsh](guide_selection.md),
> [Reading & Filtering Results](guide_results_filtering.md), or
> [The FEM Broker](guide_fem_broker.md) instead.
>
> The full design record — the 4-wave red/blue adversarial exercise,
> the killed alternatives, the phase ledger — lives in
> `docs/plans/selection-unification.md`. This page is the *operational*
> distillation: the rules you must not break when you touch this code,
> with the source and test references that enforce them.

---

## 1. What shipped, in one paragraph

A single fluent, daisy-chainable selection idiom — `.select()` — was
added **additively** at all four levels: geometry
(`g.model.select()`), the FEM broker (`fem.nodes.select()` /
`fem.elements.select()`), results (`results.nodes.select()` /
`results.elements.select()`), and the live mesh
(`g.mesh_selection.select()`). Every `.select()` returns a chainable
object with the same verbs (`.in_box / .in_sphere / .on_plane /
.nearest_to / .where`), the same set algebra (`| & - ^` and
`.union / .intersect / .difference`), and a domain terminal
(`.result()`; results uses `.get(component=, time=, stage=)`). **No
old method changed behaviour** except the one deliberate, pinned
`g.mesh_selection` box default flip (S2) and three formerly-silent
paths that now fail loud (S5). The old selection methods all still
work — `.select()` sits *beside* them, it does not replace or facade
them. This is by design: a true facade was proven fatal (FP-1 / FP-2
below).

The architecture that survives:

```
apeGmsh/_chain.py                 leaf — stdlib/typing only
  class SelectionChain            chaining + set-algebra + name enforcement

core/_selection.py    GeometryChain(SelectionChain)  FAMILY="entity"
mesh/_node_chain.py   NodeChain(SelectionChain)      FAMILY="point"
mesh/_elem_chain.py   ElementChain(SelectionChain)   FAMILY="point"
results/_result_chain.py ResultChain(SelectionChain) FAMILY="point"
mesh/_mesh_selection_chain.py MeshSelectionChain(...) FAMILY="point"

core/_resolution.py   resolve_target()   shared Loads+Masses resolver (S1)
```

The two legacy `Selection` classes (`core/_selection.py` and
`viz/Selection.py`) are left **byte-unchanged** as terminals.

---

## 2. FP-1 — the import-polarity invariant (the one that bites)

### The mechanism

`core` and `mesh` are in a *latent* import cycle on `main`, and the
process only survives because the cross-package edges have a specific
**eager/deferred polarity**:

- `core → mesh` is **eager** (module-level): `core/LoadsComposite.py`,
  `core/MassesComposite.py`, `core/ConstraintsComposite.py` import
  from `apeGmsh.mesh` at module top, and `core/__init__.py:1-6` pulls
  those three composites in.
- `mesh → core` is **deferred** (function-body): e.g.
  `mesh/_mesh_structured.py:562-567` does
  `from apeGmsh.core._helpers import resolve_to_dimtags` /
  `from apeGmsh.core._selection import …` *inside a method body*, not
  at module top.

Eager-`core→mesh` plus deferred-`mesh→core` **terminates**. Flip any
deferred `mesh→core` (or `viz→core`) edge to eager and `import
apeGmsh` crashes with `ImportError`. A static cycle detector cannot
catch this — the cycle is *already there statically*; only the
eager/deferred polarity of the edge set matters.

The original "shared `@final` ABC that reparents the existing
Selections onto a `core` base" design was **killed** here: reparenting
`viz`/`mesh`/`FEMData` Selections onto a `core` base would force a
deferred edge eager.

### Why the leaf module is safe

`apeGmsh/_chain.py` is the **package-root leaf**: it imports only the
standard library (`from typing import …`) — see its module docstring
and `_chain.py:30-34`. It is *not* one of `{core, mesh, viz,
results}`, so importing it from any of those packages adds **no**
cross-package edge to the polarity baseline.

Two structural facts make the chain hooks safe:

1. `core/_selection.py:17-23` imports `from .._chain import
   SelectionChain` at module top. This is allowed because `_chain` is
   the root leaf, not a `core↔mesh/viz/results` edge — identical idiom
   to `mesh/_node_chain.py:14`.
2. `core/__init__.py:1-14` imports `Part / Model / PartsRegistry /
   Instance / ConstraintsComposite / LoadsComposite / MassesComposite`
   **only** — it does **not** import `_selection` / `_chain` /
   `_spatial` / `_resolution`. So a sibling leaf is reachable
   *without* dragging in the eager `core→mesh` chain.

Every `.select()` host hook uses the **deferred-import idiom** —
`from ._node_chain import NodeChain` *inside the `select()` method
body*, mirroring the shipped precedent at
`mesh/_mesh_structured.py:562-567`. See `mesh/FEMData.py:338`
(`select()` for nodes), `mesh/FEMData.py:976` (elements),
`results/_composites.py:601`, `mesh/MeshSelectionSet.py:733`,
`core/Model.py:153` (the docstring there spells out the deferred
rationale verbatim).

### The CI tripwire

`tests/test_import_dag_polarity.py` is the lock. It:

- snapshots the **frozen set of eager cross-package edges** among
  `{core, mesh, viz, results}` in `BASELINE` (8 triples:
  `core→mesh` ×3 from the Loads/Masses/Constraints composites,
  `mesh→core` ×5 from `PhysicalGroups.py`,
  `_constraint_resolver/_resolver.py`, `_load_resolver.py`,
  `_mass_resolver.py`, `records/__init__.py`) and fails on **any**
  add or remove (`test_eager_cross_package_edges_frozen`);
- asserts the exact FP-1 mechanism is closed —
  `core/__init__.py` must not import any of `_selection` / `_chain` /
  `_spatial` / `_resolution`
  (`test_core_init_does_not_import_selection_leaves`);
- asserts the leaf + one point chain + the deferred host hook import
  cleanly (`test_spike_modules_present_and_safe`).

> [!warning] Maintainer rule
> If you add a new eager cross-package import among `{core, mesh, viz,
> results}`, this test goes red. That is intentional. If the new edge
> is genuinely required, update `BASELINE` **in the same commit** so
> the import-graph change is an explicit, reviewed diff — never a
> silent regression. Adding a new chain or new `.select()` host must
> use the deferred-import idiom and must **not** require a `BASELINE`
> change.

The editable install resolves `apeGmsh` to the **main repo** `src/`,
not a worktree. Every in-process gate must set
`PYTHONPATH=<worktree>\src` and assert `apeGmsh.__file__` is the
worktree, or a green is a false negative
(`docs/plans/selection-unification.md` §3 keystone).

---

## 3. FP-2 — the two legacy `Selection` classes are irreconcilable

There are two classes both named `Selection`, and they are
**structurally incompatible**:

| | `core/_selection.py:369` | `viz/Selection.py:99` |
|---|---|---|
| Base | `class Selection(list)` (mutable list subclass) | `class Selection` with `__slots__ = ('_dimtags','_dim','_parent')` (frozen) |
| Tags accessor | `.tags()` — a **method** (`:450`) | `.tags` — a **property** (`:153-154`) |
| Constructor | `(dimtags, *, _queries=)` | `(dimtags, parent)` |
| Refinement | `.to_label` (`:454`) / `.to_physical` (`:489`) — mutates live gmsh | `.filter` (`:227`) / `.limit` (`:264`) / `.sorted_by` (`:268`) |
| Label/PG filter | respects label→PG→part precedence | `labels=` / `physical=` filters **bypass** that precedence |

`.tags()` method vs `.tags` property alone makes any cross-class
`@final` identity test impossible — there is no single base they can
both honour without breaking one caller surface.

> [!warning] Maintainer rule
> Do **not** merge, reparent, or "unify" these two `Selection`
> classes. They are the **terminals** of the new chain: `GeometryChain`
> (`g.model.select()`) materialises to `core/_selection.Selection`
> *unchanged* (so `.to_label()` / `.to_physical()` / `.tags()` keep
> working — see `core/_selection.py` GeometryChain docstring at
> `:781-789` and the terminal assertion in
> `tests/test_selection_idiom.py:563-565`). `viz/Selection.py` is the
> entity-query composite's frozen snapshot and is byte-unchanged. The
> chain wraps *around* them; it never replaces them. This is exactly
> why the public API has **one** canonical new idiom but the old ways
> persist — a facade was impossible, not merely declined.

---

## 4. The `__init_subclass__` + `REQUIRED_VERBS` + `FAMILY` contract

`SelectionChain` (`_chain.py:53-223`) enforces the shared surface at
**class-definition time**, which is strictly stronger than a CI test
(a bad subclass is an `ImportError`-class failure the moment its
module loads).

`_chain.py:84-109` `__init_subclass__`:

- exempts abstract intermediates (no `FAMILY` set) — only concrete
  leaves are checked;
- rejects a `FAMILY` not in `VALID_FAMILIES = ("entity", "point")`
  (`_chain.py:36`);
- requires every verb in `REQUIRED_VERBS` (`_chain.py:40-43`:
  `in_box, in_sphere, on_plane, nearest_to, where, union, intersect,
  difference`) to be present and callable;
- requires every hook in `_REQUIRED_HOOKS` (`_chain.py:47-50`:
  `_coords_of, _spatial_box, _spatial_sphere, _spatial_plane,
  _materialize`) to be **overridden** (not left as the base
  `NotImplementedError` stub).

The set-algebra dedup law is **one** law — insertion-order-preserving
`dict.fromkeys` (`_chain.py:71-74` `_dedupe`). Every refining verb
returns `type(self)(…)` so chaining is covariant (`_chain.py:76-78`
`_wrap`). Cross-type and cross-engine combination is **loud**
(`_chain.py:163-174` `_compatible` raises `TypeError`).

### The CI lock — and its critical scope

`tests/test_selection_idiom.py` (S3e) is the **only** file that looks
at all five chains together:

- `test_exactly_these_concrete_chains` — the family is **closed at
  five** (`GeometryChain, NodeChain, ElementChain, ResultChain,
  MeshSelectionChain`); a 6th leaf breaks the `==` and forces whoever
  adds it to wire it in;
- `test_identical_public_verb_surface` — every required/set-algebra
  name is callable on all five and its `inspect.signature` is
  byte-identical across all five, **except** `in_box` whose signature
  is family-specific by ratified design (entity family has no
  `inclusive=` knob — see §5);
- `test_init_subclass_rejects_bad_family` /
  `…_rejects_dropped_verb` / `…_rejects_missing_hook` — re-prove the
  definition-time gate;
- `test_point_family_laws` (parametrised over the 4 point chains) and
  `test_entity_family_laws` (GeometryChain only) — per-family
  behavioural laws.

> [!warning] Maintainer rule — never assert cross-family identity
> `test_selection_idiom.py` asserts a shared verb-**name** /
> **signature** surface **and** per-family laws. It **never** asserts
> that `GeometryChain.in_box` and `NodeChain.in_box` return the *same
> thing* for the same box. They cannot: `in_box` is honestly three
> irreconcilable semantics (T15) — entity-family gmsh BRep CONTAINMENT
> (closed, `Geometry.Tolerance`≈1e-8 expanded, **no** half-open knob)
> vs point-family node-coordinate / element-centroid half-open
> `[lo, hi)`. The entity and point laws live in **separate,
> family-scoped test bodies** with deliberately no cross-comparison.
> Keep it that way.

---

## 5. The two `in_box` families (T15, ratified R3 / R4)

| | POINT family (`NodeChain` / `ElementChain` / `ResultChain` / `MeshSelectionChain`) | ENTITY family (`GeometryChain`) |
|---|---|---|
| Atoms | node ids / element ids | `(dim, tag)` CAD dimtags |
| `in_box` default | half-open `[lo, hi)` per axis (canonical, R4) | gmsh `getEntitiesInBoundingBox` — BRep bbox-**CONTAINMENT**, closed, box expanded by `Geometry.Tolerance`≈1e-8 |
| `inclusive=` | `inclusive=True` → closed `[lo, hi]` | **any** keyword (incl. `inclusive=`) → `TypeError` (fail loud, never silently ignored) |
| Coordinate | node coords / element centroid (mean of node coords) | entity bounding-box centre (sphere/nearest/where), 8 corners (on_plane) |

Point-family box logic: `mesh/_node_chain.py:40-50` (`_spatial_box`;
`inclusive` selects `<= hi` vs `< hi`). Entity-family override:
`core/_selection.py:820-858` (`in_box(self, lo, hi, **kw)` — `if kw:
raise TypeError(...)`), delegating to
`core/_selection.py:860+` `_spatial_box` which queries
`gmsh.model.getEntitiesInBoundingBox` per distinct dim and intersects
with the chain (preserving insertion order). The base
`SelectionChain.in_box` (`_chain.py:128-131`) has the point-family
`inclusive: bool = False` signature; `GeometryChain` overrides it with
a `**kw`-rejecting signature — this is the one verb the S3e signature
test exempts from cross-chain identity.

> [!note] R3 / R4 are decided behaviour, not bugs
> The point-family box default went **closed → half-open** in S2 (a
> reconciliation, not a relocation — `g.mesh_selection`'s box was
> closed on `main` while `results`' box was already half-open). The
> entity family physically *cannot* express a half-open box (gmsh has
> no such knob), so it rejects the kwarg loudly. Do not "fix" either
> by trying to make them agree.

---

## 6. FP-4 — the deliberate FEMData node-vs-element swallow asymmetry

`FEMData` does **not** call the shared `resolve_target`. It has its
own resolvers with a **deliberate, documented** asymmetry that S1 and
S3 must not touch:

- **Node path** — `FEMData._resolve_one_target`
  (`mesh/FEMData.py:456`) catches **`KeyError` only**
  (`:480`, `:485`). A `ValueError` from a wrong-dimension reference
  propagates (fails loud).
- **Element path** — `FEMData._resolve_one_elem_target`
  (`mesh/FEMData.py:851`) catches **`(KeyError, ValueError)`**
  (`:869`, `:873`) — a broader swallow, by design.

This asymmetry is a **correctness invariant** locked by
`tests/test_resolution_contract.py` + `tests/test_target_resolution.py`
(the S0b characterization battery pinned the node-path
`ValueError`-not-swallowed vs element-path swallowed behaviour as
*current* behaviour before S1/S2).

`fem.nodes.select()` / `fem.elements.select()` **reuse these exact
resolvers** — they delegate verbatim to `_resolve_nodes` /
`_resolve_elements` (the same methods `.get()` uses), so
`select(...).result()` is id-for-id identical to `get(...)` and the
asymmetry is preserved *by reuse*, not re-implemented. See
`mesh/FEMData.py:322-330` (the `select()` docstring spells this out)
and `mesh/FEMData.py:352-354`.

> [!warning] Maintainer rule
> S1 unified **only** the Loads/Masses `_resolve_target` byte-clone
> (see §7). It did **not** create a single library-wide resolver.
> `FEMData`'s node-vs-element swallow asymmetry and `core/_helpers`'s
> `_resolve_string` keep their own resolvers **by design**. A new
> chain must reuse the host's existing resolver — never add a new
> resolver or "harmonise" the asymmetry.

---

## 7. S1 — what actually merged (not a single resolver)

`core/_resolution.py:33` `resolve_target(parent, target, source, *,
expected_dim, not_found_prefix, noun)` is the **one shared engine for
Loads + Masses only**. It was a pure de-duplication: the
`MassesComposite._resolve_target` body was a byte-for-byte clone of
`LoadsComposite._resolve_target` (only the two error strings
differed), so both composites now delegate here and the only
per-composite difference — the not-found `KeyError` prefix
(`"Target"` vs `"Mass target"`) and the wrong-dim `ValueError` noun
(`"load"` vs `"mass"`) — is threaded through explicit parameters
(`core/_resolution.py:1-27` docstring is explicit: *"This is a pure
de-duplication … reproduces the prior behaviour byte-identically"*).

`core/_resolution.py` is itself a **leaf** (imports only `gmsh` +
stdlib; the one intra-`core` symbol `apeGmsh.core.Labels.add_prefix`
is imported deferred inside the function at `:94`, exactly as the
original methods did) — so it does not perturb the FP-1 baseline.

> [!warning] Maintainer rule
> Do **not** route `FEMData._resolve_one_target` /
> `_resolve_one_elem_target` or `core/_helpers._resolve_string`
> through `core/_resolution.py`. The contract tests
> (`test_resolution_contract.py` + `test_target_resolution.py`) lock
> the Loads/Masses/Constraints + `core/_helpers` fail-loud surface;
> the broker path is deliberately separate (FP-4). There is no
> byte-parity tautology test for S1 by design — the locked contract
> tests plus the S0b pins are the guarantee.

---

## 8. The fail-loud centroid contract (S5.3 — already merged)

> [!note] Attribution
> The end-state described here — one shared centroid fail-loud
> contract — is what is true on `main`. **S5.3 (the
> `_element_centroids` fix) merged independently, ahead of this
> docs change; it is not introduced here.** Of the three S5 paths,
> only **S5.2** (the loads/masses `__ms__` consumer, below) is the
> code behavior shipping alongside these docs.

There is **one** centroid fail-loud message/pattern, shared by
the chain centroids and the formerly-silent legacy helper:

- **Chain side** — `mesh/_elem_chain.py` (`_centroid_map`, see
  `:45`) and `results/_result_chain.py` build centroids and were
  fail-loud from the start.
- **Legacy side (the already-merged S5.3 fix)** —
  `results/_composites.py:123` `_element_centroids` previously used
  `np.clip` to silently map a missing connectivity node id to the
  last node (corrupting that element's centroid). It now **raises
  `KeyError`** with an explicit message (`:157` for the no-nodes
  case, `:177` for the absent-id case): *"element {eid} ({type})
  references node {nid} which is not in the FEM node set — refusing
  to compute a corrupted centroid (fail loud)."* The `np.clip` at
  `:168` survives **only** as `loc_clamped`, a safe index used
  *after* the `bad` mask is computed — it no longer drives the
  semantic. The docstring (`:130-136`) explicitly says it shares the
  same contract and message as the chain-side `_centroid_map`.

`_element_centroids` backs the **existing legacy**
`results.elements.in_box / nearest_to / on_plane` helpers — so the
already-merged S5.3 fix makes those legacy helpers fail loud too,
not just the new chain.

The other two S5 fail-loud paths (for completeness — full detail in
`docs/plans/selection-unification.md` §5):

1. **Results `selection=` on import-origin fem (S5.1 — already
   loud, locked)** — `from_msh`/MPCO/native produce
   `mesh_selection=None`; `results/_composites.py` `_resolve_node_ids`
   / `_resolve_element_ids` raise `RuntimeError`
   (`:313-314`, `:333-336`, `:367-368`, `:387-388`) instead of
   silently resolving to an empty set. This path was already loud on
   `main`; a characterization pin locks it — it is **not** flipped by
   this work.
2. **Loads `__ms__` consumer (S5.2 — ships with these docs)** —
   `core/LoadsComposite.py:933` `_target_nodes` did
   `if info is None: return set()` (silently binding a load to
   nothing). It now **raises `KeyError`** (`:950-955`); the
   `MassesComposite` counterpart matches. This guard is in the
   `__ms__` *consumer*, distinct from the S1
   `core/_resolution.py` resolver. **This is the one S5 code change
   shipping alongside this documentation** (with a flipped
   characterization pin + `tests/test_s5_loads_ms_failloud.py`).

---

## 9. How to add a new chain safely

A concrete checklist. Follow it exactly — the gates enforce most of
it, but the deferred-import discipline is on you.

1. **Write a new leaf module** (e.g. `mesh/_foo_chain.py`). Import
   **only** `from .._chain import SelectionChain` + numpy/stdlib at
   module top. Do **not** import `apeGmsh.core` / `mesh` / `viz` /
   `results` at module level. (Model your imports on
   `mesh/_node_chain.py:1-14`.)

2. **Subclass `SelectionChain`**, set `FAMILY` to `"point"` or
   `"entity"`, and implement every hook in `_REQUIRED_HOOKS`
   (`_coords_of`, `_spatial_box`, `_spatial_sphere`, `_spatial_plane`,
   `_materialize`). For a point family, copy the numpy box/sphere/
   plane logic from `NodeChain`; for an entity family, override
   `in_box` to reject keywords and delegate to gmsh like
   `GeometryChain` (`core/_selection.py:820-858`).
   `__init_subclass__` will reject the class at import if you miss a
   verb, a hook, or use a bad `FAMILY`.

3. **Add the `.select()` host hook** on the owning composite with a
   **deferred** import inside the method body
   (`from ._foo_chain import FooChain`), mirroring
   `mesh/FEMData.py:338`. Never import the chain at the host module
   top.

4. **Reuse the host's existing resolver** for name seeding. Do **not**
   write a new name→entity resolver — the resolution contract forbids
   it (FP-4 / §7). Delegate to the exact method `.get()` already uses
   (e.g. `_resolve_nodes`), so `select(...).result()` is id-for-id
   identical to `get(...)`. (This is exactly how
   `g.mesh_selection.select(name=N)` works — it **delegates verbatim**
   to the existing `get_tag`/`get_nodes`/`get_elements` surface via
   the private `_seed_ids_by_name`, writes **no** new resolver, only
   *reads* `_sets`, and fails loud on an unknown name — see
   `mesh/MeshSelectionSet.py` `select()` docstring and
   `tests/test_mesh_selection_chain_name_seed.py`.)

5. **Materialise to the existing terminal type.** Reuse the legacy
   result type via a deferred import inside `_materialize` (cf.
   `mesh/_node_chain.py:96` `from .FEMData import NodeResult`). Do not
   invent a new return type and do not touch the legacy `Selection`
   classes.

6. **Wire it into the cross-chain contract.**
   `tests/test_selection_idiom.py` asserts the family is *exactly*
   five (`_EXPECTED_CHAINS`); a 6th will fail
   `test_exactly_these_concrete_chains` until you add it there (and
   to `_POINT_CHAINS` if point-family) and give it a focused
   per-domain smoke test (pattern: `tests/test_fem_chain.py`,
   `tests/test_result_chain.py`, etc.).

7. **Run the gates** (opensees venv; `PYTHONPATH=<worktree>\src`;
   confirm `apeGmsh.__file__` is the worktree):

   ```
   pytest tests/test_import_dag_polarity.py \
          tests/test_selection_idiom.py \
          tests/test_resolution_contract.py \
          tests/test_target_resolution.py -q
   ```

   `test_import_dag_polarity.py` must stay green **with `BASELINE`
   unchanged** — if it demands a `BASELINE` edit, you added an eager
   cross-package import (step 1 or 3 violated). Fix the import, do not
   edit `BASELINE`.

---

## 10. Dispositions (resolved vs still-deferred)

Post-S3 dispositions are ratified in
`docs/plans/selection-unification.md` §9. One item remains genuinely
deferred; the other two are resolved.

1. **Persistence — RESOLVED query-only.** Chained selections are
   intentionally **ephemeral query objects**. There is **no**
   `.save_as(name)`. Named, round-tripping persistence remains the
   pre-mesh author-time path (`g.mesh_selection.add_nodes(...,
   name=...)` → FEMData snapshot → `selection=`), which already works
   and is unchanged.
2. **Results sub-composites `.select()` — STILL DEFERRED** (the only
   genuinely not-yet item; track, don't claim "available").
   `results.nodes` / `results.elements` have `.select()`; the five
   element sub-composites (`gauss` / `fibers` / `layers` /
   `line_stations` / `springs`) need per-terminal kwarg forwarding
   and are a follow-on.
3. **`g.mesh_selection.select()` name-seed — RESOLVED, shipped.**
   `select(*, level="node", dim=2, ids=None, name=None)`: beyond
   `ids=`/full-universe seeding, `name=` seeds id-for-id from an
   **existing** `g.mesh_selection` set (node ids for `level="node"`,
   element ids for `level="element"`). It **delegates verbatim** to
   the existing `get_tag`/`get_nodes`/`get_elements` surface via the
   private `_seed_ids_by_name` (**no** new resolver), only *reads*
   `_sets` (no registration, no tag allocation), and fails loud on an
   unknown name or a node-set name asked at the element level;
   `ids=`+`name=` together raises. `select(name=N).<spatial>` is
   id-for-id `filter_set` over set `N`, proven for an
   `add_nodes`-built set **and** a `from_physical`-built set in
   `tests/test_mesh_selection_chain_name_seed.py`. Seeding *directly*
   from a raw gmsh PG name / apeGmsh label is **not** a `select()`
   parameter (no non-registering resolver exists on
   `MeshSelectionSet`); the supported route is the two-step
   `from_physical(...)` / `from_geometric(...)` **then**
   `select(name=...)`.

---

## 11. Reference map (verified file:line + tests)

| Concern | Source | Test |
|---|---|---|
| Leaf mixin | `apeGmsh/_chain.py:53-223` | `test_import_dag_polarity.py::test_spike_modules_present_and_safe` |
| Polarity baseline | `core/__init__.py:1-14`, `mesh/_mesh_structured.py:562-567` | `test_import_dag_polarity.py` (all 3) |
| `__init_subclass__` enforcement | `_chain.py:84-109`, `REQUIRED_VERBS` `:40-43` | `test_selection_idiom.py::test_init_subclass_rejects_*` |
| Cross-chain idiom lock | — | `test_selection_idiom.py` (S3e, all) |
| GeometryChain (entity) | `core/_selection.py:769-858` | `test_selection_idiom.py::test_entity_family_laws`, `tests/test_geometry_chain.py` |
| Legacy `Selection(list)` terminal | `core/_selection.py:369`, `.tags()` `:450`, `.to_label/.to_physical` `:454/:489` | `test_selection_idiom.py:563-565` |
| Legacy `viz/Selection` | `viz/Selection.py:99`, `.tags` prop `:153-154` | (byte-unchanged) |
| NodeChain / ElementChain | `mesh/_node_chain.py`, `mesh/_elem_chain.py` | `tests/test_fem_chain.py` |
| ResultChain | `results/_result_chain.py:135` | `tests/test_result_chain.py` |
| MeshSelectionChain | `mesh/_mesh_selection_chain.py:158` | `tests/test_mesh_selection_chain.py` |
| `select(name=)` name-seed (shipped) | `mesh/MeshSelectionSet.py` `select()` (`_seed_ids_by_name`; delegates to `get_tag`/`get_nodes`/`get_elements`) | `tests/test_mesh_selection_chain_name_seed.py` |
| Host hooks (deferred import) | `core/Model.py:153`, `mesh/FEMData.py:338/976`, `results/_composites.py:601`, `mesh/MeshSelectionSet.py:733` | — |
| FP-4 swallow asymmetry | node `mesh/FEMData.py:456`/`:480`/`:485` (`KeyError`) ; elem `:851`/`:869`/`:873` (`KeyError,ValueError`) | `test_resolution_contract.py`, `test_target_resolution.py` |
| S1 shared resolver (Loads+Masses only) | `core/_resolution.py:33` | `test_resolution_contract.py`, `test_target_resolution.py` |
| S2 box → half-open + `inclusive=` | `mesh/_mesh_filters.py:46-83`; entry `MeshSelectionSet.py` `add_nodes` `:210` / `add_elements` `:268` / `filter_set` `:598` | (S0b pins, same commit) |
| S5.1 results `selection=` loud (already loud on main, locked) | `results/_composites.py:313-314/333-336/367-368/387-388` | characterization pin |
| S5.2 Loads/Masses `__ms__` consumer loud (**ships with these docs**) | `core/LoadsComposite.py:950-955` (+ `MassesComposite` counterpart) | `tests/test_s5_loads_ms_failloud.py` (+ flipped char pin) |
| S5.3 centroid fail-loud (already merged separately, not this PR) | `results/_composites.py:123` (`:157`/`:177` raise; `:168` clip is post-validation only) | (merged ahead of these docs) |

---

## See also

- `docs/plans/selection-unification.md` — the authoritative design
  record (hard truths, FP-1/2/4, T15, phase ledger, ratified
  decisions).
- [Selection in apeGmsh](guide_selection.md) — user-facing geometry +
  mesh selection.
- [Reading & Filtering Results](guide_results_filtering.md) —
  results `.select()` and the legacy helpers.
- [The FEM Broker](guide_fem_broker.md) — `fem.nodes/elements.select()`.
- [apeGmsh model queries](guide_queries.md) — the legacy entity
  `queries.select(on=/crossing=)` predicate selector.
- [MIGRATION_v1](MIGRATION_v1.md) — the S2 box-default and S5
  fail-loud user-visible changes.
