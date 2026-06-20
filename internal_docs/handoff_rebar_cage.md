# Handoff — `g.rebar` reinforcement-cage authoring (ADR 0067)

Status: **P0–P4 shipped** (this PR). All three adversarial-review gates folded.
101 rebar tests green. P5 is **blocked** on two external items (below).

`g.rebar` lets you author reinforcement cages — longitudinal bars, stirrups,
hooks, whole columns/beams — as geometry, and **delegates** the
concrete↔steel coupling to machinery that already ships in apeGmsh. It does
not invent an embedding element; it routes to `g.reinforce`
(`LadrunoEmbeddedRebar`) or to gmsh `embed`.

See `src/apeGmsh/opensees/architecture/decisions/0067-reinforcement-cage-authoring.md`
for the full design rationale.

---

## The three layers

| Layer | What | Where |
|---|---|---|
| **L1** specs | frozen, serialisable data: `Hook` `Path` `Bar` `Stirrup` `Cage`, layout inputs `BarLayout`/`TieLayout`, fluent `BarBuilder`, detailing `Raw`/`ACI318`/`ACI318_seismic` + `BarCatalog` | `src/apeGmsh/_kernel/defs/rebar.py`, `src/apeGmsh/rebar/detailing.py` |
| **L2** composite | `g.rebar` — geometry generation + `place()` coupling router + `column()`/`beam()` generators | `src/apeGmsh/core/RebarComposite.py` |
| **L3** fluent | `g.rebar.bar(...).through(...).hook_end(...).as_(name)` | `BarBuilder` in `_kernel/defs/rebar.py` |
| hook math | pure (numpy) bend-plane + fillet primitives | `src/apeGmsh/rebar/_geometry.py` |

Public surface: `from apeGmsh.rebar import (Hook, Path, Bar, Stirrup, Cage,
BarLayout, TieLayout, BarBuilder, ACI318, ACI318_seismic, Raw, BarCatalog,
DetailingError)`. The composite is `g.rebar` on a live session.

---

## Quickstart

```python
from apeGmsh import apeGmsh
from apeGmsh.rebar import Cage, BarLayout, TieLayout, Hook, ACI318_seismic, BarCatalog

with apeGmsh(model_name="col") as g:
    g.model.geometry.add_box(0, 0, 0, 0.5, 0.5, 3.0, label="Col")
    g.rebar.use_standard(ACI318_seismic(BarCatalog(unit_length=0.0254)))  # model in metres

    # standardized member → a Cage
    cage = g.rebar.column(
        section=("rect", 0.5, 0.5), height=3.0, cover=0.05,
        longitudinal=BarLayout(n_x=2, n_y=2, db="#8"),
        ties=TieLayout(db="#3", spacing=0.30, hinge_spacing=0.10, hinge_length=0.60))

    g.rebar.place(cage, into="Col", coupling="conformal")   # shared-node perfect bond
    g.mesh.sizing.set_global_size(0.3)
    g.mesh.generation.generate(dim=3)
    fem = g.mesh.queries.get_fem_data()
```

Authoring primitives + fluent:

```python
bar = g.rebar.bar([(0,0,0),(0,0,3)], db="#8", material="rebar",
                  end_hook=Hook.standard_90())
tie = g.rebar.stirrup_rect(0.5, 0.5, 0.04, db="#3", material="rebar", z=1.0)
cage = Cage(bars=(bar,), stirrups=(tie,))

L1 = (g.rebar.bar(db="#8", material="rebar")          # fluent (no points → builder)
        .through([(0,0,0),(0,0,3)]).hook_end(Hook.standard_90()).as_("L1"))
```

---

## Coupling model (the central idea)

`g.rebar.place(cage, into, *, coupling=, per_member_coupling=, bond=, perfect=, ...)`

| coupling | mechanism | host requirement | notes |
|---|---|---|---|
| `"conformal"` | gmsh `embed` of the bar curves into the host **before** `generate()` → shared nodes, perfect bond | single un-meshed volume (label OR PG) in the **same session** | MPI-OK; generated cages are inset interior so they mesh without a boundary PLC |
| `"embedded"` | forwards each member to `g.reinforce` → `LadrunoEmbeddedRebar` | host must be a **physical group**; needs `bond=<LadrunoBondSlip name>` **xor** `perfect=<axial penalty>` | **single-process only** (partitioned `LadrunoEmbeddedRebar` raises) |
| mixed | `per_member_coupling={role: coupling}` | per the chosen modes | longitudinal conformal + ties embedded, etc. |

`coupling="conformal"` across a composed Part **raises** (`embed` can't cross
a Part boundary). `place()` runs a **Pass-0** that validates the whole cage +
host before mutating gmsh, so a bad cage never leaves the model half-built.

---

## Detailing standards

`Raw()` (explicit-only — every code rule raises `DetailingError`),
`ACI318()`, `ACI318_seismic()` over a `BarCatalog(unit_length=, base=)`.
`"<k>db"` length tokens and `Hook.standard_90()/standard_135()/standard_180()/
seismic_135()` resolve at bind time. ACI 318-19 Table 25.3.1/25.3.2 bend
diameters + hook tails are encoded and **independently re-verified** (Gate C).
`bar_diameter`/`bar_area` feed `ReinforceDef`; imperial `#N` uses the ASTM
nominal area, metric/raw uses π·d²/4.

---

## v1 limitations (warned + intentional)

These are documented behaviours, not bugs — a `warnings.warn` fires for each:

1. **Cross-ties / supplementary legs not generated.** `column()` emits one
   perimeter hoop per level; intermediate bars (`n>2` per face) are not
   laterally supported (ACI 318 §25.7.2.3). Add cross-ties manually for now.
2. **Hinge densification is data-driven, not standard-derived.** A seismic
   column with no `TieLayout(hinge_spacing=, hinge_length=)` gets uniform ties
   (no confinement zone) + a warning. ACI §18.7.5 `l_o`/`s_o` are not auto-computed.
3. **Stirrup closure is a single hook**, not the real twin-tail (two 135°
   tails overlapping at one corner).
4. **Conformal embedding of boundary-touching bars** trips a tetgen PLC. The
   generators avoid this by insetting the cage interior; hand-authored bars
   whose endpoints sit on a host face should use `coupling="embedded"`.
   `on_conformal_infeasible="embedded"` only catches *embed-time* failures,
   not the mesh-time PLC.

---

## P5 — blocked future work

| Item | Blocked on |
|---|---|
| **Composed-Part cage library** (author a cage once, stamp into many members) | `apeSees.h5()` drops `LadrunoEmbeddedRebar` ties today (`H5ReinforceDeviationWarning`); needs H5 persistence + read-back of `ReinforceTieRecord` (fork ADR-20 / R2; schema 2.19.0→2.20.0). `g.compose` is H5-source-only, so a composed cage currently loses its ties. |
| **`element="beam"` rebar** (dowel action) | ADR-0010 Phase-4 orientation fan-out is unbuilt (`transform.py` raises `NotImplementedError` on `orientation=` with `vecxz=None`). Curved/hooked beam rebar is gated → raises. Ship truss-first (`CorotTruss`). |
| **Bar-axis twist stabilization** (beam rebar) | `LadrunoEmbeddedRebar` ties translations only → a torsional zero-energy mode. The soft `zeroLength`-to-ghost-node fix needs canonical tag allocation + `(fem_eid→ops_tag)` H5 handling. |

When R2 lands, the composed-Part path is `g.compose("cage.h5") +
g.reinforce(host, cage_label)`; the conformal-across-Part guard already raises.

---

## Working notes

- **Run tests:** `PYTHONPATH=src python -m pytest tests/rebar/` — apeGmsh is
  *not* pip-installed in the default Python here; `PYTHONPATH=src` imports this
  worktree directly (v2.0.0; gmsh 4.15.2 present). 101 tests, ~1 s.
- **Tests:** `tests/rebar/` — `test_rebar_specs.py` (L1), `test_detailing.py`
  (ACI), `test_rebar_geometry.py` (bend math), `test_rebar_composite.py`
  (coupling), `test_rebar_hooks.py` (hook emission), `test_rebar_generators.py`
  (column/beam/fluent).
- **Gotchas baked in (don't re-trip):** `add_line`/`add_arc` take point refs
  not coords; `add_wire` rejects `label=`; hook arc+line weld via **point-tag
  reuse** (no `make_conformal` — which renumbers entities); arc-center
  construction points are `occ.remove`d (else they mesh as phantom nodes);
  `center_of_mass(tag, *, dim=3)`; `g.reinforce` is not chain-phase guarded so
  `place()` guards itself; emit geometry eagerly in `place()`.

Built phase-by-phase with adversarial-review gates after P0, P2, P4 (each a
multi-agent workflow that found real bugs — see the commit history).
