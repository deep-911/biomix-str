"""Multi-Impeller Hydrodynamic Simulation Engine.

Orchestrates bioreactor vessel geometry, impeller topologies, fluid physical
properties, and operating conditions to compute per-stage and overall reactor
hydrodynamics, mixing kinetics, shear stresses, and mass transfer rates.
"""

from __future__ import annotations

import math
from typing import List

from pydantic import BaseModel, Field

from biomix.correlations import (
    FlowRegime,
    METZNER_OTTO_KS,
    calc_aeration_number,
    calc_average_shear,
    calc_flooding_aeration_number,
    calc_froude_number,
    calc_gas_flow_rate_m3_s,
    calc_gassed_power,
    calc_kla_vant_riet,
    calc_kolmogorov_scales,
    calc_mixing_time_95,
    calc_power_number,
    calc_pumping_and_circulation,
    calc_reynolds_number,
    calc_superficial_gas_velocity,
    calc_tip_speed,
    calc_ungassed_power,
    classify_flow_regime,
)
from biomix.models import (
    FlowDirection,
    FluidProperties,
    ImpellerSpec,
    ImpellerType,
    OperatingConditions,
    TankGeometry,
)


class ImpellerStageResult(BaseModel):
    """Detailed hydrodynamic, power, and shear metrics for an individual impeller stage."""
    stage_index: int = Field(description="Stage index from vessel bottom upwards (0 = bottom)")
    impeller_type: ImpellerType = Field(description="Impeller topology")
    flow_direction: FlowDirection = Field(description="Discharge flow pattern")
    diameter_m: float = Field(description="Impeller diameter D_i (m)")
    clearance_m: float = Field(description="Impeller off-bottom clearance from bottom dish tangent C (m)")
    re_i: float = Field(description="Impeller Reynolds Number")
    flow_regime: FlowRegime = Field(description="Hydrodynamic regime (Laminar/Transitional/Turbulent)")
    np_val: float = Field(description="Dimensionless Power Number N_p")
    spacing_interaction_factor: float = Field(
        default=1.0,
        description="Power reduction factor due to adjacent impeller proximity",
    )
    ungassed_power_w: float = Field(description="Ungassed mechanical power draw P_0 (W)")
    gassed_power_w: float = Field(description="Gassed operational power draw P_g (W)")
    tip_speed_m_s: float = Field(description="Blade tip peripheral velocity u_tip (m/s)")
    shear_rate_s_inv: float = Field(description="Average impeller shear rate gamma_dot (s^-1)")
    shear_stress_pa: float = Field(description="Average impeller shear stress tau (Pa)")
    pumping_rate_m3_s: float = Field(description="Primary liquid pumping capacity Q_p (m^3/s)")
    aeration_number: float = Field(description="Aeration Flow Number Fl_g")
    froude_number: float = Field(description="Froude Number Fr")
    flooding_aeration_number: float = Field(description="Critical flooding aeration number Fl_{g,flood}")
    is_flooded: bool = Field(description="True if stage is in gas-flooded regime (Fl_g > Fl_{g,flood})")


class ReactorSimulationResult(BaseModel):
    """Holistic bioprocess engineering report for the stirred-tank bioreactor."""
    tank: TankGeometry
    fluid: FluidProperties
    ops: OperatingConditions
    working_volume_m3: float = Field(description="Ungassed liquid working volume V_L (m^3)")
    stages: List[ImpellerStageResult] = Field(description="Individual impeller stage metrics")

    # Global power draw
    total_ungassed_power_w: float = Field(description="Total ungassed agitator power P_0 (W)")
    total_gassed_power_w: float = Field(description="Total gassed agitator power P_g (W)")
    specific_ungassed_power_w_m3: float = Field(description="Volumetric ungassed power P_0 / V_L (W/m^3)")
    specific_gassed_power_w_m3: float = Field(description="Volumetric gassed power P_g / V_L (W/m^3)")

    # Gas phase and mass transfer
    gas_flow_rate_m3_s: float = Field(description="Gas sparging volumetric flow rate Q_g (m^3/s)")
    superficial_gas_velocity_m_s: float = Field(description="Superficial gas velocity u_g (m/s)")
    kla_s_inv: float = Field(description="Volumetric mass transfer coefficient k_L a (s^-1)")
    kla_h_inv: float = Field(description="Volumetric mass transfer coefficient k_L a (h^-1)")

    # Mixing and circulation
    total_pumping_rate_m3_s: float = Field(description="Sum of all impeller pumping rates Q_p,total (m^3/s)")
    circulation_time_s: float = Field(description="Liquid turnover circulation time t_c = V_L / Q_p,total (s)")
    mixing_time_95_s: float = Field(description="95% bulk blend mixing time theta_95 (s)")

    # Microscale turbulence and shear damage criteria
    epsilon_avg_w_kg: float = Field(description="Average turbulent energy dissipation rate epsilon_avg (W/kg)")
    epsilon_max_w_kg: float = Field(description="Peak dissipation rate in blade trailing vortex epsilon_max (W/kg)")
    lambda_k_avg_um: float = Field(description="Average Kolmogorov microscale eddy length lambda_K,avg (µm)")
    lambda_k_min_um: float = Field(description="Minimum Kolmogorov microscale eddy length lambda_K,min (µm)")
    max_tip_speed_m_s: float = Field(description="Peak peripheral blade tip speed across all impellers (m/s)")
    tip_speed_exceeded: bool = Field(description="True if max tip speed exceeds cell line sensitivity threshold")
    kolmogorov_damage_risk: bool = Field(description="True if minimum Kolmogorov eddy is smaller than cell threshold")
    any_stage_flooded: bool = Field(description="True if any impeller stage is gas-flooded")

    # Vortex and surface kinematics
    vortex_depth_m: float = Field(description="Depth of central Rankine vortex in unbaffled operation (m)")
    vortex_reaches_impeller: bool = Field(description="True if surface vortex reaches topmost impeller")

    # Engineering diagnostics
    warnings: List[str] = Field(default_factory=list, description="Diagnostic warnings and design flags")


class HydrodynamicEngine:
    """Computational simulation engine for stirred-tank bioprocess reactors."""

    @staticmethod
    def run(
        tank: TankGeometry,
        fluid: FluidProperties,
        ops: OperatingConditions,
        gassed_method: str = "michel",
    ) -> ReactorSimulationResult:
        """Execute hydrodynamic and mass transfer simulation.

        Parameters
        ----------
        tank : TankGeometry
            Vessel dimensions, dish head, baffles, and impeller array.
        fluid : FluidProperties
            Liquid broth density, viscosity, and coalescence nature.
        ops : OperatingConditions
            Rotational agitation speed, aeration rate, and cell line.
        gassed_method : str, optional
            Correlation for gassed power: 'michel' or 'bakker', by default 'michel'.

        Returns
        -------
        ReactorSimulationResult
            Hydrodynamic and mass transfer simulation results.
        """
        N = ops.rps
        rho = fluid.density_kg_m3
        mu = fluid.viscosity_pa_s
        nu = fluid.kinematic_viscosity_m2_s
        V_L = tank.working_volume_m3
        A = tank.cross_sectional_area_m2
        T = tank.diameter_m
        H = tank.liquid_height_m

        Q_g = calc_gas_flow_rate_m3_s(ops.aeration_vvm, V_L)
        u_g = calc_superficial_gas_velocity(Q_g, A)

        stages: List[ImpellerStageResult] = []
        warnings: List[str] = []

        # Iterate through each impeller stage (ordered from bottom to top)
        for i, imp in enumerate(tank.impellers):
            D_i = imp.diameter_m
            C_i = imp.clearance_m

            # Check for non-Newtonian Power-Law rheology
            is_power_law = (
                getattr(fluid, "rheology_model", "newtonian") == "power_law"
                or getattr(ops, "rheology_model", "newtonian") == "power_law"
            )
            if is_power_law and N > 0:
                k_val = getattr(fluid, "consistency_k_pa_s_n", 0.001) or 0.001
                n_val = getattr(fluid, "flow_behavior_index_n", 1.0) or 1.0
                ks_val = METZNER_OTTO_KS.get(imp.impeller_type, 11.5)
                gamma_dot_stage = ks_val * N
                mu_stage = k_val * (max(gamma_dot_stage, 1e-4) ** (n_val - 1.0))
            else:
                mu_stage = mu

            re_i = calc_reynolds_number(rho, N, D_i, mu_stage)
            regime = classify_flow_regime(re_i)
            np_val = calc_power_number(re_i, imp.impeller_type, tank.is_baffled)

            # Spacing interaction factor: adjacent impellers spaced closer than 1.5 D
            # experience reduced ungassed power due to merging flow fields (Bates et al., Paul et al.)
            if i == 0:
                spacing_factor = 1.0
            else:
                delta_c = C_i - tank.impellers[i - 1].clearance_m
                prev_d = tank.impellers[i - 1].diameter_m
                if delta_c < 1.5 * prev_d:
                    spacing_factor = 0.85
                else:
                    spacing_factor = 1.0

            # Base ungassed power draw for this stage
            base_p0 = calc_ungassed_power(np_val, rho, N, D_i)
            p0_stage = spacing_factor * base_p0

            # Aeration parameters
            fr = calc_froude_number(N, D_i)
            fl_g = calc_aeration_number(Q_g, N, D_i) if Q_g > 1e-9 else 0.0
            fl_flood = calc_flooding_aeration_number(imp.impeller_type, D_i, T, fr)
            is_flooded = (Q_g > 1e-9) and (fl_g > fl_flood) and (i == 0)

            # Gassed power calculation:
            # Stage 1 (bottom) directly contacts the sparger stream (Michel/Bakker/Hughmark correlation)
            # Upper stages (i > 0) disperse rising bubbles (empirically ~85% of P_0)
            if Q_g <= 1e-9:
                pg_stage = p0_stage
            else:
                if i == 0:
                    pg_stage = calc_gassed_power(
                        p0_stage,
                        N,
                        D_i,
                        Q_g,
                        method=gassed_method,
                        working_volume_m3=V_L,
                        blade_width_m=0.20 * D_i,
                    )
                else:
                    pg_stage = 0.85 * p0_stage

            # Shear and pumping
            v_tip = calc_tip_speed(N, D_i)
            shear_rate, shear_stress = calc_average_shear(N, mu_stage, imp.impeller_type)
            qp, _ = calc_pumping_and_circulation(N, D_i, V_L, imp.impeller_type)

            stage_res = ImpellerStageResult(
                stage_index=i,
                impeller_type=imp.impeller_type,
                flow_direction=imp.flow_direction,
                diameter_m=D_i,
                clearance_m=C_i,
                re_i=re_i,
                flow_regime=regime,
                np_val=np_val,
                spacing_interaction_factor=spacing_factor,
                ungassed_power_w=p0_stage,
                gassed_power_w=pg_stage,
                tip_speed_m_s=v_tip,
                shear_rate_s_inv=shear_rate,
                shear_stress_pa=shear_stress,
                pumping_rate_m3_s=qp,
                aeration_number=fl_g,
                froude_number=fr,
                flooding_aeration_number=fl_flood,
                is_flooded=is_flooded,
            )
            stages.append(stage_res)

        # Aggregate total reactor power draws
        total_p0 = sum(s.ungassed_power_w for s in stages)
        total_pg = sum(s.gassed_power_w for s in stages)
        spec_p0 = total_p0 / V_L
        spec_pg = total_pg / V_L

        # Effective power for dissipation, mass transfer, and mixing
        effective_power = total_pg if Q_g > 1e-9 else total_p0

        # Mass transfer rate k_L a via Van 't Riet
        kla_s = calc_kla_vant_riet(total_pg, V_L, u_g, fluid.coalescing_media)
        kla_h = kla_s * 3600.0

        # Pumping and turnover
        total_qp = sum(s.pumping_rate_m3_s for s in stages)
        circ_time = V_L / total_qp if total_qp > 0.0 else float("inf")

        # 95% blend mixing time
        # Computed from total effective power and bottom impeller dimensions
        bottom_d = tank.impellers[0].diameter_m
        bottom_re = stages[0].re_i
        theta_m = calc_mixing_time_95(T, H, bottom_d, effective_power, rho, V_L, bottom_re)

        # Multi-impeller zoning factor on mixing time:
        # Radial impellers (Rushton) above Stage 1 compartmentalize circulation loops (* 1.35)
        # Axial impellers (PBT/Marine) promote bulk axial exchange (* 0.90)
        for s in stages[1:]:
            if s.flow_direction == FlowDirection.RADIAL:
                theta_m *= 1.35
            elif s.flow_direction in (FlowDirection.AXIAL, FlowDirection.MIXED_AXIAL):
                theta_m *= 0.90

        # Turbulent microscale eddy sizes (Kolmogorov)
        kolm = calc_kolmogorov_scales(effective_power, rho, V_L, nu)
        eps_avg = kolm["epsilon_avg_w_kg"]
        eps_max = kolm["epsilon_max_w_kg"]
        lambda_k_avg_um = kolm["lambda_k_avg_m"] * 1e6
        lambda_k_min_um = kolm["lambda_k_min_m"] * 1e6

        # Cell sensitivity threshold comparisons
        max_v_tip = max(s.tip_speed_m_s for s in stages)
        tip_speed_exceeded = max_v_tip > ops.cell_type.max_tip_speed_m_s
        kolmogorov_risk = kolm["lambda_k_min_m"] < ops.cell_type.critical_kolmogorov_m
        any_flooded = any(s.is_flooded for s in stages)

        # Vortex kinematics in unbaffled tanks
        if tank.is_baffled:
            vortex_depth = 0.0
            vortex_reaches_impeller = False
        else:
            d0 = tank.impellers[0].diameter_m
            fr0 = stages[0].froude_number
            re0 = stages[0].re_i
            # Viscous damping: Rankine swirl vortices only form in low-viscosity swirl (Re_i > 500)
            f_visc = (re0 ** 2) / (re0 ** 2 + 800.0 ** 2)
            raw_depth = 1.5 * d0 * fr0 * ((1.0 + (50.0 / max(1e-4, re0))) ** -0.5)
            vortex_depth = min(0.35 * H, raw_depth * f_visc)
            top_clearance = tank.impellers[-1].clearance_m
            vortex_reaches_impeller = (H - vortex_depth) <= top_clearance

        # Diagnostic Engineering Warnings
        if any_flooded:
            warnings.append(
                f"Impeller flooding detected on gas-dispersing Stage 1 "
                f"(Fl_g={stages[0].aeration_number:.4f} > Fl_{{g,flood}}={stages[0].flooding_aeration_number:.4f}): "
                "Agitator blades are engulfed in gas cavities, causing severe loss of liquid circulation and k_L a."
            )

        if tip_speed_exceeded:
            warnings.append(
                f"Peak impeller tip speed ({max_v_tip:.2f} m/s) exceeds recommended limit "
                f"({ops.cell_type.max_tip_speed_m_s:.2f} m/s) for {ops.cell_type.value} culture. "
                "High risk of mechanical shear stress damage."
            )

        if kolmogorov_risk:
            warnings.append(
                f"Kolmogorov minimum eddy size (lambda_K,min = {lambda_k_min_um:.1f} µm) is smaller than critical "
                f"eddy damage threshold ({ops.cell_type.critical_kolmogorov_m * 1e6:.1f} µm) for {ops.cell_type.value}. "
                "High risk of turbulent shear cell lysis in blade trailing vortex zones."
            )

        if not tank.is_baffled:
            if vortex_reaches_impeller:
                warnings.append(
                    f"Severe central vortex: Vortex depression ({vortex_depth:.2f} m) penetrates to the topmost "
                    f"impeller (clearance {tank.impellers[-1].clearance_m:.2f} m). "
                    "Uncontrolled surface air entrainment and dangerous shaft vibration imminent."
                )
            else:
                warnings.append(
                    f"Unbaffled vessel: Central surface vortex formed with depth {vortex_depth:.2f} m. "
                    "Power transfer and mixing efficiency significantly reduced."
                )

        if any(s.stage_index > 0 and s.impeller_type == ImpellerType.RUSHTON_6_BLADE for s in stages):
            warnings.append(
                "Multi-impeller radial compartmentalization detected: Upper Rushton turbines create isolated "
                "toroidal flow loops, increasing bulk blend mixing time (+35% per radial upper stage)."
            )

        # Aspect ratio and multi-impeller stage spacing diagnostics
        if len(tank.impellers) == 1 and (H / max(T, 1e-4)) > 1.25:
            warnings.append(
                f"High vessel aspect ratio (H_L / T = {H / T:.2f} > 1.25) with only a single impeller stage: "
                "Bioprocess design standards recommend multiple impeller stages for H_L / T > 1.25 to prevent axial dead zones "
                "and ensure uniform dissolved oxygen dispersion (Standard Bioprocess Design Practice)."
            )

        for s_idx in range(1, len(tank.impellers)):
            delta_h = tank.impellers[s_idx].clearance_m - tank.impellers[s_idx - 1].clearance_m
            prev_diam = tank.impellers[s_idx - 1].diameter_m
            spacing_ratio = delta_h / max(prev_diam, 1e-4)
            if spacing_ratio < 1.0:
                warnings.append(
                    f"Impeller stage {s_idx + 1} spacing is too tight (delta_Hi / Di = {spacing_ratio:.2f} < 1.0): "
                    "Close spacing causes severe hydrodynamic jet interference and power draw surge (up to 2.4x pair power). "
                    "Recommended spacing is 1.0 to 1.5 Di (Standard Multi-Impeller Design Practice)."
                )
            elif spacing_ratio > 1.5:
                warnings.append(
                    f"Impeller stage {s_idx + 1} spacing is excessively wide (delta_Hi / Di = {spacing_ratio:.2f} > 1.5): "
                    "Large distance between stages risks quiescent / stagnant zones with poor top-to-bottom blending. "
                    "Recommended spacing is 1.0 to 1.5 Di (Standard Agitation Design Practice)."
                )

        return ReactorSimulationResult(
            tank=tank,
            fluid=fluid,
            ops=ops,
            working_volume_m3=V_L,
            stages=stages,
            total_ungassed_power_w=total_p0,
            total_gassed_power_w=total_pg,
            specific_ungassed_power_w_m3=spec_p0,
            specific_gassed_power_w_m3=spec_pg,
            gas_flow_rate_m3_s=Q_g,
            superficial_gas_velocity_m_s=u_g,
            kla_s_inv=kla_s,
            kla_h_inv=kla_h,
            total_pumping_rate_m3_s=total_qp,
            circulation_time_s=circ_time,
            mixing_time_95_s=theta_m,
            epsilon_avg_w_kg=eps_avg,
            epsilon_max_w_kg=eps_max,
            lambda_k_avg_um=lambda_k_avg_um,
            lambda_k_min_um=lambda_k_min_um,
            max_tip_speed_m_s=max_v_tip,
            tip_speed_exceeded=tip_speed_exceeded,
            kolmogorov_damage_risk=kolmogorov_risk,
            any_stage_flooded=any_flooded,
            vortex_depth_m=vortex_depth,
            vortex_reaches_impeller=vortex_reaches_impeller,
            warnings=warnings,
        )

    simulate = run

