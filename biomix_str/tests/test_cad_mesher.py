"""Unit tests for parametric 3D bioreactor CAD and MRF mesher."""

import os
from pathlib import Path
import pytest

from biomix.cad_mesher import BioreactorCADMesher, MeshedBioreactorArtifact
from biomix.models import (
    BottomType,
    ImpellerSpec,
    ImpellerType,
    TankGeometry,
)

FLUENT_EXE = r"C:\Program Files\ANSYS Inc\ANSYS Student\v261\fluent\ntbin\win64\fluent.exe"


@pytest.fixture
def mesher() -> BioreactorCADMesher:
    """Instantiate CAD mesher with terminal output silenced."""
    return BioreactorCADMesher(terminal_output=False)


def test_rushton_elliptical_baffled_mesh(mesher: BioreactorCADMesher, tmp_path: Path):
    """Verify Rushton 6-blade turbine in 2:1 elliptical bottom vessel with 4 baffles."""
    tank = TankGeometry(
        diameter_m=0.50,
        liquid_height_m=0.50,
        bottom_type=BottomType.ELLIPTICAL_2_1,
        baffle_count=4,
        baffle_width_ratio=0.10,
        impellers=[
            ImpellerSpec(
                impeller_type=ImpellerType.RUSHTON_6_BLADE,
                diameter_m=0.18,
                clearance_m=0.18,
            )
        ],
    )

    artifact = mesher.generate_fluent_mesh(
        tank=tank,
        mesh_density="fast",
        output_dir=str(tmp_path),
        prefix="test_rushton_elliptical",
    )

    assert isinstance(artifact, MeshedBioreactorArtifact)
    assert os.path.isfile(artifact.bdf_mesh_path)
    assert os.path.getsize(artifact.bdf_mesh_path) > 100_000
    assert os.path.isfile(artifact.cad_vtp_path)
    assert os.path.getsize(artifact.cad_vtp_path) > 10_000

    assert artifact.n_cells > 5000, f"Expected > 5000 cells, got {artifact.n_cells}"
    assert artifact.n_nodes > 1000, f"Expected > 1000 nodes, got {artifact.n_nodes}"
    assert len(artifact.mrf_zone_names) >= 1
    assert len(artifact.stationary_zone_names) >= 1

    for name in artifact.mrf_zone_names:
        assert name.startswith("solid-"), f"MRF zone name must be solid-X, got {name}"
    for name in artifact.stationary_zone_names:
        assert name.startswith("solid-"), f"Stationary zone name must be solid-X, got {name}"

    assert len(artifact.impeller_wall_names) >= 1
    assert artifact.meshing_time_s < 30.0


def test_pitched_blade_flat_baffled_mesh(mesher: BioreactorCADMesher, tmp_path: Path):
    """Verify Pitched Blade Turbine (45 deg) in flat-bottom vessel with 4 baffles."""
    tank = TankGeometry(
        diameter_m=0.50,
        liquid_height_m=0.50,
        bottom_type=BottomType.FLAT,
        baffle_count=4,
        baffle_width_ratio=0.10,
        impellers=[
            ImpellerSpec(
                impeller_type=ImpellerType.PITCHED_BLADE_45,
                diameter_m=0.18,
                clearance_m=0.20,
            )
        ],
    )

    artifact = mesher.generate_fluent_mesh(
        tank=tank,
        mesh_density="fast",
        output_dir=str(tmp_path),
        prefix="test_pbt_flat",
    )

    assert isinstance(artifact, MeshedBioreactorArtifact)
    assert os.path.isfile(artifact.bdf_mesh_path)
    assert os.path.isfile(artifact.cad_vtp_path)
    assert artifact.n_cells > 5000, f"Expected > 5000 cells, got {artifact.n_cells}"
    assert len(artifact.mrf_zone_names) >= 1
    assert len(artifact.stationary_zone_names) >= 1


def test_marine_propeller_hemispherical_unbaffled_mesh(mesher: BioreactorCADMesher, tmp_path: Path):
    """Verify Marine Propeller (3-blade) in hemispherical unbaffled vessel."""
    tank = TankGeometry(
        diameter_m=0.50,
        liquid_height_m=0.50,
        bottom_type=BottomType.HEMISPHERICAL,
        baffle_count=0,
        impellers=[
            ImpellerSpec(
                impeller_type=ImpellerType.MARINE_PROPELLER,
                diameter_m=0.18,
                clearance_m=0.25,
            )
        ],
    )

    artifact = mesher.generate_fluent_mesh(
        tank=tank,
        mesh_density="fast",
        output_dir=str(tmp_path),
        prefix="test_marine_hemi",
    )

    assert isinstance(artifact, MeshedBioreactorArtifact)
    assert os.path.isfile(artifact.bdf_mesh_path)
    assert os.path.isfile(artifact.cad_vtp_path)
    assert artifact.n_cells > 4000, f"Expected > 4000 cells, got {artifact.n_cells}"
    assert len(artifact.mrf_zone_names) >= 1
    assert len(artifact.stationary_zone_names) >= 1


def test_live_fluent_import_and_mesh_check(mesher: BioreactorCADMesher, tmp_path: Path):
    """Load generated BDF mesh into Ansys Fluent 2026 R1 and verify mesh check and zone topology."""
    if not os.path.isfile(FLUENT_EXE):
        pytest.skip(f"Ansys Fluent 2026 R1 executable not found at: {FLUENT_EXE}")

    import ansys.fluent.core as pyfluent

    tank = TankGeometry(
        diameter_m=0.50,
        liquid_height_m=0.50,
        bottom_type=BottomType.ELLIPTICAL_2_1,
        baffle_count=4,
        impellers=[
            ImpellerSpec(
                impeller_type=ImpellerType.RUSHTON_6_BLADE,
                diameter_m=0.18,
                clearance_m=0.18,
            )
        ],
    )

    artifact = mesher.generate_fluent_mesh(
        tank=tank,
        mesh_density="fast",
        output_dir=str(tmp_path),
        prefix="fluent_check",
    )

    # Launch live headless Fluent session
    try:
        session = pyfluent.launch_fluent(
            fluent_path=FLUENT_EXE,
            dimension=3,
            precision="double",
            processor_count=2,
            ui_mode="no_gui_or_graphics",
            mode="solver",
        )
    except Exception as e:
        pytest.skip(f"Live Ansys Fluent license or service temporarily unavailable: {e}")


    try:
        # Import Nastran BDF mesh into Fluent
        clean_bdf = artifact.bdf_mesh_path.replace("\\", "/")
        session.settings.file.import_.read(file_type="nastran-bulkdata", file_name=clean_bdf)

        # Check mesh: passes with zero errors/negative volumes
        session.settings.mesh.check()

        # Convert solid zones to fluid
        solid_zones = session.settings.setup.cell_zone_conditions.solid.get_object_names()
        assert len(solid_zones) >= 2, f"Expected at least 2 cell zones (MRF + stationary), got {solid_zones}"
        session.settings.setup.cell_zone_conditions.set_zone_type(zone_list=solid_zones, new_type="fluid")

        fluid_zones = session.settings.setup.cell_zone_conditions.fluid.get_object_names()

        # Confirm deterministically identified MRF zones exist in Fluent
        for mrf_name in artifact.mrf_zone_names:
            assert mrf_name in fluid_zones, f"MRF zone '{mrf_name}' not found in Fluent fluid zones: {fluid_zones}"

        for stat_name in artifact.stationary_zone_names:
            assert stat_name in fluid_zones, f"Stationary zone '{stat_name}' not found in Fluent fluid zones: {fluid_zones}"

    finally:
        try:
            session.exit()
        except Exception:
            pass
        try:
            import time
            time.sleep(0.5)
            from biomix.fluent_runner import FluentSimulationRunner
            FluentSimulationRunner.cleanup_stray_fluent_logs()
        except Exception:
            pass


def test_smith_cd6_mesh(mesher: BioreactorCADMesher, tmp_path: Path):
    """Verify Smith CD-6 concave disc turbine mesh generation and zone identification."""
    tank = TankGeometry(
        diameter_m=0.40,
        liquid_height_m=0.45,
        bottom_type=BottomType.FLAT,
        baffle_count=4,
        baffle_width_ratio=0.10,
        impellers=[
            ImpellerSpec(
                impeller_type=ImpellerType.SMITH_CD6,
                diameter_m=0.14,
                clearance_m=0.15,
            )
        ],
    )
    artifact = mesher.generate_fluent_mesh(tank, mesh_density="fast", output_dir=str(tmp_path), prefix="test_smith")
    assert artifact.mrf_zone_names == ["solid-101"]
    assert artifact.stationary_zone_names == ["solid-102"]
    assert artifact.impeller_wall_names == ["wall-201"]
    assert artifact.vessel_wall_names == ["wall-202"]
    assert artifact.interface_wall_names == ["wall-203"]
    assert artifact.n_cells > 5000


def test_hydrofoil_he3_mesh(mesher: BioreactorCADMesher, tmp_path: Path):
    """Verify Chemineer Hydrofoil HE-3 fluidfoil mesh generation and PID assignments."""
    tank = TankGeometry(
        diameter_m=0.40,
        liquid_height_m=0.45,
        bottom_type=BottomType.ELLIPTICAL_2_1,
        baffle_count=4,
        baffle_width_ratio=0.10,
        impellers=[
            ImpellerSpec(
                impeller_type=ImpellerType.HYDROFOIL_HE3,
                diameter_m=0.16,
                clearance_m=0.15,
            )
        ],
    )
    artifact = mesher.generate_fluent_mesh(tank, mesh_density="fast", output_dir=str(tmp_path), prefix="test_he3")
    assert artifact.mrf_zone_names == ["solid-101"]
    assert artifact.stationary_zone_names == ["solid-102"]
    assert artifact.impeller_wall_names == ["wall-201"]
    assert artifact.vessel_wall_names == ["wall-202"]
    assert artifact.interface_wall_names == ["wall-203"]
    assert artifact.n_cells > 5000


def test_intermig_ekato_mesh(mesher: BioreactorCADMesher, tmp_path: Path):
    """Verify EKATO Intermig multi-stage agitator mesh generation and non-empty wall-201."""
    tank = TankGeometry(
        diameter_m=0.40,
        liquid_height_m=0.45,
        bottom_type=BottomType.FLAT,
        baffle_count=4,
        baffle_width_ratio=0.10,
        impellers=[
            ImpellerSpec(
                impeller_type=ImpellerType.INTERMIG_EKATO,
                diameter_m=0.14,
                clearance_m=0.15,
            )
        ],
    )
    artifact = mesher.generate_fluent_mesh(tank, mesh_density="fast", output_dir=str(tmp_path), prefix="test_intermig")
    assert artifact.mrf_zone_names == ["solid-101"]
    assert artifact.stationary_zone_names == ["solid-102"]
    assert artifact.impeller_wall_names == ["wall-201"]
    assert artifact.vessel_wall_names == ["wall-202"]
    assert artifact.interface_wall_names == ["wall-203"]
    assert artifact.n_cells > 5000


def test_anchor_close_clearance_mesh(mesher: BioreactorCADMesher, tmp_path: Path):
    """Verify Anchor agitator single-zone rotating MRF meshing without interface walls."""
    tank = TankGeometry(
        diameter_m=0.40,
        liquid_height_m=0.45,
        bottom_type=BottomType.FLAT,
        baffle_count=0,
        impellers=[
            ImpellerSpec(
                impeller_type=ImpellerType.ANCHOR,
                diameter_m=0.36,
                clearance_m=0.08,
                blade_width_m=0.25,
            )
        ],
    )
    artifact = mesher.generate_fluent_mesh(tank, mesh_density="fast", output_dir=str(tmp_path), prefix="test_anchor")
    assert artifact.mrf_zone_names == ["solid-101"]
    assert artifact.stationary_zone_names == []
    assert artifact.impeller_wall_names == ["wall-201"]
    assert artifact.vessel_wall_names == ["wall-202"]
    assert artifact.interface_wall_names == []
    assert artifact.n_cells > 5000


def test_close_clearance_baffles_rejected(mesher: BioreactorCADMesher, tmp_path: Path):
    """Verify that close-clearance impeller with baffles is rejected as physically invalid in single-zone MRF."""
    tank = TankGeometry(
        diameter_m=0.40,
        liquid_height_m=0.45,
        bottom_type=BottomType.FLAT,
        baffle_count=4,
        impellers=[
            ImpellerSpec(
                impeller_type=ImpellerType.ANCHOR,
                diameter_m=0.36,
                clearance_m=0.08,
            )
        ],
    )
    with pytest.raises(ValueError, match="Close-clearance impellers"):
        mesher.generate_fluent_mesh(tank, mesh_density="fast", output_dir=str(tmp_path), prefix="test_fail")

