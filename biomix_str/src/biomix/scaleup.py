"""Scale-up similarity engine for bioprocess stirred tank reactors.

Evaluates geometric similarity (lambda = (V2/V1)^(1/3)) and computes scaled operating
conditions, tip speeds, powers, torques, Reynolds numbers, and mixing times across the
classical scale-up similarity criteria:
- Constant Power per Unit Volume (P/V = const)
- Constant Oxygen Mass Transfer Coefficient (k_L a = const)
- Constant Impeller Tip Speed (u_tip = const)
- Constant Impeller Reynolds Number (Re_i = const)
- Constant Equal Liquid-Blend Mixing Time (theta_95 = const)
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from biomix.engine import HydrodynamicEngine
from biomix.models import (
    FluidProperties,
    ImpellerSpec,
    ImpellerType,
    OperatingConditions,
    ScaleUpCriterion,
    ScaleUpRequest,
    ScaleUpResponse,
    TankGeometry,
    VesselScaleMetrics,
)


def compute_scaleup(req: ScaleUpRequest) -> ScaleUpResponse:
    """Compute side-by-side scale-up metrics from baseline to target volume."""
    tank1 = req.tank
    if tank1 is None:
        tank1 = TankGeometry(
            diameter_m=0.40,
            liquid_height_m=0.45,
            impellers=[ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.14, clearance_m=0.15)]
        )
    fluid = req.fluid or FluidProperties()
    ops1 = req.ops or OperatingConditions()

    # 1. Baseline hydrodynamic evaluation
    res1 = HydrodynamicEngine.run(tank1, fluid, ops1)
    v1_m3 = tank1.working_volume_m3
    v1_l = v1_m3 * 1000.0

    b_power_corr = res1.total_ungassed_power_w
    if req.power_source == "active_cfd" and req.cfd_power_w is not None and req.cfd_power_w > 0:
        b_power = req.cfd_power_w
        power_source_label = "Active CFD run"
    else:
        b_power = b_power_corr
        power_source_label = "Engineering correlation"

    # 2. Determine target volume and scale ratio
    if req.target_volume_l is not None and req.target_volume_l > 0:
        v2_l = req.target_volume_l
        vol_ratio = v2_l / max(v1_l, 1e-4)
    else:
        vol_ratio = max(req.volume_ratio or 10.0, 1.01)
        v2_l = v1_l * vol_ratio

    v2_m3 = v2_l / 1000.0
    lam = vol_ratio ** (1.0 / 3.0)  # Linear scale factor

    # Scaled geometry with geometric similarity
    t2_m = tank1.diameter_m * lam
    h2_m = tank1.liquid_height_m * lam
    impellers2 = []
    for imp in tank1.impellers:
        imp2 = imp.model_copy()
        imp2.diameter_m = imp.diameter_m * lam
        imp2.clearance_m = imp.clearance_m * lam
        if imp.blade_width_m is not None:
            imp2.blade_width_m = imp.blade_width_m * lam
        impellers2.append(imp2)

    tank2 = tank1.model_copy()
    tank2.diameter_m = t2_m
    tank2.liquid_height_m = h2_m
    tank2.impellers = impellers2

    # 3. Scale-up criteria exponents for N2 / N1 = lam^alpha
    n1_rpm = ops1.rpm
    n1_rps = ops1.rps
    crit = req.criterion

    primary_imp1 = tank1.impellers[0]
    base_re = (fluid.density_kg_m3 * n1_rps * (primary_imp1.diameter_m ** 2)) / max(fluid.viscosity_pa_s, 1e-6)
    is_laminar = base_re < 10.0

    if crit == ScaleUpCriterion.CONSTANT_P_V:
        if is_laminar:
            alpha = 0.0
            crit_label = "Constant Power per Volume (P/V<sub>L</sub> = const) [Laminar Flow]"
            crit_formula = "N₂ = N₁ · λ⁰ = N₁"
            insights = [
                f"Laminar agitation regime detected (Re_i = {base_re:.1f} < 10). Power scales as P = K_L·μ·N²·D_i³.",
                f"Because liquid volume V_L ∝ D_i³, volumetric power P/V_L ∝ μ·N² is independent of vessel diameter D_i (Standard Laminar Agitation Similitude).",
                f"Maintaining constant P/V_L in laminar broths requires identical rotational speed (N₂ = N₁, λ⁰ scaling).",
            ]
        else:
            alpha = -2.0 / 3.0
            crit_label = "Constant Power per Volume (P/V<sub>L</sub> = const) [Turbulent Flow]"
            crit_formula = "N₂ = N₁ · λ<sup>−2/3</sup>"
            insights = [
                f"Preserves volumetric mass transfer rate (k<sub>L</sub>a) and average shear dissipation (ε<sub>avg</sub>) in turbulent flow.",
                f"Tip speed increases by λ<sup>1/3</sup> ({lam**(1.0/3.0):.2f}×), increasing maximum shear stress near impeller blades.",
                f"Mixing time increases by λ<sup>2/3</sup> ({lam**(2.0/3.0):.2f}×), causing larger spatial concentration and pH gradients in industrial vessels.",
            ]
    elif crit == ScaleUpCriterion.CONSTANT_KLA:
        alpha = -2.0 / 3.0
        crit_label = "Constant Oxygen Mass Transfer (k<sub>L</sub>a = const)"
        crit_formula = "N₂ = N₁ · λ<sup>−2/3</sup> (at constant superficial velocity u<sub>g</sub>)"
        insights = [
            f"Preserves volumetric oxygen mass transfer coefficient (k<sub>L</sub>a) across scales, the primary similarity criterion for aerobic bioprocesses (Aerobic Scale-Up Criterion).",
            f"Under equal superficial gas velocity u<sub>g</sub>, constant k<sub>L</sub>a requires holding P/V_L constant, yielding N₂ = N₁ · λ<sup>−2/3</sup>.",
            f"Tip speed increases by λ<sup>1/3</sup> ({lam**(1.0/3.0):.2f}×); verify cell line shear sensitivity.",
            f"Mixing time increases by λ<sup>2/3</sup> ({lam**(2.0/3.0):.2f}×); monitor vessel dissolved oxygen and nutrient uniformity.",
        ]
    elif crit == ScaleUpCriterion.CONSTANT_TIP_SPEED:
        alpha = -1.0
        crit_label = "Constant Impeller Tip Speed (u<sub>tip</sub> = const)"
        crit_formula = "N₂ = N₁ · λ<sup>−1</sup>"
        insights = [
            f"Preserves maximum blade shear stress (critical for mammalian CHO, stem cell, and filamentous fungal cultures).",
            f"Volumetric power P/V<sub>L</sub> decreases by λ<sup>−1</sup> ({(1.0/lam):.2f}×), significantly lowering oxygen mass transfer (k<sub>L</sub>a).",
            f"Mixing time increases by λ<sup>1.0</sup> ({lam:.2f}×), extending circulation cycles.",
        ]
    elif crit == ScaleUpCriterion.CONSTANT_REYNOLDS:
        alpha = -2.0
        crit_label = "Constant Impeller Reynolds Number (Re<sub>i</sub> = const)"
        crit_formula = "N₂ = N₁ · λ<sup>−2</sup>"
        insights = [
            f"Preserves hydrodynamic boundary layer similitude and turbulence ratio.",
            f"Power per volume P/V<sub>L</sub> drops drastically by λ<sup>−4</sup> ({(lam**-4):.2e}×), leading to severe under-agitation in industrial tanks.",
            f"Rarely used alone in industrial bioprocess scale-up; useful primarily for micro-scale hydrodynamic validation.",
        ]
    elif crit == ScaleUpCriterion.CONSTANT_MIXING_TIME:
        alpha = 0.0
        crit_label = "Constant Mixing Time (t<sub>95</sub> = const)"
        crit_formula = "N₂ = N₁ · λ⁰"
        insights = [
            f"Preserves identical bulk blend times between small and large scales.",
            f"Total power explodes by λ⁵ ({lam**5:.1f}×) and tip speed scales with λ ({lam:.2f}×), typically exceeding motor and mechanical limits.",
            f"Impeller blade shear stress can lyse shear-sensitive cells.",
        ]
    else:
        alpha = -2.0 / 3.0
        crit_label = "Constant Power per Volume (P/V<sub>L</sub> = const)"
        crit_formula = "N₂ = N₁ · λ<sup>−2/3</sup>"
        insights = []

    n2_rps = n1_rps * (lam ** alpha)
    n2_rpm = n2_rps * 60.0

    ops2 = ops1.model_copy()
    ops2.rpm = n2_rpm

    # 4. Scaled hydrodynamic evaluation
    res2 = HydrodynamicEngine.run(tank2, fluid, ops2)

    primary_imp1 = tank1.impellers[0]
    primary_imp2 = tank2.impellers[0]

    b_pv = b_power / max(v1_m3, 1e-4)
    b_tip = math.pi * n1_rps * primary_imp1.diameter_m
    b_torque = b_power / max(2.0 * math.pi * n1_rps, 1e-4)
    b_re = (fluid.density_kg_m3 * n1_rps * (primary_imp1.diameter_m ** 2)) / max(fluid.viscosity_pa_s, 1e-6)

    if req.power_source == "active_cfd" and req.cfd_power_w is not None and req.cfd_power_w > 0:
        is_laminar = b_re < 10.0
        power_exp_map = {
            ScaleUpCriterion.CONSTANT_P_V: 3.0,
            ScaleUpCriterion.CONSTANT_KLA: 3.0,
            ScaleUpCriterion.CONSTANT_TIP_SPEED: 1.0 if is_laminar else 2.0,
            ScaleUpCriterion.CONSTANT_REYNOLDS: -1.0,
            ScaleUpCriterion.CONSTANT_MIXING_TIME: 3.0 if is_laminar else 5.0,
        }
        pexp = power_exp_map.get(crit, 3.0)
        s_power = b_power * (lam ** pexp)
    else:
        s_power = res2.total_ungassed_power_w

    s_pv = s_power / max(v2_m3, 1e-4)
    s_tip = math.pi * n2_rps * primary_imp2.diameter_m
    s_torque = s_power / max(2.0 * math.pi * n2_rps, 1e-4)
    s_re = (fluid.density_kg_m3 * n2_rps * (primary_imp2.diameter_m ** 2)) / max(fluid.viscosity_pa_s, 1e-6)

    baseline_metrics = VesselScaleMetrics(
        scale_label="Baseline Vessel (Scale 1)",
        diameter_m=round(tank1.diameter_m, 3),
        liquid_height_m=round(tank1.liquid_height_m, 3),
        working_volume_l=round(v1_l, 1),
        working_volume_m3=round(v1_m3, 4),
        impeller_diameter_m=round(primary_imp1.diameter_m, 3),
        rpm=round(n1_rpm, 1),
        rps=round(n1_rps, 3),
        tip_speed_m_s=round(b_tip, 3),
        power_w=round(b_power, 2),
        power_per_volume_w_m3=round(b_pv, 1),
        torque_n_m=round(b_torque, 4),
        re_i=round(b_re, 1),
        flow_regime=res1.stages[0].flow_regime if res1.stages else "Turbulent",
        mixing_time_95_s=round(res1.mixing_time_95_s, 2),
    )

    scaled_metrics = VesselScaleMetrics(
        scale_label=f"Scaled Vessel ({vol_ratio:.1f}x Volume)",
        diameter_m=round(t2_m, 3),
        liquid_height_m=round(h2_m, 3),
        working_volume_l=round(v2_l, 1),
        working_volume_m3=round(v2_m3, 4),
        impeller_diameter_m=round(primary_imp2.diameter_m, 3),
        rpm=round(n2_rpm, 1),
        rps=round(n2_rps, 3),
        tip_speed_m_s=round(s_tip, 3),
        power_w=round(s_power, 2),
        power_per_volume_w_m3=round(s_pv, 1),
        torque_n_m=round(s_torque, 4),
        re_i=round(s_re, 1),
        flow_regime=res2.stages[0].flow_regime if res2.stages else "Turbulent",
        mixing_time_95_s=round(res2.mixing_time_95_s, 2),
    )

    ratios = {
        "volume_ratio": round(vol_ratio, 2),
        "diameter_ratio": round(lam, 3),
        "height_ratio": round(lam, 3),
        "impeller_diameter_ratio": round(lam, 3),
        "rpm_ratio": round(n2_rpm / max(n1_rpm, 1e-4), 3),
        "tip_speed_ratio": round(s_tip / max(b_tip, 1e-4), 3),
        "power_ratio": round(s_power / max(b_power, 1e-4), 2),
        "power_per_volume_ratio": round(s_pv / max(b_pv, 1e-4), 3),
        "torque_ratio": round(s_torque / max(b_torque, 1e-4), 2),
        "reynolds_ratio": round(s_re / max(b_re, 1e-4), 2),
        "mixing_time_ratio": round(res2.mixing_time_95_s / max(res1.mixing_time_95_s, 1e-4), 2),
    }

    return ScaleUpResponse(
        criterion=crit.value,
        criterion_label=crit_label,
        criterion_formula=crit_formula,
        linear_scale_factor_lambda=round(lam, 4),
        volume_ratio=round(vol_ratio, 2),
        baseline=baseline_metrics,
        scaled=scaled_metrics,
        ratios=ratios,
        engineering_insights=insights,
        baseline_power_source=power_source_label,
        baseline_power_w=round(b_power, 2),
    )
