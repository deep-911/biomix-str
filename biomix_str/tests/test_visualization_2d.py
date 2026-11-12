"""Tests for 2D visualization and dashboard generation module."""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
import pytest

from biomix.engine import HydrodynamicEngine, ReactorSimulationResult
from biomix.flow_solver_2d import FlowField2DResult, FlowSolver2D
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
from biomix.visualization_2d import Plotter2D


@pytest.fixture
def baffled_sim_and_field() -> tuple[ReactorSimulationResult, FlowField2DResult]:
    """Single Rushton turbine in standard baffled ASME dish tank."""
    tank = TankGeometry(
        diameter_m=0.30,
        liquid_height_m=0.30,
        total_height_m=0.45,
        bottom_type=BottomType.ELLIPTICAL_2_1,
        baffle_count=4,
        baffle_width_m=0.025,
        impellers=[
            ImpellerSpec(
                impeller_type=ImpellerType.RUSHTON_6_BLADE,
                diameter_m=0.10,
                clearance_m=0.10,
                flow_direction=FlowDirection.RADIAL,
            )
        ],
    )
    fluid = FluidProperties(density_kg_m3=1000.0, viscosity_pa_s=0.001)
    ops = OperatingConditions(rpm=250.0, aeration_vvm=0.5, cell_type=CellType.MICROBIAL)
    sim = HydrodynamicEngine.simulate(tank, fluid, ops)
    field = FlowSolver2D.solve(sim, nx=40, nz=45)
    return sim, field


@pytest.fixture
def unbaffled_sim_and_field() -> tuple[ReactorSimulationResult, FlowField2DResult]:
    """Dual-impeller (Rushton + PBT) unbaffled tank with hemispherical bottom."""
    tank = TankGeometry(
        diameter_m=0.40,
        liquid_height_m=0.50,
        total_height_m=0.65,
        bottom_type=BottomType.HEMISPHERICAL,
        baffle_count=0,
        impellers=[
            ImpellerSpec(
                impeller_type=ImpellerType.RUSHTON_6_BLADE,
                diameter_m=0.133,
                clearance_m=0.15,
                flow_direction=FlowDirection.RADIAL,
            ),
            ImpellerSpec(
                impeller_type=ImpellerType.PITCHED_BLADE_45,
                diameter_m=0.133,
                clearance_m=0.35,
                flow_direction=FlowDirection.MIXED_AXIAL,
            ),
        ],
    )
    fluid = FluidProperties(density_kg_m3=1000.0, viscosity_pa_s=0.001)
    ops = OperatingConditions(rpm=300.0, aeration_vvm=0.0, cell_type=CellType.MAMMALIAN_CELL)
    sim = HydrodynamicEngine.simulate(tank, fluid, ops)
    field = FlowSolver2D.solve(sim, nx=40, nz=45)
    return sim, field


def test_plot_velocity_streamlines(baffled_sim_and_field):
    """Verify velocity contour and streamline plotting on provided or default axes."""
    sim, field = baffled_sim_and_field
    
    # 1. Automatic axes creation
    fig, ax = plt.subplots(figsize=(6, 7))
    returned_ax = Plotter2D.plot_velocity_streamlines(sim, field, ax=ax, show_dead_zones=True)
    assert returned_ax is ax
    assert len(ax.collections) > 0  # Contourf collections present
    assert len(ax.patches) > 0  # Baffles and shaft patches present
    plt.close(fig)

    # 2. Dead zones hidden
    fig2 = plt.figure()
    ax2 = Plotter2D.plot_velocity_streamlines(sim, field, ax=None, show_dead_zones=False)
    assert isinstance(ax2, Axes)
    plt.close("all")


def test_plot_shear_and_vectors(baffled_sim_and_field):
    """Verify hydrodynamic shear rate heatmap and velocity quiver rendering."""
    sim, field = baffled_sim_and_field
    fig, ax = plt.subplots(figsize=(6, 7))
    ret_ax = Plotter2D.plot_shear_and_vectors(sim, field, ax=ax)
    assert ret_ax is ax
    assert len(ax.collections) > 0
    # Check that quiver plot artist or contours were added
    assert len(ax.artists) > 0 or len(ax.collections) > 0
    plt.close(fig)


def test_plot_power_number_curves(baffled_sim_and_field):
    """Verify BPE N_p vs. Re_i log-log chart and operating point marker."""
    sim, _ = baffled_sim_and_field

    # With sim_result (operating point plotted)
    fig, ax = plt.subplots(figsize=(6, 5))
    ret_ax = Plotter2D.plot_power_number_curves(sim_result=sim, ax=ax)
    assert ret_ax is ax
    assert len(ax.lines) >= 4  # 3 baffled curves + unbaffled dashed lines + op point
    plt.close(fig)

    # Without sim_result
    fig2, ax2 = plt.subplots(figsize=(6, 5))
    ret_ax2 = Plotter2D.plot_power_number_curves(sim_result=None, ax=ax2)
    assert ret_ax2 is ax2
    assert len(ax2.lines) >= 3
    plt.close(fig2)


def test_create_summary_dashboard_baffled(baffled_sim_and_field, tmp_path: Path):
    """Test full 3-panel dashboard generation and disk saving for baffled reactor."""
    sim, field = baffled_sim_and_field
    out_file = tmp_path / "subfolder" / "baffled_dashboard.png"

    fig = Plotter2D.create_summary_dashboard(sim, field, save_path=str(out_file))
    assert isinstance(fig, Figure)
    assert len(fig.axes) >= 3  # 3 main subplots + colorbars
    assert out_file.exists()
    assert out_file.stat().st_size > 20000  # Non-trivial PNG file size (>20 KB)
    plt.close(fig)


def test_create_summary_dashboard_unbaffled_auto_field(unbaffled_sim_and_field, tmp_path: Path):
    """Test dashboard generation when field_2d is None (triggers automatic FlowSolver2D)."""
    sim, _ = unbaffled_sim_and_field
    out_file = tmp_path / "unbaffled_dashboard.png"

    fig = Plotter2D.create_summary_dashboard(sim, field_2d=None, save_path=str(out_file))
    assert isinstance(fig, Figure)
    assert out_file.exists()
    assert out_file.stat().st_size > 20000
    plt.close(fig)


def test_anatomy_all_bottoms_and_impellers(tmp_path: Path):
    """Test anatomy rendering across Flat and Marine propeller configurations."""
    tank = TankGeometry(
        diameter_m=0.35,
        liquid_height_m=0.35,
        total_height_m=0.50,
        bottom_type=BottomType.FLAT,
        baffle_count=4,
        baffle_width_m=0.03,
        impellers=[
            ImpellerSpec(
                impeller_type=ImpellerType.MARINE_PROPELLER,
                diameter_m=0.12,
                clearance_m=0.12,
                flow_direction=FlowDirection.AXIAL,
            )
        ],
    )
    fluid = FluidProperties(density_kg_m3=1000.0, viscosity_pa_s=0.001)
    ops = OperatingConditions(rpm=350.0, aeration_vvm=0.2, cell_type=CellType.MAMMALIAN_CELL)
    sim = HydrodynamicEngine.simulate(tank, fluid, ops)
    field = FlowSolver2D.solve(sim, nx=30, nz=35)

    fig, ax = plt.subplots()
    Plotter2D._draw_reactor_anatomy(ax, sim, field)
    assert len(ax.patches) > 0
    plt.close(fig)
