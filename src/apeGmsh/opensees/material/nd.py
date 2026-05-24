"""
Typed primitives for OpenSees ``nDMaterial`` commands.

Phase 1B ships the priority-1 set: ``ElasticIsotropic``,
``J2Plasticity``, ``DruckerPrager``. The exotic soil and ASD damage
models (``PressureIndepMultiYield``, ``PM4Sand``, ``ASDConcrete3D``)
are deferred — their parameter sets are large, version-dependent,
and would benefit from an OpenSees expert sign-off before being
locked in.

Per P12, every user-facing parameter is a fully typed keyword on the
matching dataclass and on the namespace method. The OpenSees-vocabulary
varargs only appear inside ``_emit`` where the boundary is internal.

The Tcl signatures these classes emit:

* ``nDMaterial ElasticIsotropic tag E nu rho``
* ``nDMaterial J2Plasticity tag K G sig0 sigInf delta H eta``
* ``nDMaterial DruckerPrager tag K G sigmaY rho rhoBar Kinf Ko delta1 delta2 H theta``
"""
from __future__ import annotations

from dataclasses import dataclass

from .._internal.tag_resolution import resolve_tag
from .._internal.types import NDMaterial, Primitive
from ..emitter.base import Emitter


__all__ = [
    "ElasticIsotropic",
    "J2Plasticity",
    "DruckerPrager",
    "ASDPlasticMaterial3D",
    "MohrCoulombSoil",
    "PlaneStrain",
]


# ---------------------------------------------------------------------------
# ElasticIsotropic — 3-D / 2-D linear elastic continuum material
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class ElasticIsotropic(NDMaterial):
    """Linear-elastic isotropic continuum material.

    Tcl signature::

        nDMaterial ElasticIsotropic $tag $E $nu <$rho>

    Parameters
    ----------
    E
        Young's modulus. Must be strictly positive.
    nu
        Poisson's ratio. OpenSees enforces ``0 <= nu < 0.5``.
    rho
        Mass density. Defaults to ``0.0`` (statics). Must be ``>= 0``.
    """

    E: float
    nu: float
    rho: float = 0.0

    def __post_init__(self) -> None:
        if self.E <= 0:
            raise ValueError(
                f"ElasticIsotropic: E must be > 0, got {self.E!r}"
            )
        if not (0.0 <= self.nu < 0.5):
            raise ValueError(
                f"ElasticIsotropic: nu must be in [0, 0.5), got {self.nu!r}"
            )
        if self.rho < 0:
            raise ValueError(
                f"ElasticIsotropic: rho must be >= 0, got {self.rho!r}"
            )

    def _emit(self, emitter: Emitter, tag: int) -> None:
        emitter.nDMaterial("ElasticIsotropic", tag, self.E, self.nu, self.rho)

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# J2Plasticity — von Mises plasticity with isotropic + nonlinear hardening
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class J2Plasticity(NDMaterial):
    """von-Mises (J2) plasticity with combined nonlinear hardening.

    Tcl signature::

        nDMaterial J2Plasticity $tag $K $G $sig0 $sigInf $delta $H <$eta>

    Parameters
    ----------
    K
        Bulk modulus. Must be strictly positive.
    G
        Shear modulus. Must be strictly positive.
    sig0
        Initial yield stress (von-Mises radius at zero plastic strain).
        Must be strictly positive.
    sigInf
        Saturation yield stress (asymptote of the exponential hardening
        term). ``sigInf >= sig0`` for monotonic hardening.
    delta
        Exponential decay rate for the saturation term. Must be ``>= 0``.
    H
        Linear isotropic hardening modulus. Must be ``>= 0``.
    eta
        Viscoplastic regularization parameter. Defaults to ``0.0``
        (rate-independent). Must be ``>= 0``.
    """

    K: float
    G: float
    sig0: float
    sigInf: float
    delta: float
    H: float
    eta: float = 0.0

    def __post_init__(self) -> None:
        if self.K <= 0:
            raise ValueError(f"J2Plasticity: K must be > 0, got {self.K!r}")
        if self.G <= 0:
            raise ValueError(f"J2Plasticity: G must be > 0, got {self.G!r}")
        if self.sig0 <= 0:
            raise ValueError(
                f"J2Plasticity: sig0 must be > 0, got {self.sig0!r}"
            )
        if self.delta < 0:
            raise ValueError(
                f"J2Plasticity: delta must be >= 0, got {self.delta!r}"
            )
        if self.H < 0:
            raise ValueError(
                f"J2Plasticity: H must be >= 0, got {self.H!r}"
            )
        if self.eta < 0:
            raise ValueError(
                f"J2Plasticity: eta must be >= 0, got {self.eta!r}"
            )

    def _emit(self, emitter: Emitter, tag: int) -> None:
        emitter.nDMaterial(
            "J2Plasticity",
            tag,
            self.K,
            self.G,
            self.sig0,
            self.sigInf,
            self.delta,
            self.H,
            self.eta,
        )

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# DruckerPrager — pressure-dependent plasticity for soils / concrete
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class DruckerPrager(NDMaterial):
    """Drucker-Prager elasto-plastic continuum material.

    Tcl signature::

        nDMaterial DruckerPrager $tag $K $G $sigmaY \\
            $rho $rhoBar $Kinf $Ko $delta1 $delta2 $H $theta

    Parameters
    ----------
    K
        Bulk modulus. Must be strictly positive.
    G
        Shear modulus. Must be strictly positive.
    sigmaY
        Initial cohesive yield strength (von-Mises radius at zero
        plastic strain). Must be strictly positive.
    rho
        Drucker-Prager friction parameter (yield surface slope).
        Must be ``>= 0``.
    rhoBar
        Plastic-flow direction parameter (associated when
        ``rhoBar == rho``). Must be ``>= 0``.
    Kinf
        Saturation isotropic hardening parameter. Must be ``>= 0``.
    Ko
        Initial isotropic hardening parameter. Must be ``>= 0``.
    delta1
        Exponential rate for the saturation hardening term. Must be ``>= 0``.
    delta2
        Tension-cap exponential evolution parameter. Must be ``>= 0``.
    H
        Linear isotropic hardening modulus. Must be ``>= 0``.
    theta
        Mixed isotropic / kinematic hardening fraction
        (``0`` = purely kinematic, ``1`` = purely isotropic). OpenSees
        accepts ``0 <= theta <= 1``.
    """

    K: float
    G: float
    sigmaY: float
    rho: float
    rhoBar: float
    Kinf: float
    Ko: float
    delta1: float
    delta2: float
    H: float
    theta: float

    def __post_init__(self) -> None:
        if self.K <= 0:
            raise ValueError(f"DruckerPrager: K must be > 0, got {self.K!r}")
        if self.G <= 0:
            raise ValueError(f"DruckerPrager: G must be > 0, got {self.G!r}")
        if self.sigmaY <= 0:
            raise ValueError(
                f"DruckerPrager: sigmaY must be > 0, got {self.sigmaY!r}"
            )
        for name, value in (
            ("rho", self.rho),
            ("rhoBar", self.rhoBar),
            ("Kinf", self.Kinf),
            ("Ko", self.Ko),
            ("delta1", self.delta1),
            ("delta2", self.delta2),
            ("H", self.H),
        ):
            if value < 0:
                raise ValueError(
                    f"DruckerPrager: {name} must be >= 0, got {value!r}"
                )
        if not (0.0 <= self.theta <= 1.0):
            raise ValueError(
                f"DruckerPrager: theta must be in [0, 1], got {self.theta!r}"
            )

    def _emit(self, emitter: Emitter, tag: int) -> None:
        emitter.nDMaterial(
            "DruckerPrager",
            tag,
            self.K,
            self.G,
            self.sigmaY,
            self.rho,
            self.rhoBar,
            self.Kinf,
            self.Ko,
            self.delta1,
            self.delta2,
            self.H,
            self.theta,
        )

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# ASDPlasticMaterial3D — templated YF / PF / EL / IV plasticity (Abell + Petracca)
# ---------------------------------------------------------------------------
#
# The Tcl card is a 4-string-type header followed by three keyed
# blocks.  The parser
# (``SRC/material/nD/ASDPlasticMaterial3D/OPS_AllASDPlasticMaterial3Ds.cpp``)
# reads:
#
#     nDMaterial ASDPlasticMaterial3D $tag
#       $yf $pf $el $iv
#       Begin_Internal_Variables   <name> v1 [v2 v3 ...]   ... End_Internal_Variables
#       Begin_Model_Parameters     <name> value            ... End_Model_Parameters
#       Begin_Integration_Options  <name> value            ... End_Integration_Options
#
# Internal-variable values are per-name N-tuples (size determined by
# the IV type — BackStress is 6, scalar IVs are 1).  Model parameters
# are always scalar.  Integration options carry mixed value types
# (doubles, ints, string enums) keyed by ``param_name``.
#
# Phase SSI-1: the SSI MohrCoulomb soil case lives in :class:`MohrCoulombSoil`
# below.  This generic class is the escape hatch for other YF / PF / EL
# combinations and is also what :class:`MohrCoulombSoil` constructs
# internally.
#
# Valid combinations are produced by
# ``SRC/material/nD/ASDPlasticMaterial3D/gen_ASD_material_definitions_CPP.py``;
# unsupported triples cause an OpenSees runtime error (the factory
# returns ``nullptr``).  apeGmsh does not enforce client-side: any
# ``(yf, pf, el, iv)`` shape is accepted at registration time; the
# OpenSees binary is the source of truth on which combinations exist
# in this build.


@dataclass(frozen=True, kw_only=True, slots=True)
class ASDPlasticMaterial3D(NDMaterial):
    """Generic templated ASD plasticity material (Abell / Petracca / Camata).

    Tcl signature (verbatim — line breaks for readability only)::

        nDMaterial ASDPlasticMaterial3D $tag \\
            $yf $pf $el $iv \\
            Begin_Internal_Variables  ... End_Internal_Variables \\
            Begin_Model_Parameters    ... End_Model_Parameters   \\
            Begin_Integration_Options ... End_Integration_Options

    The four type strings select the templated implementation; the
    three dict blocks populate it.  ``commitStressIncrementXX/YY/ZZ
    /XY/YZ/XZ`` responses (used by :func:`apeSees.initial_stress`)
    are defined on every ASDPlasticMaterial3D instantiation —
    independent of the YF / PF / EL / IV chosen.

    Parameters
    ----------
    yf
        Yield-function type name, e.g. ``"MohrCoulomb_YF"`` /
        ``"DruckerPrager_YF"`` / ``"VonMises_YF"`` /
        ``"HoekBrown_YF"``.
    pf
        Plastic-flow direction type name (typically matches ``yf``
        for associated flow; e.g. ``"MohrCoulomb_PF"``).
    el
        Elasticity model type name, e.g.
        ``"LinearIsotropic3D_EL"``.
    iv
        Internal-variable composition string, e.g.
        ``"BackStress(NullHardeningTensorFunction):"`` (NOTE the
        trailing colon — required by the parser's name-match).
    internal_variables
        ``{name: scalar | tuple}`` — values keyed by internal-variable
        name.  Tuple length must match the IV's declared size
        (e.g. BackStress is 6-vector; scalar IVs accept a single
        value or a 1-tuple).
    model_parameters
        ``{name: scalar}`` — model-parameter dictionary.  All values
        are stored as floats.  Unknown keys are silently consumed by
        the OpenSees parser (it forwards via ``setParameterByName``);
        prefer the typed :class:`MohrCoulombSoil` helper for the SSI
        case.
    integration_options
        ``{name: scalar | str}`` — keyed by parser option name.
        Mixed types: ``f_absolute_tol`` / ``stress_absolute_tol`` /
        ``rk45_dT_min`` are floats; ``n_max_iterations`` /
        ``rk45_niter_max`` are ints; ``integration_method`` /
        ``tangent_type`` / ``return_to_yield_surface`` are string
        enums (see the OpenSees source for valid tokens).  Empty
        dict = all defaults (Backward_Euler / Secant / 1e-6 /
        100 / Disabled / 0.01 / 110).
    """

    yf: str
    pf: str
    el: str
    iv: str
    internal_variables: tuple[tuple[str, tuple[float, ...]], ...] = ()
    model_parameters: tuple[tuple[str, float], ...] = ()
    integration_options: tuple[tuple[str, float | int | str], ...] = ()

    def __post_init__(self) -> None:
        for label, value in (
            ("yf", self.yf), ("pf", self.pf),
            ("el", self.el), ("iv", self.iv),
        ):
            if not value:
                raise ValueError(
                    f"ASDPlasticMaterial3D: {label}= must be non-empty"
                )
        # Internal-variable values must be per-tuple of floats.
        for name, values in self.internal_variables:
            if not name:
                raise ValueError(
                    "ASDPlasticMaterial3D: internal_variables key "
                    "must be non-empty"
                )
            if not values:
                raise ValueError(
                    "ASDPlasticMaterial3D: internal_variables "
                    f"{name!r} must have at least one value"
                )

    def _emit(self, emitter: "Emitter", tag: int) -> None:
        args: list[float | int | str] = [self.yf, self.pf, self.el, self.iv]
        args.append("Begin_Internal_Variables")
        for name, values in self.internal_variables:
            args.append(name)
            args.extend(float(v) for v in values)
        args.append("End_Internal_Variables")
        args.append("Begin_Model_Parameters")
        for name, value in self.model_parameters:
            args.append(name)
            args.append(float(value))
        args.append("End_Model_Parameters")
        args.append("Begin_Integration_Options")
        for name, value in self.integration_options:
            args.append(name)
            # Preserve int / float / str distinction so the Tcl emit
            # renders enums (e.g. ``Backward_Euler``) as tokens, not
            # as the float ``Backward_Euler`` would coerce to NaN.
            if isinstance(value, str):
                args.append(value)
            elif isinstance(value, bool):
                # bool BEFORE int — Python's bool isinstance(int) is True.
                args.append(1 if value else 0)
            elif isinstance(value, int):
                args.append(int(value))
            else:
                args.append(float(value))
        args.append("End_Integration_Options")
        emitter.nDMaterial("ASDPlasticMaterial3D", tag, *args)

    def dependencies(self) -> tuple[Primitive, ...]:
        return ()


# ---------------------------------------------------------------------------
# MohrCoulombSoil — typed convenience helper for the SSI rock / soil case
# ---------------------------------------------------------------------------
#
# Constructs an ASDPlasticMaterial3D with the standard
# MohrCoulomb_YF + MohrCoulomb_PF + LinearIsotropic3D_EL
# + BackStress(NullHardeningTensorFunction): composition.  Zero-fills
# the non-MohrCoulomb model parameters (AF_*, DP_*, DuncanChang_*,
# etc.) defensively — STKO's emit does the same; the OpenSees parser
# accepts unknown names without erroring (forwarded via
# ``setParameterByName``).


def MohrCoulombSoil(
    *,
    c: float,
    phi: float,
    psi: float,
    E: float,
    nu: float,
    rho: float = 0.0,
    ds: float = 1e-5,
    yield_stress: float = 1e10,
    initial_p0: float = 0.0,
    integration_method: str = "Backward_Euler",
    tangent_type: str = "Secant",
    f_absolute_tol: float = 1e-6,
    stress_absolute_tol: float = 1e-6,
    n_max_iterations: int = 100,
    return_to_yield_surface: str = "Disabled",
    rk45_dT_min: float = 0.01,
    rk45_niter_max: int = 100,
) -> ASDPlasticMaterial3D:
    """Build an ASDPlasticMaterial3D wired for Mohr-Coulomb soil / rock.

    Replaces the ~30-line dict-of-parameters call to the generic
    :class:`ASDPlasticMaterial3D` for the SSI Cerro Lindo / rock-mass
    case.

    Parameters
    ----------
    c, phi, psi
        Mohr-Coulomb cohesion (stress units), friction angle (degrees),
        dilation angle (degrees).
    E, nu, rho
        Linear-elastic Young's modulus, Poisson's ratio, mass density.
        ``rho`` defaults to ``0.0`` (static analysis).
    ds
        Mohr-Coulomb rounding parameter (small number; default ``1e-5``
        matches STKO).
    yield_stress
        Initial scalar yield stress for the ``YieldStress`` internal
        variable.  Default ``1e10`` (effectively unbounded — pure
        Mohr-Coulomb with no scalar hardening cap).
    initial_p0
        Initial confining pressure offset.  Defaults to ``0.0``.
    integration_method
        One of ``"Forward_Euler"``, ``"Forward_Euler_Subincrement"``,
        ``"Modified_Euler_Error_Control"``,
        ``"Runge_Kutta_45_Error_Control"``, ``"Backward_Euler"``
        (default), ``"Backward_Euler_LineSearch"``.
    tangent_type
        One of ``"Elastic"``, ``"Continuum"``, ``"Secant"`` (default),
        ``"Numerical_Algorithmic_FirstOrder"``,
        ``"Numerical_Algorithmic_SecondOrder"``.
    f_absolute_tol, stress_absolute_tol, n_max_iterations
        Integration solver tolerances + iteration cap.
    return_to_yield_surface
        ``"Disabled"`` (default — STKO behavior), ``"One_Step_Return"``,
        or ``"Iterative_Return"``.
    rk45_dT_min, rk45_niter_max
        RK45 sub-step controls (only used when ``integration_method``
        is an RK45 variant).

    Returns
    -------
    ASDPlasticMaterial3D
        Frozen generic-class instance ready to register via
        ``ops.nDMaterial.ASDPlasticMaterial3D(...)`` or to pass
        directly to ``ops.register(...)``.
    """
    if c < 0:
        raise ValueError(f"MohrCoulombSoil: c must be >= 0, got {c!r}")
    if not (0.0 <= phi < 90.0):
        raise ValueError(
            f"MohrCoulombSoil: phi must be in [0, 90) degrees, got {phi!r}"
        )
    if not (0.0 <= psi <= phi):
        raise ValueError(
            "MohrCoulombSoil: psi must be in [0, phi] (associated flow "
            f"is psi=phi; non-associated requires psi<phi). Got "
            f"psi={psi!r}, phi={phi!r}."
        )
    if E <= 0:
        raise ValueError(f"MohrCoulombSoil: E must be > 0, got {E!r}")
    if not (0.0 <= nu < 0.5):
        raise ValueError(
            f"MohrCoulombSoil: nu must be in [0, 0.5), got {nu!r}"
        )
    if rho < 0:
        raise ValueError(f"MohrCoulombSoil: rho must be >= 0, got {rho!r}")

    return ASDPlasticMaterial3D(
        yf="MohrCoulomb_YF",
        pf="MohrCoulomb_PF",
        el="LinearIsotropic3D_EL",
        iv="BackStress(NullHardeningTensorFunction):",
        # Only ``BackStress`` is a valid IV for this YF/PF/IV combination
        # — the MohrCoulomb_YF declares one internal variable
        # (BackStress, size 6).  DP_cohesion / YieldStress are accepted
        # by the parser but silently dropped because
        # ``getInternalVariableSizeByName(name)`` returns 0 for unknown
        # names.  Emit only the recognized IV to keep the deck minimal.
        internal_variables=(
            ("BackStress", (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
        ),
        model_parameters=(
            # Required MohrCoulomb + elastic + density.
            ("AF_cr", 0.0),
            ("AF_ha", 0.0),
            ("DP_eta", 0.0),
            ("DP_etabar", 0.0),
            ("DP_xi_c", 0.0),
            ("Dilatancy", 0.0),
            ("DuncanChang_MaxSigma3", 0.0),
            ("DuncanChang_n", 0.0),
            ("InitialP0", initial_p0),
            ("MC_c", c),
            ("MC_ds", ds),
            ("MC_phi", phi),
            ("MC_psi", psi),
            ("MassDensity", rho),
            ("PoissonsRatio", nu),
            ("ReferencePressure", 0.0),
            ("ReferenceYoungsModulus", 0.0),
            ("ScalarLinearHardeningParameter", 0.0),
            ("TC_min_stress", 0.0),
            ("TensorLinearHardeningParameter", 0.0),
            ("YoungsModulus", E),
        ),
        integration_options=(
            ("f_absolute_tol", f_absolute_tol),
            ("stress_absolute_tol", stress_absolute_tol),
            ("n_max_iterations", n_max_iterations),
            ("rk45_dT_min", rk45_dT_min),
            ("rk45_niter_max", rk45_niter_max),
            ("return_to_yield_surface", return_to_yield_surface),
            ("integration_method", integration_method),
            ("tangent_type", tangent_type),
        ),
    )


# ---------------------------------------------------------------------------
# PlaneStrain — wraps a 3-D nDMaterial as a 2-D plane-strain material
# ---------------------------------------------------------------------------
#
# OpenSees command::
#
#     nDMaterial PlaneStrain $tag $base3d_tag
#
# Required wrapping for the SSI rock case: ASDPlasticMaterial3D is
# strictly 3D — passing its tag directly to ``element quad ... PlaneStrain
# $matTag`` triggers ``ASDPlasticMaterial3D::getCopy("PlaneStrain") --
# Only 3D is currently supported.``  The PlaneStrain wrapper bridges
# the 2D constitutive interface the quad element expects.


@dataclass(frozen=True, kw_only=True, slots=True)
class PlaneStrain(NDMaterial):
    """``nDMaterial PlaneStrain`` — 2-D plane-strain wrapper around a 3-D material.

    Tcl signature::

        nDMaterial PlaneStrain $tag $base3d_tag

    Parameters
    ----------
    base
        The 3-D :class:`NDMaterial` (e.g. :class:`ASDPlasticMaterial3D`)
        that supplies the 3-D constitutive law.  The wrapper exposes
        a 2-D plane-strain view by constraining ε_zz = 0 and projecting
        the stress to the in-plane components.

    Notes
    -----
    Use this whenever an apeGmsh 2-D element (``FourNodeQuad``,
    ``Tri31``) needs to consume a strictly-3-D material.  For natively
    2-D materials (``ElasticIsotropic``), the quad's ``plane_type=``
    argument selects the 2-D view directly and no wrapping is needed.
    """

    base: NDMaterial

    def _emit(self, emitter: Emitter, tag: int) -> None:
        base_tag = resolve_tag(emitter, self.base)
        emitter.nDMaterial("PlaneStrain", tag, base_tag)

    def dependencies(self) -> tuple[Primitive, ...]:
        return (self.base,)
