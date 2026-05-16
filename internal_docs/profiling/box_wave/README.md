# box_wave_propagation viewer profiling

Profiles `g.model.viewer()` and `g.mesh.viewer()` on the stratified-soil
case study (10 km × 10 km × 200 m, transfinite hex). Tracks both cold-start
build time and interactive cost; close the window to end profiling.

> **Import note:** the venv has a PEP-660 editable install of apeGmsh
> pinned to the *main* checkout (`…\Github\apeGmsh\src`). The script
> prepends this worktree's `src` to `sys.path` so it profiles the
> worktree code, and hard-aborts if that shim fails. The first
> `[profile] apeGmsh loaded from:` line in the output must point inside
> this worktree — if it doesn't, the numbers are meaningless.

## Run

```powershell
# full size (~85k hex) — both viewers
C:\Users\nmora\venv\opensees_venv\Scripts\python.exe `
    internal_docs/profiling/box_wave/profile_viewers.py both

# just model.viewer, scaled to ~5k hex for fast iteration
C:\Users\nmora\venv\opensees_venv\Scripts\python.exe `
    internal_docs/profiling/box_wave/profile_viewers.py model --scale 0.25
```

While each viewer is open:

- **Cold-start sample**: just close the window immediately after first paint.
- **Interactive sample**: rotate / pan / zoom for ~10 s, toggle a few outline
  rows, then close.

cProfile keeps running through the whole session, so doing both in one go
(close → open next stage) gives one combined profile per viewer.

## Output

- `model_viewer.prof`, `mesh_viewer.prof` — pstats binary dumps (gitignored).
- Top-30 cumulative + top-20 tottime printed to stdout on window close.
- Scene builders print their own phase breakdown (`verbose=True`) — copy
  those lines into a session note.

## Inspect

```powershell
pip install snakeviz   # one-time
snakeviz internal_docs/profiling/box_wave/mesh_viewer.prof
```

In snakeviz, the **Icicle** view is the cleanest for "where did time go".
Hover deep frames to find hot leaves.

## Notes / known suspects

- `pyvista.UnstructuredGrid.extract_all_edges()` runs once per `dim>=2`
  in [mesh_scene.py:494](../../../src/apeGmsh/viewers/scene/mesh_scene.py)
  — expensive on the 85k-hex mesh, and is the dominant wireframe-build cost.
- `MeshOutlineTree` (PR #184, merged into `main`) walks every PG / element-type
  bucket on construction; check whether its sort/format costs scale poorly.
- Per-dim node-cloud glyph build in `build_node_cloud` repeats per dim.
- `gmsh.model.getPhysicalGroups()` / `getPhysicalName()` are cheap individually
  but called from several call sites during scene build — count them in the
  profile.

Don't act on any of these until the profile data confirms them.
