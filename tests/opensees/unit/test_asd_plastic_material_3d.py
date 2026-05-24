"""Unit tests for the Phase SSI-1.5 ASDPlasticMaterial3D wrapper family.

Covers:

1. The generic :class:`ASDPlasticMaterial3D` typed dataclass — frozen,
   validates yf/pf/el/iv shape, emits the right Tcl card.
2. The :func:`MohrCoulombSoil` convenience constructor — builds the
   correct generic-class shape with MohrCoulomb_YF/PF + LinearIsotropic3D_EL
   + BackStress(NullHardeningTensorFunction):, with input validation.
3. The :class:`PlaneStrain` wrapper — emits ``nDMaterial PlaneStrain
   $tag $base_tag``.
4. The bridge namespace methods (``ops.nDMaterial.ASDPlasticMaterial3D``,
   ``ops.nDMaterial.MohrCoulombSoil``, ``ops.nDMaterial.PlaneStrain``)
   construct + register + emit correctly.
"""
from __future__ import annotations

import pytest

from apeGmsh.opensees.apesees import apeSees
from apeGmsh.opensees.emitter.tcl import TclEmitter
from apeGmsh.opensees.material.nd import (
    ASDPlasticMaterial3D,
    MohrCoulombSoil,
    PlaneStrain,
)

from tests.opensees.fixtures.fem_stub import make_two_node_beam


# ---------------------------------------------------------------------------
# 1. Generic ASDPlasticMaterial3D dataclass
# ---------------------------------------------------------------------------


def test_asd_plastic_material_3d_validates_type_strings() -> None:
    with pytest.raises(ValueError, match="yf= must be non-empty"):
        ASDPlasticMaterial3D(
            yf="", pf="MohrCoulomb_PF", el="LinearIsotropic3D_EL",
            iv="BackStress(NullHardeningTensorFunction):",
        )
    with pytest.raises(ValueError, match="pf= must be non-empty"):
        ASDPlasticMaterial3D(
            yf="MohrCoulomb_YF", pf="", el="LinearIsotropic3D_EL",
            iv="BackStress(NullHardeningTensorFunction):",
        )
    with pytest.raises(ValueError, match="iv= must be non-empty"):
        ASDPlasticMaterial3D(
            yf="MohrCoulomb_YF", pf="MohrCoulomb_PF",
            el="LinearIsotropic3D_EL", iv="",
        )


def test_asd_plastic_material_3d_emit_shape() -> None:
    mat = ASDPlasticMaterial3D(
        yf="MohrCoulomb_YF",
        pf="MohrCoulomb_PF",
        el="LinearIsotropic3D_EL",
        iv="BackStress(NullHardeningTensorFunction):",
        internal_variables=(("BackStress", (0.0,) * 6),),
        model_parameters=(("MC_c", 1000.0), ("MC_phi", 30.0)),
        integration_options=(
            ("integration_method", "Backward_Euler"),
            ("n_max_iterations", 50),
            ("f_absolute_tol", 1e-6),
        ),
    )
    e = TclEmitter()
    mat._emit(e, tag=5)
    line = e.lines()[-1]
    # Header tokens.
    assert "nDMaterial ASDPlasticMaterial3D 5" in line
    assert "MohrCoulomb_YF MohrCoulomb_PF LinearIsotropic3D_EL" in line
    assert "BackStress(NullHardeningTensorFunction):" in line
    # Blocks.
    assert "Begin_Internal_Variables BackStress 0.0 0.0 0.0 0.0 0.0 0.0 End_Internal_Variables" in line
    assert "Begin_Model_Parameters MC_c 1000.0 MC_phi 30.0 End_Model_Parameters" in line
    # Integration options: float, int, and string enum render correctly.
    assert "Begin_Integration_Options" in line
    assert "integration_method Backward_Euler" in line
    assert "n_max_iterations 50" in line  # int, not 50.0
    assert "f_absolute_tol 1e-06" in line  # float repr


def test_asd_plastic_material_3d_no_dependencies() -> None:
    mat = ASDPlasticMaterial3D(
        yf="MohrCoulomb_YF", pf="MohrCoulomb_PF",
        el="LinearIsotropic3D_EL",
        iv="BackStress(NullHardeningTensorFunction):",
    )
    assert mat.dependencies() == ()


# ---------------------------------------------------------------------------
# 2. MohrCoulombSoil convenience constructor
# ---------------------------------------------------------------------------


def test_mohr_coulomb_soil_builds_correct_generic_shape() -> None:
    mat = MohrCoulombSoil(
        c=1014.0, phi=45.95, psi=11.49,
        E=4080000.0, nu=0.18, rho=4.5,
    )
    assert isinstance(mat, ASDPlasticMaterial3D)
    assert mat.yf == "MohrCoulomb_YF"
    assert mat.pf == "MohrCoulomb_PF"
    assert mat.el == "LinearIsotropic3D_EL"
    assert mat.iv == "BackStress(NullHardeningTensorFunction):"

    iv_dict = dict(mat.internal_variables)
    assert iv_dict["BackStress"] == (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    # DP_cohesion / YieldStress are NOT in the IV list — the parser
    # silently drops them for MohrCoulomb_YF; emitting them is noise.
    assert "DP_cohesion" not in iv_dict
    assert "YieldStress" not in iv_dict

    mp_dict = dict(mat.model_parameters)
    assert mp_dict["MC_c"] == 1014.0
    assert mp_dict["MC_phi"] == 45.95
    assert mp_dict["MC_psi"] == 11.49
    assert mp_dict["YoungsModulus"] == 4080000.0
    assert mp_dict["PoissonsRatio"] == 0.18
    assert mp_dict["MassDensity"] == 4.5
    # Defensive zero-fills for non-MC parameter families.
    assert mp_dict["AF_cr"] == 0.0
    assert mp_dict["DP_eta"] == 0.0

    io_dict = dict(mat.integration_options)
    assert io_dict["integration_method"] == "Backward_Euler"
    assert io_dict["tangent_type"] == "Secant"
    assert io_dict["return_to_yield_surface"] == "Disabled"


def test_mohr_coulomb_soil_validates_inputs() -> None:
    with pytest.raises(ValueError, match="c must be >= 0"):
        MohrCoulombSoil(c=-1, phi=30, psi=0, E=1e6, nu=0.3)
    with pytest.raises(ValueError, match=r"phi must be in \[0, 90\)"):
        MohrCoulombSoil(c=0, phi=95, psi=0, E=1e6, nu=0.3)
    with pytest.raises(ValueError, match=r"psi must be in \[0, phi\]"):
        MohrCoulombSoil(c=0, phi=30, psi=50, E=1e6, nu=0.3)
    with pytest.raises(ValueError, match="E must be > 0"):
        MohrCoulombSoil(c=0, phi=30, psi=0, E=0, nu=0.3)
    with pytest.raises(ValueError, match=r"nu must be in \[0, 0.5\)"):
        MohrCoulombSoil(c=0, phi=30, psi=0, E=1e6, nu=0.5)
    with pytest.raises(ValueError, match="rho must be >= 0"):
        MohrCoulombSoil(c=0, phi=30, psi=0, E=1e6, nu=0.3, rho=-1)


def test_mohr_coulomb_soil_passes_integration_overrides() -> None:
    mat = MohrCoulombSoil(
        c=100, phi=30, psi=10, E=1e6, nu=0.3,
        integration_method="Modified_Euler_Error_Control",
        tangent_type="Continuum",
        n_max_iterations=200,
        f_absolute_tol=1e-8,
    )
    io_dict = dict(mat.integration_options)
    assert io_dict["integration_method"] == "Modified_Euler_Error_Control"
    assert io_dict["tangent_type"] == "Continuum"
    assert io_dict["n_max_iterations"] == 200
    assert io_dict["f_absolute_tol"] == 1e-8


# ---------------------------------------------------------------------------
# 3. PlaneStrain wrapper
# ---------------------------------------------------------------------------


def test_plane_strain_wraps_3d_material() -> None:
    """The wrapper carries its 3D base as a dependency so the
    topological sort emits the base first."""
    base = MohrCoulombSoil(c=100, phi=30, psi=0, E=1e6, nu=0.3)
    wrapper = PlaneStrain(base=base)
    deps = wrapper.dependencies()
    assert deps == (base,)


def test_plane_strain_emit_shape() -> None:
    """Through the bridge: PlaneStrain emits ``nDMaterial PlaneStrain
    $tag $base_tag`` with the bridge-resolved tag for ``base``."""
    fem = make_two_node_beam()
    ops = apeSees(fem, default_orientation=None)
    ops.model(ndm=2, ndf=2)
    base = ops.nDMaterial.MohrCoulombSoil(
        c=100, phi=30, psi=0, E=1e6, nu=0.3,
    )
    wrapper = ops.nDMaterial.PlaneStrain(base=base)
    bm = ops.build()
    e = TclEmitter()
    bm.emit(e)
    text = "\n".join(e.lines())
    # The base 3D material is emitted (tag is the bridge-allocated one).
    base_tag = bm.tag_for[id(base)]
    wrapper_tag = bm.tag_for[id(wrapper)]
    assert f"nDMaterial ASDPlasticMaterial3D {base_tag}" in text
    assert f"nDMaterial PlaneStrain {wrapper_tag} {base_tag}" in text


# ---------------------------------------------------------------------------
# 4. Namespace registration
# ---------------------------------------------------------------------------


def test_ndmaterial_namespace_asd_plastic_material_3d() -> None:
    fem = make_two_node_beam()
    ops = apeSees(fem, default_orientation=None)
    ops.model(ndm=2, ndf=2)
    mat = ops.nDMaterial.ASDPlasticMaterial3D(
        yf="MohrCoulomb_YF",
        pf="MohrCoulomb_PF",
        el="LinearIsotropic3D_EL",
        iv="BackStress(NullHardeningTensorFunction):",
        internal_variables={"BackStress": (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)},
        model_parameters={"MC_c": 1014.0, "MC_phi": 45.95},
        integration_options={"integration_method": "Backward_Euler"},
    )
    assert isinstance(mat, ASDPlasticMaterial3D)
    # Bridge allocated a tag.
    tag = ops.tag_for(mat)
    assert tag == 1


def test_ndmaterial_namespace_internal_variables_scalar_normalizes() -> None:
    """Passing a scalar for an IV value normalizes to a 1-tuple."""
    fem = make_two_node_beam()
    ops = apeSees(fem, default_orientation=None)
    ops.model(ndm=2, ndf=2)
    mat = ops.nDMaterial.ASDPlasticMaterial3D(
        yf="X", pf="Y", el="Z", iv="W",
        internal_variables={"ScalarIV": 42.0},
    )
    iv_dict = dict(mat.internal_variables)
    assert iv_dict["ScalarIV"] == (42.0,)


def test_ndmaterial_namespace_mohr_coulomb_soil() -> None:
    fem = make_two_node_beam()
    ops = apeSees(fem, default_orientation=None)
    ops.model(ndm=2, ndf=2)
    mat = ops.nDMaterial.MohrCoulombSoil(
        c=1014.0, phi=45.95, psi=11.49,
        E=4080000.0, nu=0.18, rho=4.5,
    )
    assert isinstance(mat, ASDPlasticMaterial3D)
    assert ops.tag_for(mat) == 1


def test_ndmaterial_namespace_plane_strain() -> None:
    fem = make_two_node_beam()
    ops = apeSees(fem, default_orientation=None)
    ops.model(ndm=2, ndf=2)
    base = ops.nDMaterial.MohrCoulombSoil(
        c=100, phi=30, psi=0, E=1e6, nu=0.3,
    )
    wrapper = ops.nDMaterial.PlaneStrain(base=base)
    assert isinstance(wrapper, PlaneStrain)
    assert wrapper.base is base
    # Both registered, both get tags from the nDMaterial bucket.
    assert ops.tag_for(base) == 1
    assert ops.tag_for(wrapper) == 2
