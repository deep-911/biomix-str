"""3D PyVista Bioreactor CAD & 3D Flow Field Visualizer.

Generates interactive, publication-grade 3D visualizations of stirred-tank bioreactors:
- CAD anatomy surface meshes (vessel shell with dish bottoms, baffles, agitator shaft,
  Rushton/PBT/Propeller impellers, sparger ring, and 3D Rankine vortex free surface)
- 3D structured Cartesian flow grid with interpolated velocity vectors, speed, and shear rate
- Off-screen 3D rendering pipeline producing high-resolution ray-traced scene screenshots
- VTK/VTP package exporter for ParaView, Ansys EnSight, and web rendering
"""

from __future__ import annotations

import math
import os
from typing import Dict, Optional, Tuple

import numpy as np
try:
    import pyvista as pv
    pv.OFF_SCREEN = True
except (ImportError, Exception):
    pv = None

from scipy.interpolate import RegularGridInterpolator

from biomix.engine import ReactorSimulationResult
from biomix.flow_solver_2d import FlowField2DResult, FlowSolver2D
from biomix.models import BottomType, ImpellerType, TankGeometry


class Visualizer3D:
    """3D PyVista engineering visualization engine for stirred-tank bioreactors."""

    @classmethod
    def build_reactor_cad_meshes(
        cls,
        tank: TankGeometry,
        free_surface_z: Optional[np.ndarray] = None,
    ) -> Dict[str, pv.PolyData]:
        """Construct individual 3D PolyData CAD meshes for all bioreactor anatomical components.

        Parameters
        ----------
        tank : TankGeometry
            Vessel dimensions, dish head, baffles, and impeller array.
        free_surface_z : Optional[np.ndarray], optional
            1D free-surface elevation profile across vessel width.

        Returns
        -------
        Dict[str, pv.PolyData]
            Dictionary containing 'vessel_shell', 'baffles', 'shaft_and_impellers',
            'sparger_ring', and 'free_surface' PolyData surface meshes.
        """
        if pv is None:
            return {}

        T = tank.diameter_m
        R = T / 2.0
        H = tank.liquid_height_m
        H_total = tank.total_height_m
        dish_depth = tank.dish_depth_m

        cad: Dict[str, pv.PolyData] = {}

        # ---------------------------------------------------------------------
        # 1. Vessel Shell (Dish bottom + cylindrical wall revolved 360 deg)
        # ---------------------------------------------------------------------
        n_r = 25
        n_z = 25
        n_theta = 48

        # Radial dish bottom profile: r in [0, R]
        r_dish = np.linspace(0.0, R, n_r)
        z_dish = np.zeros(n_r)
        for idx, r_val in enumerate(r_dish):
            if tank.bottom_type == BottomType.FLAT:
                z_dish[idx] = 0.0
            elif tank.bottom_type == BottomType.ELLIPTICAL_2_1:
                h_d = T / 4.0
                rad_sq = max(0.0, 1.0 - (r_val / R) ** 2)
                z_dish[idx] = h_d * (1.0 - math.sqrt(rad_sq))
            elif tank.bottom_type == BottomType.HEMISPHERICAL:
                h_d = R
                rad_sq = max(0.0, 1.0 - (r_val / R) ** 2)
                z_dish[idx] = h_d * (1.0 - math.sqrt(rad_sq))

        # Vertical cylindrical wall: r = R, z in [dish_depth, H_total]
        z_wall = np.linspace(dish_depth, H_total, n_z)
        r_wall = np.full(n_z, R)

        # Concatenate full 1D generator profile
        r_profile = np.concatenate([r_dish, r_wall[1:]])
        z_profile = np.concatenate([z_dish, z_wall[1:]])

        # Revolve 360 degrees
        theta = np.linspace(0.0, 2.0 * math.pi, n_theta)
        R_mesh, Theta_mesh = np.meshgrid(r_profile, theta, indexing="ij")
        Z_mesh, _ = np.meshgrid(z_profile, theta, indexing="ij")
        X_shell = R_mesh * np.cos(Theta_mesh)
        Y_shell = R_mesh * np.sin(Theta_mesh)

        shell_grid = pv.StructuredGrid(X_shell, Y_shell, Z_mesh)
        cad["vessel_shell"] = shell_grid.extract_surface(algorithm="dataset_surface")

        # ---------------------------------------------------------------------
        # 2. Baffle Plates & Stationary Draft Tubes
        # ---------------------------------------------------------------------
        baffle_parts = []
        if tank.is_baffled and tank.baffle_count > 0:
            N_b = tank.baffle_count
            W_b = tank.baffle_width_m
            t_b = max(0.003, 0.006 * T)
            h_b = max(0.01, H - dish_depth)
            z_b_mid = dish_depth + h_b / 2.0
            r_b_mid = R - W_b / 2.0

            baffle_0 = pv.Cube(
                center=(r_b_mid, 0.0, z_b_mid),
                x_length=W_b,
                y_length=t_b,
                z_length=h_b,
            )
            for i in range(N_b):
                baffle_parts.append(baffle_0.rotate_z(i * 360.0 / N_b, point=(0.0, 0.0, z_b_mid), inplace=False))

        cad["draft_tube"] = pv.PolyData()

        if baffle_parts:
            cad["baffles"] = baffle_parts[0].merge(baffle_parts[1:]) if len(baffle_parts) > 1 else baffle_parts[0]
        else:
            cad["baffles"] = pv.PolyData()

        # ---------------------------------------------------------------------
        # 3. Central Agitator Shaft & Impeller Silhouettes
        # ---------------------------------------------------------------------
        c_lowest = tank.impellers[0].clearance_m
        r_shaft = max(0.006, 0.025 * T)
        z_shaft_bot = max(0.0, c_lowest - 0.05 * T)
        h_shaft = H_total - z_shaft_bot
        z_shaft_mid = z_shaft_bot + h_shaft / 2.0

        shaft = pv.Cylinder(
            center=(0.0, 0.0, z_shaft_mid),
            direction=(0.0, 0.0, 1.0),
            radius=r_shaft,
            height=h_shaft,
            resolution=32,
        )
        parts_to_merge = [shaft]

        for imp in tank.impellers:
            D_i = imp.diameter_m
            C_k = imp.clearance_m
            W_blade = imp.blade_width_m if imp.blade_width_m is not None else 0.20 * D_i
            # Safety clamp so blades never penetrate below tank floor if low clearance is selected
            if C_k < 0.52 * W_blade and not imp.impeller_type.is_close_clearance:
                W_blade = max(0.01 * D_i, 1.8 * C_k)

            if imp.impeller_type == ImpellerType.RUSHTON_6_BLADE:
                # 1. Rushton R-100: Central disc + 6 flat vertical blades
                disk_r = 0.375 * D_i
                disk_h = max(0.004, 0.018 * D_i)
                disk = pv.Cylinder(center=(0.0, 0.0, C_k), direction=(0.0, 0.0, 1.0), radius=disk_r, height=disk_h, resolution=32)
                parts_to_merge.append(disk)

                blade_len = 0.25 * D_i
                blade_th = max(0.003, 0.015 * D_i)
                r_blade_mid = 0.375 * D_i
                b0 = pv.Cube(center=(r_blade_mid, 0.0, C_k), x_length=blade_len, y_length=blade_th, z_length=W_blade)
                for m in range(6):
                    parts_to_merge.append(b0.rotate_z(m * 60.0, point=(0.0, 0.0, C_k), inplace=False))

            elif imp.impeller_type == ImpellerType.SMITH_CD6:
                # 2. Smith CD-6: Central disc + 6 continuous C-shaped concave semi-cylindrical blades
                disk_r = 0.375 * D_i
                disk_h = max(0.004, 0.018 * D_i)
                disk = pv.Cylinder(center=(0.0, 0.0, C_k), direction=(0.0, 0.0, 1.0), radius=disk_r, height=disk_h, resolution=32)
                parts_to_merge.append(disk)

                n_r = 16
                n_phi = 16
                r_arr = np.linspace(0.25 * D_i, 0.50 * D_i, n_r)
                phi_arr = np.linspace(-math.pi / 2.0, math.pi / 2.0, n_phi)
                R_grid, Phi_grid = np.meshgrid(r_arr, phi_arr, indexing="ij")
                R_cup = 0.5 * W_blade
                t_cup = max(0.003, 0.014 * D_i)
                y_c = R_cup * (1.0 - np.cos(Phi_grid))
                z_c = C_k + R_cup * np.sin(Phi_grid)
                X_cup = np.stack([R_grid, R_grid], axis=-1)
                Y_cup = np.stack([y_c - t_cup / 2.0, y_c + t_cup / 2.0], axis=-1)
                Z_cup = np.stack([z_c, z_c], axis=-1)
                b0 = pv.StructuredGrid(X_cup, Y_cup, Z_cup).extract_surface(algorithm="dataset_surface").triangulate()
                for m in range(6):
                    parts_to_merge.append(b0.rotate_z(m * 60.0, point=(0.0, 0.0, C_k), inplace=False))

            elif imp.impeller_type == ImpellerType.FLAT_BLADE_FBT:
                # 3. Open Flat-Blade Turbine: Central hub + 6 full radial flat blades
                hub_r = 0.08 * D_i
                hub = pv.Cylinder(center=(0.0, 0.0, C_k), direction=(0.0, 0.0, 1.0), radius=hub_r, height=W_blade, resolution=24)
                parts_to_merge.append(hub)

                blade_len = 0.50 * D_i - hub_r
                blade_th = max(0.003, 0.015 * D_i)
                r_blade_mid = hub_r + blade_len / 2.0
                b0 = pv.Cube(center=(r_blade_mid, 0.0, C_k), x_length=blade_len, y_length=blade_th, z_length=W_blade)
                for m in range(6):
                    parts_to_merge.append(b0.rotate_z(m * 60.0, point=(0.0, 0.0, C_k), inplace=False))

            elif imp.impeller_type == ImpellerType.PADDLE_R200:
                # 4. Paddle R-200: Central hub + 2 wide vertical paddle blades (W/Di = 0.25)
                hub_r = 0.08 * D_i
                hub = pv.Cylinder(center=(0.0, 0.0, C_k), direction=(0.0, 0.0, 1.0), radius=hub_r, height=W_blade, resolution=24)
                parts_to_merge.append(hub)

                blade_len = 0.50 * D_i - hub_r
                blade_th = max(0.004, 0.018 * D_i)
                r_blade_mid = hub_r + blade_len / 2.0
                b0 = pv.Cube(center=(r_blade_mid, 0.0, C_k), x_length=blade_len, y_length=blade_th, z_length=W_blade)
                for m in range(2):
                    parts_to_merge.append(b0.rotate_z(m * 180.0, point=(0.0, 0.0, C_k), inplace=False))

            elif imp.impeller_type == ImpellerType.CURVED_BACKSWEPT:
                # 5. Curved Backswept: Central disc + 6 continuous parametric backward-swept arc blades (-50° sweep)
                disk_r = 0.375 * D_i
                disk_h = max(0.004, 0.018 * D_i)
                disk = pv.Cylinder(center=(0.0, 0.0, C_k), direction=(0.0, 0.0, 1.0), radius=disk_r, height=disk_h, resolution=32)
                parts_to_merge.append(disk)

                n_r, n_z = 20, 8
                r_arr = np.linspace(0.20 * D_i, 0.50 * D_i, n_r)
                z_arr = np.linspace(C_k - W_blade / 2.0, C_k + W_blade / 2.0, n_z)
                R_grid, Z_grid = np.meshgrid(r_arr, z_arr, indexing="ij")
                xi = (R_grid - 0.20 * D_i) / max(1e-4, 0.30 * D_i)
                alpha = -0.87 * (xi ** 1.3)  # -50 degrees sweep
                t_b = max(0.003, 0.015 * D_i)
                xc = R_grid * np.cos(alpha)
                yc = R_grid * np.sin(alpha)
                nx = -np.sin(alpha)
                ny = np.cos(alpha)
                X = np.stack([xc - (t_b / 2.0) * nx, xc + (t_b / 2.0) * nx], axis=-1)
                Y = np.stack([yc - (t_b / 2.0) * ny, yc + (t_b / 2.0) * ny], axis=-1)
                Z = np.stack([Z_grid, Z_grid], axis=-1)
                b0 = pv.StructuredGrid(X, Y, Z).extract_surface(algorithm="dataset_surface").triangulate()
                for m in range(6):
                    parts_to_merge.append(b0.rotate_z(m * 60.0, point=(0.0, 0.0, C_k), inplace=False))

            elif imp.impeller_type == ImpellerType.RETREAT_BLADE:
                # 6. Pfaudler Retreat-Blade: Hub + 3 thick backward-retreating blades (-55° sweep) with dish-following lower edge
                hub_r = 0.12 * D_i
                hub = pv.Cylinder(center=(0.0, 0.0, C_k), direction=(0.0, 0.0, 1.0), radius=hub_r, height=W_blade, resolution=24)
                parts_to_merge.append(hub)

                n_r, n_s = 24, 10
                u_arr = np.linspace(0.0, 1.0, n_r)
                s_arr = np.linspace(0.0, 1.0, n_s)
                U_grid, S_grid = np.meshgrid(u_arr, s_arr, indexing="ij")

                r_start = hub_r * 0.96
                r_end = 0.50 * D_i
                r_span = r_end - r_start
                r_c = r_start + U_grid * r_span
                # Polar sweep angle theta(u) = -0.96 * u^1.4 (~ -55 deg sweep)
                theta_c = -0.96 * (U_grid ** 1.4)
                xc = r_c * np.cos(theta_c)
                yc = r_c * np.sin(theta_c)

                # Compute exact 2D unit tangent and perpendicular normal vector to curve (dx/du, dy/du)
                d_theta_du = -0.96 * 1.4 * np.maximum(1e-4, U_grid ** 0.4)
                dx_du = r_span * np.cos(theta_c) - r_c * d_theta_du * np.sin(theta_c)
                dy_du = r_span * np.sin(theta_c) + r_c * d_theta_du * np.cos(theta_c)
                norm_len = np.sqrt(dx_du ** 2 + dy_du ** 2)
                tau_x = dx_du / np.maximum(1e-6, norm_len)
                tau_y = dy_du / np.maximum(1e-6, norm_len)
                # Perpendicular normal (-tau_y, tau_x)
                nx = -tau_y
                ny = tau_x

                t_b = max(0.006, 0.028 * D_i) * (1.0 - 0.20 * U_grid)
                z_bot = C_k - 0.45 * W_blade + 0.35 * W_blade * (1.0 - np.sqrt(np.maximum(0.0, 1.0 - U_grid ** 2)))
                z_top = C_k + 0.50 * W_blade * (1.0 - 0.15 * U_grid)
                Z_surface = z_bot + S_grid * (z_top - z_bot)

                X = np.stack([xc - (t_b / 2.0) * nx, xc + (t_b / 2.0) * nx], axis=-1)
                Y = np.stack([yc - (t_b / 2.0) * ny, yc + (t_b / 2.0) * ny], axis=-1)
                Z = np.stack([Z_surface, Z_surface], axis=-1)
                b0 = pv.StructuredGrid(X, Y, Z).extract_surface(algorithm="dataset_surface").triangulate()
                for m in range(3):
                    parts_to_merge.append(b0.rotate_z(m * 120.0, point=(0.0, 0.0, C_k), inplace=False))

            elif imp.impeller_type == ImpellerType.MARINE_PROPELLER:
                # 7. Marine Propeller JP-3: Machined collar hub + 3 broad cloverleaf/spoon-shaped twisted aerofoil blades
                hub_r = 0.115 * D_i
                hub_h = 0.24 * D_i

                # Machined cylindrical collar hub sleeve
                hub_cyl = pv.Cylinder(
                    center=(0.0, 0.0, C_k),
                    direction=(0.0, 0.0, 1.0),
                    radius=hub_r,
                    height=hub_h,
                    resolution=36,
                )
                # Machined chamfered top collar rim
                collar_rim = pv.Cylinder(
                    center=(0.0, 0.0, C_k + 0.5 * hub_h + 0.012 * D_i),
                    direction=(0.0, 0.0, 1.0),
                    radius=hub_r * 0.94,
                    height=0.024 * D_i,
                    resolution=36,
                )
                # Bottom rounded collar cap
                bot_cap = pv.Cylinder(
                    center=(0.0, 0.0, C_k - 0.5 * hub_h - 0.005 * D_i),
                    direction=(0.0, 0.0, 1.0),
                    radius=hub_r * 0.93,
                    height=0.010 * D_i,
                    resolution=36,
                )
                parts_to_merge.extend([hub_cyl, collar_rim, bot_cap])

                # 3 broad spoon-shaped twisted blades
                n_span = 30
                n_chord = 26
                u_arr = np.linspace(0.0, 1.0, n_span)
                v_arr = np.linspace(-1.0, 1.0, n_chord)
                U, V = np.meshgrid(u_arr, v_arr, indexing="ij")

                # Radial span with smooth elliptical tip contour
                r_hub_attach = hub_r * 0.88
                r_span = r_hub_attach + (0.50 * D_i - r_hub_attach) * U
                tip_round = 0.035 * D_i * (U ** 3.5) * (V ** 2)
                r_actual = np.maximum(r_hub_attach, r_span - tip_round)

                # Broad cloverleaf spoon chord distribution:
                # 0.19 Di at hub root, swelling to 0.44 Di at mid-span, rounding to 0.24 Di at tip
                chord = D_i * (0.19 + 0.25 * np.sin(np.pi * (U ** 0.62)))

                # Progressive pitch angle beta: 48 deg at hub to 23 deg at tip
                beta = np.radians(48.0 - 25.0 * (U ** 0.82))
                skew_angle = np.radians(6.0 * (U ** 1.5))
                s = V * 0.5 * chord

                # Gentle aerodynamic cupping (camber)
                camber = 0.055 * chord * (1.0 - V ** 2)

                # Teardrop hydrofoil thickness
                t_max = 0.095 * chord
                tip_fade = np.sqrt(np.maximum(0.01, 1.0 - (U ** 4) * (V ** 2)))
                t_dist = (t_max * np.sqrt(np.maximum(0.001, 1.0 - V ** 2)) + 0.002 * D_i) * tip_fade

                # Cylindrical helical coordinates:
                theta_tangent = skew_angle + (s * np.cos(beta) - camber * np.sin(beta)) / r_actual
                z_camber = C_k + s * np.sin(beta) + camber * np.cos(beta)

                dz_thick = 0.5 * t_dist * np.cos(beta)
                dtheta_thick = -0.5 * t_dist * np.sin(beta) / r_actual

                theta_top = theta_tangent - dtheta_thick
                z_top = z_camber + dz_thick
                theta_bot = theta_tangent + dtheta_thick
                z_bot = z_camber - dz_thick

                # Convert to Cartesian
                x_top = r_actual * np.cos(theta_top)
                y_top = r_actual * np.sin(theta_top)
                x_bot = r_actual * np.cos(theta_bot)
                y_bot = r_actual * np.sin(theta_bot)

                X = np.stack([x_bot, x_top], axis=-1)
                Y = np.stack([y_bot, y_top], axis=-1)
                Z = np.stack([z_bot, z_top], axis=-1)
                blade_grid = pv.StructuredGrid(X, Y, Z)
                b0 = blade_grid.extract_surface(algorithm="dataset_surface").triangulate()
                for m in range(3):
                    parts_to_merge.append(b0.rotate_z(m * 120.0, point=(0.0, 0.0, C_k), inplace=False))

            elif imp.impeller_type == ImpellerType.PITCHED_BLADE_45:
                # 8. Pitched-Blade Turbine PBT: Central hub + 4 continuous blades angled at 45°
                hub_r = 0.08 * D_i
                hub = pv.Cylinder(center=(0.0, 0.0, C_k), direction=(0.0, 0.0, 1.0), radius=hub_r, height=W_blade, resolution=24)
                parts_to_merge.append(hub)

                blade_len = 0.50 * D_i - hub_r
                blade_th = max(0.003, 0.015 * D_i)
                r_blade_mid = hub_r + blade_len / 2.0
                b0 = pv.Cube(center=(r_blade_mid, 0.0, C_k), x_length=blade_len, y_length=blade_th, z_length=W_blade).rotate_x(
                    45.0, point=(r_blade_mid, 0.0, C_k), inplace=False
                )
                for m in range(4):
                    parts_to_merge.append(b0.rotate_z(m * 90.0, point=(0.0, 0.0, C_k), inplace=False))

            elif imp.impeller_type == ImpellerType.HYDROFOIL_HE3:
                # 9. Chemineer HE-3 / A-310: Hub + 3 cambered blades with bent-ear swept leading edge (Np = 0.29)
                hub_r = 0.08 * D_i
                hub = pv.Cylinder(center=(0.0, 0.0, C_k), direction=(0.0, 0.0, 1.0), radius=hub_r, height=W_blade, resolution=24)
                parts_to_merge.append(hub)

                n_r, n_s = 18, 10
                r_arr = np.linspace(hub_r * 0.95, 0.50 * D_i, n_r)
                s_arr = np.linspace(-0.5, 0.5, n_s)
                R_grid, S_grid = np.meshgrid(r_arr, s_arr, indexing="ij")
                r_norm = (R_grid - hub_r * 0.95) / max(1e-4, 0.50 * D_i - hub_r * 0.95)
                x_sweep = -0.06 * D_i * (r_norm ** 1.8)
                beta = np.radians(34.0 - 20.0 * r_norm)
                chord = (0.22 * D_i) * (1.0 - 0.55 * r_norm) + 0.004 * D_i
                dx = x_sweep + S_grid * chord
                camber_factor = np.where(r_norm > 0.70, 0.08, 0.05)
                camber = camber_factor * chord * (1.0 - 4.0 * (S_grid ** 2))
                t_max = 0.10 * chord
                t_dist = t_max * np.sqrt(np.maximum(0.0, 1.0 - 4.0 * (S_grid ** 2))) + 0.002 * D_i
                dz_bot = camber - t_dist / 2.0
                dz_top = camber + t_dist / 2.0
                y_bot = dx * np.cos(beta) - dz_bot * np.sin(beta)
                z_bot = C_k + dx * np.sin(beta) + dz_bot * np.cos(beta)
                y_top = dx * np.cos(beta) - dz_top * np.sin(beta)
                z_top = C_k + dx * np.sin(beta) + dz_top * np.cos(beta)
                X = np.stack([R_grid, R_grid], axis=-1)
                Y = np.stack([y_bot, y_top], axis=-1)
                Z = np.stack([z_bot, z_top], axis=-1)
                b0 = pv.StructuredGrid(X, Y, Z).extract_surface(algorithm="dataset_surface").triangulate()
                for m in range(3):
                    parts_to_merge.append(b0.rotate_z(m * 120.0, point=(0.0, 0.0, C_k), inplace=False))

            elif imp.impeller_type == ImpellerType.MAXFLO_HIGH_SOLIDITY:
                # 10. Maxflo / A-320: Hub + 4 wide high-solidity fan-shaped cambered hydrofoil blades
                hub_r = 0.10 * D_i
                hub = pv.Cylinder(center=(0.0, 0.0, C_k), direction=(0.0, 0.0, 1.0), radius=hub_r, height=W_blade, resolution=24)
                parts_to_merge.append(hub)

                n_r, n_s = 18, 12
                r_arr = np.linspace(hub_r * 0.95, 0.50 * D_i, n_r)
                s_arr = np.linspace(-0.5, 0.5, n_s)
                R_grid, S_grid = np.meshgrid(r_arr, s_arr, indexing="ij")
                r_norm = (R_grid - hub_r * 0.95) / max(1e-4, 0.50 * D_i - hub_r * 0.95)
                beta = np.radians(36.0 - 16.0 * r_norm)
                chord = (0.26 * D_i) + (0.16 * D_i) * np.sin(0.5 * np.pi * r_norm)
                dx = S_grid * chord
                camber = 0.06 * chord * (1.0 - 4.0 * (S_grid ** 2))
                t_max = 0.12 * chord
                t_dist = t_max * np.sqrt(np.maximum(0.0, 1.0 - 4.0 * (S_grid ** 2))) + 0.003 * D_i
                dz_bot = camber - t_dist / 2.0
                dz_top = camber + t_dist / 2.0
                y_bot = dx * np.cos(beta) - dz_bot * np.sin(beta)
                z_bot = C_k + dx * np.sin(beta) + dz_bot * np.cos(beta)
                y_top = dx * np.cos(beta) - dz_top * np.sin(beta)
                z_top = C_k + dx * np.sin(beta) + dz_top * np.cos(beta)
                X = np.stack([R_grid, R_grid], axis=-1)
                Y = np.stack([y_bot, y_top], axis=-1)
                Z = np.stack([z_bot, z_top], axis=-1)
                b0 = pv.StructuredGrid(X, Y, Z).extract_surface(algorithm="dataset_surface").triangulate()
                for m in range(4):
                    parts_to_merge.append(b0.rotate_z(m * 90.0, point=(0.0, 0.0, C_k), inplace=False))

            elif imp.impeller_type == ImpellerType.INTERMIG_EKATO:
                # 11. EKATO Intermig: 2-stage axial system with slotted dual winglets & slim connector web
                z_stages = [C_k]
                stage_rots = [0.0]
                z_upper = C_k + 0.48 * D_i
                if z_upper < 0.88 * H:
                    z_stages.append(z_upper)
                    stage_rots.append(90.0)

                hub_r = 0.12 * D_i
                t_in = max(0.003, 0.016 * D_i)
                w_in = 0.15 * D_i
                beta_in = np.radians(45.0)

                t_w = max(0.0025, 0.014 * D_i)
                w_w = 0.11 * D_i
                beta_w = np.radians(-45.0)

                for z_stg, stg_rot in zip(z_stages, stage_rots):
                    hub_stg = pv.Cylinder(center=(0.0, 0.0, z_stg), direction=(0.0, 0.0, 1.0), radius=hub_r, height=W_blade * 0.9, resolution=24)
                    parts_to_merge.append(hub_stg)

                    # 1. Inner pitched blade (+45°) from hub to 0.33 Di
                    n_r, n_s = 10, 6
                    r_inner = np.linspace(hub_r * 0.95, 0.33 * D_i, n_r)
                    s_inner = np.linspace(-0.5, 0.5, n_s)
                    R_in, S_in = np.meshgrid(r_inner, s_inner, indexing="ij")
                    dx_in = S_in * w_in
                    y_in = dx_in * np.cos(beta_in)
                    z_in = z_stg + dx_in * np.sin(beta_in)
                    ny_in = -np.sin(beta_in)
                    nz_in = np.cos(beta_in)
                    X_in = np.stack([R_in, R_in], axis=-1)
                    Y_in = np.stack([y_in - (t_in / 2.0) * ny_in, y_in + (t_in / 2.0) * ny_in], axis=-1)
                    Z_in = np.stack([z_in - (t_in / 2.0) * nz_in, z_in + (t_in / 2.0) * nz_in], axis=-1)
                    b_inner = pv.StructuredGrid(X_in, Y_in, Z_in).extract_surface(algorithm="dataset_surface").triangulate()

                    # 2. Outer slotted dual winglets (-45° tilt, separated by open gap)
                    r_wing = np.linspace(0.32 * D_i, 0.50 * D_i, 12)
                    s_wing = np.linspace(-0.5, 0.5, 6)
                    R_w, S_w = np.meshgrid(r_wing, s_wing, indexing="ij")
                    dx_w = S_w * w_w
                    y_w = dx_w * np.cos(beta_w)
                    ny_w = -np.sin(beta_w)
                    nz_w = np.cos(beta_w)

                    # Leading upper winglet (+0.055 Di offset)
                    z_lead = z_stg + (0.055 * D_i) + dx_w * np.sin(beta_w)
                    X_lead = np.stack([R_w, R_w], axis=-1)
                    Y_lead = np.stack([y_w - (t_w / 2.0) * ny_w, y_w + (t_w / 2.0) * ny_w], axis=-1)
                    Z_lead = np.stack([z_lead - (t_w / 2.0) * nz_w, z_lead + (t_w / 2.0) * nz_w], axis=-1)
                    w_top = pv.StructuredGrid(X_lead, Y_lead, Z_lead).extract_surface(algorithm="dataset_surface").triangulate()

                    # Trailing lower winglet (-0.055 Di offset)
                    z_trail = z_stg - (0.055 * D_i) + dx_w * np.sin(beta_w)
                    X_trail = np.stack([R_w, R_w], axis=-1)
                    Y_trail = np.stack([y_w - (t_w / 2.0) * ny_w, y_w + (t_w / 2.0) * ny_w], axis=-1)
                    Z_trail = np.stack([z_trail - (t_w / 2.0) * nz_w, z_trail + (t_w / 2.0) * nz_w], axis=-1)
                    w_bot = pv.StructuredGrid(X_trail, Y_trail, Z_trail).extract_surface(algorithm="dataset_surface").triangulate()

                    # 3. Slim connector web at r = 0.325 Di
                    web = pv.Cube(
                        center=(0.325 * D_i, 0.0, z_stg),
                        x_length=max(0.003, 0.018 * D_i),
                        y_length=0.065 * D_i,
                        z_length=2.0 * 0.055 * D_i + t_w,
                    )

                    arm0 = b_inner.merge([web, w_top, w_bot])
                    arm_stg = arm0.merge(arm0.rotate_z(180.0, point=(0.0, 0.0, z_stg), inplace=False))
                    if stg_rot != 0.0:
                        arm_stg = arm_stg.rotate_z(stg_rot, point=(0.0, 0.0, z_stg), inplace=False)
                    parts_to_merge.append(arm_stg)

            elif imp.impeller_type == ImpellerType.ANCHOR:
                # 12. Anchor: Dish-following U-anchor hugging vertical tank walls & bottom corners with tight elbows
                R_outer = 0.48 * D_i
                z_top = min(0.75 * H, C_k + 0.75 * (H - C_k))
                w_radial = max(0.012, 0.085 * D_i)
                t_tangential = max(0.005, 0.024 * D_i)
                r_elbow = min(0.14 * D_i, R_outer - r_shaft * 1.5)

                # Segment 1: Vertical left blade (from z_top down to C_k + r_elbow at x = -R_outer)
                n_v = 16
                z_v_left = np.linspace(z_top, C_k + r_elbow, n_v)
                x_v_left = np.full(n_v, -R_outer)
                nx_v_left = np.full(n_v, 1.0)
                nz_v_left = np.zeros(n_v)

                # Segment 2: Bottom-left rounded elbow quarter circle (from angle pi to 3*pi/2)
                n_elb = 14
                phi_left = np.linspace(math.pi, 1.5 * math.pi, n_elb)
                xc_left = -(R_outer - r_elbow)
                zc_left = C_k + r_elbow
                x_elb_left = xc_left + r_elbow * np.cos(phi_left)
                z_elb_left = zc_left + r_elbow * np.sin(phi_left)
                nx_elb_left = -np.cos(phi_left)
                nz_elb_left = -np.sin(phi_left)

                # Segment 3: Bottom horizontal / dish-following bar (from -xc_left to +xc_right at z = C_k)
                n_b = 20
                x_bot = np.linspace(-(R_outer - r_elbow), +(R_outer - r_elbow), n_b)
                z_bot = np.full(n_b, C_k)
                nx_bot = np.zeros(n_b)
                nz_bot = np.full(n_b, 1.0)

                # Segment 4: Bottom-right rounded elbow quarter circle (from angle -pi/2 to 0)
                phi_right = np.linspace(-0.5 * math.pi, 0.0, n_elb)
                xc_right = +(R_outer - r_elbow)
                zc_right = C_k + r_elbow
                x_elb_right = xc_right + r_elbow * np.cos(phi_right)
                z_elb_right = zc_right + r_elbow * np.sin(phi_right)
                nx_elb_right = -np.cos(phi_right)
                nz_elb_right = -np.sin(phi_right)

                # Segment 5: Vertical right blade (from C_k + r_elbow up to z_top at x = +R_outer)
                z_v_right = np.linspace(C_k + r_elbow, z_top, n_v)
                x_v_right = np.full(n_v, R_outer)
                nx_v_right = np.full(n_v, -1.0)
                nz_v_right = np.zeros(n_v)

                # Concatenate continuous path (slicing boundaries to avoid duplicates)
                x_path = np.concatenate([x_v_left[:-1], x_elb_left[:-1], x_bot[:-1], x_elb_right[:-1], x_v_right])
                z_path = np.concatenate([z_v_left[:-1], z_elb_left[:-1], z_bot[:-1], z_elb_right[:-1], z_v_right])
                nx_path = np.concatenate([nx_v_left[:-1], nx_elb_left[:-1], nx_bot[:-1], nx_elb_right[:-1], nx_v_right])
                nz_path = np.concatenate([nz_v_left[:-1], nz_elb_left[:-1], nz_bot[:-1], nz_elb_right[:-1], nz_v_right])

                # Sweep blade radial width w_radial along inward normal
                n_w = 4
                w_steps = np.linspace(0.0, w_radial, n_w)
                X_p, W_g = np.meshgrid(x_path, w_steps, indexing="ij")
                Z_p, _ = np.meshgrid(z_path, w_steps, indexing="ij")
                NX_p, _ = np.meshgrid(nx_path, w_steps, indexing="ij")
                NZ_p, _ = np.meshgrid(nz_path, w_steps, indexing="ij")

                X_plane = X_p + W_g * NX_p
                Z_plane = Z_p + W_g * NZ_p

                # Extrude tangential thickness t_tangential in y
                X_u = np.stack([X_plane, X_plane], axis=-1)
                Y_u = np.stack([np.full_like(X_plane, -t_tangential / 2.0), np.full_like(X_plane, t_tangential / 2.0)], axis=-1)
                Z_u = np.stack([Z_plane, Z_plane], axis=-1)

                u_arch_solid = pv.StructuredGrid(X_u, Y_u, Z_u).extract_surface(algorithm="dataset_surface").triangulate()
                parts_to_merge.append(u_arch_solid)

                # Horizontal cylindrical tie-rod at z = 0.40 * H connecting vertical arms to shaft
                z_tie = 0.40 * H
                tie_r = max(0.005, 0.016 * D_i)
                tie_len = 2.0 * R_outer
                tie_rod = pv.Cylinder(center=(0.0, 0.0, z_tie), direction=(1.0, 0.0, 0.0), radius=tie_r, height=tie_len, resolution=24)
                hub_mid = pv.Cylinder(center=(0.0, 0.0, z_tie), direction=(0.0, 0.0, 1.0), radius=r_shaft * 1.35, height=tie_r * 3.0, resolution=24)
                parts_to_merge.extend([tie_rod, hub_mid])

            elif imp.impeller_type == ImpellerType.HELICAL_RIBBON:
                # 13. Double Helical Ribbon: 2 continuous 3D spiral ribbons connected by 3 cylindrical cross-arms to shaft
                h_top = min(0.88 * H, C_k + 0.85 * (H - C_k))
                h_span = max(0.15 * T, h_top - C_k)
                n_turns = 1.5
                theta_total = n_turns * 2.0 * math.pi

                n_th, n_r = 60, 6
                th_arr = np.linspace(0.0, theta_total, n_th)
                r_arr = np.linspace(0.40 * D_i, 0.50 * D_i, n_r)
                TH, R_arr = np.meshgrid(th_arr, r_arr, indexing="ij")
                Z_base = C_k + (TH / theta_total) * h_span
                t_ribbon = max(0.004, 0.020 * D_i)

                X1 = np.stack([R_arr * np.cos(TH), R_arr * np.cos(TH)], axis=-1)
                Y1 = np.stack([R_arr * np.sin(TH), R_arr * np.sin(TH)], axis=-1)
                Z1 = np.stack([Z_base - t_ribbon / 2.0, Z_base + t_ribbon / 2.0], axis=-1)
                ribbon1 = pv.StructuredGrid(X1, Y1, Z1).extract_surface(algorithm="dataset_surface").triangulate()

                TH2 = TH + math.pi
                X2 = np.stack([R_arr * np.cos(TH2), R_arr * np.cos(TH2)], axis=-1)
                Y2 = np.stack([R_arr * np.sin(TH2), R_arr * np.sin(TH2)], axis=-1)
                Z2 = np.stack([Z_base - t_ribbon / 2.0, Z_base + t_ribbon / 2.0], axis=-1)
                ribbon2 = pv.StructuredGrid(X2, Y2, Z2).extract_surface(algorithm="dataset_surface").triangulate()

                r_rod = max(0.003, 0.015 * D_i)
                rod_len = 0.90 * D_i
                z_mid = C_k + 0.5 * h_span
                z_top = C_k + h_span

                rod_bot = pv.Cylinder(center=(0.0, 0.0, C_k), direction=(1.0, 0.0, 0.0), radius=r_rod, height=rod_len, resolution=20)
                rod_mid = pv.Cylinder(center=(0.0, 0.0, z_mid), direction=(0.0, 1.0, 0.0), radius=r_rod, height=rod_len, resolution=20)
                rod_top = pv.Cylinder(center=(0.0, 0.0, z_top), direction=(1.0, 0.0, 0.0), radius=r_rod, height=rod_len, resolution=20)

                hub_r = 1.35 * r_shaft
                h1 = pv.Cylinder(center=(0.0, 0.0, C_k), direction=(0.0, 0.0, 1.0), radius=hub_r, height=r_rod * 3.0, resolution=24)
                h2 = pv.Cylinder(center=(0.0, 0.0, z_mid), direction=(0.0, 0.0, 1.0), radius=hub_r, height=r_rod * 3.0, resolution=24)
                h3 = pv.Cylinder(center=(0.0, 0.0, z_top), direction=(0.0, 0.0, 1.0), radius=hub_r, height=r_rod * 3.0, resolution=24)
                parts_to_merge.extend([ribbon1, ribbon2, rod_bot, rod_mid, rod_top, h1, h2, h3])

            elif imp.impeller_type == ImpellerType.AUGER_SCREW:
                # 14. Helical Auger Screw: High-precision continuous Archimedes screw flight
                # Matching reference: central shaft with 2.0-turn continuous helical flight attached directly to shaft
                r_core = max(r_shaft, 0.10 * D_i)
                R_outer = 0.50 * D_i
                n_turns = 2.0
                pitch = 0.95 * D_i
                h_flight = min(n_turns * pitch, max(0.20 * T, 0.78 * H - C_k))
                pitch_eff = h_flight / n_turns
                z_bot = C_k
                theta_total = n_turns * 2.0 * math.pi

                n_theta = 160
                n_r = 18

                theta = np.linspace(0.0, theta_total, n_theta)
                r = np.linspace(r_core * 0.96, R_outer, n_r)
                TH, R_mesh = np.meshgrid(theta, r, indexing="ij")

                p_bar = pitch_eff / (2.0 * math.pi)
                norm_mag = np.sqrt(R_mesh**2 + p_bar**2)
                nx = (np.sin(TH) * p_bar) / norm_mag
                ny = (-np.cos(TH) * p_bar) / norm_mag
                nz = R_mesh / norm_mag

                # Thickness tapering: 0.032 Di at root to 0.018 Di at outer tip
                t_root = max(0.005, 0.032 * D_i)
                t_tip = max(0.003, 0.018 * D_i)
                T_flight = t_root - (t_root - t_tip) * ((R_mesh - r_core * 0.96) / max(1e-4, R_outer - r_core * 0.96))

                Z_mid = z_bot + (TH / (2.0 * math.pi)) * pitch_eff
                X_top = R_mesh * np.cos(TH) + 0.5 * T_flight * nx
                Y_top = R_mesh * np.sin(TH) + 0.5 * T_flight * ny
                Z_top = Z_mid + 0.5 * T_flight * nz

                X_bot = R_mesh * np.cos(TH) - 0.5 * T_flight * nx
                Y_bot = R_mesh * np.sin(TH) - 0.5 * T_flight * ny
                Z_bot = Z_mid - 0.5 * T_flight * nz

                X_vol = np.stack([X_bot, X_top], axis=-1)
                Y_vol = np.stack([Y_bot, Y_top], axis=-1)
                Z_vol = np.stack([Z_bot, Z_top], axis=-1)

                grid = pv.StructuredGrid(X_vol, Y_vol, Z_vol)
                flight = grid.extract_surface(algorithm="dataset_surface").triangulate().clean()
                flight = flight.compute_normals(auto_orient_normals=True)

                h_core = h_flight + 0.08 * D_i
                z_core_mid = z_bot + h_flight / 2.0
                core_shaft = pv.Cylinder(
                    center=(0.0, 0.0, z_core_mid),
                    direction=(0.0, 0.0, 1.0),
                    radius=r_core,
                    height=h_core,
                    resolution=48,
                ).triangulate().clean()

                parts_to_merge.extend([flight, core_shaft])

            elif imp.impeller_type == ImpellerType.GATE_IMPELLER:
                # 15. Gate Anchor: Dished U-anchor frame with intermediate vertical grid limbs & mid-level tie-bar
                # Exactly matches standard industrial Gate Anchor reference:
                # - Outer U-anchor limbs and sweeping dished bottom contour hugging tank floor
                # - Two intermediate vertical limbs (grid bars) rising from bottom contour to open top
                # - Mid-height horizontal tie-bar connecting upper hub to intermediate limbs only
                # - Lower hub and upper hub on central shaft
                # - Top is completely open across all 4 vertical limbs (no top crossbar)
                R_outer = 0.48 * D_i
                z_bot = C_k
                z_top = min(0.80 * H, C_k + 0.75 * (H - C_k))
                if imp.blade_width_m is not None and imp.blade_width_m > 0:
                    z_top = min(0.85 * H, C_k + imp.blade_width_m)
                h_gate = max(0.15 * T, z_top - z_bot)

                bar_w = max(0.008, 0.035 * D_i)      # In-plane bar width
                bar_t = max(0.005, 0.022 * D_i)      # Out-of-plane thickness
                r_elbow = min(0.14 * D_i, 0.30 * R_outer)
                delta_dish = 0.030 * D_i              # Dish curvature rise

                # Segment 1: Left vertical wall limb (from z_top down to z_elbow_top)
                n_v = 24
                z_elbow_top = C_k + r_elbow + delta_dish
                z_v_left = np.linspace(z_top, z_elbow_top, n_v)
                x_v_left = np.full(n_v, -R_outer)
                nx_v_left = np.full(n_v, 1.0)
                nz_v_left = np.zeros(n_v)

                # Segment 2: Left elbow arc
                n_elb = 16
                phi_left = np.linspace(math.pi, 1.5 * math.pi, n_elb)
                xc_left = -(R_outer - r_elbow)
                zc_left = z_elbow_top
                x_elb_left = xc_left + r_elbow * np.cos(phi_left)
                z_elb_left = zc_left + r_elbow * np.sin(phi_left)
                nx_elb_left = -np.cos(phi_left)
                nz_elb_left = -np.sin(phi_left)

                # Segment 3: Gentle dished bottom bar
                n_b = 30
                xb = np.linspace(-(R_outer - r_elbow), +(R_outer - r_elbow), n_b)
                u_b = xb / (R_outer - r_elbow)
                zb = C_k + delta_dish * (u_b ** 2)
                dz_dx = 2.0 * delta_dish * u_b / (R_outer - r_elbow)
                mag = np.sqrt(1.0 + dz_dx**2)
                nx_b = -dz_dx / mag
                nz_b = 1.0 / mag

                # Segment 4: Right elbow arc
                phi_right = np.linspace(-0.5 * math.pi, 0.0, n_elb)
                xc_right = +(R_outer - r_elbow)
                zc_right = z_elbow_top
                x_elb_right = xc_right + r_elbow * np.cos(phi_right)
                z_elb_right = zc_right + r_elbow * np.sin(phi_right)
                nx_elb_right = -np.cos(phi_right)
                nz_elb_right = -np.sin(phi_right)

                # Segment 5: Right vertical wall limb
                z_v_right = np.linspace(z_elbow_top, z_top, n_v)
                x_v_right = np.full(n_v, R_outer)
                nx_v_right = np.full(n_v, -1.0)
                nz_v_right = np.zeros(n_v)

                # Assemble continuous outer U-frame
                x_path = np.concatenate([x_v_left[:-1], x_elb_left[:-1], xb[:-1], x_elb_right[:-1], x_v_right])
                z_path = np.concatenate([z_v_left[:-1], z_elb_left[:-1], zb[:-1], z_elb_right[:-1], z_v_right])
                nx_path = np.concatenate([nx_v_left[:-1], nx_elb_left[:-1], nx_b[:-1], nx_elb_right[:-1], nx_v_right])
                nz_path = np.concatenate([nz_v_left[:-1], nz_elb_left[:-1], nz_b[:-1], nz_elb_right[:-1], nz_v_right])

                n_w = 4
                w_steps = np.linspace(0.0, bar_w, n_w)
                X_p, W_g = np.meshgrid(x_path, w_steps, indexing="ij")
                Z_p, _ = np.meshgrid(z_path, w_steps, indexing="ij")
                NX_p, _ = np.meshgrid(nx_path, w_steps, indexing="ij")
                NZ_p, _ = np.meshgrid(nz_path, w_steps, indexing="ij")

                X_plane = X_p + W_g * NX_p
                Z_plane = Z_p + W_g * NZ_p

                X_u = np.stack([X_plane, X_plane], axis=-1)
                Y_u = np.stack([np.full_like(X_plane, -bar_t / 2.0), np.full_like(X_plane, bar_t / 2.0)], axis=-1)
                Z_u = np.stack([Z_plane, Z_plane], axis=-1)

                u_frame = pv.StructuredGrid(X_u, Y_u, Z_u).extract_surface(algorithm="dataset_surface").triangulate()

                # Intermediate vertical grid limbs (inner fingers, open at top)
                R_inner = 0.50 * R_outer
                w_inner = bar_w * 0.85
                u_in = R_inner / (R_outer - r_elbow)
                z_in_bot = C_k + delta_dish * (u_in ** 2) + bar_w * 0.75
                h_in = max(0.05, z_top - z_in_bot)
                z_in_mid = z_in_bot + h_in / 2.0

                v_in1 = pv.Cube(center=(-R_inner, 0.0, z_in_mid), x_length=w_inner, y_length=bar_t, z_length=h_in).triangulate()
                v_in2 = pv.Cube(center=(R_inner, 0.0, z_in_mid), x_length=w_inner, y_length=bar_t, z_length=h_in).triangulate()

                # Mid-level tie crossbar connecting inner limbs only
                z_upper = C_k + 0.54 * h_gate
                w_cross = bar_w * 0.85
                upper_bar = pv.Cube(center=(0.0, 0.0, z_upper), x_length=2.0 * R_inner + w_inner, y_length=bar_t, z_length=w_cross).triangulate()

                # Hubs
                hub_r = 1.35 * r_shaft
                h_lower = pv.Cylinder(center=(0.0, 0.0, C_k + bar_w * 0.5), direction=(0.0, 0.0, 1.0), radius=hub_r, height=bar_w * 1.6, resolution=24).triangulate()
                h_upper = pv.Cylinder(center=(0.0, 0.0, z_upper), direction=(0.0, 0.0, 1.0), radius=hub_r, height=w_cross * 1.6, resolution=24).triangulate()

                parts_to_merge.extend([u_frame, v_in1, v_in2, upper_bar, h_lower, h_upper])

            else:  # SIGMA_Z_KNEADER
                # 16. Sigma / Z-Blade Kneader: Dual sweeping 3D helical Sigma saddle blades that twist 90° as they rise
                hub_r = 0.12 * D_i
                hub = pv.Cylinder(center=(0.0, 0.0, C_k + 0.225 * H), direction=(0.0, 0.0, 1.0), radius=hub_r, height=0.45 * H, resolution=24)

                n_u = 32
                u_vals = np.linspace(0.0, 1.0, n_u)
                r_vals = hub_r * 0.95 + (0.48 * D_i - hub_r * 0.95) * (np.sin(np.pi * u_vals) ** 0.75)
                phi_vals = np.radians(90.0) * (u_vals - 0.5)
                z_vals = C_k + u_vals * (0.45 * H)
                t_arm = max(0.008, 0.035 * D_i)
                w_arm = max(0.010, 0.045 * D_i)

                s_vals = np.linspace(-w_arm / 2.0, w_arm / 2.0, 6)
                U_grid, S_grid = np.meshgrid(u_vals, s_vals, indexing="ij")
                R_grid, _ = np.meshgrid(r_vals, s_vals, indexing="ij")
                Phi_grid, _ = np.meshgrid(phi_vals, s_vals, indexing="ij")
                Z_grid, _ = np.meshgrid(z_vals, s_vals, indexing="ij")

                nx = -np.sin(Phi_grid)
                ny = np.cos(Phi_grid)
                X_c = R_grid * np.cos(Phi_grid) + S_grid * nx
                Y_c = R_grid * np.sin(Phi_grid) + S_grid * ny
                X_3d = np.stack([X_c, X_c], axis=-1)
                Y_3d = np.stack([Y_c, Y_c], axis=-1)
                Z_3d = np.stack([Z_grid - t_arm / 2.0, Z_grid + t_arm / 2.0], axis=-1)

                arm1 = pv.StructuredGrid(X_3d, Y_3d, Z_3d).extract_surface(algorithm="dataset_surface").triangulate()
                arm2 = arm1.rotate_z(180.0, point=(0.0, 0.0, C_k + 0.225 * H), inplace=False)
                parts_to_merge.extend([hub, arm1, arm2])

        merged_impellers = parts_to_merge[0].merge(parts_to_merge[1:]) if len(parts_to_merge) > 1 else parts_to_merge[0]
        cad["shaft_and_impellers"] = merged_impellers.clean(tolerance=1e-5)

        # ---------------------------------------------------------------------
        # 4. Sparger (Ring, Open Pipe, or None)
        # ---------------------------------------------------------------------
        is_close_active = any(
            imp.impeller_type.is_close_clearance or imp.impeller_type == ImpellerType.RETREAT_BLADE
            for imp in tank.impellers
        )
        sp_type = getattr(tank, "sparger_type", "ring") or "ring"
        if not is_close_active and sp_type != "none":
            d_lowest = tank.impellers[0].diameter_m
            r_sparger = 0.40 * d_lowest
            z_sparger = 0.45 * c_lowest
            t_sparger = max(0.003, 0.008 * T)

            if sp_type == "pipe":
                # Open Horizontal Pipe Sparger: Radial feed pipe beneath bottom impeller with upward discharge
                pipe_len = 0.82 * R
                p_horiz = pv.Cylinder(
                    center=(pipe_len / 2.0, 0.0, z_sparger),
                    direction=(1.0, 0.0, 0.0),
                    radius=t_sparger * 1.1,
                    height=pipe_len,
                    resolution=24,
                )
                p_nozzle = pv.Cylinder(
                    center=(0.0, 0.0, z_sparger + 0.025 * H),
                    direction=(0.0, 0.0, 1.0),
                    radius=t_sparger * 1.3,
                    height=0.05 * H,
                    resolution=24,
                )
                cad["sparger_ring"] = p_horiz.merge(p_nozzle).clean(tolerance=1e-5)
            else:
                # Standard Torus Ring
                sparger = pv.ParametricTorus(ringradius=r_sparger, crosssectionradius=t_sparger)
                sparger.translate((0.0, 0.0, z_sparger), inplace=True)
                cad["sparger_ring"] = sparger
        else:
            cad["sparger_ring"] = pv.PolyData()

        # ---------------------------------------------------------------------
        # 4b. DO / pH Dip-Tube Sensor Probes (Optional)
        # ---------------------------------------------------------------------
        if getattr(tank, "include_probes", False):
            r_probe = 0.65 * R
            r_tube = max(0.0035, 0.010 * T)
            z_top = 1.05 * H
            z_bot = max(0.08 * H, c_lowest * 0.75)
            probe_h = z_top - z_bot
            z_mid = (z_top + z_bot) / 2.0

            # Probe 1 at +45 degrees (inter-baffle quadrant)
            phi1 = np.radians(45.0)
            p1_x, p1_y = r_probe * np.cos(phi1), r_probe * np.sin(phi1)
            probe1 = pv.Cylinder(center=(p1_x, p1_y, z_mid), direction=(0.0, 0.0, 1.0), radius=r_tube, height=probe_h, resolution=20)
            cap1 = pv.Cylinder(center=(p1_x, p1_y, z_bot), direction=(0.0, 0.0, 1.0), radius=r_tube * 1.35, height=0.035 * H, resolution=20)

            # Probe 2 at +225 degrees (opposite quadrant)
            phi2 = np.radians(225.0)
            p2_x, p2_y = r_probe * np.cos(phi2), r_probe * np.sin(phi2)
            probe2 = pv.Cylinder(center=(p2_x, p2_y, z_mid), direction=(0.0, 0.0, 1.0), radius=r_tube, height=probe_h, resolution=20)
            cap2 = pv.Cylinder(center=(p2_x, p2_y, z_bot), direction=(0.0, 0.0, 1.0), radius=r_tube * 1.35, height=0.035 * H, resolution=20)

            cad["probes"] = probe1.merge([cap1, probe2, cap2]).clean(tolerance=1e-5)
        else:
            cad["probes"] = pv.PolyData()

        # ---------------------------------------------------------------------
        # 4c. External Thermal Cooling Jacket (Optional)
        # ---------------------------------------------------------------------
        if getattr(tank, "include_cooling_jacket", False):
            r_jacket = 1.06 * R
            z_j_bot = 0.04 * H
            z_j_top = 0.92 * H
            j_height = z_j_top - z_j_bot
            j_mid = (z_j_top + z_j_bot) / 2.0
            jacket_cyl = pv.Cylinder(
                center=(0.0, 0.0, j_mid),
                direction=(0.0, 0.0, 1.0),
                radius=r_jacket,
                height=j_height,
                resolution=48,
                capping=False,
            )
            cad["cooling_jacket"] = jacket_cyl.clean(tolerance=1e-5)
        else:
            cad["cooling_jacket"] = pv.PolyData()

        # ---------------------------------------------------------------------
        # 5. Liquid Free Surface (Flat disc or 3D Rankine vortex funnel)
        # ---------------------------------------------------------------------
        if free_surface_z is not None and len(free_surface_z) > 1:
            n_surf_r = 25
            r_surf = np.linspace(0.0, R, n_surf_r)
            x_raw = np.linspace(-R, R, len(free_surface_z))
            # Take positive radial half of free surface
            mask_half = x_raw >= 0.0
            z_surf_r = np.interp(r_surf, x_raw[mask_half], free_surface_z[mask_half])

            R_surf, Theta_surf = np.meshgrid(r_surf, theta, indexing="ij")
            Z_surf, _ = np.meshgrid(z_surf_r, theta, indexing="ij")
            X_surf = R_surf * np.cos(Theta_surf)
            Y_surf = R_surf * np.sin(Theta_surf)

            surf_grid = pv.StructuredGrid(X_surf, Y_surf, Z_surf)
            cad["free_surface"] = surf_grid.extract_surface(algorithm="dataset_surface")
        else:
            cad["free_surface"] = pv.Disc(center=(0.0, 0.0, H), inner=0.0, outer=R, r_res=15, c_res=48)

        return cad

    @classmethod
    def build_3d_flow_grid(
        cls,
        sim_result: ReactorSimulationResult,
        field_2d: FlowField2DResult,
        n_grid: int = 45,
    ) -> pv.StructuredGrid:
        """Interpolate axisymmetric 2D flow field onto a 3D Cartesian StructuredGrid.

        Parameters
        ----------
        sim_result : ReactorSimulationResult
            Output from HydrodynamicEngine containing vessel geometry and metrics.
        field_2d : FlowField2DResult
            2D hydrodynamic cross-sectional solver results.
        n_grid : int, optional
            Number of grid points along x, y, and z dimensions (default: 45).

        Returns
        -------
        pv.StructuredGrid
            3D structured grid populated with 'velocity', 'speed', 'shear_rate',
            and 'in_vessel' point data arrays.
        """
        if pv is None:
            return None

        T = sim_result.tank.diameter_m
        R = T / 2.0
        H = sim_result.tank.liquid_height_m

        # 1. Create 3D Cartesian coordinates
        x_1d = np.linspace(-R, R, n_grid)
        y_1d = np.linspace(-R, R, n_grid)
        z_1d = np.linspace(0.0, H, n_grid)
        X, Y, Z = np.meshgrid(x_1d, y_1d, z_1d, indexing="ij")

        R_3d = np.sqrt(X ** 2 + Y ** 2)
        Theta_3d = np.arctan2(Y, X)

        # 2. Extract 2D field regular coordinates (z_2d, r_2d)
        z_2d = field_2d.z_grid[:, 0]
        x_2d = field_2d.x_grid[0, :]
        half_mask = x_2d >= -1e-9
        r_2d_half = x_2d[half_mask]

        ur_half = field_2d.u_x[:, half_mask]
        uz_half = field_2d.u_z[:, half_mask]
        utheta_half = field_2d.u_theta[:, half_mask]
        speed_half = field_2d.total_speed[:, half_mask]
        shear_half = field_2d.shear_rate_s_inv[:, half_mask]
        mask_half = field_2d.vessel_mask[:, half_mask].astype(float)

        # 3. Build fast 2D regular-grid interpolators
        interp_ur = RegularGridInterpolator((z_2d, r_2d_half), ur_half, bounds_error=False, fill_value=0.0)
        interp_uz = RegularGridInterpolator((z_2d, r_2d_half), uz_half, bounds_error=False, fill_value=0.0)
        interp_utheta = RegularGridInterpolator((z_2d, r_2d_half), utheta_half, bounds_error=False, fill_value=0.0)
        interp_speed = RegularGridInterpolator((z_2d, r_2d_half), speed_half, bounds_error=False, fill_value=0.0)
        interp_shear = RegularGridInterpolator((z_2d, r_2d_half), shear_half, bounds_error=False, fill_value=0.0)
        interp_mask = RegularGridInterpolator((z_2d, r_2d_half), mask_half, bounds_error=False, fill_value=0.0)

        # 4. Interpolate onto 3D sample points (Z, R)
        pts_zr = np.column_stack([Z.ravel(), R_3d.ravel()])
        ur_pts = interp_ur(pts_zr)
        uz_pts = interp_uz(pts_zr)
        utheta_pts = interp_utheta(pts_zr)
        speed_pts = interp_speed(pts_zr)
        shear_pts = interp_shear(pts_zr)
        in_vessel = (interp_mask(pts_zr) >= 0.5) & (R_3d.ravel() <= R)

        # 5. Convert Cylindrical (u_r, u_theta, u_z) to Cartesian (v_x, v_y, v_z)
        theta_flat = Theta_3d.ravel()
        vx = np.where(in_vessel, ur_pts * np.cos(theta_flat) - utheta_pts * np.sin(theta_flat), 0.0)
        vy = np.where(in_vessel, ur_pts * np.sin(theta_flat) + utheta_pts * np.cos(theta_flat), 0.0)
        vz = np.where(in_vessel, uz_pts, 0.0)

        speed_pts = np.where(in_vessel, speed_pts, 0.0)
        shear_pts = np.where(in_vessel, shear_pts, 0.0)
        velocity_3d = np.column_stack([vx, vy, vz])

        # 6. Populate PyVista StructuredGrid
        grid = pv.StructuredGrid(X, Y, Z)
        grid.point_data["velocity"] = velocity_3d
        grid.point_data["speed"] = speed_pts
        grid.point_data["shear_rate"] = shear_pts
        grid.point_data["in_vessel"] = in_vessel.astype(np.uint8)

        return grid

    @classmethod
    def render_3d_scene(
        cls,
        sim_result: ReactorSimulationResult,
        field_2d: Optional[FlowField2DResult] = None,
        save_path: Optional[str] = None,
        window_size: Tuple[int, int] = (1200, 900),
    ) -> np.ndarray:
        """Render high-contrast 3D engineering scene with CAD meshes, 3D streamlines, and metrics.

        Parameters
        ----------
        sim_result : ReactorSimulationResult
            Output from HydrodynamicEngine containing vessel geometry and metrics.
        field_2d : Optional[FlowField2DResult], optional
            2D hydrodynamic cross-sectional solver results (computed if None).
        save_path : Optional[str], optional
            File path to save the rendered screenshot (.png).
        window_size : Tuple[int, int], optional
            Off-screen render window resolution (width, height), default: (1200, 900).

        Returns
        -------
        np.ndarray
            RGB image array of shape (height, width, 3).
        """
        if field_2d is None:
            field_2d = FlowSolver2D.solve(sim_result)

        tank = sim_result.tank
        T = tank.diameter_m
        R = T / 2.0
        H = tank.liquid_height_m

        cad = cls.build_reactor_cad_meshes(tank, field_2d.free_surface_z)
        grid_3d = cls.build_3d_flow_grid(sim_result, field_2d, n_grid=45)

        plotter = pv.Plotter(off_screen=True, window_size=window_size)
        plotter.set_background("#0F172A")  # Deep engineering slate

        # 1. Add CAD meshes with curated materials
        plotter.add_mesh(
            cad["vessel_shell"],
            color="#E2E8F0",
            opacity=0.18,
            smooth_shading=True,
            show_edges=False,
        )

        if cad["baffles"].n_points > 0:
            plotter.add_mesh(
                cad["baffles"],
                color="#64748B",
                opacity=0.65,
                smooth_shading=True,
            )

        if cad["shaft_and_impellers"].n_points > 0:
            plotter.add_mesh(
                cad["shaft_and_impellers"],
                color="#F59E0B",
                metallic=0.45,
                roughness=0.35,
                smooth_shading=True,
            )

        if cad["sparger_ring"].n_points > 0:
            plotter.add_mesh(
                cad["sparger_ring"],
                color="#EF4444",
                opacity=0.85,
                smooth_shading=True,
            )

        if cad.get("probes") and cad["probes"].n_points > 0:
            plotter.add_mesh(
                cad["probes"],
                color="#CBD5E1",
                metallic=0.65,
                roughness=0.25,
                smooth_shading=True,
            )

        if cad.get("cooling_jacket") and cad["cooling_jacket"].n_points > 0:
            plotter.add_mesh(
                cad["cooling_jacket"],
                color="#0284C7",
                opacity=0.18,
                smooth_shading=True,
            )

        if cad["free_surface"].n_points > 0:
            plotter.add_mesh(
                cad["free_surface"],
                color="#38BDF8",
                opacity=0.32,
                smooth_shading=True,
            )

        # 2. Seed 3D Streamlines around each impeller stage
        seed_parts = []
        for imp in tank.impellers:
            D_i = imp.diameter_m
            C_k = imp.clearance_m
            # Disc seed around impeller tip
            s = pv.Disc(
                center=(0.0, 0.0, C_k),
                inner=0.38 * D_i,
                outer=0.55 * D_i,
                r_res=2,
                c_res=16,
            )
            seed_parts.append(s)

        merged_seeds = seed_parts[0].merge(seed_parts[1:]) if len(seed_parts) > 1 else seed_parts[0]

        try:
            streamlines = grid_3d.streamlines_from_source(
                merged_seeds,
                vectors="velocity",
                max_length=1.6 * H,
                integration_direction="both",
            )
            if streamlines.n_points > 0:
                tubes = streamlines.tube(radius=max(0.0015, 0.0035 * T))
                plotter.add_mesh(
                    tubes,
                    scalars="speed",
                    cmap="viridis",
                    smooth_shading=True,
                    scalar_bar_args={
                        "title": "Circulation Speed (m/s)",
                        "color": "white",
                        "title_font_size": 11,
                        "label_font_size": 9,
                        "vertical": True,
                        "position_x": 0.88,
                        "position_y": 0.25,
                        "width": 0.05,
                        "height": 0.50,
                    },
                )
        except Exception:
            pass

        # 3. Add Title Annotation & Metadata Header
        p0 = sim_result.total_ungassed_power_w
        vtip = sim_result.max_tip_speed_m_s
        theta = sim_result.mixing_time_95_s
        dz = field_2d.dead_zone_fraction * 100.0
        imp_name = tank.impellers[0].impeller_type.value.replace("_", " ").upper()

        title_text = (
            f"BioMix-STR 3D Bioreactor Hydrodynamics\n"
            f"{imp_name} | P0 = {p0:.1f} W | v_tip = {vtip:.2f} m/s | "
            f"theta_95 = {theta:.1f} s | Dead Zones = {dz:.1f}%"
        )
        plotter.add_text(title_text, position="upper_left", font_size=10, color="white")

        # 4. Set Camera & Axes
        plotter.add_axes(color="white")
        plotter.view_isometric()
        plotter.reset_camera()
        plotter.camera.zoom(0.85)

        # 5. Render screenshot
        if save_path:
            dir_name = os.path.dirname(save_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            img = plotter.screenshot(save_path, return_img=True)
        else:
            img = plotter.screenshot(return_img=True)

        plotter.close()
        return img

    @classmethod
    def export_vtk_package(
        cls,
        sim_result: ReactorSimulationResult,
        field_2d: FlowField2DResult,
        output_dir: str,
    ) -> Dict[str, str]:
        """Export 3D flow grid (.vtk) and combined CAD anatomy (.vtp) for external CFD inspection.

        Parameters
        ----------
        sim_result : ReactorSimulationResult
            Output from HydrodynamicEngine containing vessel geometry and metrics.
        field_2d : FlowField2DResult
            2D hydrodynamic cross-sectional solver results.
        output_dir : str
            Directory to save .vtk and .vtp package files.

        Returns
        -------
        Dict[str, str]
            File paths for 'flow_field_3d' (.vtk) and 'reactor_anatomy' (.vtp).
        """
        if pv is None:
            return {}

        os.makedirs(output_dir, exist_ok=True)

        # 1. Export 3D structured flow grid
        grid_3d = cls.build_3d_flow_grid(sim_result, field_2d, n_grid=45)
        flow_path = os.path.join(output_dir, "flow_field_3d.vtk")
        grid_3d.save(flow_path)

        # 2. Export combined CAD anatomy as VTP
        cad = cls.build_reactor_cad_meshes(sim_result.tank, field_2d.free_surface_z)
        meshes = [m for m in cad.values() if m.n_points > 0]
        if meshes:
            merged_cad = meshes[0].merge(meshes[1:]) if len(meshes) > 1 else meshes[0]
            cad_path = os.path.join(output_dir, "reactor_anatomy.vtp")
            merged_cad.save(cad_path)
        else:
            cad_path = ""

        return {
            "flow_field_3d": flow_path,
            "reactor_anatomy": cad_path,
        }
