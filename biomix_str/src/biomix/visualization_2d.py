"""2D Fluent-Style Contour, Streamline & Engineering Reference Curve Plotter.

Generates engineering-grade 2D visualizations of stirred-tank bioreactor hydrodynamics:
- Velocity magnitude contours with overlaid circulation streamlines and dead-zone highlights
- Local spatial shear rate heatmaps with velocity vector quivers
- Classic Power Number curves (N_p vs. Re_i) with active operating point markers
- 3-panel holistic summary dashboard with complete bioreactor metrics
"""

from __future__ import annotations

import math
import os
from typing import Optional

import matplotlib
if matplotlib.get_backend().lower() != "agg":
    try:
        matplotlib.use("Agg")
    except Exception:
        pass

import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from biomix.correlations import calc_power_number
from biomix.engine import ReactorSimulationResult
from biomix.flow_solver_2d import FlowField2DResult, FlowSolver2D
from biomix.models import BottomType, ImpellerType


class Plotter2D:
    """Headless-compatible engineering visualization engine for stirred-tank bioreactors."""

    @classmethod
    def _draw_reactor_anatomy(
        cls,
        ax: Axes,
        sim_result: ReactorSimulationResult,
        field_2d: FlowField2DResult,
    ) -> None:
        """Render outer vessel walls, dish bottom, baffles, free surface, and impellers."""
        tank = sim_result.tank
        T = tank.diameter_m
        R = T / 2.0
        H = tank.liquid_height_m

        x_1d = field_2d.x_grid[0, :]
        z_1d = field_2d.z_grid[:, 0]

        # 1. Shade / hatch outside liquid domain
        outside_mask = (~field_2d.vessel_mask).astype(float)
        if np.any(~field_2d.vessel_mask):
            ax.contourf(
                field_2d.x_grid,
                field_2d.z_grid,
                outside_mask,
                levels=[0.5, 1.5],
                colors=["#E2E8F0"],
                alpha=0.95,
                zorder=4,
            )

        # 2. Draw Vessel Dish Bottom Contour
        z_bottom = np.zeros_like(x_1d)
        for i, x in enumerate(x_1d):
            r = abs(x)
            if r <= R:
                if tank.bottom_type == BottomType.FLAT:
                    z_bottom[i] = 0.0
                elif tank.bottom_type == BottomType.ELLIPTICAL_2_1:
                    h_d = T / 4.0
                    z_bottom[i] = h_d * (1.0 - math.sqrt(max(0.0, 1.0 - (r / R) ** 2)))
                elif tank.bottom_type == BottomType.HEMISPHERICAL:
                    h_d = R
                    z_bottom[i] = h_d * (1.0 - math.sqrt(max(0.0, 1.0 - (r / R) ** 2)))

        ax.plot(x_1d, z_bottom, color="#2D3748", linewidth=2.5, zorder=6)

        # 3. Outer Vessel Vertical Walls
        dish_depth = tank.dish_depth_m
        ax.plot([-R, -R], [dish_depth, H], color="#2D3748", linewidth=2.5, zorder=6)
        ax.plot([R, R], [dish_depth, H], color="#2D3748", linewidth=2.5, zorder=6)

        # 4. Free Surface Profile (Flat baffled or unbaffled Rankine vortex)
        surf_color = "#0077B6" if tank.is_baffled else "#E63946"
        surf_style = "-" if tank.is_baffled else "-."
        ax.plot(x_1d, field_2d.free_surface_z, color=surf_color, linestyle=surf_style, linewidth=2.2, zorder=7)

        # 5. Wall Baffles
        if tank.is_baffled:
            W = tank.baffle_width_m
            baffle_h = H - dish_depth
            # Left wall baffle
            baffle_left = patches.Rectangle(
                (-R, dish_depth),
                W,
                baffle_h,
                facecolor="#718096",
                edgecolor="#2D3748",
                linewidth=1.0,
                alpha=0.85,
                zorder=8,
            )
            # Right wall baffle
            baffle_right = patches.Rectangle(
                (R - W, dish_depth),
                W,
                baffle_h,
                facecolor="#718096",
                edgecolor="#2D3748",
                linewidth=1.0,
                alpha=0.85,
                zorder=8,
            )
            ax.add_patch(baffle_left)
            ax.add_patch(baffle_right)

        # 6. Agitator Shaft
        r_shaft = 0.025 * T
        lowest_c = tank.impellers[0].clearance_m
        shaft_bot = max(0.0, lowest_c - 0.04 * T)
        shaft = patches.Rectangle(
            (-r_shaft, shaft_bot),
            2.0 * r_shaft,
            H - shaft_bot,
            facecolor="#4A5568",
            edgecolor="#1A202C",
            linewidth=1.2,
            zorder=9,
        )
        ax.add_patch(shaft)

        # 7. Impeller Stage Silhouettes
        for imp in tank.impellers:
            D_i = imp.diameter_m
            C_k = imp.clearance_m
            W_b = imp.blade_width_m if imp.blade_width_m is not None else D_i / 5.0

            if imp.impeller_type == ImpellerType.RUSHTON_6_BLADE:
                # Central disk
                disk_h = 0.015 * D_i
                disk_r = 0.375 * D_i
                disk = patches.Rectangle(
                    (-disk_r, C_k - disk_h / 2.0),
                    2.0 * disk_r,
                    disk_h,
                    facecolor="#1A202C",
                    zorder=10,
                )
                ax.add_patch(disk)

                # Vertical outer blades
                blade_w = 0.125 * D_i
                b_left = patches.Rectangle(
                    (-D_i / 2.0, C_k - W_b / 2.0),
                    blade_w,
                    W_b,
                    facecolor="#E53E3E",
                    edgecolor="#9B2C2C",
                    linewidth=1.0,
                    zorder=11,
                )
                b_right = patches.Rectangle(
                    (D_i / 2.0 - blade_w, C_k - W_b / 2.0),
                    blade_w,
                    W_b,
                    facecolor="#E53E3E",
                    edgecolor="#9B2C2C",
                    linewidth=1.0,
                    zorder=11,
                )
                ax.add_patch(b_left)
                ax.add_patch(b_right)

            elif imp.impeller_type == ImpellerType.PITCHED_BLADE_45:
                # Angled blades at 45 degrees
                hub_r = 0.06 * D_i
                hub = patches.Circle((0, C_k), hub_r, facecolor="#1A202C", zorder=10)
                ax.add_patch(hub)

                # Angled parallelogram blades
                dx_b = D_i / 2.0 - hub_r
                dz_b = W_b / 2.0
                poly_left = np.array([
                    [-hub_r, C_k - 0.2 * dz_b],
                    [-D_i / 2.0, C_k + dz_b],
                    [-D_i / 2.0, C_k + 0.2 * dz_b],
                    [-hub_r, C_k - dz_b],
                ])
                poly_right = np.array([
                    [hub_r, C_k - 0.2 * dz_b],
                    [D_i / 2.0, C_k + dz_b],
                    [D_i / 2.0, C_k + 0.2 * dz_b],
                    [hub_r, C_k - dz_b],
                ])
                ax.add_patch(patches.Polygon(poly_left, facecolor="#3182CE", edgecolor="#2B6CB0", zorder=11))
                ax.add_patch(patches.Polygon(poly_right, facecolor="#3182CE", edgecolor="#2B6CB0", zorder=11))

            elif imp.impeller_type == ImpellerType.MARINE_PROPELLER:
                # Marine Propeller: rounded hydrofoil blades
                hub_r = 0.07 * D_i
                hub = patches.Circle((0, C_k), hub_r, facecolor="#1A202C", zorder=10)
                ax.add_patch(hub)

                ellipse_w = (D_i / 2.0) - hub_r
                e_left = patches.Ellipse(
                    (-hub_r - ellipse_w / 2.0, C_k),
                    ellipse_w,
                    W_b,
                    angle=15,
                    facecolor="#38A169",
                    edgecolor="#22543D",
                    zorder=11,
                )
                e_right = patches.Ellipse(
                    (hub_r + ellipse_w / 2.0, C_k),
                    ellipse_w,
                    W_b,
                    angle=-15,
                    facecolor="#38A169",
                    edgecolor="#22543D",
                    zorder=11,
                )
                ax.add_patch(e_left)
                ax.add_patch(e_right)

        ax.set_xlim(-R * 1.15, R * 1.15)
        ax.set_ylim(-0.05 * H, 1.10 * H)

    @classmethod
    def plot_velocity_streamlines(
        cls,
        sim_result: ReactorSimulationResult,
        field_2d: FlowField2DResult,
        ax: Optional[Axes] = None,
        show_dead_zones: bool = True,
    ) -> Axes:
        """Render in-plane circulation speed contours with overlaid streamlines and dead zones."""
        if ax is None:
            _, ax = plt.subplots(figsize=(7, 8), dpi=150)

        x_1d = field_2d.x_grid[0, :]
        z_1d = field_2d.z_grid[:, 0]

        # Mask velocity magnitude outside liquid domain
        vel_masked = np.ma.masked_where(~field_2d.vessel_mask, field_2d.velocity_mag)

        levels = np.linspace(0.0, max(0.1, float(np.max(vel_masked))), 30)
        cf = ax.contourf(
            field_2d.x_grid,
            field_2d.z_grid,
            vel_masked,
            levels=levels,
            cmap="viridis",
            alpha=0.92,
            zorder=1,
        )
        cbar = plt.colorbar(cf, ax=ax, fraction=0.046, pad=0.04)
        cbar.set_label("Circulation Velocity (m/s)", fontsize=9)

        # Streamlines
        ux_stream = field_2d.u_x.copy()
        uz_stream = field_2d.u_z.copy()
        ux_stream[~field_2d.vessel_mask] = 0.0
        uz_stream[~field_2d.vessel_mask] = 0.0

        try:
            ax.streamplot(
                x_1d,
                z_1d,
                ux_stream,
                uz_stream,
                color="white",
                linewidth=0.9,
                density=1.2,
                arrowsize=0.8,
                zorder=2,
            )
        except Exception:
            pass

        # Dead zones highlight
        if show_dead_zones and np.any(field_2d.dead_zone_mask):
            ax.contourf(
                field_2d.x_grid,
                field_2d.z_grid,
                field_2d.dead_zone_mask.astype(float),
                levels=[0.5, 1.5],
                colors=["#E53E3E"],
                alpha=0.35,
                hatches=["//"],
                zorder=3,
            )

        cls._draw_reactor_anatomy(ax, sim_result, field_2d)

        dz_pct = field_2d.dead_zone_fraction * 100.0
        ax.set_title(f"Velocity & Streamlines (Dead Zones: {dz_pct:.1f}%)", fontsize=11, fontweight="bold")
        ax.set_xlabel("Radius x (m)", fontsize=10)
        ax.set_ylabel("Height z (m)", fontsize=10)
        ax.set_aspect("equal")

        return ax

    @classmethod
    def plot_shear_and_vectors(
        cls,
        sim_result: ReactorSimulationResult,
        field_2d: FlowField2DResult,
        ax: Optional[Axes] = None,
    ) -> Axes:
        """Render spatial shear rate heatmap with overlaid velocity vector quiver."""
        if ax is None:
            _, ax = plt.subplots(figsize=(7, 8), dpi=150)

        shear_masked = np.ma.masked_where(~field_2d.vessel_mask, field_2d.shear_rate_s_inv)
        max_shear = max(1.0, float(np.max(shear_masked)))
        levels = np.linspace(0.0, max_shear, 30)

        cf = ax.contourf(
            field_2d.x_grid,
            field_2d.z_grid,
            shear_masked,
            levels=levels,
            cmap="plasma",
            alpha=0.92,
            zorder=1,
        )
        cbar = plt.colorbar(cf, ax=ax, fraction=0.046, pad=0.04)
        cbar.set_label("Shear Rate γ̇ (s⁻¹)", fontsize=9)

        # Subsampled quiver
        step = 6
        qx = field_2d.x_grid[::step, ::step]
        qz = field_2d.z_grid[::step, ::step]
        qu = field_2d.u_x[::step, ::step].copy()
        qv = field_2d.u_z[::step, ::step].copy()
        qmask = field_2d.vessel_mask[::step, ::step]

        speed = np.sqrt(qu ** 2 + qv ** 2)
        speed_safe = np.where(speed == 0.0, 1.0, speed)
        u_max = float(np.max(field_2d.velocity_mag))
        scale_factor = (np.clip(speed / u_max, 0.0, 1.0)) ** 0.45 if u_max > 1e-6 else 1.0
        qu_scaled = np.where(qmask, (qu / speed_safe) * scale_factor, 0.0)
        qv_scaled = np.where(qmask, (qv / speed_safe) * scale_factor, 0.0)

        ax.quiver(
            qx,
            qz,
            qu_scaled,
            qv_scaled,
            color="white",
            alpha=0.85,
            scale=28,
            width=0.0035,
            zorder=2,
        )

        cls._draw_reactor_anatomy(ax, sim_result, field_2d)

        ax.set_title("Hydrodynamic Shear Rate & Vectors", fontsize=11, fontweight="bold")
        ax.set_xlabel("Radius x (m)", fontsize=10)
        ax.set_ylabel("Height z (m)", fontsize=10)
        ax.set_aspect("equal")

        return ax

    @classmethod
    def plot_power_number_curves(
        cls,
        sim_result: Optional[ReactorSimulationResult] = None,
        ax: Optional[Axes] = None,
    ) -> Axes:
        """Render the classic log-log Power Number chart (N_p vs. Re_i) across all flow regimes."""
        if ax is None:
            _, ax = plt.subplots(figsize=(7, 6), dpi=150)

        re_dense = np.logspace(-0.3, 6.0, 300)

        curves = [
            (ImpellerType.RUSHTON_6_BLADE, "Rushton (6-Blade)", "#D90429"),
            (ImpellerType.PITCHED_BLADE_45, "Pitched-Blade (45°)", "#0077B6"),
            (ImpellerType.MARINE_PROPELLER, "Marine Propeller", "#2A9D8F"),
        ]

        for imp_type, label, col in curves:
            np_baffled = [calc_power_number(re, imp_type, is_baffled=True) for re in re_dense]
            ax.loglog(re_dense, np_baffled, label=f"{label} (baffled)", color=col, linewidth=2.0)

            # Dashed line for unbaffled above Re = 300
            re_unbaffled = re_dense[re_dense >= 300.0]
            np_unbaffled = [calc_power_number(re, imp_type, is_baffled=False) for re in re_unbaffled]
            ax.loglog(re_unbaffled, np_unbaffled, linestyle="--", color=col, linewidth=1.6, alpha=0.85)

        # Regime vertical dividers and shading
        ax.axvspan(0.5, 10.0, color="#E9D8A6", alpha=0.25)
        ax.axvspan(10.0, 10000.0, color="#94D2BD", alpha=0.20)
        ax.axvspan(10000.0, 1e6, color="#0A9396", alpha=0.15)

        ax.text(1.5, 80.0, "Laminar\n(Re < 10)", fontsize=8, color="#5F4B18", fontweight="bold")
        ax.text(80.0, 80.0, "Transitional\n(10 ≤ Re < 10⁴)", fontsize=8, color="#1D5B4D", fontweight="bold")
        ax.text(50000.0, 0.26, "Turbulent\n(Re ≥ 10⁴)", fontsize=8, color="#073B4C", fontweight="bold")

        # Active operating point marker if sim_result is given
        if sim_result is not None:
            stg0 = sim_result.stages[0]
            ax.plot(
                stg0.re_i,
                stg0.np_val,
                marker="o",
                markersize=9,
                markerfacecolor="#FFD166",
                markeredgecolor="#000000",
                markeredgewidth=1.8,
                zorder=10,
                label=f"Stage 1 (Re={stg0.re_i:.0f}, N_p={stg0.np_val:.2f})",
            )

        # Add a custom note for dashed line
        ax.plot([], [], linestyle="--", color="#4A5568", label="Unbaffled (Re ≥ 300)")

        ax.set_xlim(0.5, 1e6)
        ax.set_ylim(0.2, 150.0)
        ax.set_xlabel("Impeller Reynolds Number (Re_i)", fontsize=10)
        ax.set_ylabel("Power Number (N_p)", fontsize=10)
        ax.set_title("BPE Power Number Curve (Doran Fig. 8.11)", fontsize=11, fontweight="bold")
        ax.grid(True, which="both", linestyle=":", alpha=0.6)
        ax.legend(fontsize=7.5, loc="upper right")

        return ax

    @classmethod
    def create_summary_dashboard(
        cls,
        sim_result: ReactorSimulationResult,
        field_2d: Optional[FlowField2DResult] = None,
        save_path: Optional[str] = None,
    ) -> Figure:
        """Create a complete 3-panel bioreactor hydrodynamic and mixing summary dashboard."""
        if field_2d is None:
            field_2d = FlowSolver2D.solve(sim_result)

        fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(18, 6.5), dpi=150)

        cls.plot_velocity_streamlines(sim_result, field_2d, ax=ax1)
        cls.plot_shear_and_vectors(sim_result, field_2d, ax=ax2)
        cls.plot_power_number_curves(sim_result, ax=ax3)

        p0 = sim_result.total_ungassed_power_w
        pg = sim_result.total_gassed_power_w
        vtip = sim_result.max_tip_speed_m_s
        lambda_min = sim_result.lambda_k_min_um
        theta = sim_result.mixing_time_95_s
        kla = sim_result.kla_h_inv
        dz_pct = field_2d.dead_zone_fraction * 100.0

        fig.suptitle(
            f"BioMix-STR Stirred-Tank Bioreactor Hydrodynamic & Mass Transfer Dashboard\n"
            f"P₀ = {p0:.1f} W | P_g = {pg:.1f} W | v_tip = {vtip:.2f} m/s | "
            f"λ_K,min = {lambda_min:.1f} µm | θ_95 = {theta:.1f} s | k_L a = {kla:.1f} h⁻¹ | Dead Zones = {dz_pct:.1f}%",
            fontsize=12,
            fontweight="bold",
            y=0.98,
        )
        plt.tight_layout(rect=[0, 0, 1, 0.93])

        if save_path:
            dir_name = os.path.dirname(save_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            fig.savefig(save_path, dpi=150, bbox_inches="tight")

        return fig
