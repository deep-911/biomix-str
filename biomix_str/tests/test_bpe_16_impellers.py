"""Unit tests for all 16 Bioprocess Engineering (BPE) impellers.

Validates the complete 16-impeller curriculum catalog, hydrodynamic calculation engine,
2D flow solver, 3D CAD mesh generation, and automated engineering suitability advisor.
"""

import pytest
import numpy as np
import pyvista as pv

from biomix.models import (
    BottomType,
    CellType,
    FlowDirection,
    FluidProperties,
    ImpellerClearanceClass,
    ImpellerSpec,
    ImpellerType,
    OperatingConditions,
    TankGeometry,
)
from biomix.bpe_catalog import IMPELLER_BPE_CATALOG, evaluate_bpe_suitability
from biomix.engine import HydrodynamicEngine
from biomix.flow_solver_2d import FlowSolver2D
from biomix.visualization_3d import Visualizer3D


ALL_16_IMPELLERS = list(ImpellerType)


class TestBPE16ImpellerCatalog:
    """Verifies that all 16 impellers are fully registered with complete curriculum data."""

    def test_catalog_has_all_16_impellers(self):
        assert len(ALL_16_IMPELLERS) == 16
        for imp_type in ALL_16_IMPELLERS:
            assert imp_type in IMPELLER_BPE_CATALOG, f"Missing catalog entry for {imp_type}"
            entry = IMPELLER_BPE_CATALOG[imp_type]

            # Structural metadata
            assert entry.impeller_type == imp_type
            assert len(entry.display_name.strip()) > 0
            assert len(entry.model_code.strip()) > 0
            assert isinstance(entry.clearance_class, ImpellerClearanceClass)
            assert isinstance(entry.flow_direction, FlowDirection)

            # Course text content
            assert len(entry.construction.strip()) > 20
            assert len(entry.working_principle.strip()) > 20
            assert len(entry.applications.strip()) > 20
            assert len(entry.limitations_and_advantages.strip()) > 20

            # Viscosity envelopes
            assert entry.viscosity_min_cp >= 0.0
            assert entry.viscosity_max_cp > entry.viscosity_min_cp
            assert len(entry.viscosity_label.strip()) > 0

            # Geometric ratios
            min_r, max_r, std_r = entry.recommended_di_dt_range
            assert 0.1 <= min_r <= std_r <= max_r <= 1.0
            assert "dt_di" in entry.standard_ratios
            assert "hl_di" in entry.standard_ratios
            assert "wi_di" in entry.standard_ratios

            # Hydrodynamic coefficients
            assert entry.turbulent_np > 0.0
            assert entry.laminar_kl > 0.0
            assert entry.pumping_nq > 0.0
            assert entry.metzner_otto_ks > 0.0
            assert entry.flooding_factor > 0.0

    def test_clearance_classes_distribution(self):
        open_turbines = [i for i in ALL_16_IMPELLERS if i.clearance_class == ImpellerClearanceClass.OPEN_TURBINE]
        close_clearance = [i for i in ALL_16_IMPELLERS if i.clearance_class == ImpellerClearanceClass.CLOSE_CLEARANCE]

        assert len(open_turbines) == 11  # 6 radial + 5 axial/mixed
        assert len(close_clearance) == 5  # anchor, helical ribbon, auger, gate, sigma/z-kneader


class TestBPE16SimulationAndCAD:
    """Verifies that HydrodynamicEngine, FlowSolver2D, and Visualizer3D handle all 16 impellers."""

    @pytest.mark.parametrize("impeller_type", ALL_16_IMPELLERS)
    def test_all_16_impellers_end_to_end(self, impeller_type: ImpellerType):
        T = 1.0
        H = 1.5

        if impeller_type.is_close_clearance:
            # Unbaffled tank with high-ratio close-clearance agitator
            D_i = 0.92 * T
            C = 0.08 * T
            baffle_count = 0
            fluid = FluidProperties(
                name="Viscous Biopolymer",
                density_kg_m3=1050.0,
                viscosity_pa_s=10.0,  # 10,000 cP
                coalescing_media=False,
            )
            ops = OperatingConditions(rpm=45.0, aeration_vvm=0.0, cell_type=CellType.MICROBIAL)
        elif impeller_type == ImpellerType.PADDLE_R200:
            D_i = 0.60 * T
            C = 0.30 * T
            baffle_count = 4
            fluid = FluidProperties(
                name="Aqueous Broth",
                density_kg_m3=1000.0,
                viscosity_pa_s=0.05,
                coalescing_media=False,
            )
            ops = OperatingConditions(rpm=120.0, aeration_vvm=0.2, cell_type=CellType.MICROBIAL)
        elif impeller_type == ImpellerType.RETREAT_BLADE:
            D_i = 0.50 * T
            C = 0.08 * T  # Bottom-sweeping retreat blade
            baffle_count = 0  # Unbaffled or retreat baffle
            fluid = FluidProperties(
                name="Chemical/Biopharma Broth",
                density_kg_m3=1000.0,
                viscosity_pa_s=0.01,
                coalescing_media=False,
            )
            ops = OperatingConditions(rpm=150.0, aeration_vvm=0.1, cell_type=CellType.MICROBIAL)
        else:
            # Standard baffled vessel
            D_i = 0.35 * T
            C = 0.35 * T
            baffle_count = 4
            fluid = FluidProperties(
                name="Water Broth",
                density_kg_m3=1000.0,
                viscosity_pa_s=0.001,
                coalescing_media=False,
            )
            ops = OperatingConditions(rpm=250.0, aeration_vvm=0.5, cell_type=CellType.MICROBIAL)

        tank = TankGeometry(
            diameter_m=T,
            liquid_height_m=H,
            bottom_type=BottomType.ELLIPTICAL_2_1,
            baffle_count=baffle_count,
            baffle_width_ratio=0.10,
            impellers=[
                ImpellerSpec(
                    impeller_type=impeller_type,
                    diameter_m=D_i,
                    clearance_m=C,
                )
            ],
        )

        # 1. HydrodynamicEngine calculation
        engine = HydrodynamicEngine()
        sim_result = engine.run(tank, fluid, ops)

        assert sim_result.total_ungassed_power_w > 0.0
        assert sim_result.mixing_time_95_s > 0.0
        assert len(sim_result.stages) == 1
        stage = sim_result.stages[0]
        assert stage.ungassed_power_w > 0.0
        assert stage.re_i > 0.0
        assert stage.np_val > 0.0
        assert stage.pumping_rate_m3_s > 0.0

        # 2. FlowSolver2D velocity and shear field calculation
        flow_sol = FlowSolver2D.solve(sim_result, nx=31, nz=45)

        assert flow_sol.total_speed.shape == (45, 31)
        assert flow_sol.shear_rate_s_inv.shape == (45, 31)
        assert 0.0 <= flow_sol.dead_zone_fraction <= 1.0
        assert np.all(np.isfinite(flow_sol.total_speed[flow_sol.vessel_mask]))

        # 3. Visualizer3D CAD procedural meshes
        vis = Visualizer3D()
        cad_meshes = vis.build_reactor_cad_meshes(tank)

        assert "shaft_and_impellers" in cad_meshes
        imp_mesh = cad_meshes["shaft_and_impellers"]
        assert isinstance(imp_mesh, pv.PolyData)
        assert imp_mesh.n_points > 50, f"Impeller mesh for {impeller_type} has only {imp_mesh.n_points} points"

        assert "vessel_shell" in cad_meshes
        vessel_mesh = cad_meshes["vessel_shell"]
        assert vessel_mesh.n_points > 50


class TestBPESuitabilityAdvisor:
    """Verifies that evaluate_bpe_suitability flags physical, geometric, and hydrodynamic mismatches."""

    def test_marine_propeller_high_viscosity_warning(self):
        # Marine propeller limit is 200 cP; test with 5,000 cP (5.0 Pa·s)
        tank = TankGeometry(
            diameter_m=1.0,
            liquid_height_m=1.5,
            bottom_type=BottomType.ELLIPTICAL_2_1,
            baffle_count=4,
            baffle_width_ratio=0.10,
            impellers=[
                ImpellerSpec(
                    impeller_type=ImpellerType.MARINE_PROPELLER,
                    diameter_m=0.33,
                    clearance_m=0.33,
                )
            ],
        )
        fluid = FluidProperties(
            name="Viscous Slurry",
            density_kg_m3=1000.0,
            viscosity_pa_s=5.0,  # 5,000 cP >> 200 cP limit
        )
        ops = OperatingConditions(rpm=200.0, cell_type=CellType.MICROBIAL)

        alerts = evaluate_bpe_suitability(tank, fluid, ops)
        visc_warnings = [a for a in alerts if a["code"] == "ENG_VISCOSITY_EXCEEDED"]
        assert len(visc_warnings) == 1
        assert "200 cP" in visc_warnings[0]["message"]
        assert "5,000" in visc_warnings[0]["message"]

    def test_anchor_in_baffled_tank_warning(self):
        # Anchor operates in unbaffled vessels; test in baffled vessel
        tank = TankGeometry(
            diameter_m=1.0,
            liquid_height_m=1.2,
            bottom_type=BottomType.ELLIPTICAL_2_1,
            baffle_count=4,
            baffle_width_ratio=0.10,
            impellers=[
                ImpellerSpec(
                    impeller_type=ImpellerType.ANCHOR,
                    diameter_m=0.92,
                    clearance_m=0.06,
                )
            ],
        )
        fluid = FluidProperties(
            name="Xanthan Slurry",
            density_kg_m3=1050.0,
            viscosity_pa_s=15.0,  # 15,000 cP
        )
        ops = OperatingConditions(rpm=30.0, cell_type=CellType.MICROBIAL)

        alerts = evaluate_bpe_suitability(tank, fluid, ops)
        baffle_warnings = [a for a in alerts if a["code"] == "ENG_BAFFLE_OBSTRUCTION"]
        assert len(baffle_warnings) == 1
        assert "UNBAFFLED" in baffle_warnings[0]["message"]

    def test_anchor_above_viscosity_ceiling_warning(self):
        # Anchor ceiling is 50,000 cP; test with 60,000 cP (60.0 Pa·s)
        tank = TankGeometry(
            diameter_m=1.0,
            liquid_height_m=1.2,
            bottom_type=BottomType.ELLIPTICAL_2_1,
            baffle_count=0,
            baffle_width_ratio=0.10,
            impellers=[
                ImpellerSpec(
                    impeller_type=ImpellerType.ANCHOR,
                    diameter_m=0.92,
                    clearance_m=0.06,
                )
            ],
        )
        fluid = FluidProperties(
            name="Ultra-Viscous Broth",
            density_kg_m3=1050.0,
            viscosity_pa_s=60.0,  # 60,000 cP > 50,000 cP ceiling
        )
        ops = OperatingConditions(rpm=25.0, cell_type=CellType.MICROBIAL)

        alerts = evaluate_bpe_suitability(tank, fluid, ops)
        visc_warnings = [a for a in alerts if a["code"] == "ENG_VISCOSITY_EXCEEDED"]
        assert len(visc_warnings) == 1
        assert "50,000 cP" in visc_warnings[0]["message"]

    def test_anchor_suboptimal_diameter_ratio_warning(self):
        # Anchor standard range is [0.85, 0.98]; test with 0.50
        tank = TankGeometry(
            diameter_m=1.0,
            liquid_height_m=1.2,
            bottom_type=BottomType.ELLIPTICAL_2_1,
            baffle_count=0,
            baffle_width_ratio=0.10,
            impellers=[
                ImpellerSpec(
                    impeller_type=ImpellerType.ANCHOR,
                    diameter_m=0.50,
                    clearance_m=0.10,
                )
            ],
        )
        fluid = FluidProperties(
            name="Resin",
            density_kg_m3=1050.0,
            viscosity_pa_s=10.0,
        )
        ops = OperatingConditions(rpm=30.0, cell_type=CellType.MICROBIAL)

        alerts = evaluate_bpe_suitability(tank, fluid, ops)
        ratio_warnings = [a for a in alerts if a["code"] == "ENG_DIAMETER_RATIO_SUBOPTIMAL"]
        assert len(ratio_warnings) == 1
        assert "0.85" in ratio_warnings[0]["message"]

    def test_shear_sensitive_mammalian_cell_warning(self):
        # Mammalian cells max tip speed is 1.5 m/s; Rushton at 400 RPM with D=0.4m -> v_tip = pi * 400/60 * 0.4 = 8.38 m/s
        tank = TankGeometry(
            diameter_m=1.0,
            liquid_height_m=1.5,
            bottom_type=BottomType.ELLIPTICAL_2_1,
            baffle_count=4,
            baffle_width_ratio=0.10,
            impellers=[
                ImpellerSpec(
                    impeller_type=ImpellerType.RUSHTON_6_BLADE,
                    diameter_m=0.40,
                    clearance_m=0.35,
                )
            ],
        )
        fluid = FluidProperties(name="CHO Broth", density_kg_m3=1000.0, viscosity_pa_s=0.001)
        ops = OperatingConditions(rpm=400.0, cell_type=CellType.MAMMALIAN_CELL)

        alerts = evaluate_bpe_suitability(tank, fluid, ops)
        shear_warnings = [a for a in alerts if a["code"] == "ENG_SHEAR_SENSITIVITY_EXCEEDED"]
        assert len(shear_warnings) == 1
        assert "1.50 m/s" in shear_warnings[0]["message"]
        assert "mammalian" in shear_warnings[0]["message"].lower()

    def test_optimal_configuration_returns_success(self):
        tank = TankGeometry(
            diameter_m=1.0,
            liquid_height_m=1.5,
            bottom_type=BottomType.ELLIPTICAL_2_1,
            baffle_count=4,
            baffle_width_ratio=0.10,
            impellers=[
                ImpellerSpec(
                    impeller_type=ImpellerType.RUSHTON_6_BLADE,
                    diameter_m=0.33,
                    clearance_m=0.33,
                )
            ],
        )
        fluid = FluidProperties(name="E. coli Broth", density_kg_m3=1000.0, viscosity_pa_s=0.001)
        ops = OperatingConditions(rpm=200.0, aeration_vvm=0.5, cell_type=CellType.MICROBIAL)

        alerts = evaluate_bpe_suitability(tank, fluid, ops)
        assert len(alerts) == 1
        assert alerts[0]["level"] == "success"
        assert alerts[0]["code"] == "ENG_CONFIG_OPTIMAL"
