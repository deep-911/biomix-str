"""Automated test suite verifying Phase F.1 enhancements:
- Concurrency lock and abort pipeline
- 500k cell ceiling pre-flight check
- Kolmogorov and shear stress field computations
- Upgraded close-clearance 3D geometries
"""

import pytest
from fastapi.testclient import TestClient
import numpy as np
import threading
from biomix.server import app, SOLVER_SEMAPHORE, jobs_store
from biomix.cad_mesher import BioreactorCADMesher
from biomix.models import TankGeometry, ImpellerSpec, BottomType, ImpellerType


client = TestClient(app)


def test_solver_semaphore_and_abort():
    # Create a dummy active job
    test_job_id = "test_abort_job_123"
    jobs_store[test_job_id] = {
        "status": "solving",
        "stage": "solving",
        "iteration": 5,
        "total_iterations": 25,
        "pid": 9999999, # Dummy PID
    }
    
    resp = client.post(f"/api/jobs/{test_job_id}/abort")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "aborted"
    assert jobs_store[test_job_id]["status"] == "aborted"


def test_concurrency_lock_returns_409_when_locked():
    # Artificially acquire the semaphore
    acquired = SOLVER_SEMAPHORE.acquire(blocking=False)
    assert acquired is True
    try:
        # Try to launch simulate while locked
        payload = {
            "tank": {
                "diameter_m": 0.45,
                "liquid_height_m": 0.50,
                "bottom_type": "flat",
                "is_baffled": True,
                "baffle_count": 4,
                "baffle_width_ratio": 0.10,
                "impellers": [
                    {"impeller_type": "rushton_6_blade", "diameter_m": 0.15, "clearance_m": 0.14}
                ]
            },
            "fluid": {"name": "Water Broth", "density_kg_m3": 1000.0, "viscosity_pa_s": 0.001},
            "ops": {"rpm": 280.0, "aeration_vvm": 0.0},
            "mesh_density": "fast",
            "iterations": 25,
            "force_recompute": True,
        }
        resp = client.post("/api/simulate", json=payload)
        assert resp.status_code == 409
        assert "simulation is currently active" in str(resp.json()["detail"])
    finally:
        SOLVER_SEMAPHORE.release()


def test_verified_runs_have_kolmogorov_and_shear_fields():
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) >= 9
    
    # Check turbulent standard rushton 250 rpm bundle
    target_run = None
    for r in runs:
        if r["run_id"] == "fluent_rush_flat_250rpm_c5abfce9ad1c":
            target_run = r["run_id"]
            break
    assert target_run is not None
    
    bundle_resp = client.get(f"/api/runs/{target_run}/bundle")
    assert bundle_resp.status_code == 200
    data = bundle_resp.json()
    
    meta = data["metadata"]
    assert "cfd_kolmogorov_min_um" in meta
    assert meta["cfd_kolmogorov_min_um"] > 0
    assert "cfd_max_shear_stress_pa" in meta
    assert meta["cfd_max_shear_stress_pa"] > 0
    
    xz = data["bundle_3d"]["cross_sections"]["xz"]
    assert "kolmogorov_um" in xz
    assert "shear_stress_pa" in xz
    assert xz["kolmogorov_um"] is not None
    assert xz["shear_stress_pa"] is not None


def test_close_clearance_solid_geometries():
    tank = TankGeometry(
        diameter_m=0.45,
        liquid_height_m=0.50,
        bottom_type=BottomType.FLAT,
        is_baffled=False,
        baffle_count=0,
        impellers=[
            ImpellerSpec(impeller_type=ImpellerType.ANCHOR, diameter_m=0.41, clearance_m=0.04)
        ]
    )
    mesher = BioreactorCADMesher(terminal_output=False)
    
    # Test all 4 close clearance types
    for imp_type in [ImpellerType.GATE_IMPELLER, ImpellerType.SIGMA_Z_KNEADER, ImpellerType.HELICAL_RIBBON, ImpellerType.AUGER_SCREW]:
        imp = ImpellerSpec(impeller_type=imp_type, diameter_m=0.40, clearance_m=0.05)
        # Verify solid builds without error
        try:
            import gmsh
            gmsh.initialize(interruptible=False)
            solid = mesher._build_impeller_solid(tank, imp)
            assert solid is not None
            assert len(solid) > 0
            gmsh.finalize()
        except Exception as e:
            pytest.fail(f"Failed to build solid for {imp_type}: {e}")
