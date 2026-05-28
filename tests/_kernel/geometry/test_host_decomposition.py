"""Phase 1 — Kuhn decomposition lift (Compose v1.1-A.2 / ADR 0041).

Pure-numpy unit tests for
:func:`apeGmsh._kernel.geometry._host_decomposition.decompose_hosts_to_subelements`.
The function is source-agnostic: tests build connectivity arrays
directly, never touch gmsh, and never instantiate FEMData.

Positive-volume + Gmsh-ordering invariants for the three Kuhn tables
(``HEX8_TO_6_TETS`` / ``PRISM6_TO_3_TETS`` / ``PYRAMID5_TO_2_TETS``)
are exhaustively guarded by ``tests/test_embedded_decomposition.py``
against ``gmsh.model.mesh.getElementProperties(...)``; this file does
not duplicate those checks — it exercises the dispatch logic that
sits *above* the tables.
"""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from apeGmsh._kernel.geometry._host_decomposition import (
    HEX8_TO_6_TETS,
    PRISM6_TO_3_TETS,
    PYRAMID5_TO_2_TETS,
    decompose_hosts_to_subelements,
)


# ---------------------------------------------------------------------
# Linear hosts — identity / table decomposition produces expected shapes
# ---------------------------------------------------------------------


class TestLinearHosts:
    def test_tri3_identity(self) -> None:
        """One tri3 → one (F=1, 3) row containing the same nodes."""
        conn = np.array([1, 2, 3], dtype=int)
        out = decompose_hosts_to_subelements([(2, conn)])
        assert out.shape == (1, 3)
        np.testing.assert_array_equal(out[0], [1, 2, 3])

    def test_tet4_identity(self) -> None:
        conn = np.array([10, 11, 12, 13], dtype=int)
        out = decompose_hosts_to_subelements([(4, conn)])
        assert out.shape == (1, 4)
        np.testing.assert_array_equal(out[0], [10, 11, 12, 13])

    def test_quad4_splits_to_two_tris(self) -> None:
        """quad4 → 2 tris via (0,1,2) + (0,2,3) split."""
        conn = np.array([100, 101, 102, 103], dtype=int)
        out = decompose_hosts_to_subelements([(3, conn)])
        assert out.shape == (2, 3)
        np.testing.assert_array_equal(out[0], [100, 101, 102])
        np.testing.assert_array_equal(out[1], [100, 102, 103])

    def test_hex8_produces_six_tets(self) -> None:
        """hex8 → 6 tets, each row picking 4 nodes per ``HEX8_TO_6_TETS``."""
        conn = np.arange(1, 9, dtype=int)  # nodes 1..8
        out = decompose_hosts_to_subelements([(5, conn)])
        assert out.shape == (6, 4)
        # Row i = nodes[HEX8_TO_6_TETS[i]] = HEX8_TO_6_TETS[i] + 1.
        for i, tet_idx in enumerate(HEX8_TO_6_TETS):
            np.testing.assert_array_equal(out[i], conn[tet_idx])

    def test_prism6_produces_three_tets(self) -> None:
        conn = np.arange(1, 7, dtype=int)
        out = decompose_hosts_to_subelements([(6, conn)])
        assert out.shape == (3, 4)
        for i, tet_idx in enumerate(PRISM6_TO_3_TETS):
            np.testing.assert_array_equal(out[i], conn[tet_idx])

    def test_pyramid5_produces_two_tets(self) -> None:
        conn = np.arange(1, 6, dtype=int)
        out = decompose_hosts_to_subelements([(7, conn)])
        assert out.shape == (2, 4)
        for i, tet_idx in enumerate(PYRAMID5_TO_2_TETS):
            np.testing.assert_array_equal(out[i], conn[tet_idx])

    def test_multi_hex_aggregates(self) -> None:
        """Two hex8 hosts → 12 tet rows (6 per hex), packed Kuhn-row first.

        Aggregation order: the function iterates ``HEX8_TO_6_TETS``
        and for each Kuhn row pushes the whole (n_elems, 4) slice — so
        rows group by Kuhn index, not by element.  Result rows are
        ``[(tet0, elem0), (tet0, elem1), (tet1, elem0), ...]``.
        """
        a = np.arange(1, 9, dtype=int)
        b = np.arange(11, 19, dtype=int)
        packed = np.concatenate([a, b])
        out = decompose_hosts_to_subelements([(5, packed)])
        assert out.shape == (12, 4)
        for i, tet_idx in enumerate(HEX8_TO_6_TETS):
            np.testing.assert_array_equal(out[2 * i], a[tet_idx])
            np.testing.assert_array_equal(out[2 * i + 1], b[tet_idx])


# ---------------------------------------------------------------------
# Higher-order hosts — corner-node-only fallback + warning
# ---------------------------------------------------------------------


class TestHigherOrderHosts:
    def test_tet10_keeps_first_four_nodes(self) -> None:
        """tet10 → 1 tet using only corner nodes [0:4]."""
        conn = np.arange(1, 11, dtype=int)
        out = decompose_hosts_to_subelements([(11, conn)])
        assert out.shape == (1, 4)
        np.testing.assert_array_equal(out[0], conn[:4])

    def test_hex20_falls_back_to_six_kuhn_tets_on_corners(self) -> None:
        """hex20 corners → 6 Kuhn tets (same as hex8 over the corner subset)."""
        conn = np.arange(1, 21, dtype=int)
        out = decompose_hosts_to_subelements([(17, conn)])
        assert out.shape == (6, 4)
        for i, tet_idx in enumerate(HEX8_TO_6_TETS):
            np.testing.assert_array_equal(out[i], conn[:8][tet_idx])

    def test_tri6_keeps_first_three_nodes(self) -> None:
        conn = np.arange(1, 7, dtype=int)
        out = decompose_hosts_to_subelements([(9, conn)])
        assert out.shape == (1, 3)
        np.testing.assert_array_equal(out[0], conn[:3])

    def test_quad8_splits_to_two_tris_on_corners(self) -> None:
        conn = np.arange(1, 9, dtype=int)
        out = decompose_hosts_to_subelements([(16, conn)])
        assert out.shape == (2, 3)
        np.testing.assert_array_equal(out[0], [1, 2, 3])
        np.testing.assert_array_equal(out[1], [1, 3, 4])

    def test_higher_order_warning_callback_fires_once(self) -> None:
        """Warning emitter fires once per call for the same higher-order etype."""
        calls: list[tuple[int, str]] = []
        # Two tet10 elements packed together — the function should
        # invoke the callback exactly once for code 11.
        conn = np.concatenate(
            [np.arange(1, 11, dtype=int), np.arange(11, 21, dtype=int)],
        )
        out = decompose_hosts_to_subelements(
            [(11, conn)], warn_higher_order=lambda c, n: calls.append((c, n)),
        )
        assert out.shape == (2, 4)
        assert calls == [(11, "tet10")]

    def test_higher_order_warning_silent_when_callback_is_none(self) -> None:
        """No callback supplied → no warnings raised by Python's warnings."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            decompose_hosts_to_subelements([(11, np.arange(1, 11, dtype=int))])
        # The function does NOT call ``warnings.warn`` itself when no
        # callback is supplied — silent fallback is acceptable.
        assert caught == []

    def test_linear_etype_does_not_invoke_callback(self) -> None:
        """Linear (non-higher-order) etypes never call the warning emitter."""
        calls: list[tuple[int, str]] = []
        decompose_hosts_to_subelements(
            [(5, np.arange(1, 9, dtype=int))],
            warn_higher_order=lambda c, n: calls.append((c, n)),
        )
        assert calls == []


# ---------------------------------------------------------------------
# Mixed-dim host — fail-loud per ADR 0036
# ---------------------------------------------------------------------


class TestMixedDimensionFailsLoud:
    def test_tri3_plus_tet4_raises(self) -> None:
        with pytest.raises(ValueError, match="BOTH 2D sub-tris and 3D sub-tets"):
            decompose_hosts_to_subelements(
                [
                    (2, np.array([1, 2, 3], dtype=int)),       # tri3
                    (4, np.array([4, 5, 6, 7], dtype=int)),    # tet4
                ],
            )

    def test_quad4_plus_hex8_raises(self) -> None:
        with pytest.raises(ValueError, match="BOTH 2D sub-tris and 3D sub-tets"):
            decompose_hosts_to_subelements(
                [
                    (3, np.array([1, 2, 3, 4], dtype=int)),    # quad4
                    (5, np.arange(11, 19, dtype=int)),         # hex8
                ],
            )


# ---------------------------------------------------------------------
# Unsupported etype — fail-loud, names the offender
# ---------------------------------------------------------------------


class TestUnsupportedEtypeRaises:
    def test_line2_unsupported(self) -> None:
        """line2 (etype 1) is not an embeddable host — fail-loud."""
        with pytest.raises(ValueError, match="line2"):
            decompose_hosts_to_subelements(
                [(1, np.array([1, 2], dtype=int))],
            )

    def test_point1_unsupported(self) -> None:
        with pytest.raises(ValueError, match="point1"):
            decompose_hosts_to_subelements(
                [(15, np.array([1], dtype=int))],
            )

    def test_unknown_code_uses_fallback_name(self) -> None:
        """An etype not in ``_ETYPE_NAMES`` still raises with a code hint."""
        with pytest.raises(ValueError, match="etype=999"):
            decompose_hosts_to_subelements(
                [(999, np.array([1, 2, 3, 4], dtype=int))],
            )


# ---------------------------------------------------------------------
# Empty / edge cases
# ---------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_groups_returns_empty(self) -> None:
        out = decompose_hosts_to_subelements([])
        assert out.shape == (0, 0)

    def test_empty_connectivity_skipped(self) -> None:
        """An (etype, empty conn) pair is silently skipped."""
        out = decompose_hosts_to_subelements(
            [(5, np.array([], dtype=int))],
        )
        assert out.shape == (0, 0)

    def test_function_is_idempotent(self) -> None:
        """Two calls with the same inputs produce identical outputs."""
        conn = np.arange(1, 9, dtype=int)
        a = decompose_hosts_to_subelements([(5, conn)])
        b = decompose_hosts_to_subelements([(5, conn)])
        np.testing.assert_array_equal(a, b)

    def test_function_does_not_mutate_input(self) -> None:
        """Input connectivity is not modified."""
        conn = np.arange(1, 9, dtype=int)
        original = conn.copy()
        decompose_hosts_to_subelements([(5, conn)])
        np.testing.assert_array_equal(conn, original)


# ---------------------------------------------------------------------
# Re-export aliases preserved for backward compat
# ---------------------------------------------------------------------


class TestBackwardCompatReExports:
    """ADR 0041 §"Decision 7" — three Kuhn tables remain importable
    from ``apeGmsh.core.ConstraintsComposite`` so legacy tests don't
    break."""

    def test_constants_re_exported_from_legacy_module(self) -> None:
        from apeGmsh.core.ConstraintsComposite import (
            HEX8_TO_6_TETS as legacy_hex,
            PRISM6_TO_3_TETS as legacy_prism,
            PYRAMID5_TO_2_TETS as legacy_pyramid,
        )

        np.testing.assert_array_equal(legacy_hex, HEX8_TO_6_TETS)
        np.testing.assert_array_equal(legacy_prism, PRISM6_TO_3_TETS)
        np.testing.assert_array_equal(legacy_pyramid, PYRAMID5_TO_2_TETS)
