"""``SectionCutDef.preflight`` — drift validator (v2.3).

A :class:`SectionCutDef` is frozen and picklable, so it survives mesh
edits that would otherwise have invalidated it. ``preflight`` checks a
cut against a live :class:`apeGmsh.mesh.FEMData.FEMData` (optionally
also a :class:`FemToOpsTagMap`) and returns a structured
:class:`PreflightReport` of any drift that's accumulated.

The validator is pure inspection — it never mutates the cut. To "fix"
a drifted cut, construct a new :class:`SectionCutDef` from the current
FEM via :meth:`SectionCutDef.from_planar_pg`.

Issue codes
-----------
``E1``  OpenSees tag in ``cut.element_ids`` not present in the tag map.
``E2``  OpenSees tag → FEM eid that no longer exists in ``fem.elements``.
``E3``  ``bounding_polygon`` vertex distance from cut plane > ``tol``.
``E4``  Filter resolves to zero existing elements in the current FEM.
``W1``  Filter element-node AABB lies entirely on one side of the plane.

Errors mean the cut cannot produce a correct result as written.
Warnings flag suspicious configurations that may still be legitimate
(e.g. an intentional edge-of-structure sweep that integrates zero
area on the far end). The architecture note in ``ARCHITECTURE.md``
(§ v2.3) documents the design decisions.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Mapping

import numpy as np

if TYPE_CHECKING:
    from apeGmsh.mesh.FEMData import FEMData

    from ._defs import SectionCutDef
    from ._tag_map import FemToOpsTagMap


Severity = Literal["error", "warning"]


class PreflightError(Exception):
    """Raised by :meth:`PreflightReport.raise_for_errors` when a report has errors."""


@dataclass(frozen=True)
class PreflightIssue:
    """One drift finding from :meth:`SectionCutDef.preflight`.

    Parameters
    ----------
    code:
        Stable issue code (``"E1"`` … ``"E4"`` or ``"W1"``). See the
        module docstring for the full catalog.
    severity:
        ``"error"`` if the cut cannot produce a correct result;
        ``"warning"`` if the configuration is suspicious but may be
        legitimate.
    message:
        One-line human-readable summary.
    detail:
        Optional structured payload (e.g. the list of missing tags).
        Caller-inspectable; not formatted into :attr:`message`.
    """

    code: str
    severity: Severity
    message: str
    detail: Mapping[str, object] | None = None


@dataclass(frozen=True)
class PreflightReport:
    """Result of :meth:`SectionCutDef.preflight`.

    Carries the originating cut's label (for legible multi-cut output)
    and a flat tuple of :class:`PreflightIssue` in check-order.
    Errors and warnings are exposed as properties so the ordering is
    preserved and there is one source of truth.
    """

    cut_label: str | None
    issues: tuple[PreflightIssue, ...]

    @property
    def errors(self) -> tuple[PreflightIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> tuple[PreflightIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "warning")

    @property
    def ok(self) -> bool:
        """``True`` when the report has no error-severity issues.

        Warnings do not block; callers that want strict semantics can
        check ``len(report.warnings) == 0`` themselves.
        """
        return not self.errors

    def raise_for_errors(self) -> None:
        """Raise :class:`PreflightError` if any error-severity issues."""
        errs = self.errors
        if not errs:
            return
        label = f" ({self.cut_label!r})" if self.cut_label else ""
        lines = [f"SectionCutDef preflight failed{label}:"]
        for e in errs:
            lines.append(f"  [{e.code}] {e.message}")
        raise PreflightError("\n".join(lines))

    def __str__(self) -> str:
        suffix = f" — {self.cut_label}" if self.cut_label else ""
        if not self.issues:
            return f"PreflightReport(ok{suffix})"
        lines = [f"PreflightReport{suffix}:"]
        for issue in self.issues:
            tag = "ERROR" if issue.severity == "error" else "warn "
            lines.append(f"  [{tag} {issue.code}] {issue.message}")
        return "\n".join(lines)


# --------------------------------------------------------------------- #
# Internal check pipeline
# --------------------------------------------------------------------- #
def run_cut_checks(
    cut: "SectionCutDef",
    fem: "FEMData",
    *,
    model_h5: str | Path | None = None,
    tag_map: "FemToOpsTagMap | None" = None,
    tol: float = 1e-6,
) -> PreflightReport:
    """Check ``cut`` against ``fem``; return a structured report.

    See :meth:`SectionCutDef.preflight` for the user-facing API. This
    module-level function is the single implementation that both
    ``SectionCutDef.preflight`` and ``SectionSweepDef.preflight``
    dispatch through; the latter pre-resolves one ``tag_map`` and
    reuses it across all cuts in the sweep.

    ``model_h5`` and ``tag_map`` are mutually exclusive. If both are
    omitted, the OpenSees-tag checks (E1/E2/E4 and the W1 AABB scan,
    which depends on resolving the filter to FEM eids) are silently
    skipped — only E3 (polygon-on-plane) runs.
    """
    if model_h5 is not None and tag_map is not None:
        raise ValueError(
            "Pass either model_h5=... or tag_map=..., not both."
        )

    if tag_map is None and model_h5 is not None:
        from ._tag_map import FemToOpsTagMap
        tag_map = FemToOpsTagMap.from_h5(model_h5)

    issues: list[PreflightIssue] = []

    # E3 — bounding polygon vertices on the cut plane (independent of tag map).
    if cut.bounding_polygon is not None:
        n = cut.plane_normal_arr
        p = cut.plane_point_arr
        poly = np.asarray(cut.bounding_polygon, dtype=float)
        d_poly = (poly - p) @ n
        off = np.abs(d_poly) > tol
        if off.any():
            issues.append(PreflightIssue(
                code="E3",
                severity="error",
                message=(
                    f"{int(off.sum())} of {len(poly)} bounding-polygon "
                    f"vertex/vertices lie off the cut plane "
                    f"(|signed distance| > tol={tol:g}; "
                    f"max = {float(np.abs(d_poly).max()):g})."
                ),
                detail={
                    "max_abs_distance": float(np.abs(d_poly).max()),
                    "n_off_plane": int(off.sum()),
                    "n_total": int(len(poly)),
                },
            ))

    if tag_map is None:
        return PreflightReport(cut_label=cut.label, issues=tuple(issues))

    # E1 — every ops_tag in cut.element_ids must be present in the tag map.
    missing_ops_tags: list[int] = []
    resolved_pairs: list[tuple[int, int]] = []  # (ops_tag, fem_eid)
    for ops_tag in cut.element_ids:
        try:
            fem_eid = tag_map.fem_eids_for_ops_tags([ops_tag])[0]
        except KeyError:
            missing_ops_tags.append(int(ops_tag))
        else:
            resolved_pairs.append((int(ops_tag), int(fem_eid)))
    if missing_ops_tags:
        sample = missing_ops_tags[:10]
        tail = "…" if len(missing_ops_tags) > 10 else ""
        issues.append(PreflightIssue(
            code="E1",
            severity="error",
            message=(
                f"{len(missing_ops_tags)} OpenSees tag(s) in cut.element_ids "
                f"not present in the tag map: {sample}{tail}."
            ),
            detail={"missing_ops_tags": tuple(missing_ops_tags)},
        ))

    # E2 — every resolved FEM eid must still exist in fem.elements.
    existing_fem_ids = set(int(x) for x in np.asarray(fem.elements.ids))
    surviving_fem_eids: list[int] = []
    missing_fem_eids: list[tuple[int, int]] = []
    for ops_tag, fem_eid in resolved_pairs:
        if fem_eid in existing_fem_ids:
            surviving_fem_eids.append(fem_eid)
        else:
            missing_fem_eids.append((ops_tag, fem_eid))
    if missing_fem_eids:
        sample = missing_fem_eids[:10]  # type: ignore[assignment]
        tail = "…" if len(missing_fem_eids) > 10 else ""
        issues.append(PreflightIssue(
            code="E2",
            severity="error",
            message=(
                f"{len(missing_fem_eids)} FEM element(s) referenced by the "
                f"cut no longer exist in the FEM. "
                f"Sample (ops_tag → fem_eid): {sample}{tail}."
            ),
            detail={"missing": tuple(missing_fem_eids)},
        ))

    # E4 — at least one filter element must remain.
    if not surviving_fem_eids:
        issues.append(PreflightIssue(
            code="E4",
            severity="error",
            message=(
                "All filter elements are missing from the current FEM; "
                "the cut would resolve to zero elements."
            ),
        ))
        return PreflightReport(cut_label=cut.label, issues=tuple(issues))

    # W1 — bulk filter-node AABB must straddle the cut plane.
    _maybe_w1(cut, fem, surviving_fem_eids, tol, issues)

    return PreflightReport(cut_label=cut.label, issues=tuple(issues))


def _maybe_w1(
    cut: "SectionCutDef",
    fem: "FEMData",
    surviving_fem_eids: list[int],
    tol: float,
    issues: list[PreflightIssue],
) -> None:
    """Append a W1 issue if every filter node is on one side of the plane."""
    surviving_set = set(surviving_fem_eids)
    node_ids: set[int] = set()
    for group in fem.elements:
        if len(group.ids) == 0:
            continue
        mask = np.isin(group.ids, list(surviving_set))
        if mask.any():
            node_ids.update(int(n) for n in group.connectivity[mask].ravel())
    if not node_ids:
        return

    coords = _coords_for_node_ids(fem, node_ids)
    if coords.size == 0:
        return
    d = (coords - cut.plane_point_arr) @ cut.plane_normal_arr
    d_min = float(d.min())
    d_max = float(d.max())
    if d_min > tol:
        side = "positive"
    elif d_max < -tol:
        side = "negative"
    else:
        return
    issues.append(PreflightIssue(
        code="W1",
        severity="warning",
        message=(
            f"All filter element nodes lie on the {side} side of the cut "
            f"plane (signed distance range [{d_min:g}, {d_max:g}], tol={tol:g}). "
            "Cut would integrate zero area."
        ),
        detail={
            "min_signed_distance": d_min,
            "max_signed_distance": d_max,
            "side": side,
        },
    ))


def _coords_for_node_ids(fem: "FEMData", node_ids: set[int]) -> np.ndarray:
    """Look up node coordinates for ``node_ids`` via :class:`NodeComposite`."""
    out: list[np.ndarray] = []
    for nid in node_ids:
        try:
            idx = fem.nodes.index(nid)
        except KeyError:
            continue
        out.append(np.asarray(fem.nodes.coords[idx], dtype=float))
    if not out:
        return np.zeros((0, 3))
    return np.stack(out, axis=0)
