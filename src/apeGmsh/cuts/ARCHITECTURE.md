# `apeGmsh.cuts` — section-cut spec producer

Architecture note for the `apeGmsh.cuts` subpackage. Lives next to the
code, like `opensees/architecture/`.

## Charter

apeGmsh produces, [STKO_to_python](https://github.com/nmorabowen/STKO_to_python)
consumes.

STKO_to_python (the MPCO post-processor) already ships a battle-tested
section-cut kernel: beam / shell / solid integration, side-aware
shared-edge resolution, Cyrus-Beck + Sutherland-Hodgman polygon
clipping, layered-shell per-fiber views, and three universal validators
(`consistency_check`, `compare_to`, `moment_about`). Reimplementing any
of that here is months of work for zero engineering payoff.

What apeGmsh *uniquely* has is CAD-level geometry and named physical
groups — exactly what's painful to derive from raw MPCO output. So:

**apeGmsh's job is to produce `SectionCutSpec` objects from physical
groups; STKO_to_python's job is to consume them.**

The seam is `STKO_to_python.cuts.SectionCutSpec`, which is already
designed as a portable carrier: dataset-agnostic, picklable, hashable,
validated at construction. We just feed it.

## Data flow

```
Gmsh model + physical groups + model.h5 (Phase 8.6 fem_eids)
        │
        │  apeGmsh: derive plane (from PG surface), resolve
        │  element_ids (from PG → FEM eid → ops_tag mapping)
        ▼
SectionCutDef                              ← apeGmsh.cuts
        │
        │  .to_spec()  (lazy STKO import)
        ▼
STKO_to_python.cuts.SectionCutSpec         ← seam
        │
        │  pickle, persist, ship to batch worker
        ▼
ds.section_cut(spec=spec, model_stage=...)
        │
        ▼
SectionCut (F, M, time, …)                  ← STKO_to_python
```

## Strategic decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Where this lives | `apeGmsh.cuts` (new top-level subpackage) | Cuts are neither pure-mesh nor pure-results; they bridge. Top-level keeps the import path clean. |
| 2 | STKO_to_python dependency | **Optional, lazy import** at `.to_spec()` time | STKO pulls h5py / pandas / matplotlib transitively. Modeling-only users shouldn't pay for that. |
| 3 | `Plane` representation | Store as `(point_tuple, normal_tuple)` in `SectionCutDef`; construct STKO `Plane` only in `.to_spec()` | Don't require STKO to construct a Def or to pickle it. |
| 4 | v1 scope | Spec producer only | No result consumption, no viewer overlay, no recorder emission. |
| 5 | FEM eid → ops_tag bridge | Read from `model.h5` (`/opensees/element_meta/{type}/fem_eids` parallel to `ids`) | Phase 8.6's chosen source-of-truth. Survives session boundaries; matches Phase 8.7's viewer direction. |

## Package layout

```
src/apeGmsh/cuts/
├── ARCHITECTURE.md          ← this file
├── __init__.py              ← re-exports SectionCutDef (and SectionSweepDef once it exists)
├── _defs.py                 ← SectionCutDef frozen dataclass + to_spec()
├── _optional_stko.py        ← lazy STKO_to_python import with clean error
├── _planes.py               ← plane builders (horizontal / vertical / 3-point / SVD-fit / from-PG)
├── _polygons.py             ← convex hull + bounding_polygon_from_physical_surface
├── _tag_map.py              ← FemToOpsTagMap reading model.h5
└── _sweeps.py               ← SectionSweepDef (sequence of SectionCutDef, one filter, many planes)
```

Tests mirror under `tests/cuts/test_*.py`.

## Public API (v1 — spec producer)

```python
from apeGmsh.cuts import SectionCutDef

# Manual construction — caller already has plane and ops_tags
cut_def = SectionCutDef(
    plane_point=(0.0, 0.0, 2500.0),
    plane_normal=(0.0, 0.0, 1.0),
    element_ids=(101, 102, 103),       # OpenSees tags
    side="positive",
    label="Story 3 base shear",
)

# Round-trip to STKO (lazy import — requires STKO_to_python installed)
spec = cut_def.to_spec()
assert spec.label == "Story 3 base shear"

# Persistence (uses apeGmsh-side pickle; no STKO needed to save/load)
cut_def.save_pickle("story3.pkl")
restored = SectionCutDef.load_pickle("story3.pkl")
```

The ergonomic constructor (Phase 4):

```python
# Physical-group driven — the real API
cut_def = SectionCutDef.from_planar_pg(
    plane_pg="diaphragm-3",       # PG defining the cut plane
    elements_pg="tower-cols",     # PG defining the element filter
    fem=fem,                       # FEMData for FEM-eid lookup
    model_h5="path/to/model.h5",   # for FEM↔ops_tag bridge
)
# .label auto-set to "plane=diaphragm-3, elements=tower-cols"

# Or, plane from elsewhere:
cut_def = SectionCutDef.from_plane_and_pg(
    plane=plane_horizontal(z=2500.0),
    elements_pg="tower-cols",
    fem=fem,
    model_h5="path/to/model.h5",
    label="Story 3 base shear",
)
```

## Phase roadmap

| Phase | Deliverable | Status |
|-------|-------------|--------|
| 1 | Package scaffold + `SectionCutDef` + `.to_spec()` + pickle | **done** |
| 2 | `plane_from_physical_surface()` + Plane convenience wrappers | **done** |
| 3 | `FemToOpsTagMap` from `model.h5` | **done** |
| 4 | `SectionCutDef.from_plane_and_pg` / `.from_planar_pg` builders | **done** |
| 5 | `SectionSweepDef` + `from_pg_pattern` | **done** |
| v2.1 | `bounding_polygon_from_physical_surface` + `with_bounding=True` flag | **done** |

v2 and beyond (viewer overlay, bounding-polygon derivation, `model.h5`
persistence, drift specs, sweep templates) are described in the
session that drafted this plan — out of scope for this directory until
v1 is complete.

## Acceptance test (north star)

A single integration test, skipped if STKO_to_python is not installed:

```python
def test_section_cut_end_to_end(tmp_path):
    # 1. Build a fixture tower with named "diaphragm-3" and "tower-cols" PGs
    g = build_fixture_tower(tmp_path)
    fem = g.mesh.queries.get_fem_data(dim=3)
    ape = apeSees(fem)
    # ... wire recorders, run analysis to tmp_path/"Results.mpco"
    ape.h5(tmp_path / "model.h5")

    # 2. Build a SectionCutDef from physical groups
    cut_def = SectionCutDef.from_planar_pg(
        plane_pg="diaphragm-3",
        elements_pg="tower-cols",
        model_h5=tmp_path / "model.h5",
        label="Story 3 base shear",
    )
    spec = cut_def.to_spec()

    # 3. Consume with STKO_to_python — kernel-side validator is the oracle
    from STKO_to_python import MPCODataSet
    ds = MPCODataSet(str(tmp_path), "Results", verbose=False)
    cut = ds.section_cut(spec=spec, model_stage="MODEL_STAGE[1]")

    assert cut.F.shape[1] == 3
    ok, _ = cut.consistency_check(ds)      # Newton's 3rd law
    assert ok
```

If this passes, the seam holds.

## Out of scope for v1

- Reimplementing any kernel math. Use STKO's `Plane.intersect_*`, the
  beam/shell/solid kernels, the polygon clipping. No exceptions.
- Reading MPCO output. apeGmsh users open the dataset themselves.
- Viewer overlay. Separate effort; reuses `SectionCutDef` as data.
- Recorder emission (computing the cut during analysis). Probably never.
- Non-convex bounding polygons. STKO doesn't support them; we won't either.

## Dependencies

- **Required at construction:** numpy. That's it.
- **Required for `to_spec()`:** `STKO_to_python` (optional, lazy-imported).
- **Required for `from_planar_pg(...)` (Phase 4):** `h5py` (already a hard apeGmsh dep via `model.h5`).

## Versioning

apeGmsh follows pyproject `version` bumps. New optional subpackage =
minor bump. Schema bump only at Phase 4 if we decide to persist cuts
in `model.h5` (currently planned for v4 of the roadmap, not v1).
