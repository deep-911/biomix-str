"""Unit tests for Ansys Fluent (PyFluent) CFD bridge and parity verifier."""

import math
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
import pytest

from biomix.engine import HydrodynamicEngine, ReactorSimulationResult
from biomix.flow_solver_2d import FlowField2DResult, FlowSolver2D
from biomix.fluent_bridge import (
    CFDParityReport,
    FluentCFDVerifier,
    FluentJournalGenerator,
    FluentMRFConfig,
)
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
def pilot_rushton_sim_and_field() -> tuple[ReactorSimulationResult, FlowField2DResult]:
    """Standard pilot 100L Rushton bioreactor simulation and 2D flow field."""
    tank = TankGeometry(
        diameter_m=0.50,
        liquid_height_m=0.65,
        total_height_m=0.85,
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
        name="Microbial Broth",
        density_kg_m3=1020.0,
        viscosity_pa_s=0.0018,
    )
    ops = OperatingConditions(
        rpm=220.0,
        aeration_vvm=0.5,
        cell_type=CellType.MICROBIAL,
    )
    sim = HydrodynamicEngine.run(tank, fluid, ops)
    field = FlowSolver2D.solve(sim, nx=55, nz=65)
    return sim, field


class TestFluentMRFConfig:
    """Test 1: Verification of MRF zone, rotational kinematics, and turbulence model switching."""

    def test_turbulent_regime_mrf_config(self, pilot_rushton_sim_and_field):
        sim, _ = pilot_rushton_sim_and_field
        cfg = FluentMRFConfig.from_simulation(sim, stage_index=0)

        # 1. Kinematics: N = 220 RPM -> N_rps = 3.6667 -> omega = 2 * pi * N_rps ~ 23.038 rad/s
        expected_omega = 2.0 * math.pi * (220.0 / 60.0)
        assert math.isclose(cfg.angular_velocity_rad_s, expected_omega, rel_tol=1e-5)

        # 2. Turbulence model selection: Re_i ~ 39,000 >= 1000 -> realizable-k-epsilon
        assert cfg.turbulence_model == "realizable-k-epsilon"

        # 3. MRF zone sizing: r_mrf ~ 0.65 * D_i
        assert math.isclose(cfg.mrf_zone_radius_m, 0.65 * 0.18, rel_tol=1e-5)

        # 4. Expected shaft torque: M = P_0 / omega
        p0_stage = sim.stages[0].ungassed_power_w
        expected_torque = p0_stage / expected_omega
        assert math.isclose(cfg.expected_shaft_torque_n_m, expected_torque, rel_tol=1e-5)
        assert cfg.expected_shaft_torque_n_m > 0.0

    def test_laminar_and_transitional_turbulence_switching(self):
        tank = TankGeometry(
            diameter_m=0.30,
            liquid_height_m=0.35,
            bottom_type=BottomType.FLAT,
            impellers=[
                ImpellerSpec(
                    impeller_type=ImpellerType.RUSHTON_6_BLADE,
                    diameter_m=0.10,
                    clearance_m=0.10,
                )
            ],
        )

        # Very viscous fluid -> Re < 10 (Laminar)
        laminar_fluid = FluidProperties(density_kg_m3=1200.0, viscosity_pa_s=5.0)
        ops_slow = OperatingConditions(rpm=10.0, aeration_vvm=0.0, cell_type=CellType.MICROBIAL)
        sim_lam = HydrodynamicEngine.run(tank, laminar_fluid, ops_slow)
        cfg_lam = FluentMRFConfig.from_simulation(sim_lam)
        assert cfg_lam.re_i < 10.0
        assert cfg_lam.turbulence_model == "laminar"

        # Moderate fluid -> 10 <= Re < 1000 (Transitional)
        trans_fluid = FluidProperties(density_kg_m3=1000.0, viscosity_pa_s=0.20)
        ops_med = OperatingConditions(rpm=60.0, aeration_vvm=0.0, cell_type=CellType.MICROBIAL)
        sim_trans = HydrodynamicEngine.run(tank, trans_fluid, ops_med)
        cfg_trans = FluentMRFConfig.from_simulation(sim_trans)
        assert 10.0 <= cfg_trans.re_i < 1000.0
        assert cfg_trans.turbulence_model == "k-omega-sst"


class TestFluentJournalGenerator:
    """Test 2: Verification of generated Ansys Fluent TUI journal scripts."""

    def test_generate_tui_journal(self, pilot_rushton_sim_and_field, tmp_path: Path):
        sim, _ = pilot_rushton_sim_and_field
        out_jou = tmp_path / "rushton_pilot.jou"

        journal = FluentJournalGenerator.generate_tui_journal(
            sim,
            output_path=str(out_jou),
            iterations=250,
            stage_index=0,
        )

        assert out_jou.exists()
        assert len(journal) > 500

        # Verify key Fluent TUI commands
        assert "/define/models/solver/pressure-based yes" in journal
        assert "/define/models/viscous/ke-realizable yes" in journal
        assert "broth-liquid" in journal
        assert f"{sim.fluid.density_kg_m3:.4f}" in journal
        assert f"{sim.fluid.viscosity_pa_s:.6f}" in journal
        assert "/solve/set/p-v-coupling 24" in journal  # Coupled solver
        assert "/solve/set/discretization-scheme/pressure 14" in journal  # PRESTO!
        assert "/solve/initialize/hybrid-initialization" in journal
        assert "/solve/iterate 250" in journal


class TestFluentCFDVerifier:
    """Test 3: Verification of CFD parity comparison and plotting."""

    def test_check_local_installation(self):
        info = FluentCFDVerifier.check_local_fluent_installation()
        assert isinstance(info, dict)
        assert info["pyfluent_installed"] is True
        assert info["fluent_exe_exists"] is True
        assert "fluent.exe" in info["fluent_exe_path"]

    def test_compute_cfd_benchmark_comparison(self, pilot_rushton_sim_and_field):
        sim, field = pilot_rushton_sim_and_field
        parity = FluentCFDVerifier.compute_cfd_benchmark_comparison(sim, field)

        assert isinstance(parity, CFDParityReport)
        assert parity.impeller_type == ImpellerType.RUSHTON_6_BLADE
        # N_p parity within 5% for turbulent Rushton turbine
        assert parity.np_parity_pct < 5.0
        # Shaft torque parity within 5%
        assert parity.torque_parity_pct < 5.0
        # Pumping number parity within 5%
        assert parity.nq_parity_pct < 5.0
        # Velocity profile RMSE within 0.15 * v_tip
        assert parity.velocity_profile_rmse < 0.15
        assert parity.is_verified is True

    def test_plot_cfd_parity_comparison(self, pilot_rushton_sim_and_field, tmp_path: Path):
        sim, field = pilot_rushton_sim_and_field
        out_png = tmp_path / "parity_plot.png"

        fig = FluentCFDVerifier.plot_cfd_parity_comparison(sim, field, save_path=str(out_png))
        assert isinstance(fig, Figure)
        assert len(fig.axes) == 2
        assert out_png.exists()
        assert out_png.stat().st_size > 30000
        plt.close(fig)

    def test_run_live_pyfluent_check(self, pilot_rushton_sim_and_field):
        sim, _ = pilot_rushton_sim_and_field
        res = FluentCFDVerifier.run_live_pyfluent_material_check(sim)
        assert res["status"] == "ready"
        assert res["session_configured"] is True
        assert "pyfluent_version" in res
