# P3-K oracle — frozen behaviour record for P3-R proof-file rewrites

`selection-unification-v2.md` §6.2 P3-K ("Record the P3-K oracle run")
+ P3-R gate ("rewritten proof tests behaviour-equal to the recorded
P3-K oracle"). Created at the P3-K commit, while the legacy
removal-target surface still exists and is proven byte-faithful (the
P3-K invisibility gate: full suite 5909/64/0, the 4 proof files
byte-unchanged & green, only `mesh/_mesh_selection.py` +
`_kernel/spatial.py` changed).

## Why these files are the oracle

`tests/test_target_resolution.py` and `tests/test_pin_resolution_v2.py`
are **characterization pins**: each assertion encodes a *concrete,
inline* expected value (resolved id-sets, exact integer lattice counts,
label-vs-PG precedence) observed on the legacy `fem.*.get` /
`fem.*.resolve` surface. The pins **are** the behaviour record — no
separate value dump can be more authoritative than the asserted
literals themselves.

P3-R hard-removes `fem.*.get/get_ids/get_coords/resolve`, so these two
files must be rewritten onto the new idiom (`fem.*.select(...).ids` /
`.groups()` / `.result()`). The `.P3K.frozen` files here are the
**byte-exact P3-K-state copies** (identical to `git show
<P3K-commit>:tests/<name>`; both are byte-unchanged vs `63a4312`).

## The P3-R contract (how to use this)

For each scenario, the P3-R-rewritten test MUST assert the **same
concrete expected values** as the corresponding `.P3K.frozen` copy —
only the *resolution call* changes:

| legacy (frozen) | P3-R rewrite |
|---|---|
| `fem.nodes.get(label="foo").ids` | `fem.nodes.select(label="foo").ids` |
| `fem.elements.get(pg=X).ids` | `fem.elements.select(pg=X).ids` |
| `fem.elements.get(...).resolve()` | `fem.elements.select(...).result().resolve()` |

The scene builders, the expected id-sets, the exact lattice counts, the
label/PG precedence assertions, and the silent-empty / union
characterizations **must be byte-for-byte identical** between the
rewritten test and the `.frozen` copy. Verify by diffing the rewritten
file against the `.frozen` copy: the *only* allowed delta is the
resolution-call surface (`.get(` → `.select(`...). Any change to an
expected literal is a behaviour change and must be a separately
reviewed pin-flip (it is **not** in P3-R scope — P3-R is removal +
behaviour-identical migration; the only ratified behaviour change is
the P3-R `_mesh_filters.py:159/:215` silent-row-0→fail-loud diff,
which is unrelated to these two files).

`p3k_state.txt` records the P3-K commit SHA and the recorded
green-result for `pytest tests/test_target_resolution.py
tests/test_pin_resolution_v2.py` at P3-K.

Not collected by pytest (`.frozen` ≠ `test_*.py`); purely additive.
