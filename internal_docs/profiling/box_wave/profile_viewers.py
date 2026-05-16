"""Profile model.viewer / mesh.viewer on the box_wave_propagation model.

How to run
----------
1. Activate the apeGmsh venv (per memory: C:\\Users\\nmora\\venv\\opensees_venv\\).
2. From the repo root::

       python internal_docs/profiling/box_wave/profile_viewers.py [stage] [--scale S]

   ``stage`` is one of ``model`` | ``mesh`` | ``both`` (default: ``both``).
   ``--scale S`` shrinks the mesh by overriding ``P`` (nodes per wavelength)
   and ``fmax``. ``S=1.0`` is full size (~85k hex), ``S=0.25`` is ~5k hex,
   useful for iteration.

3. Interact normally (rotate, pan, toggle outline rows). When you close
   the window, cProfile dumps ``.prof`` next to this script and prints the
   top-30 cumulative-time entries.

4. Inspect with snakeviz::

       snakeviz internal_docs/profiling/box_wave/model_viewer.prof
       snakeviz internal_docs/profiling/box_wave/mesh_viewer.prof

The scene builders' built-in ``verbose=True`` timings also print to stdout
(controlled by ``apeGmsh(verbose=True)``), so cold-start phase breakdown
shows up even without opening snakeviz.
"""
from __future__ import annotations

import argparse
import cProfile
import pstats
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ─────────────────────────────────────────────────────────────────────
# Import shim — force the worktree's apeGmsh, not the editable install.
#
# The venv has a PEP-660 editable install of apeGmsh pinned to the main
# checkout (C:\Users\nmora\Github\apeGmsh\src). Its finder is *appended*
# to sys.meta_path, so it runs AFTER the default PathFinder. Putting the
# worktree's src on sys.path[0] makes PathFinder resolve apeGmsh here
# first and the editable finder never gets consulted.
# ─────────────────────────────────────────────────────────────────────
_WORKTREE_SRC = HERE.parents[2] / "src"
sys.path.insert(0, str(_WORKTREE_SRC))


# ─────────────────────────────────────────────────────────────────────
# Model build (mirrors the notebook, parameterised on ``scale``)
# ─────────────────────────────────────────────────────────────────────

def build_model(scale: float):
    import gmsh
    from apeGmsh import apeGmsh
    from baseUnits.systems.kN_m_s import m, s, kg

    class Layer:
        def __init__(self, name, gamma, Vp, nu):
            self.name, self.gamma, self.Vp, self.nu = name, gamma, Vp, nu

        @property
        def G(self):
            return self.gamma * self.Vp**2 * (1 - 2*self.nu) / (2 * (1 - self.nu))

        @property
        def Vs(self):
            return (self.G / self.gamma) ** 0.5

    # Mesh sizing — same as the notebook, but scaled.
    fmax = 5.0 * scale       # scale<1 → fewer nodes per wavelength → coarser
    P    = 3
    ztop, z1, z2, zbot = 0.0, -45.0, -120.0, -200.0
    xmin, xmax = -5000.0, 5000.0
    ymin, ymax = -5000.0, 5000.0
    nu = 0.3

    layers = {
        'layer_top': Layer('layer_top', gamma=2.3*kg/m**3, Vp=300.0 *m/s, nu=nu),
        'layer_mid': Layer('layer_mid', gamma=2.4*kg/m**3, Vp=1100.0*m/s, nu=nu),
        'layer_bot': Layer('layer_bot', gamma=2.4*kg/m**3, Vp=1200.0*m/s, nu=nu),
    }
    dz = {n: L.Vs / (P * fmax) for n, L in layers.items()}
    dh = 10.0 * min(dz.values())
    h_top, h_mid, h_bot = ztop - z1, z1 - z2, z2 - zbot

    def n_from(L, d):
        return max(2, round(L / d) + 1)

    Nz_top = n_from(h_top, dz['layer_top'])
    Nz_mid = n_from(h_mid, dz['layer_mid'])
    Nz_bot = n_from(h_bot, dz['layer_bot'])
    Nh     = n_from(xmax - xmin, dh)

    g = apeGmsh(model_name="box_wave_profile", verbose=True)
    g.begin()
    L, W = xmax - xmin, ymax - ymin
    g.model.geometry.add_box(xmin, ymin, zbot, L, W, h_bot, label="layer_bot")
    g.model.geometry.add_box(xmin, ymin, z2,   L, W, h_mid, label="layer_mid")
    g.model.geometry.add_box(xmin, ymin, z1,   L, W, h_top, label="layer_top")
    g.model.boolean.fragment(["layer_bot"], ["layer_mid", "layer_top"])
    for name in ("layer_top", "layer_mid", "layer_bot"):
        g.physical.add_volume(name, name=name)
    g.model.queries.select(tags='layer_bot', crossing={"z": zbot}).to_physical(name='bottom')
    surf = g.model.queries.select_all_surfaces()
    (surf.normal_along("x") | surf.normal_along("y")).to_physical(name="sides")

    return g, dict(Nh=Nh, Nz_top=Nz_top, Nz_mid=Nz_mid, Nz_bot=Nz_bot), gmsh


def generate_mesh(g, sizing, gmsh):
    for layer, n_z in [
        ("layer_top", sizing["Nz_top"]),
        ("layer_mid", sizing["Nz_mid"]),
        ("layer_bot", sizing["Nz_bot"]),
    ]:
        g.mesh.structured.set_transfinite(
            layer, n={"x": sizing["Nh"], "y": sizing["Nh"], "z": n_z}
        )
    gmsh.option.setNumber("Mesh.SubdivisionAlgorithm", 2)
    gmsh.option.setNumber("Mesh.Smoothing", 5)
    t = time.perf_counter()
    g.mesh.generation.generate()
    print(f"[profile] mesh generation: {time.perf_counter() - t:.2f}s")


# ─────────────────────────────────────────────────────────────────────
# Profile drivers
# ─────────────────────────────────────────────────────────────────────

def _dump(profiler: cProfile.Profile, out: Path, label: str):
    profiler.disable()
    out.parent.mkdir(parents=True, exist_ok=True)
    profiler.dump_stats(str(out))
    print(f"\n[profile] {label} → {out}")
    stats = pstats.Stats(profiler).sort_stats("cumulative")
    print(f"\n── Top 30 cumulative-time (whole {label} session) ──")
    stats.print_stats(30)
    print(f"\n── Top 20 internal-time (whole {label} session) ──")
    pstats.Stats(profiler).sort_stats("tottime").print_stats(20)


def profile_model_viewer(g, out_dir: Path):
    print("\n[profile] opening model.viewer — interact then close the window …")
    profiler = cProfile.Profile()
    profiler.enable()
    g.model.viewer()
    _dump(profiler, out_dir / "model_viewer.prof", "model.viewer")


def profile_mesh_viewer(g, out_dir: Path):
    print("\n[profile] opening mesh.viewer — interact then close the window …")
    profiler = cProfile.Profile()
    profiler.enable()
    g.mesh.viewer()
    _dump(profiler, out_dir / "mesh_viewer.prof", "mesh.viewer")


# ─────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("stage", nargs="?", default="both",
                   choices=("model", "mesh", "both"))
    p.add_argument("--scale", type=float, default=1.0,
                   help="Mesh-size scale (1.0 = full, 0.25 ≈ 5k hex)")
    p.add_argument("--out", type=Path, default=HERE)
    args = p.parse_args(argv)

    print(f"[profile] scale={args.scale}  stage={args.stage}")

    # Hard guard: confirm we're profiling the worktree code, not the
    # editable install. Abort loudly if the shim didn't take.
    import apeGmsh as _ape
    _ape_path = Path(_ape.__file__).resolve()
    print(f"[profile] apeGmsh loaded from: {_ape_path}")
    if str(_WORKTREE_SRC) not in str(_ape_path):
        print(
            f"[profile] FATAL: expected apeGmsh under {_WORKTREE_SRC}, "
            f"got {_ape_path}. The sys.path shim failed — aborting so we "
            f"don't profile the wrong code.",
            file=sys.stderr,
        )
        return 2

    t0 = time.perf_counter()
    g, sizing, gmsh = build_model(args.scale)
    print(f"[profile] model build: {time.perf_counter() - t0:.2f}s  "
          f"(Nh={sizing['Nh']}, Nz_top={sizing['Nz_top']}, "
          f"Nz_mid={sizing['Nz_mid']}, Nz_bot={sizing['Nz_bot']})")

    if args.stage in ("model", "both"):
        profile_model_viewer(g, args.out)

    if args.stage in ("mesh", "both"):
        generate_mesh(g, sizing, gmsh)
        profile_mesh_viewer(g, args.out)

    g.end()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
