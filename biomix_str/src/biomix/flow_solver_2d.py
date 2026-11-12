"""2D Axisymmetric Hydrodynamic Flow Field, Vortex & Dead-Zone Solver.

Solves the 2D vertical cross-section (x in [-T/2, T/2], z in [0, H]) of the stirred-tank
bioreactor, calculating:
- Vectorized velocity field (u_x, u_z, u_theta) for multi-impeller configurations
- Free-surface Rankine vortex profile in unbaffled vessels
- Bottom dish masking for Flat, ASME 2:1 Elliptical, and Hemispherical vessels
- Local spatial shear rate map combining tensor gradients and blade tip trailing vortex kernels
- Bioprocess dead-zone mapping and dead-zone volume fraction
"""

from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from biomix.engine import ReactorSimulationResult
from biomix.models import BottomType, FlowDirection, ImpellerType


class FlowField2DResult(BaseModel):
    """Container for 2D cross-sectional hydrodynamic flow field metrics."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    x_grid: np.ndarray = Field(description="2D array of radial coordinates x in [-T/2, T/2] (m)")
    z_grid: np.ndarray = Field(description="2D array of axial coordinates z in [0, H] (m)")
    vessel_mask: np.ndarray = Field(description="Boolean array True inside liquid broth domain")
    u_x: np.ndarray = Field(description="In-plane horizontal/radial velocity u_x (m/s)")
    u_z: np.ndarray = Field(description="In-plane vertical/axial velocity u_z (m/s)")
    u_theta: np.ndarray = Field(description="Tangential swirl velocity u_theta (m/s)")
    velocity_mag: np.ndarray = Field(description="In-plane circulation speed sqrt(u_x^2 + u_z^2) (m/s)")
    total_speed: np.ndarray = Field(description="Total 3D velocity magnitude sqrt(u_x^2 + u_z^2 + u_theta^2) (m/s)")
    shear_rate_s_inv: np.ndarray = Field(description="Local shear rate field dot_gamma(x, z) (s^-1)")
    dead_zone_mask: np.ndarray = Field(description="Boolean array True where total_speed < 0.05 * v_tip_max")
    dead_zone_fraction: float = Field(description="Fraction of active liquid domain in dead zones (0 to 1)")
    free_surface_z: np.ndarray = Field(description="1D array of liquid free-surface height across tank width (m)")


class AnalyticalFlowEstimator2D:
    """Analytical 2D axisymmetric kinematic flow estimator for rapid bioreactor preview.
    
    NOTE: This is an analytical/empirical kinematic preview estimator based on
    superimposed discharge jets, Rankine vortex swirl, and semi-empirical circulation
    profiles. It is NOT a Navier-Stokes PDE solver; authoritative CFD fields are
    computed strictly using Ansys Fluent 2026 R1.
    """

    @classmethod
    def solve(
        cls,
        sim_result: ReactorSimulationResult,
        nx: int = 101,
        nz: int = 151,
    ) -> FlowField2DResult:
        """Compute the 2D cross-sectional flow field for the simulated bioreactor.

        Parameters
        ----------
        sim_result : ReactorSimulationResult
            Output from HydrodynamicEngine containing vessel geometry, operating conditions,
            and per-stage metrics.
        nx : int, optional
            Number of horizontal grid nodes across tank diameter (default: 101, odd for centered shaft).
        nz : int, optional
            Number of vertical grid nodes from bottom to liquid surface (default: 151).

        Returns
        -------
        FlowField2DResult
            2D hydrodynamic field arrays and dead-zone analysis.
        """
        tank = sim_result.tank
        fluid = sim_result.fluid
        ops = sim_result.ops
        stages = sim_result.stages

        T = tank.diameter_m
        R = T / 2.0
        H = tank.liquid_height_m

        # 1. Construct 2D Cartesian spatial mesh
        x_1d = np.linspace(-R, R, nx)
        z_1d = np.linspace(0.0, H, nz)
        x_grid, z_grid = np.meshgrid(x_1d, z_1d)
        r_grid = np.abs(x_grid)

        # 2. Compute Bottom Dish Profile z_bottom(r)
        z_bottom_1d = np.zeros(nx)
        for i, x_val in enumerate(x_1d):
            r = abs(x_val)
            if r > R:
                z_bottom_1d[i] = H
            elif tank.bottom_type == BottomType.FLAT:
                z_bottom_1d[i] = 0.0
            elif tank.bottom_type == BottomType.ELLIPTICAL_2_1:
                h_d = T / 4.0
                rad_term = max(0.0, 1.0 - (r / R) ** 2)
                z_bottom_1d[i] = h_d * (1.0 - math.sqrt(rad_term))
            elif tank.bottom_type == BottomType.HEMISPHERICAL:
                h_d = R
                rad_term = max(0.0, 1.0 - (r / R) ** 2)
                z_bottom_1d[i] = h_d * (1.0 - math.sqrt(rad_term))

        # Broadcast z_bottom across 2D grid
        z_bottom_2d = np.tile(z_bottom_1d, (nz, 1))

        # 3. Compute Free-Surface Profile z_surf(r) (Nagata Combined Rankine Vortex)
        free_surface_1d = np.full(nx, H)
        if not tank.is_baffled and sim_result.vortex_depth_m > 1e-4:
            h_v = min(0.35 * H, sim_result.vortex_depth_m)
            d0 = tank.impellers[0].diameter_m
            r_c = 0.35 * d0  # Critical core radius
            for i, x_val in enumerate(x_1d):
                r = abs(x_val)
                if r <= r_c:
                    # Forced vortex core
                    free_surface_1d[i] = (H - h_v) + (h_v / 2.0) * ((r / r_c) ** 2)
                else:
                    # Free vortex outer region normalized so z(R) = H and z(r_c) = H - h_v/2
                    denom = 1.0 - (r_c / R) ** 2
                    if denom > 1e-6:
                        norm_factor = ((r_c / r) ** 2 - (r_c / R) ** 2) / denom
                        free_surface_1d[i] = H - (h_v / 2.0) * norm_factor
                    else:
                        free_surface_1d[i] = H

        free_surface_2d = np.tile(free_surface_1d, (nz, 1))

        # 4. Define Vessel Liquid Mask
        vessel_mask = (z_grid >= z_bottom_2d) & (z_grid <= free_surface_2d) & (r_grid <= R)

        # 5. Multi-Impeller Axial Zone Partitioning
        K = len(tank.impellers)
        clearances = [imp.clearance_m for imp in tank.impellers]
        zone_bounds = [0.0]
        for k in range(K - 1):
            zone_bounds.append(0.5 * (clearances[k] + clearances[k + 1]))
        zone_bounds.append(H)

        # Viscous damping factor based on bottom impeller Re
        re_0 = stages[0].re_i
        alpha_visc = float(np.clip(math.log10(max(re_0, 1.5)) / 4.0, 0.15, 1.0))

        # Initialize velocity fields
        u_r_total = np.zeros_like(r_grid)
        u_z_total = np.zeros_like(z_grid)
        u_theta_total = np.zeros_like(r_grid)

        # 6. Synthesize In-Plane Recirculation for each Impeller Stage
        for k, imp in enumerate(tank.impellers):
            stage_metric = stages[k]
            v_tip = stage_metric.tip_speed_m_s
            D_i = imp.diameter_m
            C_k = imp.clearance_m
            z_min = zone_bounds[k]
            z_max = zone_bounds[k + 1]

            # In-plane velocity field for this stage
            u_r_k, u_z_k = cls._compute_stage_circulation(
                r_grid=r_grid,
                z_grid=z_grid,
                D_i=D_i,
                C_k=C_k,
                R=R,
                z_min=z_min,
                z_max=z_max,
                impeller_type=imp.impeller_type,
                v_tip=v_tip,
                alpha_visc=alpha_visc,
            )

            # Tangential swirl velocity for this stage
            u_theta_k = cls._compute_stage_swirl(
                r_grid=r_grid,
                z_grid=z_grid,
                D_i=D_i,
                C_k=C_k,
                R=R,
                v_tip=v_tip,
                is_baffled=tank.is_baffled,
                alpha_visc=alpha_visc,
                is_close_clearance=imp.impeller_type.is_close_clearance,
            )

            u_r_total += u_r_k
            u_z_total += u_z_k
            u_theta_total += u_theta_k

        # 7. Convert (u_r, u_z) to Cartesian in-plane (u_x, u_z)
        # u_x points outward (positive for x > 0, negative for x < 0)
        sign_x = np.sign(x_grid)
        sign_x[x_grid == 0.0] = 0.0
        u_x = sign_x * u_r_total
        u_z = u_z_total
        u_theta = u_theta_total

        # Apply boundary masking: 0.0 outside liquid domain
        u_x[~vessel_mask] = 0.0
        u_z[~vessel_mask] = 0.0
        u_theta[~vessel_mask] = 0.0

        # Velocity magnitudes
        vel_mag = np.sqrt(u_x ** 2 + u_z ** 2)
        vel_mag[~vessel_mask] = 0.0

        total_speed = np.sqrt(u_x ** 2 + u_z ** 2 + u_theta ** 2)
        total_speed[~vessel_mask] = 0.0

        # 8. Compute Local Shear Rate Map dot_gamma(x, z)
        dx = x_1d[1] - x_1d[0]
        dz = z_1d[1] - z_1d[0]

        dux_dz, dux_dx = np.gradient(u_x, dz, dx)
        duz_dz, duz_dx = np.gradient(u_z, dz, dx)

        gamma_grad = np.sqrt((dux_dz + duz_dx) ** 2 + 2.0 * (dux_dx ** 2) + 2.0 * (duz_dz ** 2))

        # Add Gaussian blade-tip trailing vortex kernels
        trailing_vortex_kernel = np.zeros_like(r_grid)
        for k, imp in enumerate(tank.impellers):
            stage_metric = stages[k]
            D_i = imp.diameter_m
            C_k = imp.clearance_m
            gamma_avg = stage_metric.shear_rate_s_inv

            if imp.impeller_type in (ImpellerType.RUSHTON_6_BLADE, ImpellerType.SMITH_CD6, ImpellerType.FLAT_BLADE_FBT):
                peak_factor = 8.0
            elif imp.impeller_type in (ImpellerType.PADDLE_R200, ImpellerType.CURVED_BACKSWEPT, ImpellerType.RETREAT_BLADE):
                peak_factor = 6.0
            elif imp.impeller_type in (ImpellerType.PITCHED_BLADE_45, ImpellerType.MAXFLO_HIGH_SOLIDITY):
                peak_factor = 4.5
            elif imp.impeller_type in (ImpellerType.INTERMIG_EKATO, ImpellerType.GATE_IMPELLER):
                peak_factor = 3.5
            elif imp.impeller_type in (ImpellerType.ANCHOR, ImpellerType.HELICAL_RIBBON, ImpellerType.SIGMA_Z_KNEADER):
                peak_factor = 5.0
            else:  # MARINE_PROPELLER, HYDROFOIL_HE3, AUGER_SCREW
                peak_factor = 2.5

            sigma_r = 0.12 * D_i
            sigma_z = 0.08 * D_i
            k_gaussian = (
                peak_factor
                * gamma_avg
                * np.exp(-((r_grid - D_i / 2.0) ** 2) / (2.0 * (sigma_r ** 2)))
                * np.exp(-((z_grid - C_k) ** 2) / (2.0 * (sigma_z ** 2)))
            )
            trailing_vortex_kernel = np.maximum(trailing_vortex_kernel, k_gaussian)

        shear_rate = np.sqrt(gamma_grad ** 2 + trailing_vortex_kernel ** 2)
        shear_rate[~vessel_mask] = 0.0

        # 9. Dead-Zone Analysis
        v_tip_max = sim_result.max_tip_speed_m_s
        is_any_close = any(imp.impeller_type.is_close_clearance for imp in tank.impellers)
        if is_any_close:
            dead_zone_threshold = 0.02 * v_tip_max
        else:
            dead_zone_threshold = 0.05 * v_tip_max
        dead_zone_mask = vessel_mask & (total_speed < dead_zone_threshold)

        total_liquid_nodes = int(np.sum(vessel_mask))
        dead_zone_nodes = int(np.sum(dead_zone_mask))
        dead_zone_fraction = (
            float(dead_zone_nodes / total_liquid_nodes) if total_liquid_nodes > 0 else 0.0
        )

        return FlowField2DResult(
            x_grid=x_grid,
            z_grid=z_grid,
            vessel_mask=vessel_mask,
            u_x=u_x,
            u_z=u_z,
            u_theta=u_theta,
            velocity_mag=vel_mag,
            total_speed=total_speed,
            shear_rate_s_inv=shear_rate,
            dead_zone_mask=dead_zone_mask,
            dead_zone_fraction=dead_zone_fraction,
            free_surface_z=free_surface_1d,
        )

    @classmethod
    def _compute_stage_circulation(
        cls,
        r_grid: np.ndarray,
        z_grid: np.ndarray,
        D_i: float,
        C_k: float,
        R: float,
        z_min: float,
        z_max: float,
        impeller_type: ImpellerType,
        v_tip: float,
        alpha_visc: float,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Compute the in-plane (u_r, u_z) circulation loops for a single impeller stage."""
        u_r = np.zeros_like(r_grid)
        u_z = np.zeros_like(z_grid)

        in_zone = (z_grid >= z_min) & (z_grid <= z_max)
        if not np.any(in_zone):
            return u_r, u_z

        # 1. No-slip shaft core attenuation factor f_shaft(r, z)
        r_shaft = 0.06 * D_i
        dr_shaft = np.maximum(0.0, r_grid - r_shaft)
        f_shaft_r = 1.0 - np.exp(-((dr_shaft / (0.08 * D_i)) ** 2))

        z_shaft_tip = C_k - 0.10 * D_i
        s_z = 1.0 / (1.0 + np.exp(-np.clip((z_grid - z_shaft_tip) / (0.02 * D_i), -20.0, 20.0)))
        f_shaft = s_z * f_shaft_r + (1.0 - s_z) * 1.0

        is_radial = (impeller_type.default_flow_direction == FlowDirection.RADIAL)
        is_close_clearance = impeller_type.is_close_clearance

        if is_radial:
            # -----------------------------------------------------------------
            # Radial Impellers: Upper and lower counter-rotating circulation loops
            # -----------------------------------------------------------------
            if impeller_type == ImpellerType.SMITH_CD6:
                v_jet_peak = 0.80 * v_tip
            elif impeller_type in (ImpellerType.RUSHTON_6_BLADE, ImpellerType.FLAT_BLADE_FBT, ImpellerType.CURVED_BACKSWEPT):
                v_jet_peak = 0.75 * v_tip
            elif impeller_type == ImpellerType.RETREAT_BLADE:
                v_jet_peak = 0.65 * v_tip
            else:  # PADDLE_R200
                v_jet_peak = 0.55 * v_tip

            v_bulk_return = 0.25 * v_tip

            # Upper Loop: z in [C_k, z_max]
            delta_z_u = max(1e-4, z_max - C_k)
            mask_u = (z_grid >= C_k) & (z_grid <= z_max) & (r_grid <= R)
            zeta_u = np.clip((z_grid - C_k) / delta_z_u, 0.0, 1.0)
            xi_u = np.clip(r_grid / R, 0.0, 1.0)

            V_r_u = v_jet_peak - (v_jet_peak - v_bulk_return) * zeta_u
            ur_u = V_r_u * (4.0 * xi_u * (1.0 - xi_u)) * np.cos(math.pi * zeta_u) * f_shaft
            c_z_scale_u = 0.18 * v_tip * min(1.0, delta_z_u / R)
            uz_u = c_z_scale_u * (3.0 * xi_u - 2.0) * np.sin(math.pi * zeta_u) * f_shaft

            u_r[mask_u] = ur_u[mask_u]
            u_z[mask_u] = uz_u[mask_u]

            # Lower Loop: z in [z_min, C_k]
            delta_z_l = max(1e-4, C_k - z_min)
            mask_l = (z_grid >= z_min) & (z_grid < C_k) & (r_grid <= R)
            zeta_l = np.clip((C_k - z_grid) / delta_z_l, 0.0, 1.0)
            xi_l = np.clip(r_grid / R, 0.0, 1.0)

            # For retreat blade, bias lower loop slightly downward along dish contour
            bias = 1.15 if impeller_type == ImpellerType.RETREAT_BLADE else 1.0
            V_r_l = v_jet_peak - (v_jet_peak - v_bulk_return) * zeta_l
            ur_l = V_r_l * (4.0 * xi_l * (1.0 - xi_l)) * np.cos(math.pi * zeta_l) * f_shaft
            c_z_scale_l = 0.18 * v_tip * min(1.0, delta_z_l / R) * bias
            uz_l = c_z_scale_l * (2.0 - 3.0 * xi_l) * np.sin(math.pi * zeta_l) * f_shaft

            u_r[mask_l] = ur_l[mask_l]
            u_z[mask_l] = uz_l[mask_l]

        elif is_close_clearance:
            # -----------------------------------------------------------------
            # Close-Clearance Impellers (Anchor, Helical Ribbon, Auger, Gate, Sigma)
            # Wall-adjacent scraping boundary layer + central axial displacement
            # -----------------------------------------------------------------
            mask_zone = in_zone & (r_grid <= R)
            xi = np.clip(r_grid / R, 0.0, 1.0)
            delta_z = max(1e-4, z_max - z_min)
            zeta = np.clip((z_grid - z_min) / delta_z, 0.0, 1.0)

            if impeller_type == ImpellerType.AUGER_SCREW:
                # Strong downward pumping along central screw flight (r <= 0.50 Di), upward return in outer annulus
                r_core = 0.50 * D_i
                xi_core = np.clip(r_grid / r_core, 0.0, 1.0)
                uz_screw = np.where(
                    r_grid <= r_core,
                    -0.62 * v_tip * (1.0 - xi_core**2),
                    0.45 * v_tip * np.sin(math.pi * np.clip((r_grid - r_core) / max(1e-4, R - r_core), 0.0, 1.0)),
                )
                ur_screw = 0.16 * v_tip * np.sin(2.0 * math.pi * zeta) * (4.0 * xi * (1.0 - xi))
                u_z[mask_zone] = uz_screw[mask_zone]
                u_r[mask_zone] = ur_screw[mask_zone]

            elif impeller_type == ImpellerType.HELICAL_RIBBON:
                # Upward pumping along outer wall (r > 0.60 R), downward central cascade (r <= 0.60 R)
                uz_ribbon = np.where(
                    xi > 0.60,
                    0.52 * v_tip * np.sin(math.pi * np.clip((xi - 0.60) / 0.40, 0.0, 1.0)),
                    -0.42 * v_tip * (1.0 - (xi / 0.60) ** 2),
                )
                ur_ribbon = 0.15 * v_tip * np.cos(math.pi * zeta) * (4.0 * xi * (1.0 - xi))
                u_z[mask_zone] = uz_ribbon[mask_zone]
                u_r[mask_zone] = ur_ribbon[mask_zone]

            elif impeller_type == ImpellerType.ANCHOR:
                # Upward flow along swept outer wall (r > 0.60 R), downward central return (r <= 0.60 R)
                uz_anchor = np.where(
                    xi > 0.60,
                    0.48 * v_tip * np.sin(math.pi * np.clip((xi - 0.60) / 0.40, 0.0, 1.0)),
                    -0.36 * v_tip * (1.0 - (xi / 0.60) ** 2),
                )
                ur_anchor = 0.15 * v_tip * np.sin(math.pi * zeta) * (4.0 * xi * (1.0 - xi)) * f_shaft
                u_z[mask_zone] = uz_anchor[mask_zone]
                u_r[mask_zone] = ur_anchor[mask_zone]

            else:  # GATE_IMPELLER, SIGMA_Z_KNEADER
                # Wall scraping updraft, central core downdraft
                uz_close = np.where(
                    xi > 0.60,
                    0.44 * v_tip * np.sin(math.pi * np.clip((xi - 0.60) / 0.40, 0.0, 1.0)),
                    -0.32 * v_tip * (1.0 - (xi / 0.60) ** 2),
                )
                ur_close = 0.14 * v_tip * np.sin(math.pi * zeta) * (4.0 * xi * (1.0 - xi)) * f_shaft
                u_z[mask_zone] = uz_close[mask_zone]
                u_r[mask_zone] = ur_close[mask_zone]

        else:
            # -----------------------------------------------------------------
            # Axial & Mixed Impellers (Marine Propeller, PBT, HE-3, Maxflo, Intermig)
            # Continuous top-to-bottom downward pumping loop
            # -----------------------------------------------------------------
            is_pbt = (impeller_type == ImpellerType.PITCHED_BLADE_45)
            is_maxflo = (impeller_type == ImpellerType.MAXFLO_HIGH_SOLIDITY)
            is_intermig = (impeller_type == ImpellerType.INTERMIG_EKATO)

            if is_pbt:
                v_jet_peak = 0.68 * v_tip
            elif is_maxflo:
                v_jet_peak = 0.72 * v_tip
            elif is_intermig:
                v_jet_peak = 0.62 * v_tip
            elif impeller_type == ImpellerType.HYDROFOIL_HE3:
                v_jet_peak = 0.65 * v_tip
            else:  # MARINE_PROPELLER
                v_jet_peak = 0.60 * v_tip

            v_bulk_return = 0.20 * v_tip

            delta_z = max(1e-4, z_max - z_min)
            mask_zone = in_zone & (r_grid <= R)
            zeta = np.clip((z_grid - z_min) / delta_z, 0.0, 1.0)
            xi = np.clip(r_grid / R, 0.0, 1.0)

            # 1. Base circulation loop maintaining continuous streamfunction
            ur_axial = v_bulk_return * (4.0 * xi * (1.0 - xi)) * np.cos(math.pi * zeta) * f_shaft
            c_z_axial = 0.16 * v_tip * min(1.0, delta_z / R)
            uz_axial = c_z_axial * (3.0 * xi - 2.0) * np.sin(math.pi * zeta) * f_shaft

            # 2. Localized high-velocity downward discharge jet at/below the blades
            r_peak = 0.35 * D_i * s_z
            sigma_r_jet = 0.16 * D_i + (1.0 - s_z) * 0.10 * D_i
            g_r = np.exp(-((r_grid - r_peak) ** 2) / (2.0 * (sigma_r_jet ** 2))) * f_shaft

            sigma_z_jet = max(0.08 * D_i, 0.25 * (C_k - z_min))
            g_z = np.exp(-((z_grid - (C_k - 0.08 * D_i)) ** 2) / (2.0 * (sigma_z_jet ** 2)))
            g_z = np.where(
                z_grid > C_k + 0.10 * D_i,
                g_z * np.exp(-(((z_grid - (C_k + 0.10 * D_i)) / (0.08 * D_i)) ** 2)),
                g_z,
            )

            v_jet_add = v_jet_peak - v_bulk_return
            uz_jet = -v_jet_add * g_r * g_z
            uz_axial += uz_jet

            if is_pbt or is_maxflo:
                # Add 45° outward discharge flare at blade level
                flare = np.exp(-((z_grid - C_k) ** 2) / (2.0 * ((0.12 * D_i) ** 2)))
                flare_fac = 0.40 if is_maxflo else 0.35
                ur_flare = flare_fac * v_jet_peak * (4.0 * xi * (1.0 - xi)) * flare * f_shaft
                ur_axial += ur_flare

            if is_intermig:
                # Add outer slotted winglet shear jet at r in [0.55 Di, 0.70 Di]
                r_winglet = 0.62 * D_i
                winglet_flare = np.exp(-((r_grid - r_winglet) ** 2) / (2.0 * ((0.08 * D_i) ** 2))) * np.exp(
                    -((z_grid - C_k) ** 2) / (2.0 * ((0.06 * D_i) ** 2))
                )
                ur_axial += 0.28 * v_jet_peak * winglet_flare

            u_r[mask_zone] = ur_axial[mask_zone]
            u_z[mask_zone] = uz_axial[mask_zone]

        # Apply Viscous Exponential Attenuation away from impeller core ONLY for open localized impellers!
        # Close-clearance mixers sweep the entire vessel volume and actively turnover viscous fluid across tank height!
        if alpha_visc < 0.99 and not is_close_clearance:
            delta_r = np.maximum(0.0, r_grid - D_i / 2.0)
            delta_z_dist = np.abs(z_grid - C_k)
            damping = np.exp(
                -3.5
                * (1.0 - alpha_visc)
                * (
                    ((delta_r / max(1e-3, alpha_visc * (R - D_i / 2.0))) ** 1.5)
                    + ((delta_z_dist / max(1e-3, alpha_visc * (z_max - z_min))) ** 1.5)
                )
            )
            u_r *= damping
            u_z *= damping

        return u_r, u_z

    @classmethod
    def _compute_stage_swirl(
        cls,
        r_grid: np.ndarray,
        z_grid: np.ndarray,
        D_i: float,
        C_k: float,
        R: float,
        v_tip: float,
        is_baffled: bool,
        alpha_visc: float,
        is_close_clearance: bool = False,
    ) -> np.ndarray:
        """Compute the tangential swirl velocity field u_theta(r, z)."""
        r_blade = D_i / 2.0
        u_theta = np.zeros_like(r_grid)

        if is_close_clearance:
            # Physically grounded Couette boundary-layer profile across clearance gap:
            # 1. Inside blade sweep (r <= r_blade): fluid entrained by moving blade assembly,
            #    reaching u_theta(r_blade) = v_tip at the outer blade tip (no-slip moving boundary).
            # 2. In narrow wall clearance gap (r_blade < r <= R): fluid shears down to 0 at the stationary vessel wall.
            mask_inner = (r_grid <= r_blade) & (r_grid > 0.0)
            u_theta[mask_inner] = v_tip * (r_grid[mask_inner] / r_blade)

            mask_gap = (r_grid > r_blade) & (r_grid <= R)
            gap_w = max(1e-4, R - r_blade)
            u_theta[mask_gap] = v_tip * ((R - r_grid[mask_gap]) / gap_w)

            # Smooth axial profile centered around impeller stage
            z_decay = np.exp(-((z_grid - C_k) ** 2) / (2.0 * ((0.65 * D_i) ** 2)))
            u_theta *= z_decay
            return u_theta

        # Core solid body rotation for r <= r_blade
        mask_core = (r_grid <= r_blade) & (r_grid > 0.0)
        u_theta[mask_core] = v_tip * (r_grid[mask_core] / r_blade)

        # Free vortex outer profile for r > r_blade
        mask_outer = (r_grid > r_blade) & (r_grid <= R)
        u_theta[mask_outer] = v_tip * (r_blade / r_grid[mask_outer])

        # Axial decay away from impeller plane
        z_decay = np.exp(-((z_grid - C_k) ** 2) / (2.0 * ((0.50 * D_i) ** 2)))
        u_theta *= z_decay

        # Baffle damping: wall baffles strongly suppress tangential swirl
        if is_baffled:
            baffle_damp = 0.20 * np.exp(-2.5 * np.maximum(0.0, r_grid - r_blade) / (R - r_blade))
            u_theta[mask_outer] *= baffle_damp[mask_outer]

        # Viscous damping
        if alpha_visc < 0.99:
            delta_r = np.maximum(0.0, r_grid - r_blade)
            delta_z = np.abs(z_grid - C_k)
            damping_theta = np.exp(
                -3.5
                * (1.0 - alpha_visc)
                * (
                    ((delta_r / max(1e-3, alpha_visc * (R - r_blade))) ** 1.5)
                    + ((delta_z / max(1e-3, alpha_visc * D_i)) ** 1.5)
                )
            )
            u_theta *= damping_theta

        return u_theta
 
 
# Backward-compatible alias
FlowSolver2D = AnalyticalFlowEstimator2D
