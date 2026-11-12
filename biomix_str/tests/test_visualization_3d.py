"""Unit tests for 3D PyVista bioreactor CAD and flow field visualizer."""

import os
from pathlib import Path

import numpy as np
import pytest
import pyvista as pv

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
from biomix.visualization_3d import Visualizer3D


@pytest.fixture
def pilot_rushton_sim_and_field() -> tuple[ReactorSimulationResult, FlowField2DResult]:
    """Single Rushton turbine pilot reactor simulation and 2D field."""
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
    field = FlowSolver2D.solve(sim, nx=45, nz=55)
    return sim, field


@pytest.fixture
def unbaffled_dual_sim_and_field() -> tuple[ReactorSimulationResult, FlowField2DResult]:
    """Unbaffled dual-impeller (Marine + PBT) reactor simulation with Rankine vortex."""
    tank = TankGeometry(
        diameter_m=0.60,
        liquid_height_m=0.80,
        bottom_type=BottomType.HEMISPHERICAL,
        baffle_count=0,
        impellers=[
            ImpellerSpec(
                impeller_type=ImpellerType.MARINE_PROPELLER,
                diameter_m=0.20,
                clearance_m=0.22,
                flow_direction=FlowDirection.AXIAL,
            ),
            ImpellerSpec(
                impeller_type=ImpellerType.PITCHED_BLADE_45,
                diameter_m=0.22,
                clearance_m=0.52,
                flow_direction=FlowDirection.MIXED_AXIAL,
            ),
        ],
    )
    fluid = FluidProperties(density_kg_m3=1000.0, viscosity_pa_s=0.0012)
    ops = OperatingConditions(rpm=260.0, aeration_vvm=0.0, cell_type=CellType.MAMMALIAN_CELL)
    sim = HydrodynamicEngine.run(tank, fluid, ops)
    field = FlowSolver2D.solve(sim, nx=45, nz=55)
    return sim, field


class TestCADMeshing:
    """Test 1: Verification of 3D CAD anatomical components generation."""

    def test_rushton_baffled_cad_meshes(self, pilot_rushton_sim_and_field):
        sim, field = pilot_rushton_sim_and_field
        cad = Visualizer3D.build_reactor_cad_meshes(sim.tank, field.free_surface_z)

        # Expected keys present
        for key in ["vessel_shell", "baffles", "shaft_and_impellers", "sparger_ring", "free_surface"]:
            assert key in cad
            mesh = cad[key]
            assert isinstance(mesh, pv.PolyData)
            assert mesh.n_points > 0

        # Baffled vessel must have baffle points
        assert cad["baffles"].n_points > 20

    def test_unbaffled_and_all_impeller_types(self, unbaffled_dual_sim_and_field):
        sim, field = unbaffled_dual_sim_and_field
        cad = Visualizer3D.build_reactor_cad_meshes(sim.tank, field.free_surface_z)

        # Unbaffled vessel has 0 baffle points
        assert cad["baffles"].n_points == 0

        # Dual impellers (Marine + PBT)
        assert cad["shaft_and_impellers"].n_points > 100

        # Free surface 3D mesh has points
        assert cad["free_surface"].n_points > 50

    def test_flat_bottom_cad(self):
        tank = TankGeometry(
            diameter_m=0.30,
            liquid_height_m=0.30,
            bottom_type=BottomType.FLAT,
            impellers=[
                ImpellerSpec(
                    impeller_type=ImpellerType.PITCHED_BLADE_45,
                    diameter_m=0.10,
                    clearance_m=0.10,
                )
            ],
        )
        cad = Visualizer3D.build_reactor_cad_meshes(tank)
        assert cad["vessel_shell"].n_points > 0

    def test_vessel_internals_cad_meshes(self):
        """Verify CAD mesh generation supports sparger_type, include_probes, and include_cooling_jacket."""
        # 1. Torus Ring Sparger
        tank_ring = TankGeometry(
            diameter_m=0.45,
            liquid_height_m=0.50,
            bottom_type=BottomType.FLAT,
            sparger_type="ring",
            include_probes=True,
            include_cooling_jacket=True,
            impellers=[ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.15, clearance_m=0.14)],
        )
        cad_ring = Visualizer3D.build_reactor_cad_meshes(tank_ring)
        assert cad_ring["sparger_ring"].n_points > 0
        assert "probes" in cad_ring and cad_ring["probes"].n_points > 0
        assert "cooling_jacket" in cad_ring and cad_ring["cooling_jacket"].n_points > 0

        # 2. Horizontal Pipe Sparger
        tank_pipe = TankGeometry(
            diameter_m=0.45,
            liquid_height_m=0.50,
            bottom_type=BottomType.FLAT,
            sparger_type="pipe",
            include_probes=False,
            include_cooling_jacket=False,
            impellers=[ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.15, clearance_m=0.14)],
        )
        cad_pipe = Visualizer3D.build_reactor_cad_meshes(tank_pipe)
        assert cad_pipe["sparger_ring"].n_points > 0
        assert "probes" in cad_pipe and cad_pipe["probes"].n_points == 0
        assert "cooling_jacket" in cad_pipe and cad_pipe["cooling_jacket"].n_points == 0

        # 3. Unsparged (none)
        tank_none = TankGeometry(
            diameter_m=0.45,
            liquid_height_m=0.50,
            bottom_type=BottomType.FLAT,
            sparger_type="none",
            include_probes=False,
            include_cooling_jacket=False,
            impellers=[ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.15, clearance_m=0.14)],
        )
        cad_none = Visualizer3D.build_reactor_cad_meshes(tank_none)
        assert cad_none["sparger_ring"].n_points == 0


class TestFlowGrid3D:
    """Test 2: Verification of 3D Cartesian flow grid interpolation and point data arrays."""

    def test_build_3d_flow_grid_arrays(self, pilot_rushton_sim_and_field):
        sim, field = pilot_rushton_sim_and_field
        grid = Visualizer3D.build_3d_flow_grid(sim, field, n_grid=25)

        assert isinstance(grid, pv.StructuredGrid)
        assert grid.n_points == 25 ** 3

        # Point data array checks
        assert "velocity" in grid.point_data
        assert "speed" in grid.point_data
        assert "shear_rate" in grid.point_data
        assert "in_vessel" in grid.point_data

        vel = grid.point_data["velocity"]
        assert vel.shape == (grid.n_points, 3)
        assert np.all(np.isfinite(vel))

        speed = grid.point_data["speed"]
        assert np.all(np.isfinite(speed))
        assert np.max(speed) > 0.5  # Substantial circulation speed

        shear = grid.point_data["shear_rate"]
        assert np.all(np.isfinite(shear))
        assert np.max(shear) > 10.0


class TestRenderingAndExport:
    """Test 3: Verification of 3D off-screen rendering pipeline and VTK export package."""

    def test_render_3d_scene(self, pilot_rushton_sim_and_field, tmp_path: Path):
        sim, field = pilot_rushton_sim_and_field
        out_png = tmp_path / "scene_3d.png"

        img = Visualizer3D.render_3d_scene(
            sim,
            field,
            save_path=str(out_png),
            window_size=(800, 600),
        )

        assert isinstance(img, np.ndarray)
        assert img.shape == (600, 800, 3)  # (H, W, C)
        assert out_png.exists()
        assert out_png.stat().st_size > 20000

    def test_render_3d_scene_auto_field(self, unbaffled_dual_sim_and_field):
        sim, _ = unbaffled_dual_sim_and_field
        img = Visualizer3D.render_3d_scene(sim, field_2d=None, window_size=(600, 450))
        assert isinstance(img, np.ndarray)
        assert img.shape == (450, 600, 3)

    def test_export_vtk_package(self, pilot_rushton_sim_and_field, tmp_path: Path):
        sim, field = pilot_rushton_sim_and_field
        export_dir = tmp_path / "vtk_output"

        paths = Visualizer3D.export_vtk_package(sim, field, output_dir=str(export_dir))

        assert "flow_field_3d" in paths
        assert "reactor_anatomy" in paths

        assert os.path.isfile(paths["flow_field_3d"])
        assert os.path.isfile(paths["reactor_anatomy"])

        assert os.path.getsize(paths["flow_field_3d"]) > 10000
        assert os.path.getsize(paths["reactor_anatomy"]) > 1000
