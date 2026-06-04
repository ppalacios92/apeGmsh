"""Unit tests for the ``LadrunoEmbeddedRebar`` emit-grammar builder.

``embedded_rebar_args`` is the single source of truth for the
positional argument order of ``element LadrunoEmbeddedRebar`` — it must
mirror ``OPS_LadrunoEmbeddedRebar.cpp`` exactly. These tests assert the
emitted arg list for each flag combination and the validation guards.
No geometry, no fork, no run.
"""
from __future__ import annotations

import pytest

from apeGmsh.opensees.element.embedded_rebar import (
    ELE_TAG,
    ELEMENT_TYPE,
    embedded_rebar_args,
)


class TestHappyPath:
    def test_host_xi_perfect_minimal(self) -> None:
        # 3D LadrunoBrick host queried by element tag, weights via -xi,
        # perfect bond, default penalty enforcement.
        args = embedded_rebar_args(
            rebar_node=5,
            host_ele=100,
            xi=(0.0, 0.0, 0.0),
            direction=(1.0, 0.0, 0.0),
            perfect=1.0e8,
        )
        assert args == [
            5, "-host", 100, "-xi", 0.0, 0.0, 0.0,
            "-dir", 1.0, 0.0, 0.0, "-perfect", 1.0e8,
        ]

    def test_explicit_hosts_shape_bond(self) -> None:
        # 2D quad host: explicit nodes + apeGmsh-computed -shape weights,
        # bond-slip axial law with a bondScale.
        args = embedded_rebar_args(
            rebar_node=7,
            host_nodes=(1, 2, 3, 4),
            shape=(0.25, 0.25, 0.25, 0.25),
            direction=(0.0, 1.0),
            bond=9,
            bond_scale=37.7,
        )
        assert args == [
            7, 4, 1, 2, 3, 4, "-shape", 0.25, 0.25, 0.25, 0.25,
            "-dir", 0.0, 1.0, "-bond", 9, "-bondScale", 37.7,
        ]

    def test_kt_auto_with_alpha(self) -> None:
        args = embedded_rebar_args(
            rebar_node=1, host_ele=2, xi=(0.5, 0.5, 0.5),
            direction=(1.0, 0.0, 0.0), perfect=1e9,
            kt="auto", kt_alpha=1.0e3,
        )
        assert args[-4:] == ["-kt", "auto", "-ktAlpha", 1.0e3]

    def test_kt_numeric(self) -> None:
        args = embedded_rebar_args(
            rebar_node=1, host_nodes=(1, 2, 3),
            shape=(0.3, 0.3, 0.4), direction=(1.0, 0.0),
            perfect=1e9, kt=1.0e8,
        )
        assert args[-2:] == ["-kt", 1.0e8]

    def test_enforce_al_emitted(self) -> None:
        args = embedded_rebar_args(
            rebar_node=1, host_ele=2, xi=(0.0, 0.0, 0.0),
            direction=(1.0, 0.0, 0.0), perfect=1e9, enforce="al",
        )
        assert args[-2:] == ["-enforce", "al"]

    def test_enforce_penalty_is_default_and_omitted(self) -> None:
        # penalty is the parser default — emit nothing to keep decks lean.
        args = embedded_rebar_args(
            rebar_node=1, host_ele=2, xi=(0.0, 0.0, 0.0),
            direction=(1.0, 0.0, 0.0), perfect=1e9, enforce="penalty",
        )
        assert "-enforce" not in args

    def test_corot_with_xiB(self) -> None:
        args = embedded_rebar_args(
            rebar_node=1, host_ele=2, xi=(0.0, 0.0, 0.0),
            direction=(1.0, 0.0, 0.0), perfect=1e9,
            corot=True, xi_b=(0.5, 0.0, 0.0),
        )
        assert args[-5:] == ["-corot", "-xiB", 0.5, 0.0, 0.0]

    def test_corot_with_shapeB(self) -> None:
        args = embedded_rebar_args(
            rebar_node=1, host_nodes=(1, 2, 3, 4),
            shape=(0.25, 0.25, 0.25, 0.25), direction=(1.0, 0.0),
            perfect=1e9, corot=True, shape_b=(0.1, 0.2, 0.3, 0.4),
        )
        assert args[-6:] == ["-corot", "-shapeB", 0.1, 0.2, 0.3, 0.4]

    def test_bipenalty_dtcr(self) -> None:
        args = embedded_rebar_args(
            rebar_node=1, host_ele=2, xi=(0.0, 0.0, 0.0),
            direction=(1.0, 0.0, 0.0), perfect=1e9,
            bipenalty=True, dtcr=1.0e-6,
        )
        assert args[-3:] == ["-bipenalty", "-dtcr", 1.0e-6]

    def test_bipenalty_wcap(self) -> None:
        args = embedded_rebar_args(
            rebar_node=1, host_ele=2, xi=(0.0, 0.0, 0.0),
            direction=(1.0, 0.0, 0.0), perfect=1e9,
            bipenalty=True, wcap=0.8,
        )
        assert args[-3:] == ["-bipenalty", "-wcap", 0.8]

    def test_full_grammar_order(self) -> None:
        # all optionals together — locks the canonical ordering.
        args = embedded_rebar_args(
            rebar_node=3, host_ele=50, xi=(0.1, 0.2, 0.3),
            direction=(1.0, 0.0, 0.0),
            bond=9, bond_scale=12.0,
            kt="auto", kt_alpha=1.0e3,
            corot=True, xi_b=(0.4, 0.2, 0.3),
            enforce="al",
        )
        assert args == [
            3, "-host", 50, "-xi", 0.1, 0.2, 0.3,
            "-dir", 1.0, 0.0, 0.0,
            "-bond", 9, "-bondScale", 12.0,
            "-kt", "auto", "-ktAlpha", 1.0e3,
            "-corot", "-xiB", 0.4, 0.2, 0.3,
            "-enforce", "al",
        ]

    def test_module_constants(self) -> None:
        assert ELEMENT_TYPE == "LadrunoEmbeddedRebar"
        assert ELE_TAG == 33005


class TestValidation:
    BASE = dict(rebar_node=1, direction=(1.0, 0.0, 0.0))

    def test_rejects_bad_direction_dim(self) -> None:
        with pytest.raises(ValueError, match="2 or 3 components"):
            embedded_rebar_args(
                rebar_node=1, direction=(1.0,), host_ele=2,
                xi=(0.0,), perfect=1e9,
            )

    def test_rejects_both_host_specs(self) -> None:
        with pytest.raises(ValueError, match="exactly one of host_ele"):
            embedded_rebar_args(
                **self.BASE, host_ele=2, host_nodes=(1, 2, 3),
                xi=(0.0, 0.0, 0.0), perfect=1e9,
            )

    def test_rejects_no_host_spec(self) -> None:
        with pytest.raises(ValueError, match="exactly one of host_ele"):
            embedded_rebar_args(
                **self.BASE, shape=(0.5, 0.5), perfect=1e9,
            )

    def test_rejects_both_weight_specs(self) -> None:
        with pytest.raises(ValueError, match="exactly one of xi"):
            embedded_rebar_args(
                **self.BASE, host_ele=2,
                xi=(0.0, 0.0, 0.0), shape=(0.25, 0.25, 0.25, 0.25),
                perfect=1e9,
            )

    def test_xi_requires_host_form(self) -> None:
        with pytest.raises(ValueError, match="xi .* requires the host_ele"):
            embedded_rebar_args(
                **self.BASE, host_nodes=(1, 2, 3, 4),
                xi=(0.0, 0.0, 0.0), perfect=1e9,
            )

    def test_xi_dim_must_match_direction(self) -> None:
        with pytest.raises(ValueError, match="xi must have ndm=3"):
            embedded_rebar_args(
                **self.BASE, host_ele=2, xi=(0.0, 0.0), perfect=1e9,
            )

    def test_shape_len_must_match_hosts(self) -> None:
        with pytest.raises(ValueError, match="shape has 3 weights"):
            embedded_rebar_args(
                rebar_node=1, direction=(1.0, 0.0),
                host_nodes=(1, 2, 3, 4), shape=(0.3, 0.3, 0.4),
                perfect=1e9,
            )

    def test_rejects_both_axial_laws(self) -> None:
        with pytest.raises(ValueError, match="exactly one axial law"):
            embedded_rebar_args(
                **self.BASE, host_ele=2, xi=(0.0, 0.0, 0.0),
                perfect=1e9, bond=9,
            )

    def test_rejects_no_axial_law(self) -> None:
        with pytest.raises(ValueError, match="exactly one axial law"):
            embedded_rebar_args(
                **self.BASE, host_ele=2, xi=(0.0, 0.0, 0.0),
            )

    def test_bond_scale_needs_bond(self) -> None:
        with pytest.raises(ValueError, match="bond_scale .* only valid with"):
            embedded_rebar_args(
                **self.BASE, host_ele=2, xi=(0.0, 0.0, 0.0),
                perfect=1e9, bond_scale=10.0,
            )

    def test_kt_auto_needs_host(self) -> None:
        with pytest.raises(ValueError, match="kt='auto' .* requires the host"):
            embedded_rebar_args(
                rebar_node=1, direction=(1.0, 0.0),
                host_nodes=(1, 2, 3, 4), shape=(0.25, 0.25, 0.25, 0.25),
                perfect=1e9, kt="auto",
            )

    def test_kt_alpha_needs_auto(self) -> None:
        with pytest.raises(ValueError, match="kt_alpha .* only applies"):
            embedded_rebar_args(
                **self.BASE, host_ele=2, xi=(0.0, 0.0, 0.0),
                perfect=1e9, kt=1e8, kt_alpha=1e3,
            )

    def test_rejects_bad_enforce(self) -> None:
        with pytest.raises(ValueError, match="enforce must be"):
            embedded_rebar_args(
                **self.BASE, host_ele=2, xi=(0.0, 0.0, 0.0),
                perfect=1e9, enforce="nitsche",
            )

    def test_corot_needs_point_b(self) -> None:
        with pytest.raises(ValueError, match="corot requires exactly one"):
            embedded_rebar_args(
                **self.BASE, host_ele=2, xi=(0.0, 0.0, 0.0),
                perfect=1e9, corot=True,
            )

    def test_pointb_without_corot_rejected(self) -> None:
        with pytest.raises(ValueError, match="only valid with corot"):
            embedded_rebar_args(
                **self.BASE, host_ele=2, xi=(0.0, 0.0, 0.0),
                perfect=1e9, xi_b=(0.5, 0.0, 0.0),
            )

    def test_bipenalty_needs_one_budget(self) -> None:
        with pytest.raises(ValueError, match="bipenalty requires exactly one"):
            embedded_rebar_args(
                **self.BASE, host_ele=2, xi=(0.0, 0.0, 0.0),
                perfect=1e9, bipenalty=True,
            )

    def test_bipenalty_gated_on_penalty(self) -> None:
        with pytest.raises(ValueError, match="gated on enforce='penalty'"):
            embedded_rebar_args(
                **self.BASE, host_ele=2, xi=(0.0, 0.0, 0.0),
                perfect=1e9, enforce="al", bipenalty=True, dtcr=1e-6,
            )

    def test_wcap_needs_host(self) -> None:
        with pytest.raises(ValueError, match="wcap .* requires the host"):
            embedded_rebar_args(
                rebar_node=1, direction=(1.0, 0.0),
                host_nodes=(1, 2, 3, 4), shape=(0.25, 0.25, 0.25, 0.25),
                perfect=1e9, bipenalty=True, wcap=0.8,
            )

    def test_budget_without_bipenalty_rejected(self) -> None:
        with pytest.raises(ValueError, match="only valid with bipenalty"):
            embedded_rebar_args(
                **self.BASE, host_ele=2, xi=(0.0, 0.0, 0.0),
                perfect=1e9, dtcr=1e-6,
            )
