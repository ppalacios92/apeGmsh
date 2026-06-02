"""
``_DampingNS`` — backs ``ops.damping.<verb>(...)`` (ADR 0053).

Damping is a domain-level concern (sibling of ``fix`` / ``mass`` /
``region``), not part of the analysis chain.  Every verb is a declaration
recorded on the bridge and resolved at emit time — there is no ``assign``
step and no user-held object (ADR 0053).

D1 ships ``rayleigh`` (global only).  Region scoping (``on=``), modal damping
(``modal``), and the object-backed forms (``uniform`` / ``sec_stif`` /
``urd`` / ``urd_beta``) land in later slices.
"""
from __future__ import annotations

from ...analysis.rayleigh import Stiffness, rayleigh_from_ratio
from ..build import RayleighRecord
from ._base import _BridgeNamespace


__all__ = ["_DampingNS"]


class _DampingNS(_BridgeNamespace):
    """``ops.damping.<verb>(...)`` — domain-level damping declarations."""

    def rayleigh(
        self,
        *,
        alpha_m: float | None = None,
        beta_k: float | None = None,
        beta_k_init: float = 0.0,
        beta_k_comm: float = 0.0,
        ratio: float | None = None,
        f_i: float | None = None,
        f_j: float | None = None,
        stiffness: Stiffness = "initial",
    ) -> None:
        """Declare global Rayleigh damping → ``rayleigh αM βK βK0 βKc``.

        Two mutually exclusive forms:

        * **raw** — supply ``alpha_m`` and/or ``beta_k`` (and optionally
          ``beta_k_init`` / ``beta_k_comm``); the four coefficients pass
          straight through to the OpenSees command.
        * **ratio** — supply ``ratio``, ``f_i``, ``f_j`` (Hz); the
          two-target Rayleigh fit computes ``alpha_m`` and a single ``β``
          placed in the slot named by ``stiffness`` (default ``initial`` =
          ``betaK0``, the nonlinear-safe choice — ADR 0053).  ``stiffness``
          is ignored by the raw form.

        Global scope only in D1; ``on=`` region scoping lands in D2.

        Raises
        ------
        ValueError
            If both forms (or neither) are supplied, or the ratio form is
            missing any of ``ratio`` / ``f_i`` / ``f_j``.
        """
        raw_given = (
            alpha_m is not None
            or beta_k is not None
            or beta_k_init != 0.0
            or beta_k_comm != 0.0
        )
        ratio_given = ratio is not None or f_i is not None or f_j is not None
        if raw_given and ratio_given:
            raise ValueError(
                "ops.damping.rayleigh: supply the raw form "
                "(alpha_m/beta_k/...) OR the ratio form (ratio/f_i/f_j), "
                "not both.",
            )
        if ratio_given:
            if ratio is None or f_i is None or f_j is None:
                raise ValueError(
                    "ops.damping.rayleigh: the ratio form needs all of "
                    f"ratio=, f_i=, f_j= (got ratio={ratio!r}, f_i={f_i!r}, "
                    f"f_j={f_j!r}).",
                )
            coeffs = rayleigh_from_ratio(
                ratio=ratio, f_i=f_i, f_j=f_j, stiffness=stiffness,
            )
        elif raw_given:
            coeffs = (
                float(alpha_m or 0.0),
                float(beta_k or 0.0),
                float(beta_k_init),
                float(beta_k_comm),
            )
        else:
            raise ValueError(
                "ops.damping.rayleigh: supply either the raw form "
                "(alpha_m/beta_k/...) or the ratio form (ratio/f_i/f_j).",
            )
        self._bridge._rayleigh_records.append(RayleighRecord(*coeffs))
