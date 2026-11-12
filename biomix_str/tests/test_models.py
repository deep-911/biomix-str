"""Unit tests for BioMix-STR physics-validated models."""

import math
import pytest
from pydantic import ValidationError

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


class TestWorkingVolumeCalculations:
    """Test 1: Exact working volume calculations for FLAT, ELLIPTICAL_2_1, and HEMISPHERICAL bottoms."""

    @pytest.fixture
    def base_impeller(self) -> ImpellerSpec:
        return ImpellerSpec(
            impeller_type=ImpellerType.RUSHTON_6_BLADE,
            diameter_m=0.33,
            clearance_m=0.35,
        )

    def test_flat_bottom_volume(self, base_impeller: ImpellerSpec):
        T = 1.0
        H = 1.5
        tank = TankGeometry(
            diameter_m=T,
            liquid_height_m=H,
            bottom_type=BottomType.FLAT,
            impellers=[base_impeller],
        )
        # Flat: (pi / 4) * T^2 * H = (pi / 4) * 1.0 * 1.5 = 0.375 * pi
        expected_vol = (math.pi / 4.0) * (T ** 2) * H
        assert math.isclose(tank.working_volume_m3, expected_vol, rel_tol=1e-9)
        assert math.isclose(tank.working_volume_m3, 0.375 * math.pi, rel_tol=1e-9)
        assert tank.dish_depth_m == 0.0

    def test_elliptical_2_1_bottom_volume(self, base_impeller: ImpellerSpec):
        T = 1.0
        H = 1.5
        tank = TankGeometry(
            diameter_m=T,
            liquid_height_m=H,
            bottom_type=BottomType.ELLIPTICAL_2_1,
            impellers=[base_impeller],
        )
        # 2:1 Elliptical: (pi / 4) * T^2 * (H - T/4) + (pi / 24) * T^3
        # = (pi / 4) * 1.25 + (pi / 24) * 1.0 = (17 / 48) * pi
        expected_cyl = (math.pi / 4.0) * (T ** 2) * (H - T / 4.0)
        expected_dish = (math.pi / 24.0) * (T ** 3)
        expected_vol = expected_cyl + expected_dish
        assert math.isclose(tank.dish_depth_m, 0.25, rel_tol=1e-9)
        assert math.isclose(tank.working_volume_m3, expected_vol, rel_tol=1e-9)
        assert math.isclose(tank.working_volume_m3, (17.0 / 48.0) * math.pi, rel_tol=1e-9)

    def test_hemispherical_bottom_volume(self, base_impeller: ImpellerSpec):
        T = 1.0
        H = 1.5
        tank = TankGeometry(
            diameter_m=T,
            liquid_height_m=H,
            bottom_type=BottomType.HEMISPHERICAL,
            impellers=[base_impeller],
        )
        # Hemispherical: (pi / 4) * T^2 * (H - T/2) + (pi / 12) * T^3
        # = (pi / 4) * 1.0 + (pi / 12) * 1.0 = (4 / 12) * pi = (1 / 3) * pi
        expected_cyl = (math.pi / 4.0) * (T ** 2) * (H - T / 2.0)
        expected_dish = (math.pi / 12.0) * (T ** 3)
        expected_vol = expected_cyl + expected_dish
        assert math.isclose(tank.dish_depth_m, 0.5, rel_tol=1e-9)
        assert math.isclose(tank.working_volume_m3, expected_vol, rel_tol=1e-9)
        assert math.isclose(tank.working_volume_m3, math.pi / 3.0, rel_tol=1e-9)

    def test_liquid_height_must_exceed_dish_depth(self, base_impeller: ImpellerSpec):
        # T = 1.0, Hemispherical dish depth = 0.5 m; liquid height <= 0.5 must fail
        with pytest.raises(ValidationError, match="strictly greater than bottom dish depth"):
            TankGeometry(
                diameter_m=1.0,
                liquid_height_m=0.45,
                bottom_type=BottomType.HEMISPHERICAL,
                impellers=[base_impeller],
            )


class TestImpellerDefaultsAndProperties:
    """Test 2: Auto-population of blade counts, widths, and flow directions."""

    def test_rushton_defaults(self):
        D = 0.35
        C = 0.35
        imp = ImpellerSpec(
            impeller_type=ImpellerType.RUSHTON_6_BLADE,
            diameter_m=D,
            clearance_m=C,
        )
        assert imp.blade_count == 6
        assert math.isclose(imp.blade_width_m, D / 5.0, rel_tol=1e-9)
        assert imp.flow_direction == FlowDirection.RADIAL
        expected_swept = (math.pi / 4.0) * (D ** 2) * (D / 5.0)
        assert math.isclose(imp.swept_volume_m3, expected_swept, rel_tol=1e-9)

    def test_pitched_blade_defaults(self):
        D = 0.40
        C = 0.40
        imp = ImpellerSpec(
            impeller_type=ImpellerType.PITCHED_BLADE_45,
            diameter_m=D,
            clearance_m=C,
        )
        assert imp.blade_count == 4
        assert math.isclose(imp.blade_width_m, D / 5.0, rel_tol=1e-9)
        assert imp.flow_direction == FlowDirection.MIXED_AXIAL

    def test_marine_propeller_defaults(self):
        D = 0.30
        C = 0.30
        imp = ImpellerSpec(
            impeller_type=ImpellerType.MARINE_PROPELLER,
            diameter_m=D,
            clearance_m=C,
        )
        assert imp.blade_count == 3
        assert math.isclose(imp.blade_width_m, D / 4.0, rel_tol=1e-9)
        assert imp.flow_direction == FlowDirection.AXIAL

    def test_explicit_overrides_preserved(self):
        imp = ImpellerSpec(
            impeller_type=ImpellerType.RUSHTON_6_BLADE,
            diameter_m=0.30,
            clearance_m=0.30,
            blade_width_m=0.08,
            blade_count=8,
        )
        assert imp.blade_count == 8
        assert imp.blade_width_m == 0.08


class TestBaffleWidthCalculations:
    """Test 3: Baffle width calculation for standard ratios and unbaffled configuration."""

    @pytest.fixture
    def base_impeller(self) -> ImpellerSpec:
        return ImpellerSpec(
            impeller_type=ImpellerType.RUSHTON_6_BLADE,
            diameter_m=0.40,
            clearance_m=0.40,
        )

    def test_standard_baffle_tenth(self, base_impeller: ImpellerSpec):
        T = 1.2
        tank = TankGeometry(
            diameter_m=T,
            liquid_height_m=1.8,
            baffle_count=4,
            baffle_width_ratio=0.10,
            impellers=[base_impeller],
        )
        assert tank.is_baffled is True
        assert math.isclose(tank.baffle_width_m, 0.12, rel_tol=1e-9)

    def test_standard_baffle_twelfth(self, base_impeller: ImpellerSpec):
        T = 1.2
        tank = TankGeometry(
            diameter_m=T,
            liquid_height_m=1.8,
            baffle_count=4,
            baffle_width_ratio=1.0 / 12.0,
            impellers=[base_impeller],
        )
        assert tank.is_baffled is True
        assert math.isclose(tank.baffle_width_m, 0.10, rel_tol=1e-9)

    def test_unbaffled_tank(self, base_impeller: ImpellerSpec):
        T = 1.2
        tank = TankGeometry(
            diameter_m=T,
            liquid_height_m=1.8,
            baffle_count=0,
            impellers=[base_impeller],
        )
        assert tank.is_baffled is False
        assert tank.baffle_width_m == 0.0

    def test_invalid_baffle_count(self, base_impeller: ImpellerSpec):
        with pytest.raises(ValidationError):
            TankGeometry(
                diameter_m=1.0,
                liquid_height_m=1.5,
                baffle_count=2,  # Baffles must be 0 or 3..8
                impellers=[base_impeller],
            )

    def test_invalid_baffle_width_ratio(self, base_impeller: ImpellerSpec):
        with pytest.raises(ValidationError):
            TankGeometry(
                diameter_m=1.0,
                liquid_height_m=1.5,
                baffle_width_ratio=0.02,  # Must be in [0.05, 0.15]
                impellers=[base_impeller],
            )


class TestMultiImpellerValidation:
    """Test 4: Multi-impeller sorting, separation distance, and liquid boundary checks."""

    def test_automatic_clearance_sorting(self):
        imp_upper = ImpellerSpec(
            impeller_type=ImpellerType.PITCHED_BLADE_45,
            diameter_m=0.33,
            clearance_m=0.85,
        )
        imp_lower = ImpellerSpec(
            impeller_type=ImpellerType.RUSHTON_6_BLADE,
            diameter_m=0.33,
            clearance_m=0.35,
        )
        # Pass in reverse order (upper first, lower second)
        tank = TankGeometry(
            diameter_m=1.0,
            liquid_height_m=1.5,
            impellers=[imp_upper, imp_lower],
        )
        assert tank.impellers[0].clearance_m == 0.35
        assert tank.impellers[0].impeller_type == ImpellerType.RUSHTON_6_BLADE
        assert tank.impellers[1].clearance_m == 0.85
        assert tank.impellers[1].impeller_type == ImpellerType.PITCHED_BLADE_45

    def test_adjacent_impeller_collision_error(self):
        # D_i = 0.33 m; minimum separation is 0.8 * 0.33 = 0.264 m
        imp1 = ImpellerSpec(diameter_m=0.33, clearance_m=0.35)
        imp2 = ImpellerSpec(diameter_m=0.33, clearance_m=0.45)  # delta C = 0.10 m < 0.264 m
        with pytest.raises(ValidationError, match="less than 0.8 \\* D_i"):
            TankGeometry(
                diameter_m=1.0,
                liquid_height_m=1.5,
                impellers=[imp1, imp2],
            )

    def test_impeller_exceeds_liquid_height(self):
        # T = 1.0 m, H = 1.5 m -> max clearance is H - 0.03*T = 1.47 m
        imp = ImpellerSpec(diameter_m=0.33, clearance_m=1.48)
        with pytest.raises(ValidationError, match="violates allowable range"):
            TankGeometry(
                diameter_m=1.0,
                liquid_height_m=1.5,
                impellers=[imp],
            )

    def test_impeller_too_close_to_tank_bottom(self):
        # T = 1.0 m -> min clearance is 0.03*T = 0.03 m
        imp = ImpellerSpec(diameter_m=0.33, clearance_m=0.02)
        with pytest.raises(ValidationError, match="violates allowable range"):
            TankGeometry(
                diameter_m=1.0,
                liquid_height_m=1.5,
                impellers=[imp],
            )


class TestImpellerDiameterRatioRule:
    """Test 5: Validation error when D_i / T is outside [0.15, 0.65]."""

    def test_diameter_too_small(self):
        T = 1.0
        # D_i = 0.12 -> D_i / T = 0.12 < 0.15
        imp = ImpellerSpec(diameter_m=0.12, clearance_m=0.35)
        with pytest.raises(ValidationError, match="outside recommended BPE range \\[0.15, 0.65\\]"):
            TankGeometry(
                diameter_m=T,
                liquid_height_m=1.5,
                impellers=[imp],
            )

    def test_diameter_too_large(self):
        T = 1.0
        # D_i = 0.70 -> D_i / T = 0.70 > 0.65
        imp = ImpellerSpec(diameter_m=0.70, clearance_m=0.35)
        with pytest.raises(ValidationError, match="outside recommended BPE range \\[0.15, 0.65\\]"):
            TankGeometry(
                diameter_m=T,
                liquid_height_m=1.5,
                impellers=[imp],
            )

    def test_diameter_valid_boundaries(self):
        T = 1.0
        imp_min = ImpellerSpec(diameter_m=0.15, clearance_m=0.35)
        tank_min = TankGeometry(diameter_m=T, liquid_height_m=1.5, impellers=[imp_min])
        assert tank_min.impellers[0].diameter_m == 0.15

        imp_max = ImpellerSpec(diameter_m=0.65, clearance_m=0.35)
        tank_max = TankGeometry(diameter_m=T, liquid_height_m=1.5, impellers=[imp_max])
        assert tank_max.impellers[0].diameter_m == 0.65


class TestFluidAndOperatingConditions:
    """Test 6: Fluid properties and operating conditions helpers."""

    def test_fluid_kinematic_viscosity(self):
        fluid = FluidProperties(
            name="Glycerol solution",
            density_kg_m3=1100.0,
            viscosity_pa_s=0.005,
            coalescing_media=False,
        )
        assert math.isclose(fluid.kinematic_viscosity_m2_s, 0.005 / 1100.0, rel_tol=1e-9)

    def test_operating_conditions_rps_and_cells(self):
        op = OperatingConditions(
            rpm=300.0,
            aeration_vvm=1.2,
            cell_type=CellType.MAMMALIAN_CELL,
        )
        assert math.isclose(op.rps, 5.0, rel_tol=1e-9)
        assert op.cell_type.max_tip_speed_m_s == 1.5
        assert op.cell_type.critical_kolmogorov_m == 20e-6
