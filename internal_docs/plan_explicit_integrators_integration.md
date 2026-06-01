# Plan — Explicit integrators emit surface (`ops.integrator.ExplicitBathe` / `ExplicitBatheLNVD` / `CentralDifferenceLadruno`)

**Status:** proposed (2026-06-01) · **Owner:** nmora · **Scope:** apeGmsh-side
*emit surface* for the OpenSees *Ladruno fork*'s three explicit-dynamics
integrators. **Integrators only** — no runtime `criticalTimeStep()` query, no
auto-`dt` sub-stepping helper, no `EnergyBalance` recorder (all explicit
non-goals below; doors left open).

This is the apeGmsh half of the fork's **implied 6th feature** ("explicit
integrator/analysis emit surface") from the ladruno integration sequence. The
fork C++ is shipped + merged to `ladruno` and **present in the venv build**
(`opensees_venv` carries `605affeb`; verified live this session — all three
integrators load and `criticalTimeStep()` answers).

Contract: `nmorabowen/OpenSees@ladruno:Ladruno_implementation/ladruno_apegmsh_contract.md`
(ExplicitBathe / ExplicitBatheLNVD / CentralDifferenceLadruno rows).

---

## Governing constraints (non-negotiable)

1. **Fork is opt-in; vanilla never breaks.** apeGmsh must keep running on stock
   `openseespy`. These integrators are unavailable there — gate **at the point
   of use**, never force the fork, never fail at import.
   - *Emit:* `ops.integrator.ExplicitBathe(...)` (and siblings) produce deck
     text on **any** build — emission is just an `integrator <Type> ...` line.
     The fork requirement bites only at `ops.analyze(...)` / `ops.run()` (stock
     OpenSees raises "unknown integrator"). **No emit-time gating** — mirrors
     `ops.recorder.Ladruno` (recorder-plan L1).
2. **Match existing integrator style.** The seven existing typed integrators
   (`LoadControl` … `ExplicitDifference`) are flat `@dataclass(frozen=True,
   kw_only=True, slots=True)` subclasses of `Integrator`, each with `_emit` +
   `dependencies() -> ()`. No inheritance among them, no mixins. The three new
   ones follow the same shape; shared option-rendering is a **module-level
   helper function**, not a dataclass base (avoids frozen+slots inheritance
   friction; keeps the diff in-idiom).
3. **Class tags are irrelevant here.** We emit by *name* string
   (`integrator ExplicitBathe ...`); the fork's ≥33000 class tags only matter to
   the response catalog / object broker, neither of which this slice touches.

---

## Source-grounded command grammar (verified against `ladruno` branch)

Read this session from the fork C++ (`SRC/analysis/integrator/{ExplicitBathe,
ExplicitBatheLNVD,CentralDifferenceLadruno}.cpp`). All option flags are parsed
in an **order-free loop** (`OPS_GetString` switch); positionals lead.

### `ExplicitBathe`
```
integrator ExplicitBathe p [-cfl] [-cflAbort] [-tangent] [-recompute N]
                           [-lump rowsum|diagonal] [-verbose] [-divergence f]
```
- `p` — sub-step parameter, **first positional**, `∈(0,1)`, default `0.54`. C++
  warns + bails if outside `(0,1)`.
- `-lump` default = **RowSum** when omitted.

### `ExplicitBatheLNVD`
```
integrator ExplicitBatheLNVD p alpha [...same flags as ExplicitBathe...]
```
- `p` — `∈(0,1)`, default `0.54`.
- `alpha` — FLAC local non-viscous damping, **`∈[0,1)`** (note: `0` is valid),
  default `0.80`. C++ reads `p` and `alpha` as a *2-vector of leading numerics*;
  if only one numeric is present it reads just `p` and `alpha` stays default.
  **→ apeGmsh always emits both `p alpha`** to sidestep the positional ambiguity.
- `-lump` default = **RowSum**.

### `CentralDifferenceLadruno`
```
integrator CentralDifferenceLadruno [-cfl] [-cflAbort] [-tangent] [-recompute N]
                                     [-lump rowsum|diagonal] [-verbose] [-divergence f]
```
- **No positional.** "Robust central difference" with a correct first-step
  starter + built-in `dt_cr` + βK guard. Coupled mode was dropped (use
  `NewmarkExplicit 0.5` for that case — out of scope).
- `-lump` default = **Diagonal** (⚠ *different* from the Bathe default RowSum) —
  diagonal-of-consistent. We do **not** re-emit the default; we let C++ apply it.

### Shared flag semantics (all three)
| Flag | apeGmsh kwarg | Emit | Notes (from C++) |
|---|---|---|---|
| `-cfl` | `cfl: bool=False` | `-cfl` | enable `dt_cr` estimation |
| `-cflAbort` | `cfl_abort: bool=False` | `-cflAbort` | abort if `dt`>Noh-Bathe limit; **inert unless `dt_cr` is computed** (needs one of cfl/tangent/recompute) |
| `-tangent` | `tangent: bool=False` | `-tangent` | estimate `dt_cr` from current tangent; **implies** dt_cr compute |
| `-recompute N` | `recompute: int\|None=None` | `-recompute N` | refresh `dt_cr` every N committed steps; C++ requires **N≥1** (warns + ignores otherwise); implies tangent-based dt_cr |
| `-lump rowsum\|diagonal` | `lump: Literal["rowsum","diagonal"]\|None=None` | `-lump <v>` | omit → C++ default (RowSum Bathe / Diagonal CDL) |
| `-verbose` | `verbose: bool=False` | `-verbose` | per-step dt/energy reporting |
| `-divergence f` | `divergence: float\|None=None` | `-divergence f` | abort if KE grows by factor `f`; C++ only acts when `f>0` |

**Canonical emit order** (deterministic, byte-stable):
`p [alpha] [-cfl] [-cflAbort] [-tangent] [-recompute N] [-lump v] [-verbose] [-divergence f]`.

---

## Validation (`__post_init__`) — minimal, grounded only

Per CLAUDE.md §2 ("no error handling for impossible scenarios") and §1 ("don't
assume"). We enforce only what the C++ itself rejects or what is a clear authoring
slip; we do **not** enforce cross-flag coupling (C++ is permissive there — e.g.
`-cflAbort` alone is silently inert, not an error).

- `p`: must be `∈(0,1)` → `ValueError`. *(grounded: C++ warns+bails)*
- `alpha` (LNVD): must be `∈[0,1)` → `ValueError`. *(grounded: C++ `<0 || >=1` reject)*
- `recompute`: if set, must be `≥1` → `ValueError`. *(grounded: C++ warns+ignores)*
- `divergence`: if set, must be `>0` → `ValueError`. *(C++ no-ops at `≤0`; a
  non-positive divergence factor is an authoring slip, fail loud.)*
- `lump`: `Literal["rowsum","diagonal"]` type + runtime membership guard.

A short docstring note flags that `-cflAbort` does nothing without one of
`-cfl`/`-tangent`/`-recompute` (advisory, not enforced).

---

## Files touched

**Source (4):**
1. `src/apeGmsh/opensees/analysis/integrator.py`
   - `+ def _render_explicit_cfl_options(args, *, cfl, cfl_abort, tangent, recompute, lump, verbose, divergence) -> None` — module-level helper appending flags to an `args` list in canonical order. Single source of the option grammar for all three.
   - `+ class ExplicitBathe(Integrator)` — `p` + 7 flag fields; `__post_init__`; `_emit`; `dependencies()`.
   - `+ class ExplicitBatheLNVD(Integrator)` — `p`, `alpha` + 7 flags.
   - `+ class CentralDifferenceLadruno(Integrator)` — 7 flags (no positional).
   - extend `__all__`.
2. `src/apeGmsh/opensees/analysis/__init__.py` — re-export the 3 + `__all__`.
3. `src/apeGmsh/opensees/_internal/ns/analysis.py` — import the 3; add three
   `_IntegratorNS` methods (kw-only signatures mirroring the dataclasses,
   docstrings carrying the command line + fork-only-at-run note).
4. *(none — live emitter `integrator(i_type, *args)` is already generic; no
   change needed, same as the Ladruno recorder.)*

**Tests (3):**
5. `tests/opensees/unit/primitives/test_analysis.py` — for each integrator:
   `_emit` defaults (minimal line), `_emit` all-flags (full canonical line),
   each `__post_init__` rejection, `dependencies() == ()`, and
   `ops.integrator.<X>(...)` namespace construction/registration. Mirror the
   existing `TestCentralDifference` / `TestIntegratorNamespace` blocks.
6. `tests/opensees/contract/test_analysis_contract.py` — add the 3 to imports,
   `ALL_INTEGRATORS`, and `_MINIMAL_PARAMS` (`ExplicitBathe: {"p":0.54}`,
   `ExplicitBatheLNVD: {"p":0.54,"alpha":0.8}`, `CentralDifferenceLadruno: {}`).
   This auto-enrolls them in the cross-family base-inheritance + emitter-method
   + round-trip contract suite.
7. `tests/opensees/unit/test_emitter_tcl.py` + `test_emitter_py.py` — literal
   deck-line assertions for one representative (e.g. ExplicitBathe with a couple
   of flags) on each emitter, matching how `CentralDifference` is covered.
8. **Live, fork-gated** (`@pytest.mark.live`) — new
   `tests/opensees/live/test_explicit_integrators_live.py`: build a tiny
   lumped-mass truss (system Diagonal, algorithm Linear), emit each integrator
   (ExplicitBathe `-cfl`, LNVD, CDL), `ops.analyze(steps, dt)`, assert ret==0 and
   the run advances. Skips cleanly when openseespy/fork absent.
   ⚠ **Verification caveat (from memory):** the editable install resolves to
   *main* `src/`, not this worktree — run live checks with
   `PYTHONPATH=<worktree>/src` prepended so the worktree code is exercised.

**Docs (2, canonical-only):**
9. `skills/apegmsh/references/ladruno.md` — flip the three integrator rows from
   "fork shipped" to "apeGmsh emit surface live", with the apeGmsh call.
10. `internal_docs/guide_opensees.md` (or the recorders/analysis guide) — a short
    "explicit dynamics (Ladruno fork)" subsection showing the recipe
    (lumped/element mass · `system Diagonal` · `algorithm Linear` · `dt < dt_cr`).
    Then `python scripts/sync_skill.py` + `--check` exit 0.

---

## Verification (success criteria — loop until green)

1. `mypy` clean on the 4 source files (0 new errors vs baseline).
2. `pytest tests/opensees/unit/primitives/test_analysis.py
   tests/opensees/contract/test_analysis_contract.py
   tests/opensees/unit/test_emitter_tcl.py tests/opensees/unit/test_emitter_py.py`
   — all green (new + existing).
3. Live: `PYTHONPATH=<worktree>/src <opensees_venv python> -m pytest -m live
   tests/opensees/live/test_explicit_integrators_live.py` — green against the
   fork build; each integrator analyzes ≥1 step with ret==0.
4. `scripts/sync_skill.py --check` exit 0 (skill mirror in sync).
5. No regression: targeted `pytest tests/opensees/unit tests/opensees/contract`
   (NOT whole-tree — see [[feedback-full-suite-pollution-cascade]]).

---

## Non-goals (explicit; doors left open)

- **`criticalTimeStep()` runtime query.** Verified to exist + answer in the venv
  build. A future slice exposes it via a `LiveOpsEmitter.critical_time_step()`
  method + an `apeSees` accessor (mirrors how `eigen` is plumbed). Without it,
  the user picks `dt` by hand / external estimate. **Deferred per scope choice.**
- **Auto-`dt` sub-stepping helper** (ADR D5: `n=ceil(dt/(safety·dt_cr));
  analyze(n, dt/n)`). The genuinely-useful explicit-run UX; depends on the query
  above. **Deferred.**
- **`EnergyBalance` text-sidecar recorder + reader.** Energy already lands inside
  `.ladruno` via `-G energy` (recorder-plan L4 shipped). The standalone text
  recorder is redundant for apeGmsh users on the canonical recorder. **Deferred.**
- Staged (`ops.stage`) explicit runs — `analyze` already rejects staged live
  execution; staged explicit decks emit fine via `ops.tcl`/`ops.py`. No change.

---

## Open questions to resolve *during* implementation (not blocking the plan)

- **Q1 — shared option fields: helper fn vs frozen base dataclass?** Plan picks a
  module-level `_render_explicit_cfl_options(...)` helper (the 7 flag *fields*
  are still declared on each dataclass; only the *emit rendering* is shared).
  Revisit only if field duplication across 3 classes reads worse than a
  `@dataclass` base — current call: helper, matches the flat house style.
- **Q2 — `lump` default elision.** Plan: omit `-lump` when `None` and rely on the
  C++ default. This means the *same* apeGmsh `lump=None` yields RowSum on Bathe
  but Diagonal on CDL (their differing C++ defaults). Acceptable (we mirror the
  fork, don't paper over it); the docstrings state each default explicitly.
- **Q3 — CDL reference tests.** The `ladruno` branch ships
  `tests/test_centralDifferenceLadruno_integrator.py` (+ Bathe/LNVD siblings);
  consult them for the canonical runtime recipe when writing the live test.
