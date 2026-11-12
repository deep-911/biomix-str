"""Unit tests for BioMix-STR 2D axisymmetric hydrodynamic flow field solver."""

import math
import numpy as np
import pytest

from biomix.engine import HydrodynamicEngine
from biomix.flow_solver_2d import FlowField2DResult, FlowSolver2D
from biomix.models import (
    BottomType,
    CellType,
    FluidProperties,
    ImpellerSpec,
    ImpellerType,
    OperatingConditions,
    TankGeometry,
)


@pytest.fixture
def water_fluid() -> FluidProperties:
    return FluidProperties(
        name="Water",
        density_kg_m3=1000.0,
        viscosity_pa_s=0.001,
        coalescing_media=True,
    )


@pytest.fixture
def viscous_fluid() -> FluidProperties:
    return FluidProperties(
        name="Concentrated Xanthan Gum Broth",
        density_kg_m3=1050.0,
        viscosity_pa_s=10.0,  # 10,000 cP
        coalescing_media=False,
    )


@pytest.fixture
def standard_ops() -> OperatingConditions:
    return OperatingConditions(
        rpm=250.0,
        aeration_vvm=0.5,
        cell_type=CellType.MICROBIAL,
    )


class TestGridAndDomainMasking:
    """Test 1: Verification of bottom dish geometries and free-surface boundary masking."""

    def test_bottom_dish_corner_masking(self, water_fluid: FluidProperties, standard_ops: OperatingConditions):
        T = 1.0
        H = 1.5
        R = T / 2.0  # 0.5 m

        # A point very close to the bottom corner: r = 0.95 * R (0.475 m), z = 0.03 m
        # For FLAT bottom: z_bottom = 0.0 -> point is inside
        # For 2:1 ELLIPTICAL: h_d = 0.25 m -> z_bottom(0.475) ~ 0.17 m > 0.03 m -> point is outside
        # For HEMISPHERICAL: h_d = 0.50 m -> z_bottom(0.475) ~ 0.34 m > 0.03 m -> point is outside

        impeller = ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.33, clearance_m=0.35)

        # 1. Flat bottom
        tank_flat = TankGeometry(diameter_m=T, liquid_height_m=H, bottom_type=BottomType.FLAT, impellers=[impeller])
        sim_flat = HydrodynamicEngine.run(tank_flat, water_fluid, standard_ops)
        res_flat = FlowSolver2D.solve(sim_flat, nx=101, nz=151)

        # Find grid indices closest to x = 0.95 * R and z = 0.03 m
        ix_corner = np.argmin(np.abs(res_flat.x_grid[0, :] - 0.95 * R))
        iz_corner = np.argmin(np.abs(res_flat.z_grid[:, 0] - 0.03))

        assert bool(res_flat.vessel_mask[iz_corner, ix_corner]) is True

        # 2. 2:1 Elliptical bottom
        tank_elliptical = TankGeometry(diameter_m=T, liquid_height_m=H, bottom_type=BottomType.ELLIPTICAL_2_1, impellers=[impeller])
        sim_elliptical = HydrodynamicEngine.run(tank_elliptical, water_fluid, standard_ops)
        res_elliptical = FlowSolver2D.solve(sim_elliptical, nx=101, nz=151)

        assert bool(res_elliptical.vessel_mask[iz_corner, ix_corner]) is False

        # 3. Hemispherical bottom
        tank_hemi = TankGeometry(diameter_m=T, liquid_height_m=H, bottom_type=BottomType.HEMISPHERICAL, impellers=[impeller])
        sim_hemi = HydrodynamicEngine.run(tank_hemi, water_fluid, standard_ops)
        res_hemi = FlowSolver2D.solve(sim_hemi, nx=101, nz=151)

        assert bool(res_hemi.vessel_mask[iz_corner, ix_corner]) is False

        # Points outside vessel diameter (r > R) must always be masked out
        assert np.all(res_flat.u_x[~res_flat.vessel_mask] == 0.0)
        assert np.all(res_flat.u_z[~res_flat.vessel_mask] == 0.0)


class TestImpellerFlowFieldTopology:
    """Test 2: Radial flow (Rushton double loop) vs Axial flow (Propeller downward pumping)."""

    def test_rushton_radial_discharge_and_double_loops(
        self,
        water_fluid: FluidProperties,
        standard_ops: OperatingConditions,
    ):
        T = 1.0
        H = 1.5
        R = T / 2.0
        D = 0.35
        C = 0.50

        tank = TankGeometry(
            diameter_m=T,
            liquid_height_m=H,
            impellers=[
                ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=D, clearance_m=C)
            ],
        )
        sim = HydrodynamicEngine.run(tank, water_fluid, standard_ops)
        res = FlowSolver2D.solve(sim, nx=101, nz=151)

        # 1. At impeller centerline z = C, in the discharge stream (r in [0.55 * D, 0.85 * D], x > 0):
        # Radial velocity u_x > 0 and dominates over vertical velocity |u_z|
        iz_plane = np.argmin(np.abs(res.z_grid[:, 0] - C))
        ix_jet = np.argmin(np.abs(res.x_grid[0, :] - 0.70 * D))

        ux_jet = res.u_x[iz_plane, ix_jet]
        uz_jet = res.u_z[iz_plane, ix_jet]

        assert ux_jet > 0.0  # Strongly discharging outward
        assert ux_jet > 3.0 * abs(uz_jet)  # Radially dominated

        # 2. Near outer wall (r = 0.85 * R):
        ix_wall = np.argmin(np.abs(res.x_grid[0, :] - 0.85 * R))

        # Above impeller (z = C + 0.30 m): upper loop flows UPWARD (u_z > 0)
        iz_upper = np.argmin(np.abs(res.z_grid[:, 0] - (C + 0.30)))
        uz_upper_wall = res.u_z[iz_upper, ix_wall]
        assert uz_upper_wall > 0.0

        # Below impeller (z = C - 0.25 m): lower loop flows DOWNWARD (u_z < 0)
        iz_lower = np.argmin(np.abs(res.z_grid[:, 0] - (C - 0.25)))
        uz_lower_wall = res.u_z[iz_lower, ix_wall]
        assert uz_lower_wall < 0.0

    def test_marine_propeller_axial_downward_loop(
        self,
        water_fluid: FluidProperties,
        standard_ops: OperatingConditions,
    ):
        T = 1.0
        H = 1.5
        R = T / 2.0
        D = 0.35
        C = 0.50

        tank = TankGeometry(
            diameter_m=T,
            liquid_height_m=H,
            impellers=[
                ImpellerSpec(impeller_type=ImpellerType.MARINE_PROPELLER, diameter_m=D, clearance_m=C)
            ],
        )
        sim = HydrodynamicEngine.run(tank, water_fluid, standard_ops)
        res = FlowSolver2D.solve(sim, nx=101, nz=151)

        # 1. Directly below the propeller (r = 0.25 * D, z < C): strong downward pumping jet (u_z < 0)
        iz_below = np.argmin(np.abs(res.z_grid[:, 0] - (C - 0.15)))
        ix_shaft = np.argmin(np.abs(res.x_grid[0, :] - 0.25 * D))
        uz_jet = res.u_z[iz_below, ix_shaft]
        assert uz_jet < 0.0

        # 2. Near the outer wall (r = 0.85 * R): upward return flow throughout (u_z > 0)
        ix_wall = np.argmin(np.abs(res.x_grid[0, :] - 0.85 * R))
        uz_wall = res.u_z[iz_below, ix_wall]
        assert uz_wall > 0.0


class TestDeadZoneViscousExpansion:
    """Test 3: Significant expansion of dead zones in highly viscous / laminar fermentation broths."""

    def test_viscosity_increases_dead_zone_fraction(
        self,
        water_fluid: FluidProperties,
        viscous_fluid: FluidProperties,
        standard_ops: OperatingConditions,
    ):
        tank = TankGeometry(
            diameter_m=1.0,
            liquid_height_m=1.5,
            impellers=[
                ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.33, clearance_m=0.40)
            ],
        )

        # Turbulent water simulation
        sim_water = HydrodynamicEngine.run(tank, water_fluid, standard_ops)
        res_water = FlowSolver2D.solve(sim_water, nx=101, nz=151)

        # Viscous laminar broth simulation
        sim_viscous = HydrodynamicEngine.run(tank, viscous_fluid, standard_ops)
        res_viscous = FlowSolver2D.solve(sim_viscous, nx=101, nz=151)

        # Dead-zone fraction must be significantly higher in the viscous broth
        assert res_water.dead_zone_fraction < 0.20
        assert res_viscous.dead_zone_fraction > 0.40
        assert res_viscous.dead_zone_fraction > res_water.dead_zone_fraction * 2.0


class TestUnbaffledVortexSurface:
    """Test 4: Free-surface Rankine vortex formation and tangential swirl enhancement in unbaffled vessels."""

    def test_unbaffled_surface_depression_and_swirl(
        self,
        water_fluid: FluidProperties,
        standard_ops: OperatingConditions,
    ):
        T = 1.0
        H = 1.5

        impeller = ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.35, clearance_m=0.35)

        # Baffled vessel
        tank_baffled = TankGeometry(
            diameter_m=T,
            liquid_height_m=H,
            baffle_count=4,
            impellers=[impeller],
        )
        sim_baffled = HydrodynamicEngine.run(tank_baffled, water_fluid, standard_ops)
        res_baffled = FlowSolver2D.solve(sim_baffled, nx=101, nz=151)

        # Unbaffled vessel
        tank_unbaffled = TankGeometry(
            diameter_m=T,
            liquid_height_m=H,
            baffle_count=0,
            impellers=[impeller],
        )
        sim_unbaffled = HydrodynamicEngine.run(tank_unbaffled, water_fluid, standard_ops)
        res_unbaffled = FlowSolver2D.solve(sim_unbaffled, nx=101, nz=151)

        # 1. Baffled surface is flat at H everywhere
        assert np.allclose(res_baffled.free_surface_z, H)

        # 2. Unbaffled surface has significant central depression at center (x = 0)
        assert res_unbaffled.free_surface_z.min() < H - 0.05
        ix_center = len(res_unbaffled.free_surface_z) // 2
        assert res_unbaffled.free_surface_z[ix_center] < H

        # 3. Average tangential swirl is substantially higher in the unbaffled vessel
        mean_swirl_unbaffled = float(np.mean(res_unbaffled.u_theta[res_unbaffled.vessel_mask]))
        mean_swirl_baffled = float(np.mean(res_baffled.u_theta[res_baffled.vessel_mask]))
        assert mean_swirl_unbaffled > 2.0 * mean_swirl_baffled
