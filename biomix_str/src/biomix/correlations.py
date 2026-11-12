"""Core Bioprocess Engineering (BPE) Hydrodynamic & Mass Transfer Correlations.

Provides physics-based analytical and empirical correlations for:
- Impeller Reynolds number and flow regime classification
- Empirical Power Number (N_p) curves with log-log PCHIP interpolation
- Ungassed and gassed power draw (Michel and Bakker correlations)
- Aeration number, Froude number, and impeller flooding criteria (Nienow)
- Hydrodynamic shear, impeller tip speed, and Kolmogorov microscale eddy sizes
- Impeller pumping rates, circulation time, and 95% blend mixing time
- Volumetric oxygen mass transfer coefficient (k_L a, Van 't Riet correlations)
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Dict, Optional, Tuple

import numpy as np
from scipy.interpolate import PchipInterpolator

from biomix.models import ImpellerType

# ---------------------------------------------------------------------------
# Flow Regime & Reynolds Number
# ---------------------------------------------------------------------------


class FlowRegime(str, Enum):
    """Agitation flow regime based on Impeller Reynolds Number (Re_i)."""
    LAMINAR = "laminar"  # Re_i < 10.0
    TRANSITIONAL = "transitional"  # 10.0 <= Re_i < 10000.0
    TURBULENT = "turbulent"  # Re_i >= 10000.0


def calc_reynolds_number(
    density_kg_m3: float,
    rps: float,
    diameter_m: float,
    viscosity_pa_s: float,
) -> float:
    """Calculate the Impeller Reynolds Number: Re_i = (rho * N * D_i^2) / mu.

    Parameters
    ----------
    density_kg_m3 : float
        Liquid/broth density rho (kg/m^3).
    rps : float
        Agitation speed N (rev/s).
    diameter_m : float
        Impeller diameter D_i (m).
    viscosity_pa_s : float
        Dynamic viscosity mu (Pa.s).

    Returns
    -------
    float
        Dimensionless Impeller Reynolds Number Re_i.
    """
    if viscosity_pa_s <= 0.0:
        raise ValueError("viscosity_pa_s must be strictly positive")
    return (density_kg_m3 * rps * (diameter_m ** 2)) / viscosity_pa_s


def classify_flow_regime(re_i: float) -> FlowRegime:
    """Classify the agitation flow regime into LAMINAR, TRANSITIONAL, or TURBULENT."""
    if re_i < 10.0:
        return FlowRegime.LAMINAR
    elif re_i < 10000.0:
        return FlowRegime.TRANSITIONAL
    else:
        return FlowRegime.TURBULENT


# ---------------------------------------------------------------------------
# Empirical Power Number (N_p) Curve Interpolators
# ---------------------------------------------------------------------------

# Standard empirical (Re_i, N_p) curves (Rushton et al., Bates et al., Doran Fig. 8.11)
_NP_ANCHORS: Dict[ImpellerType, list[tuple[float, float]]] = {
    # A1. Open Radial-Flow Impellers
    ImpellerType.RUSHTON_6_BLADE: [
        (1.0, 70.0), (10.0, 7.2), (20.0, 4.8), (50.0, 3.7), (100.0, 3.6),
        (300.0, 4.0), (1000.0, 4.6), (10000.0, 5.0), (100000.0, 5.0),
    ],
    ImpellerType.SMITH_CD6: [
        (1.0, 60.0), (10.0, 6.2), (50.0, 3.0), (200.0, 2.8),
        (1000.0, 3.0), (10000.0, 3.2), (100000.0, 3.2),
    ],
    ImpellerType.FLAT_BLADE_FBT: [
        (1.0, 65.0), (10.0, 6.5), (50.0, 3.6), (200.0, 3.5),
        (1000.0, 3.8), (10000.0, 4.0), (100000.0, 4.0),
    ],
    ImpellerType.PADDLE_R200: [
        (1.0, 50.0), (10.0, 5.0), (50.0, 2.1), (200.0, 1.9),
        (1000.0, 2.0), (10000.0, 2.0), (100000.0, 2.0),
    ],
    ImpellerType.CURVED_BACKSWEPT: [
        (1.0, 55.0), (10.0, 5.8), (50.0, 3.4), (200.0, 3.5),
        (1000.0, 3.8), (10000.0, 4.0), (100000.0, 4.0),
    ],
    ImpellerType.RETREAT_BLADE: [
        (1.0, 48.0), (10.0, 5.2), (50.0, 2.9), (200.0, 2.8),
        (1000.0, 3.0), (10000.0, 3.1), (100000.0, 3.1),
    ],

    # A2. Open Axial & Mixed-Flow Impellers
    ImpellerType.MARINE_PROPELLER: [
        (1.0, 40.0), (10.0, 4.2), (50.0, 1.3), (200.0, 0.7),
        (1000.0, 0.45), (10000.0, 0.35), (100000.0, 0.35),
    ],
    ImpellerType.PITCHED_BLADE_45: [
        (1.0, 44.0), (10.0, 4.6), (50.0, 2.0), (200.0, 1.5),
        (1000.0, 1.35), (10000.0, 1.5), (100000.0, 1.5),
    ],
    ImpellerType.HYDROFOIL_HE3: [
        (1.0, 36.0), (10.0, 3.8), (50.0, 1.2), (200.0, 0.60),
        (1000.0, 0.38), (10000.0, 0.29), (100000.0, 0.29),
    ],
    ImpellerType.MAXFLO_HIGH_SOLIDITY: [
        (1.0, 52.0), (10.0, 5.5), (50.0, 3.2), (200.0, 2.8),
        (1000.0, 3.1), (10000.0, 3.3), (100000.0, 3.3),
    ],
    ImpellerType.INTERMIG_EKATO: [
        (1.0, 35.0), (10.0, 3.6), (50.0, 1.5), (200.0, 0.90),
        (1000.0, 0.70), (10000.0, 0.65), (100000.0, 0.65),
    ],

    # B. Close-Clearance Impellers
    ImpellerType.ANCHOR: [
        (1.0, 150.0), (10.0, 16.0), (50.0, 4.0), (200.0, 1.8),
        (1000.0, 0.80), (10000.0, 0.45), (100000.0, 0.45),
    ],
    ImpellerType.HELICAL_RIBBON: [
        (1.0, 300.0), (10.0, 32.0), (50.0, 7.5), (200.0, 2.5),
        (1000.0, 1.0), (10000.0, 0.40), (100000.0, 0.40),
    ],
    ImpellerType.AUGER_SCREW: [
        (1.0, 200.0), (10.0, 22.0), (50.0, 5.5), (200.0, 2.2),
        (1000.0, 1.2), (10000.0, 0.80), (100000.0, 0.80),
    ],
    ImpellerType.GATE_IMPELLER: [
        (1.0, 180.0), (10.0, 20.0), (50.0, 6.0), (200.0, 3.0),
        (1000.0, 2.2), (10000.0, 1.8), (100000.0, 1.8),
    ],
    ImpellerType.SIGMA_Z_KNEADER: [
        (1.0, 400.0), (10.0, 45.0), (50.0, 15.0), (200.0, 7.0),
        (1000.0, 4.5), (10000.0, 3.5), (100000.0, 3.5),
    ],
}

_LAMINAR_KL: Dict[ImpellerType, float] = {
    ImpellerType.RUSHTON_6_BLADE: 70.0,
    ImpellerType.SMITH_CD6: 60.0,
    ImpellerType.FLAT_BLADE_FBT: 65.0,
    ImpellerType.PADDLE_R200: 50.0,
    ImpellerType.CURVED_BACKSWEPT: 55.0,
    ImpellerType.RETREAT_BLADE: 48.0,
    ImpellerType.MARINE_PROPELLER: 40.0,
    ImpellerType.PITCHED_BLADE_45: 44.0,
    ImpellerType.HYDROFOIL_HE3: 36.0,
    ImpellerType.MAXFLO_HIGH_SOLIDITY: 52.0,
    ImpellerType.INTERMIG_EKATO: 35.0,
    ImpellerType.ANCHOR: 150.0,
    ImpellerType.HELICAL_RIBBON: 300.0,
    ImpellerType.AUGER_SCREW: 200.0,
    ImpellerType.GATE_IMPELLER: 180.0,
    ImpellerType.SIGMA_Z_KNEADER: 400.0,
}

_TURBULENT_NP: Dict[ImpellerType, float] = {
    ImpellerType.RUSHTON_6_BLADE: 5.0,
    ImpellerType.SMITH_CD6: 3.2,
    ImpellerType.FLAT_BLADE_FBT: 4.0,
    ImpellerType.PADDLE_R200: 2.0,
    ImpellerType.CURVED_BACKSWEPT: 4.0,
    ImpellerType.RETREAT_BLADE: 3.1,
    ImpellerType.MARINE_PROPELLER: 0.35,
    ImpellerType.PITCHED_BLADE_45: 1.5,
    ImpellerType.HYDROFOIL_HE3: 0.29,
    ImpellerType.MAXFLO_HIGH_SOLIDITY: 3.3,
    ImpellerType.INTERMIG_EKATO: 0.65,
    ImpellerType.ANCHOR: 0.45,
    ImpellerType.HELICAL_RIBBON: 0.40,
    ImpellerType.AUGER_SCREW: 0.80,
    ImpellerType.GATE_IMPELLER: 1.8,
    ImpellerType.SIGMA_Z_KNEADER: 3.5,
}

# Pre-construct log10-log10 Pchip interpolators for each impeller type
_NP_INTERPOLATORS: Dict[ImpellerType, PchipInterpolator] = {}
for _imp_type, _pts in _NP_ANCHORS.items():
    _re_arr = np.array([pt[0] for pt in _pts], dtype=float)
    _np_arr = np.array([pt[1] for pt in _pts], dtype=float)
    _NP_INTERPOLATORS[_imp_type] = PchipInterpolator(np.log10(_re_arr), np.log10(_np_arr))


def calc_power_number(
    re_i: float,
    impeller_type: ImpellerType,
    is_baffled: bool = True,
) -> float:
    """Calculate the Impeller Power Number (N_p) across all flow regimes.

    - Laminar (Re_i <= 1.0): N_p = K_L / Re_i
    - Transitional (1.0 < Re_i < 10000.0): log10-log10 PchipInterpolator
    - Fully Turbulent (Re_i >= 10000.0): constant plateau N_{p,turb}
    - Unbaffled correction: for unbaffled vessels and Re_i > 300.0,
      multiplies N_p by (300.0 / Re_i)^0.18 to model vortex power reduction.

    Parameters
    ----------
    re_i : float
        Impeller Reynolds Number.
    impeller_type : ImpellerType
        Design geometry of the impeller.
    is_baffled : bool, optional
        Whether the vessel contains wall baffles, by default True.

    Returns
    -------
    float
        Dimensionless Power Number N_p.
    """
    if re_i < 0.0:
        raise ValueError("re_i must be non-negative")
    if re_i == 0.0:
        return 0.0

    k_l = _LAMINAR_KL[impeller_type]
    np_turb = _TURBULENT_NP[impeller_type]

    if re_i <= 1.0:
        np_val = k_l / re_i
    elif re_i >= 10000.0:
        np_val = np_turb
    else:
        interpolator = _NP_INTERPOLATORS[impeller_type]
        log_re = math.log10(re_i)
        log_np = float(interpolator(log_re))
        np_val = 10.0 ** log_np

    # Unbaffled central vortex correction above Re = 300 (only open turbines, not close-clearance)
    if not is_baffled and not impeller_type.is_close_clearance and re_i > 300.0:
        np_val *= (300.0 / re_i) ** 0.18

    return float(np_val)


# ---------------------------------------------------------------------------
# Ungassed Power (P_0)
# ---------------------------------------------------------------------------


def calc_ungassed_power(
    np_val: float,
    density_kg_m3: float,
    rps: float,
    diameter_m: float,
) -> float:
    """Calculate the ungassed power draw: P_0 = N_p * rho * N^3 * D_i^5 (Watts)."""
    return np_val * density_kg_m3 * (rps ** 3) * (diameter_m ** 5)


# ---------------------------------------------------------------------------
# Aeration, Froude, Flooding, and Gassed Power (P_g)
# ---------------------------------------------------------------------------


def calc_gas_flow_rate_m3_s(aeration_vvm: float, working_volume_m3: float) -> float:
    """Convert aeration rate in vvm (vol gas / vol liquid / min) to m^3/s:

    Q_g = (vvm * V_L) / 60.0
    """
    return (aeration_vvm * working_volume_m3) / 60.0


def calc_aeration_number(q_g_m3_s: float, rps: float, diameter_m: float) -> float:
    """Calculate the Aeration / Gas Flow Number: Fl_g = Q_g / (N * D_i^3)."""
    if rps <= 0.0 or diameter_m <= 0.0:
        raise ValueError("rps and diameter_m must be strictly positive")
    return q_g_m3_s / (rps * (diameter_m ** 3))


def calc_froude_number(rps: float, diameter_m: float, g: float = 9.80665) -> float:
    """Calculate the Froude Number: Fr = (N^2 * D_i) / g."""
    return ((rps ** 2) * diameter_m) / g


def calc_flooding_aeration_number(
    impeller_type: ImpellerType,
    diameter_m: float,
    tank_diameter_m: float,
    froude_number: float,
) -> float:
    """Calculate the critical flooding aeration number Fl_{g,flood} (Nienow correlation).

    When Fl_g > Fl_{g,flood}, the impeller is flooded by gas and loses circulation capability.
    """
    diameter_ratio = diameter_m / tank_diameter_m
    if impeller_type == ImpellerType.SMITH_CD6:
        factor = 75.0  # 2.5x higher than Rushton 30.0
    elif impeller_type == ImpellerType.MAXFLO_HIGH_SOLIDITY:
        factor = 27.0  # 1.8x higher than standard axial 15.0
    elif impeller_type in (
        ImpellerType.RUSHTON_6_BLADE,
        ImpellerType.FLAT_BLADE_FBT,
        ImpellerType.CURVED_BACKSWEPT,
    ):
        factor = 30.0
    elif impeller_type in (ImpellerType.RETREAT_BLADE, ImpellerType.PADDLE_R200):
        factor = 22.0
    elif impeller_type in (
        ImpellerType.MARINE_PROPELLER,
        ImpellerType.PITCHED_BLADE_45,
        ImpellerType.HYDROFOIL_HE3,
        ImpellerType.INTERMIG_EKATO,
    ):
        factor = 15.0
    else:  # Close-clearance impellers (Anchor, Helical Ribbon, etc.)
        factor = 10.0

    return factor * (diameter_ratio ** 3.5) * froude_number


def calc_gassed_power(
    p0_w: float,
    rps: float,
    diameter_m: float,
    q_g_m3_s: float,
    method: str = "michel",
    working_volume_m3: Optional[float] = None,
    blade_width_m: Optional[float] = None,
) -> float:
    """Calculate the gassed power draw P_g (Watts) using Michel, Bakker, or Hughmark correlation.

    Parameters
    ----------
    p0_w : float
        Ungassed power draw P_0 (W).
    rps : float
        Agitation speed N (rev/s).
    diameter_m : float
        Impeller diameter D_i (m).
    q_g_m3_s : float
        Gas sparging volumetric flow rate Q_g (m^3/s).
    method : str, optional
        Correlation to apply: 'michel', 'bakker', or 'hughmark', by default 'michel'.
    working_volume_m3 : float, optional
        Liquid working volume V_L (m^3), required for Hughmark.
    blade_width_m : float, optional
        Impeller blade width W_i (m), defaults to 0.20 * D_i if omitted.

    Returns
    -------
    float
        Gassed power draw P_g (W).
    """
    if q_g_m3_s <= 1e-9 or p0_w <= 0.0 or rps <= 0.0:
        return p0_w

    method_lower = method.lower()
    if method_lower == "michel":
        # Michel's correlation: P_g = 0.706 * [ (P_0^2 * N * D_i^3) / Q_g^0.56 ]^0.45
        numerator = (p0_w ** 2) * rps * (diameter_m ** 3)
        denominator = q_g_m3_s ** 0.56
        pg = 0.706 * ((numerator / denominator) ** 0.45)
        # Clamped to [0.30 * P_0, P_0]
        return float(min(p0_w, max(0.30 * p0_w, pg)))

    elif method_lower == "bakker":
        # Bakker's correlation: P_g = P_0 * [ 1.0 - 6.3 * Fl_g * Fr^0.18 ]
        fl_g = calc_aeration_number(q_g_m3_s, rps, diameter_m)
        fr = calc_froude_number(rps, diameter_m)
        factor = 1.0 - 6.3 * fl_g * (fr ** 0.18)
        pg = p0_w * factor
        # Clamped to [0.35 * P_0, P_0]
        return float(min(p0_w, max(0.35 * p0_w, pg)))

    elif method_lower == "hughmark":
        # Hughmark (1980) correlation for gassed stirred tanks:
        # P_g / P_0 = 0.10 * [ F_g / (N * V_L) ]^(-0.25) * [ (N^2 * D_i^4) / (g * W_i * V_L^(2/3)) ]^(-0.20)
        v_l = working_volume_m3 if (working_volume_m3 is not None and working_volume_m3 > 0.0) else (math.pi / 4.0 * (3.0 * diameter_m) ** 3)
        w_i = blade_width_m if (blade_width_m is not None and blade_width_m > 0.0) else (0.20 * diameter_m)
        g_acc = 9.80665

        term1 = (q_g_m3_s / max(1e-9, rps * v_l)) ** (-0.25)
        term2 = ((rps ** 2 * (diameter_m ** 4)) / max(1e-9, g_acc * w_i * (v_l ** (2.0 / 3.0)))) ** (-0.20)
        pg_ratio = 0.10 * term1 * term2
        pg = p0_w * min(1.0, max(0.30, pg_ratio))
        return float(pg)

    else:
        raise ValueError(
            f"Unknown gassed power correlation method: '{method}'. Expected 'michel', 'bakker', or 'hughmark'."
        )


# ---------------------------------------------------------------------------
# Hydrodynamic Shear, Tip Speed, and Kolmogorov Microscale
# ---------------------------------------------------------------------------

# Metzner-Otto shear constant k_s for different impeller topologies
METZNER_OTTO_KS: Dict[ImpellerType, float] = {
    ImpellerType.RUSHTON_6_BLADE: 11.5,
    ImpellerType.SMITH_CD6: 11.0,
    ImpellerType.FLAT_BLADE_FBT: 11.5,
    ImpellerType.PADDLE_R200: 10.0,
    ImpellerType.CURVED_BACKSWEPT: 11.0,
    ImpellerType.RETREAT_BLADE: 10.5,
    ImpellerType.MARINE_PROPELLER: 8.5,
    ImpellerType.PITCHED_BLADE_45: 10.5,
    ImpellerType.HYDROFOIL_HE3: 7.5,
    ImpellerType.MAXFLO_HIGH_SOLIDITY: 10.0,
    ImpellerType.INTERMIG_EKATO: 8.0,
    ImpellerType.ANCHOR: 25.0,
    ImpellerType.HELICAL_RIBBON: 30.0,
    ImpellerType.AUGER_SCREW: 22.0,
    ImpellerType.GATE_IMPELLER: 26.0,
    ImpellerType.SIGMA_Z_KNEADER: 35.0,
}


def calc_tip_speed(rps: float, diameter_m: float) -> float:
    """Calculate impeller peripheral tip speed: v_tip = pi * N * D_i (m/s)."""
    return math.pi * rps * diameter_m


def calc_average_shear(
    rps: float,
    viscosity_pa_s: float,
    impeller_type: ImpellerType,
) -> Tuple[float, float]:
    """Calculate the average impeller shear rate and shear stress using Metzner-Otto concept.

    gamma_dot_avg = k_s * N (s^-1)
    tau_avg = mu * gamma_dot_avg (Pa)

    Returns
    -------
    tuple[float, float]
        (shear_rate_s_inv, shear_stress_pa)
    """
    ks = METZNER_OTTO_KS[impeller_type]
    gamma_dot = ks * rps
    tau = viscosity_pa_s * gamma_dot
    return gamma_dot, tau


def calc_kolmogorov_scales(
    power_w: float,
    density_kg_m3: float,
    working_volume_m3: float,
    kinematic_viscosity_m2_s: float,
) -> Dict[str, float]:
    """Calculate turbulent energy dissipation rates and Kolmogorov microscale eddy sizes.

    - Average energy dissipation: epsilon_avg = P / (rho * V_L) (W/kg)
    - Peak energy dissipation in impeller swept vortex: epsilon_max = 10.0 * epsilon_avg (W/kg)
    - Average Kolmogorov microscale: lambda_K,avg = (nu^3 / epsilon_avg)^0.25 (m)
    - Minimum Kolmogorov microscale: lambda_K,min = (nu^3 / epsilon_max)^0.25 (m)

    Returns
    -------
    dict[str, float]
        Dictionary with keys 'epsilon_avg_w_kg', 'epsilon_max_w_kg', 'lambda_k_avg_m', 'lambda_k_min_m'.
    """
    mass_kg = density_kg_m3 * working_volume_m3
    eps_avg = max(0.0, power_w) / max(1e-9, mass_kg)
    eps_max = 10.0 * eps_avg

    if eps_avg <= 1e-12:
        return {
            "epsilon_avg_w_kg": 0.0,
            "epsilon_max_w_kg": 0.0,
            "lambda_k_avg_m": float("inf"),
            "lambda_k_min_m": float("inf"),
        }

    nu3 = kinematic_viscosity_m2_s ** 3
    lambda_avg = (nu3 / eps_avg) ** 0.25
    lambda_min = (nu3 / eps_max) ** 0.25

    return {
        "epsilon_avg_w_kg": eps_avg,
        "epsilon_max_w_kg": eps_max,
        "lambda_k_avg_m": lambda_avg,
        "lambda_k_min_m": lambda_min,
    }


# ---------------------------------------------------------------------------
# Pumping, Circulation Time, and Mixing Time
# ---------------------------------------------------------------------------

# Pumping number N_Q for standard impellers (Doran Table 8.3)
PUMPING_NUMBER_NQ: Dict[ImpellerType, float] = {
    ImpellerType.RUSHTON_6_BLADE: 0.72,
    ImpellerType.SMITH_CD6: 0.76,
    ImpellerType.FLAT_BLADE_FBT: 0.70,
    ImpellerType.PADDLE_R200: 0.65,
    ImpellerType.CURVED_BACKSWEPT: 0.74,
    ImpellerType.RETREAT_BLADE: 0.68,
    ImpellerType.MARINE_PROPELLER: 0.55,
    ImpellerType.PITCHED_BLADE_45: 0.79,
    ImpellerType.HYDROFOIL_HE3: 0.52,
    ImpellerType.MAXFLO_HIGH_SOLIDITY: 0.85,
    ImpellerType.INTERMIG_EKATO: 0.75,
    ImpellerType.ANCHOR: 0.35,
    ImpellerType.HELICAL_RIBBON: 0.45,
    ImpellerType.AUGER_SCREW: 0.50,
    ImpellerType.GATE_IMPELLER: 0.40,
    ImpellerType.SIGMA_Z_KNEADER: 0.30,
}


def calc_pumping_and_circulation(
    rps: float,
    diameter_m: float,
    working_volume_m3: float,
    impeller_type: ImpellerType,
) -> Tuple[float, float]:
    """Calculate impeller pumping rate and bulk liquid circulation turnover time.

    Q_p = N_Q * N * D_i^3 (m^3/s)
    t_c = V_L / Q_p (s)

    Returns
    -------
    tuple[float, float]
        (pumping_rate_m3_s, circulation_time_s)
    """
    nq = PUMPING_NUMBER_NQ[impeller_type]
    qp = nq * rps * (diameter_m ** 3)
    tc = working_volume_m3 / qp if qp > 0.0 else float("inf")
    return qp, tc


def calc_mixing_time_95(
    tank_diameter_m: float,
    liquid_height_m: float,
    impeller_diameter_m: float,
    power_w: float,
    density_kg_m3: float,
    working_volume_m3: float,
    re_i: float,
) -> float:
    """Calculate 95% blend mixing time theta_m (seconds) using Ruszkowski/Doran correlation:

    theta_m = 5.9 * T^(2/3) * ( (rho * V_L) / P )^(1/3) * (T / D_i)^(1/3) * (H / T)^2.43 * (1.0 + 200.0 / (Re_i + 50.0))
    """
    if power_w <= 0.0:
        return float("inf")

    T = tank_diameter_m
    H = liquid_height_m
    D = impeller_diameter_m
    mass_kg = density_kg_m3 * working_volume_m3

    term1 = 5.9 * (T ** (2.0 / 3.0))
    term2 = (mass_kg / power_w) ** (1.0 / 3.0)
    term3 = (T / D) ** (1.0 / 3.0)
    term4 = (H / T) ** 2.43
    viscous_penalty = 1.0 + (200.0 / (re_i + 50.0))

    return float(term1 * term2 * term3 * term4 * viscous_penalty)


def calc_mixing_time_reference(
    rps: float,
    diameter_m: float,
    working_volume_m3: float,
) -> float:
    """Calculate blend mixing time t_m (seconds) using standard turbulent correlation:

    N * t_m = 1.54 * (V_L / D_i^3)  ==>  t_m = 1.54 * V_L / (N * D_i^3)

    Valid for standard Rushton turbine baffled systems at high Reynolds numbers (Re_i > 5000).
    """
    if rps <= 0.0 or diameter_m <= 0.0:
        return float("inf")
    return float(1.54 * working_volume_m3 / (rps * (diameter_m ** 3)))


# ---------------------------------------------------------------------------
# Volumetric Oxygen Mass Transfer Coefficient (k_L a)
# ---------------------------------------------------------------------------


def calc_superficial_gas_velocity(
    q_g_m3_s: float,
    cross_sectional_area_m2: float,
) -> float:
    """Calculate superficial gas velocity: u_g = Q_g / A (m/s)."""
    if cross_sectional_area_m2 <= 0.0:
        raise ValueError("cross_sectional_area_m2 must be strictly positive")
    return q_g_m3_s / cross_sectional_area_m2


def calc_kla_vant_riet(
    gassed_power_w: float,
    working_volume_m3: float,
    superficial_gas_velocity_m_s: float,
    coalescing_media: bool = True,
) -> float:
    """Calculate volumetric mass transfer coefficient k_L a (s^-1) via Van 't Riet correlations:

    - Coalescing media (pure water, nutrient salts):
      k_L a = 0.026 * (P_g / V_L)^0.4 * u_g^0.5
    - Non-coalescing media (electrolytes, ionic broth, antifoam, viscous broths):
      k_L a = 0.002 * (P_g / V_L)^0.7 * u_g^0.2

    Parameters
    ----------
    gassed_power_w : float
        Gassed power input P_g (W).
    working_volume_m3 : float
        Liquid working volume V_L (m^3).
    superficial_gas_velocity_m_s : float
        Superficial gas velocity u_g (m/s).
    coalescing_media : bool, optional
        Whether the fermentation media is coalescing, by default True.

    Returns
    -------
    float
        k_L a in s^-1.
    """
    if gassed_power_w <= 0.0 or superficial_gas_velocity_m_s <= 0.0 or working_volume_m3 <= 0.0:
        return 0.0

    pg_vl = gassed_power_w / working_volume_m3
    ug = superficial_gas_velocity_m_s

    if coalescing_media:
        return float(0.026 * (pg_vl ** 0.4) * (ug ** 0.5))
    else:
        return float(0.002 * (pg_vl ** 0.7) * (ug ** 0.2))
