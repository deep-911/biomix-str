"""Unit and integration tests for the Streamlit interactive application (src/biomix/app.py)."""

import pytest

pytest.importorskip('streamlit')
pytest.importorskip('pandas')

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

from biomix.app import (
    PRESETS,
    build_simulation_from_params,
    compare_impeller_topologies,
    load_preset,
)
from biomix.correlations import FlowRegime
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


class TestCoursePresets:
    """Test suite for pedagogical course case presets."""

    def test_all_five_presets_exist(self):
        """Verify all 5 course case presets are defined with required attributes."""
        expected_presets = [
            "1. Standard Baffled Rushton Fermenter (Microbial)",
            "2. Gentle Axial Propeller Bioreactor (Mammalian CHO)",
            "3. Unbaffled Rankine Vortex Tank (Swirl & Air Entrainment)",
            "4. Tall Dual-Impeller Hybrid (Bottom Rushton + Upper PBT)",
            "5. Viscous Mycelial Fermentation (Laminar/Transitional Dead Zones)",
        ]
        assert len(PRESETS) == 5
        for key in expected_presets:
            assert key in PRESETS
            p = PRESETS[key]
            assert "diameter_m" in p
            assert "liquid_height_m" in p
            assert "bottom_type" in p
            assert "stages" in p
            assert len(p["stages"]) >= 1

    def test_load_preset(self):
        """Test preset loader with valid and fallback keys."""
        p1 = load_preset("1. Standard Baffled Rushton Fermenter (Microbial)")
        assert p1["diameter_m"] == 0.50
        assert p1["baffle_count"] == 4

        # Fallback to first preset on unknown key
        p_unknown = load_preset("Nonexistent Preset")
        assert p_unknown["diameter_m"] == 0.50

    def test_all_presets_simulate_cleanly(self):
        """Verify all presets execute end-to-end simulation and 2D solver without failure."""
        for preset_name, params in PRESETS.items():
            tank, fluid, ops, sim_result, field_2d = build_simulation_from_params(params)

            assert sim_result.working_volume_m3 > 0.0
            assert sim_result.total_ungassed_power_w > 0.0
            assert sim_result.total_gassed_power_w > 0.0
            assert field_2d.total_speed.shape == (65, 55)

            if "Microbial" in preset_name:
                assert sim_result.stages[0].flow_regime == FlowRegime.TURBULENT
                assert sim_result.stages[0].re_i > 10000.0

            if "Mammalian" in preset_name:
                assert sim_result.ops.cell_type == CellType.MAMMALIAN_CELL
                assert sim_result.max_tip_speed_m_s < 1.50

            if "Vortex" in preset_name:
                assert tank.is_baffled is False
                assert sim_result.vortex_depth_m > 0.0
                assert any("vortex" in w.lower() for w in sim_result.warnings)

            if "Dual-Impeller" in preset_name:
                assert len(sim_result.stages) == 2
                assert sim_result.stages[0].impeller_type == ImpellerType.RUSHTON_6_BLADE
                assert sim_result.stages[1].impeller_type == ImpellerType.PITCHED_BLADE_45

            if "Viscous" in preset_name:
                assert sim_result.stages[0].flow_regime == FlowRegime.TRANSITIONAL
                assert field_2d.dead_zone_fraction > 0.20


class TestTopologyComparator:
    """Test suite for multi-impeller topology side-by-side benchmark."""

    @pytest.fixture
    def test_reactor(self):
        tank = TankGeometry(
            diameter_m=0.50,
            liquid_height_m=0.65,
            bottom_type=BottomType.ELLIPTICAL_2_1,
            baffle_count=4,
            baffle_width_m=0.05,
            impellers=[
                ImpellerSpec(
                    impeller_type=ImpellerType.RUSHTON_6_BLADE,
                    diameter_m=0.18,
                    clearance_m=0.20,
                    flow_direction=FlowDirection.RADIAL,
                )
            ],
        )
        fluid = FluidProperties(
            name="Water Broth",
            density_kg_m3=1000.0,
            viscosity_pa_s=0.001,
        )
        ops = OperatingConditions(
            rpm=200.0,
            aeration_vvm=0.5,
            cell_type=CellType.MICROBIAL,
        )
        return tank, fluid, ops

    def test_compare_impeller_topologies(self, test_reactor):
        """Verify comparator produces 4 topologies and valid comparison figure."""
        tank, fluid, ops = test_reactor
        df_comp, fig = compare_impeller_topologies(tank, fluid, ops)

        assert isinstance(df_comp, pd.DataFrame)
        assert len(df_comp) == 4
        expected_topologies = [
            "Rushton 6-Blade",
            "Pitched-Blade 45°",
            "Marine Propeller",
            "Dual Hybrid (Rushton + PBT)",
        ]
        assert list(df_comp["Topology"]) == expected_topologies

        # Power hierarchy check: Rushton > PBT > Marine Propeller
        p_rushton = df_comp.loc[df_comp["Topology"] == "Rushton 6-Blade", "Power Pg (W)"].values[0]
        p_pbt = df_comp.loc[df_comp["Topology"] == "Pitched-Blade 45°", "Power Pg (W)"].values[0]
        p_prop = df_comp.loc[df_comp["Topology"] == "Marine Propeller", "Power Pg (W)"].values[0]

        assert p_rushton > p_pbt > p_prop

        # Check figure
        assert isinstance(fig, plt.Figure)
        assert len(fig.axes) == 4
        plt.close(fig)


class TestAppHeadlessExecution:
    """Headless integration test using Streamlit AppTest."""

    def test_app_loads_and_runs_without_exceptions(self):
        """Run app.py headless via Streamlit AppTest and verify 0 exceptions."""
        import os
        app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "biomix", "app.py"))
        if not os.path.isfile(app_path):
            app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "biomix_str", "src", "biomix", "app.py"))
        at = AppTest.from_file(app_path, default_timeout=60)
        at.run()
        assert len(at.exception) == 0, f"App execution failed with: {[e.message for e in at.exception]}"
