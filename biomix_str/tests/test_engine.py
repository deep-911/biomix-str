"""Unit tests for BioMix-STR HydrodynamicEngine and simulation orchestration."""

import math
import pytest

from biomix.engine import HydrodynamicEngine, ReactorSimulationResult
from biomix.models import (
    BottomType,
    CellType,
    FlowDirection,
    FluidProperties,
    ImpellerSpec,
    ImpellerType,
    OperatingConditions,
    TankGeometry,
)


@pytest.fixture
def standard_fluid() -> FluidProperties:
    return FluidProperties(
        name="Water/Standard Broth",
        density_kg_m3=1000.0,
        viscosity_pa_s=0.001,
        coalescing_media=False,
    )


@pytest.fixture
def standard_microbial_ops() -> OperatingConditions:
    return OperatingConditions(
        rpm=250.0,
        aeration_vvm=0.5,
        cell_type=CellType.MICROBIAL,
    )


class TestSingleStageRushtonSimulation:
    """Test 1: Single-stage Rushton turbine end-to-end simulation metrics."""

    def test_single_rushton_metrics(
        self,
        standard_fluid: FluidProperties,
        standard_microbial_ops: OperatingConditions,
    ):
        T = 1.0
        H = 1.5
        D = 0.33
        C = 0.33

        tank = TankGeometry(
            diameter_m=T,
            liquid_height_m=H,
            bottom_type=BottomType.ELLIPTICAL_2_1,
            baffle_count=4,
            baffle_width_ratio=0.10,
            impellers=[
                ImpellerSpec(
                    impeller_type=ImpellerType.RUSHTON_6_BLADE,
                    diameter_m=D,
                    clearance_m=C,
                )
            ],
        )

        res = HydrodynamicEngine.run(tank, standard_fluid, standard_microbial_ops)

        # Working volume check for 2:1 elliptical dish: V_L = (17/48) * pi * 1.0^3 ~ 1.1126 m^3
        assert math.isclose(res.working_volume_m3, (17.0 / 48.0) * math.pi, rel_tol=1e-6)

        # Stage 0 metrics
        assert len(res.stages) == 1
        stg = res.stages[0]
        assert stg.stage_index == 0
        assert stg.impeller_type == ImpellerType.RUSHTON_6_BLADE
        assert stg.flow_direction == FlowDirection.RADIAL
        assert stg.spacing_interaction_factor == 1.0
        assert math.isclose(stg.re_i, (1000.0 * (250.0 / 60.0) * (0.33 ** 2)) / 0.001, rel_tol=1e-5)
        assert math.isclose(stg.np_val, 5.0, rel_tol=1e-6)

        # Tip speed: pi * (250/60) * 0.33 ~ 4.3197 m/s
        expected_vtip = math.pi * (250.0 / 60.0) * 0.33
        assert math.isclose(stg.tip_speed_m_s, expected_vtip, rel_tol=1e-5)
        assert math.isclose(res.max_tip_speed_m_s, expected_vtip, rel_tol=1e-5)

        # Power draw checks
        assert stg.ungassed_power_w > 1000.0
        assert 0.30 * stg.ungassed_power_w <= stg.gassed_power_w < stg.ungassed_power_w
        assert math.isclose(res.total_ungassed_power_w, stg.ungassed_power_w, rel_tol=1e-6)
        assert math.isclose(res.total_gassed_power_w, stg.gassed_power_w, rel_tol=1e-6)

        # Mass transfer and mixing
        assert res.kla_h_inv > 100.0  # k_L a > 100 h^-1
        assert res.mixing_time_95_s > 0.0
        assert res.circulation_time_s > 0.0
        assert res.lambda_k_min_um > 0.0
        assert res.lambda_k_avg_um > res.lambda_k_min_um

        # Microbial cell sensitivity: 4.32 m/s <= 7.0 m/s limit -> passed
        assert res.tip_speed_exceeded is False


class TestMultiStageInteractionAndZoning:
    """Test 2: Proximity spacing interaction factor and multi-impeller zoning factors."""

    def test_spacing_interaction_factor(
        self,
        standard_fluid: FluidProperties,
        standard_microbial_ops: OperatingConditions,
    ):
        # D = 0.33 m; 1.5 * D = 0.495 m
        # Case A: Close spacing: C1 = 0.33 m, C2 = 0.60 m -> delta C = 0.27 m < 0.495 m -> factor = 0.85
        tank_close = TankGeometry(
            diameter_m=1.0,
            liquid_height_m=1.5,
            impellers=[
                ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.33, clearance_m=0.33),
                ImpellerSpec(impeller_type=ImpellerType.PITCHED_BLADE_45, diameter_m=0.33, clearance_m=0.60),
            ],
        )
        res_close = HydrodynamicEngine.run(tank_close, standard_fluid, standard_microbial_ops)
        assert res_close.stages[0].spacing_interaction_factor == 1.0
        assert res_close.stages[1].spacing_interaction_factor == 0.85

        # Case B: Well-separated spacing: C1 = 0.33 m, C2 = 0.90 m -> delta C = 0.57 m >= 0.495 m -> factor = 1.0
        tank_well = TankGeometry(
            diameter_m=1.0,
            liquid_height_m=1.5,
            impellers=[
                ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.33, clearance_m=0.33),
                ImpellerSpec(impeller_type=ImpellerType.PITCHED_BLADE_45, diameter_m=0.33, clearance_m=0.90),
            ],
        )
        res_well = HydrodynamicEngine.run(tank_well, standard_fluid, standard_microbial_ops)
        assert res_well.stages[1].spacing_interaction_factor == 1.0

    def test_radial_compartmentalization_warning(
        self,
        standard_fluid: FluidProperties,
        standard_microbial_ops: OperatingConditions,
    ):
        # Dual Rushton setup has two radial impellers: triggers radial compartmentalization warning
        tank_dual_rushton = TankGeometry(
            diameter_m=1.0,
            liquid_height_m=1.5,
            impellers=[
                ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.33, clearance_m=0.33),
                ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.33, clearance_m=0.90),
            ],
        )
        res_dual_rushton = HydrodynamicEngine.run(tank_dual_rushton, standard_fluid, standard_microbial_ops)
        assert any("radial compartmentalization" in w.lower() for w in res_dual_rushton.warnings)


class TestCellSensitivityAndShearWarnings:
    """Test 3: Mammalian cell culture shear and Kolmogorov damage warnings."""

    def test_mammalian_shear_failure_at_high_rpm(self, standard_fluid: FluidProperties):
        # Mammalian culture at 250 RPM with Rushton: v_tip = 4.32 m/s > 1.5 m/s limit
        ops_mammalian = OperatingConditions(
            rpm=250.0,
            aeration_vvm=0.1,
            cell_type=CellType.MAMMALIAN_CELL,
        )
        tank = TankGeometry(
            diameter_m=1.0,
            liquid_height_m=1.5,
            impellers=[
                ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.33, clearance_m=0.33)
            ],
        )
        res = HydrodynamicEngine.run(tank, standard_fluid, ops_mammalian)
        assert res.tip_speed_exceeded is True
        assert any("exceeds recommended limit" in w for w in res.warnings)

    def test_mammalian_gentle_low_shear_pass(self, standard_fluid: FluidProperties):
        # Gentle agitation for CHO cells: 60 RPM with Marine Propeller (D = 0.25 m)
        # v_tip = pi * 1.0 * 0.25 = 0.785 m/s < 1.5 m/s limit
        ops_gentle = OperatingConditions(
            rpm=60.0,
            aeration_vvm=0.05,
            cell_type=CellType.MAMMALIAN_CELL,
        )
        tank = TankGeometry(
            diameter_m=1.0,
            liquid_height_m=1.5,
            impellers=[
                ImpellerSpec(impeller_type=ImpellerType.MARINE_PROPELLER, diameter_m=0.25, clearance_m=0.33)
            ],
        )
        res = HydrodynamicEngine.run(tank, standard_fluid, ops_gentle)
        assert res.tip_speed_exceeded is False
        assert res.kolmogorov_damage_risk is False
        # No tip speed shear warning
        assert not any("exceeds recommended limit" in w for w in res.warnings)


class TestUnbaffledVortexKinematics:
    """Test 4: Unbaffled tank vortex depth and air-entrainment penetration."""

    def test_unbaffled_vortex_depth_and_warning(
        self,
        standard_fluid: FluidProperties,
        standard_microbial_ops: OperatingConditions,
    ):
        # Unbaffled vessel (baffle_count = 0) with high top impeller
        tank_unbaffled = TankGeometry(
            diameter_m=1.0,
            liquid_height_m=1.5,
            baffle_count=0,
            impellers=[
                ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.33, clearance_m=0.33),
                ImpellerSpec(impeller_type=ImpellerType.PITCHED_BLADE_45, diameter_m=0.33, clearance_m=1.20),
            ],
        )
        res = HydrodynamicEngine.run(tank_unbaffled, standard_fluid, standard_microbial_ops)

        assert res.vortex_depth_m > 0.0
        # Check whether warning mentions central vortex
        assert any("vortex" in w.lower() for w in res.warnings)
        if res.vortex_reaches_impeller:
            assert any("penetrates to the topmost impeller" in w for w in res.warnings)
