"""Integration and unit tests for BioMix-STR FastAPI Backend & WebSocket Streamer.

Verifies:
1. GET /api/status returns 200 OK with fluent_exe_found == True and cached_runs_count >= 1.
2. GET /api/presets and GET /api/runs return valid lists including cached runs.
3. GET /api/runs/{run_id}/bundle returns non-empty metadata, streamlines, slices, and CAD meshes.
4. POST /api/simulate with cached parameters returns completed cached solution in <0.2 s.
5. POST /api/ensemble/preview-geometry updates 3D CAD meshes when inter-impeller gap changes.
6. GET /api/jobs/{job_id} and WS /ws/jobs/{job_id} test job polling and real-time streaming.
"""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient
import pytest

from biomix.server import app, jobs_lock, jobs_store


@pytest.fixture
def client():
    """Create a FastAPI TestClient instance."""
    return TestClient(app)


# =============================================================================
# Test 1: System Status
# =============================================================================

def test_api_status(client):
    """Verify /api/status returns 200 OK, Fluent executable status, and cached runs count."""
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "healthy"
    assert data["fluent_exe_found"] is True
    assert "2026" in data["fluent_version"]
    assert "pyfluent_version" in data
    assert data["cached_runs_count"] >= 1
    assert data["active_jobs_count"] >= 0


# =============================================================================
# Test 2: Presets & Runs
# =============================================================================

def test_api_presets_and_runs(client):
    """Verify /api/presets and /api/runs return valid collections with cached solutions."""
    # Presets
    resp_presets = client.get("/api/presets")
    assert resp_presets.status_code == 200
    presets = resp_presets.json()
    assert len(presets) >= 5

    categories = {p["category"] for p in presets}
    assert "radial" in categories
    assert "axial" in categories
    assert "viscous" in categories
    assert "sweeps" in categories

    # Verify at least one preset is marked as cached
    cached_presets = [p for p in presets if p["is_cached"]]
    assert len(cached_presets) >= 1, "Expected at least one preset to match a cached CFD run"

    # Runs
    resp_runs = client.get("/api/runs")
    assert resp_runs.status_code == 200
    runs = resp_runs.json()
    assert len(runs) >= 1

    first_run = runs[0]
    assert "run_id" in first_run
    assert "metadata" in first_run
    assert "config" in first_run
    assert first_run["metadata"]["cfd_max_velocity_m_s"] > 0.0


# =============================================================================
# Test 3: Run Bundle Retrieval
# =============================================================================

def test_api_run_bundle(client):
    """Verify /api/runs/{run_id}/bundle returns 3D streamlines, vectors_3d, full-vessel slices, CAD, and textbook metrics."""
    resp_runs = client.get("/api/runs")
    runs = resp_runs.json()
    assert len(runs) >= 1

    # Verify all cached runs have full-vessel 3D vectors, streamlines, and high-coverage XZ slices
    for run_entry in runs:
        target_run_id = run_entry["run_id"]
        resp_bundle = client.get(f"/api/runs/{target_run_id}/bundle")
        assert resp_bundle.status_code == 200
        data = resp_bundle.json()

        assert data["run_id"] == target_run_id

        # 1. Metadata
        assert "metadata" in data
        meta = data["metadata"]
        assert meta["cfd_max_velocity_m_s"] > 0.1
        assert meta["cfd_power_w"] > 0.0
        assert meta["rpm"] > 0.0

        # 2. BPE Textbook Comparison
        assert "bpe_textbook" in data
        if data["bpe_textbook"] is not None:
            bpe = data["bpe_textbook"]
            assert "total_ungassed_power_w" in bpe
            assert "lambda_k_min_um" in bpe

        # 3. 3D Web Bundle
        assert "bundle_3d" in data
        b3d = data["bundle_3d"]

        # Streamlines: >= 60 full-tank streamlines spanning upper & lower circulation loops
        assert "streamlines" in b3d
        assert len(b3d["streamlines"]) >= 60
        assert len(b3d["streamlines"][0]) >= 2

        # 3D Velocity Vector Field: >= 300 volumetric vectors [x, y, z, ux, uy, uz, speed]
        assert "vectors_3d" in b3d
        assert len(b3d["vectors_3d"]) >= 300
        first_vec = b3d["vectors_3d"][0]
        assert len(first_vec) == 7, "Vector format must be [x, y, z, ux, uy, uz, speed]"

        # Full-Vessel Cross section slices (XZ and YZ)
        assert "cross_sections" in b3d
        assert "xz" in b3d["cross_sections"]
        assert "yz" in b3d["cross_sections"]

        # Non-zero velocity coverage across wet XZ domain (> 75% to accommodate fluid fill height and dish bottoms)
        xz_matrix = b3d["cross_sections"]["xz"]["velocity_mag"]
        valid_cells = sum(1 for row in xz_matrix for val in row if val is not None and val > 0.0)
        total_cells = sum(len(row) for row in xz_matrix)
        coverage_ratio = valid_cells / total_cells
        assert coverage_ratio > 0.75, f"XZ non-zero coverage for {target_run_id} is {coverage_ratio:.2%}, expected > 75%"

        # Horizontal slices
        assert "horizontal_slices" in b3d
        assert len(b3d["horizontal_slices"]) >= 1

        # 3D CAD Meshes (vessel_shell, shaft_and_impellers, and free_surface meniscus)
        assert "cad_meshes" in b3d
        cad = b3d["cad_meshes"]
        assert "vessel_shell" in cad and len(cad["vessel_shell"]["vertices"]) > 0
        assert "shaft_and_impellers" in cad and len(cad["shaft_and_impellers"]["vertices"]) > 0
        assert "free_surface" in cad and len(cad["free_surface"]["vertices"]) > 0

    # 4. Error case: non-existent run_id
    resp_404 = client.get("/api/runs/non_existent_run_id_12345/bundle")
    assert resp_404.status_code == 404



# =============================================================================
# Test 4: Instant Simulation Cache Hit
# =============================================================================

def test_api_simulate_cache_hit(client):
    """Verify /api/simulate returns completed cached run in <0.2 s without running Fluent."""
    # Payload matching our cached single Rushton run (c5abfce9ad1c)
    cached_payload = {
        "tank": {
            "diameter_m": 0.40,
            "liquid_height_m": 0.45,
            "bottom_type": "flat",
            "baffle_count": 4,
            "baffle_width_ratio": 0.10,
            "impellers": [
                {
                    "impeller_type": "rushton_6_blade",
                    "diameter_m": 0.14,
                    "clearance_m": 0.15,
                }
            ],
        },
        "fluid": {
            "name": "Water Broth",
            "density_kg_m3": 1000.0,
            "viscosity_pa_s": 0.001,
            "coalescing_media": True,
        },
        "ops": {
            "rpm": 250.0,
            "aeration_vvm": 0.5,
            "cell_type": "microbial",
        },
        "mesh_density": "fast",
        "iterations": 15,
        "force_recompute": False,
    }

    t0 = time.perf_counter()
    resp = client.post("/api/simulate", json=cached_payload)
    elapsed = time.perf_counter() - t0

    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "completed"
    assert data["cached"] is True
    assert data["run_id"] == "fluent_rush_flat_250rpm_c5abfce9ad1c"
    assert data["job_id"] is None
    assert elapsed < 0.20, f"Cache hit took {elapsed:.3f} s, expected < 0.2 s"


# =============================================================================
# Test 5: Instant 3D CAD Preview Geometry Sensitivity
# =============================================================================

def test_api_preview_geometry_sensitivity(client):
    """Verify /api/ensemble/preview-geometry updates 3D CAD meshes immediately when gap changes."""
    # 1. Dual impeller with narrow gap (clearances 0.14 m and 0.28 m -> Delta C = 0.14 m)
    payload_narrow = {
        "tank": {
            "diameter_m": 0.45,
            "liquid_height_m": 0.50,
            "bottom_type": "flat",
            "baffle_count": 4,
            "baffle_width_ratio": 0.10,
            "impellers": [
                {"impeller_type": "rushton_6_blade", "diameter_m": 0.15, "clearance_m": 0.14},
                {"impeller_type": "pitched_blade_45", "diameter_m": 0.15, "clearance_m": 0.28},
            ],
        }
    }

    t0 = time.perf_counter()
    resp_narrow = client.post("/api/ensemble/preview-geometry", json=payload_narrow)
    elapsed_narrow = time.perf_counter() - t0

    assert resp_narrow.status_code == 200
    data_narrow = resp_narrow.json()
    assert elapsed_narrow < 10.0, f"Preview took {elapsed_narrow:.3f} s, expected < 10.0 s"
    assert "cad_meshes" in data_narrow
    assert "shaft_and_impellers" in data_narrow["cad_meshes"]

    # 2. Dual impeller with wide gap (clearances 0.14 m and 0.40 m -> Delta C = 0.26 m)
    payload_wide = {
        "tank": {
            "diameter_m": 0.45,
            "liquid_height_m": 0.50,
            "bottom_type": "flat",
            "baffle_count": 4,
            "baffle_width_ratio": 0.10,
            "impellers": [
                {"impeller_type": "rushton_6_blade", "diameter_m": 0.15, "clearance_m": 0.14},
                {"impeller_type": "pitched_blade_45", "diameter_m": 0.15, "clearance_m": 0.40},
            ],
        }
    }

    resp_wide = client.post("/api/ensemble/preview-geometry", json=payload_wide)
    assert resp_wide.status_code == 200
    data_wide = resp_wide.json()

    # The deterministic run_ids must be different
    assert data_narrow["deterministic_run_id"] != data_wide["deterministic_run_id"]

    # The shaft and impeller vertex arrays must differ because the upper impeller elevation changed
    verts_narrow = data_narrow["cad_meshes"]["shaft_and_impellers"]["vertices"]
    verts_wide = data_wide["cad_meshes"]["shaft_and_impellers"]["vertices"]
    assert len(verts_narrow) > 0
    assert len(verts_wide) > 0
    assert verts_narrow != verts_wide, "Different gap must produce different 3D CAD vertex coordinates"


# =============================================================================
# Test 6: Jobs Polling & WebSocket Streaming
# =============================================================================

def test_api_jobs_polling_and_websocket(client):
    """Verify /api/jobs/{job_id} and WebSocket /ws/jobs/{job_id} connection and data delivery."""
    test_job_id = "job_test_ws_stream_123"
    with jobs_lock:
        jobs_store[test_job_id] = {
            "job_id": test_job_id,
            "run_id": "fluent_test_run_123",
            "status": "running",
            "stage": "solving",
            "progress_pct": 65.0,
            "current_iteration": 10,
            "total_iterations": 15,
            "message": "Iterating Navier-Stokes 10/15...",
            "residuals": [
                {"iteration": 1, "continuity": 1.0, "x_velocity": 0.005, "y_velocity": 0.005, "z_velocity": 0.002, "k": 0.001, "epsilon": 0.05}
            ],
            "error": None,
            "created_at": time.time(),
            "completed_at": None,
        }

    # 1. HTTP Polling
    resp = client.get(f"/api/jobs/{test_job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == test_job_id
    assert data["progress_pct"] == 65.0
    assert data["stage"] == "solving"
    assert len(data["residuals"]) == 1

    # 2. Non-existent job polling
    resp_404 = client.get("/api/jobs/job_invalid_id_9999")
    assert resp_404.status_code == 404

    # 3. WebSocket Streaming
    with client.websocket_connect(f"/ws/jobs/{test_job_id}") as ws:
        init_msg = ws.receive_json()
        assert init_msg["type"] == "state"
        assert init_msg["job_id"] == test_job_id
        assert init_msg["data"]["progress_pct"] == 65.0


# =============================================================================
# Test 7: Static Files & Web App Single-Page Entrypoint
# =============================================================================

def test_root_serves_html(client):
    """Verify GET / serves index.html single-page application with 200 OK."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    content = resp.text
    assert "BioMix-STR" in content
    assert "Ansys Fluent 2026 R1 CFD Studio" in content
    assert "three.min.js" in content
    assert "OrbitControls.js" in content
    assert "styles.css" in content
    assert "app.js" in content


def test_static_files_accessible(client):
    """Verify static assets /static/styles.css and /static/app.js are served cleanly."""
    resp_css = client.get("/static/styles.css")
    assert resp_css.status_code == 200
    assert "--google-blue" in resp_css.text
    assert "--elevation-1" in resp_css.text

    resp_js = client.get("/static/app.js")
    assert resp_js.status_code == 200
    assert "initThreeEngine" in resp_js.text
    assert "updateStreamlines" in resp_js.text
    assert "Colormaps" in resp_js.text


# =============================================================================
# Test 8: 16-Impeller BPE Curriculum Catalog Endpoint
# =============================================================================

def test_api_bpe_catalog(client):
    """Verify GET /api/bpe/catalog returns all 16 impellers, class/flow groups, and textbook tables."""
    resp = client.get("/api/bpe/catalog")
    assert resp.status_code == 200
    data = resp.json()

    # Total 16 impellers
    assert "impellers" in data
    assert len(data["impellers"]) == 16

    # Grouped by clearance class
    assert "by_class" in data
    assert len(data["by_class"]["open_turbine"]) == 11
    assert len(data["by_class"]["close_clearance"]) == 5

    # Grouped by flow direction
    assert "by_flow" in data
    assert len(data["by_flow"]["radial"]) == 6
    assert len(data["by_flow"]["mixed_axial"]) == 2
    assert len(data["by_flow"]["axial"]) == 3
    assert len(data["by_flow"]["close_clearance_tangential"]) == 5

    # Section 6 standard geometric ratios table
    assert "section_6_standard_ratios" in data
    sec6 = data["section_6_standard_ratios"]["standard_rushton"]
    assert sec6["dt_di"] == 3.0
    assert sec6["hl_di"] == 3.0
    assert sec6["li_di"] == 0.25
    assert sec6["wi_di"] == 0.20
    assert sec6["hi_di"] == 1.0
    assert sec6["wb_dt"] == 0.10
    assert sec6["baffles"] == 4

    # Section 7 quick revision table
    assert "section_7_quick_revision" in data
    assert len(data["section_7_quick_revision"]) >= 6

    # Verify each impeller has rich curriculum content and viscosity envelopes
    for imp in data["impellers"]:
        assert len(imp["construction"]) > 10
        assert len(imp["working_principle"]) > 10
        assert len(imp["applications"]) > 10
        assert len(imp["limitations_and_advantages"]) > 10
        assert imp["viscosity_max_cp"] > 0
        assert "standard_ratios" in imp and len(imp["standard_ratios"]) > 0


# =============================================================================
# Test 9: Automated BPE Suitability Advisor Endpoint
# =============================================================================

def test_api_bpe_suitability(client):
    """Verify POST /api/bpe/suitability returns warnings for out-of-range viscosity and baffle conflicts."""
    # 1. Marine Propeller with excessive viscosity (5,000 cP > 2,000 cP limit)
    payload_high_visc = {
        "tank": {
            "diameter_m": 0.40,
            "liquid_height_m": 0.50,
            "bottom_type": "flat",
            "baffle_count": 4,
            "baffle_width_ratio": 0.10,
            "impellers": [
                {"impeller_type": "marine_propeller", "diameter_m": 0.14, "clearance_m": 0.15}
            ],
        },
        "fluid": {
            "name": "High Viscosity Broth",
            "density_kg_m3": 1050.0,
            "viscosity_pa_s": 5.0,  # 5,000 cP
            "coalescing_media": True,
        },
        "ops": {
            "rpm": 120.0,
        },
    }
    resp = client.post("/api/bpe/suitability", json=payload_high_visc)
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_warnings"] is True
    assert any("viscosity" in a["message"].lower() for a in data["alerts"])
    assert len(data["recommended_adjustments"]) > 0
    assert "bpe_metrics" in data
    assert len(data["bpe_metrics"]["stages"]) >= 1
    assert data["bpe_metrics"]["stages"][0]["re_i"] > 0
    assert data["bpe_metrics"]["total_ungassed_power_w"] > 0

    # 2. Anchor impeller in a baffled tank (Close clearance impellers require unbaffled tanks)
    payload_baffle_conflict = {
        "tank": {
            "diameter_m": 0.50,
            "liquid_height_m": 0.60,
            "bottom_type": "flat",
            "baffle_count": 4,
            "baffle_width_ratio": 0.10,
            "impellers": [
                {"impeller_type": "anchor", "diameter_m": 0.46, "clearance_m": 0.05}
            ],
        },
        "fluid": {
            "name": "Polymer Broth",
            "density_kg_m3": 1100.0,
            "viscosity_pa_s": 15.0,
            "coalescing_media": False,
        },
        "ops": {
            "rpm": 40.0,
        },
    }
    resp_baffle = client.post("/api/bpe/suitability", json=payload_baffle_conflict)
    assert resp_baffle.status_code == 200
    data_baffle = resp_baffle.json()
    assert data_baffle["has_warnings"] is True
    assert any("baffle" in a["message"].lower() or "unbaffled" in a["message"].lower() for a in data_baffle["alerts"])


# =============================================================================
# Test 10: Instant Full-Flow Preview for 16 Impellers
# =============================================================================

def test_api_preview_geometry_16_impellers(client):
    """Verify POST /api/ensemble/preview-geometry returns full 3D CAD, streamlines, vectors, and slices for 16 impellers."""
    test_cases = [
        {
            "type": "smith_cd6",
            "tank": {
                "diameter_m": 0.45,
                "liquid_height_m": 0.50,
                "bottom_type": "flat",
                "baffle_count": 4,
                "baffle_width_ratio": 0.10,
                "impellers": [
                    {"impeller_type": "smith_cd6", "diameter_m": 0.15, "clearance_m": 0.16}
                ],
            },
        },
        {
            "type": "intermig_ekato",
            "tank": {
                "diameter_m": 0.50,
                "liquid_height_m": 0.80,
                "bottom_type": "elliptical_2_1",
                "baffle_count": 4,
                "baffle_width_ratio": 0.10,
                "impellers": [
                    {"impeller_type": "intermig_ekato", "diameter_m": 0.32, "clearance_m": 0.22},
                    {"impeller_type": "intermig_ekato", "diameter_m": 0.32, "clearance_m": 0.55},
                ],
            },
        },
        {
            "type": "helical_ribbon",
            "tank": {
                "diameter_m": 0.45,
                "liquid_height_m": 0.55,
                "bottom_type": "flat",
                "baffle_count": 0,
                "baffle_width_ratio": 0.10,
                "impellers": [
                    {"impeller_type": "helical_ribbon", "diameter_m": 0.42, "clearance_m": 0.05}
                ],
            },

        },
    ]

    for tc in test_cases:
        payload = {
            "tank": tc["tank"],
            "fluid": {"name": "Test Fluid", "density_kg_m3": 1000.0, "viscosity_pa_s": 0.01},
            "ops": {"rpm": 150.0},
        }
        t0 = time.perf_counter()
        resp = client.post("/api/ensemble/preview-geometry", json=payload)
        elapsed = time.perf_counter() - t0

        assert resp.status_code == 200, f"Preview failed for {tc['type']}: {resp.text}"
        assert elapsed < 3.00, f"Preview took {elapsed:.3f} s, expected < 3.00 s"
        data = resp.json()

        # CAD Meshes
        assert "cad_meshes" in data
        cad = data["cad_meshes"]
        assert "vessel_shell" in cad and len(cad["vessel_shell"]["vertices"]) > 0
        assert "shaft_and_impellers" in cad and len(cad["shaft_and_impellers"]["vertices"]) > 0
        assert "free_surface" in cad and len(cad["free_surface"]["vertices"]) > 0

        # 3D Streamlines
        assert "streamlines" in data
        assert len(data["streamlines"]) >= 60, f"Expected >= 60 streamlines for {tc['type']}, got {len(data['streamlines'])}"

        # 3D Velocity Vectors
        assert "vectors_3d" in data
        assert len(data["vectors_3d"]) >= 300, f"Expected >= 300 3D vectors for {tc['type']}, got {len(data['vectors_3d'])}"
        assert len(data["vectors_3d"][0]) == 7

        # 2D Cross Sections
        assert "cross_sections" in data
        assert "xz" in data["cross_sections"] and len(data["cross_sections"]["xz"]["velocity_mag"]) > 0
        assert "yz" in data["cross_sections"] and len(data["cross_sections"]["yz"]["velocity_mag"]) > 0

        # BPE Metrics & Suitability Alerts
        assert "bpe_metrics" in data
        assert data["bpe_metrics"]["total_ungassed_power_w"] > 0
        assert len(data["bpe_metrics"]["stages"]) >= 1
        assert data["bpe_metrics"]["stages"][0]["re_i"] > 0
        assert "suitability_alerts" in data
        assert isinstance(data["suitability_alerts"], list)


# =============================================================================
# Phase E & F Tests: 18 Verified Presets, Non-Newtonian Theory, and Vessel Internals
# =============================================================================

def test_api_all_22_verified_presets(client):
    """Verify GET /api/presets returns all 30 verified Fluent presets with correct provenance."""
    resp = client.get("/api/presets")
    assert resp.status_code == 200
    presets = resp.json()

    assert len(presets) == 30, f"Expected exactly 30 verified presets, got {len(presets)}"

    expected_runs = {
        # 6 Radial
        "rushton_single_standard": "fluent_rush_flat_250rpm_c5abfce9ad1c",
        "smith_cd6_standard": "fluent_smit_flat_250rpm_0bfbe7c7de0c",
        "flat_blade_fbt_open": "fluent_flat_flat_250rpm_e27322b426fb",
        "curved_backswept_radial": "fluent_curv_flat_240rpm_bcbe35d749b0",
        "paddle_r200_gentle": "fluent_padd_flat_100rpm_dc803c6e30e7",
        "retreat_blade_glass_lined": "fluent_retr_elli_200rpm_409fa03695fc",
        # 5 Axial
        "pitched_blade_single_axial": "fluent_pitc_elli_220rpm_432bbc081267",
        "marine_propeller_mammalian": "fluent_mari_hemi_130rpm_51527ba4791c",
        "hydrofoil_he3_axial": "fluent_hydr_elli_250rpm_959ef9534ed6",
        "maxflo_high_solidity_axial": "fluent_maxf_elli_220rpm_536fe85176c2",
        "intermig_ekato_axial": "fluent_inte_elli_150rpm_f3a8df7cfc08",
        # 5 Viscous / Close-Clearance
        "anchor_laminar_powerlaw": "fluent_anch_flat_40rpm_d12f32384b94",
        "helical_ribbon_polymer": "fluent_heli_flat_35rpm_c45f087adfac",
        "auger_screw_paste": "fluent_auge_flat_50rpm_4aa49a4651ba",
        "gate_impeller_slurry": "fluent_gate_flat_35rpm_43b96abc45e8",
        "sigma_kneader_biopolymer": "fluent_sigm_flat_30rpm_2b5fe06fc5b9",
        # 6 Sweeps
        "dual_impeller_wide_gap": "fluent_rush_flat_280rpm_1f9d1ae137f1",
        "dual_impeller_narrow_gap": "fluent_rush_flat_280rpm_dd6c74f598ba",
        "unbaffled_rankine_vortex": "fluent_rush_flat_260rpm_c0ff9b8ebcd1",
        "rushton_sweep_low_120rpm": "fluent_rush_flat_120rpm_05c5a8739b78",
        "rushton_sweep_high_400rpm": "fluent_rush_flat_400rpm_f11532130aa6",
        "rushton_cavern_3000cp": "fluent_rush_flat_250rpm_37e0a7c99627",
        # 8 Canonical Additions
        "rushton_elliptical_250rpm": "fluent_rush_elli_250rpm_af88246294c0",
        "rushton_hemi_250rpm": "fluent_rush_hemi_250rpm_685d06cfca27",
        "smith_cd6_high_400rpm": "fluent_smit_flat_400rpm_d0992a970257",
        "pbt_flat_220rpm": "fluent_pitc_flat_220rpm_05afb991d9d4",
        "dual_pbt_axial_220rpm": "fluent_pitc_elli_220rpm_575975675a94",
        "hydrofoil_he3_viscous_500cp": "fluent_hydr_elli_250rpm_43d61e397676",
        "pbt_unbaffled_vortex_220rpm": "fluent_pitc_elli_220rpm_8c536769d748",
        "dual_smith_hydrofoil_hybrid": "fluent_smit_flat_260rpm_6ba58aa1688a",
    }

    preset_map = {p["preset_id"]: p for p in presets}

    for pid, expected_run_id in expected_runs.items():
        assert pid in preset_map, f"Missing preset {pid}"
        p = preset_map[pid]
        assert p["run_id"] == expected_run_id, f"Preset {pid} has run_id {p['run_id']}, expected {expected_run_id}"
        assert p["is_cached"] is True, f"Preset {pid} is_cached is not True"
        assert "label" in p["provenance"]

    # Verify specialized tier labels for verified runs per Oracle 11
    assert preset_map["retreat_blade_glass_lined"]["provenance"]["label"] == "Verified Fluent (Experimental CFD)"
    assert preset_map["paddle_r200_gentle"]["provenance"]["label"] == "Verified Fluent (Experimental CFD)"
    assert preset_map["rushton_cavern_3000cp"]["provenance"]["label"] == "Verified Fluent"
    assert preset_map["rushton_sweep_high_400rpm"]["provenance"]["label"] == "Verified Fluent"
    assert preset_map["rushton_single_standard"]["provenance"]["label"] == "Verified Fluent"


def test_api_theory_evaluate_power_law(client):
    """Verify /api/theory/evaluate evaluates the Power-Law card when rheology_model='power_law'."""
    payload = {
        "tank": {
            "diameter_m": 0.45,
            "liquid_height_m": 0.50,
            "bottom_type": "flat",
            "is_baffled": False,
            "baffle_count": 0,
            "impellers": [{"impeller_type": "anchor", "diameter_m": 0.40, "clearance_m": 0.04}],
        },
        "fluid": {"name": "Polymer Broth", "density_kg_m3": 1050.0, "viscosity_pa_s": 5.0},
        "ops": {
            "rpm": 40.0,
            "rheology_model": "power_law",
            "consistency_k_pa_s_n": 5.0,
            "flow_behavior_index_n": 0.85,
        },
    }
    resp = client.post("/api/theory/evaluate", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    cards = data.get("cards", [])
    pl_cards = [c for c in cards if c.get("key") == "power_law" or "power-law" in c.get("title", "").lower()]
    assert len(pl_cards) == 1, "Expected exactly 1 Power-Law Rheology card"
    pl_card = pl_cards[0]

    assert pl_card["available"] is True
    assert "K = 5" in pl_card["worked_substitution"]
    assert "0.85" in pl_card["worked_substitution"]
    assert "μ_app" in pl_card["result"]


def test_api_preview_geometry_vessel_internals(client):
    """Verify /api/ensemble/preview-geometry generates CAD meshes for sparger, probes, and cooling jacket."""
    payload = {
        "tank": {
            "diameter_m": 0.45,
            "liquid_height_m": 0.50,
            "bottom_type": "flat",
            "is_baffled": True,
            "baffle_count": 4,
            "sparger_type": "pipe",
            "include_probes": True,
            "include_cooling_jacket": True,
            "impellers": [{"impeller_type": "rushton_6_blade", "diameter_m": 0.15, "clearance_m": 0.14}],
        },
        "fluid": {"name": "Water", "density_kg_m3": 1000.0, "viscosity_pa_s": 0.001},
        "ops": {"rpm": 250.0},
    }
    resp = client.post("/api/ensemble/preview-geometry", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    cad = data["cad_meshes"]
    assert "sparger_ring" in cad and len(cad["sparger_ring"]["vertices"]) > 0
    assert "probes" in cad and len(cad["probes"]["vertices"]) > 0
    assert "cooling_jacket" in cad and len(cad["cooling_jacket"]["vertices"]) > 0


def test_all_22_presets_verified_and_cover_all_16_impellers(client):
    """Verify that all 22 presets cover 100% of all 16 impellers and pass verification."""
    from biomix.models import ImpellerType
    from biomix.provenance import inspect_run_provenance
    from biomix.server import RUNS_BASE_DIR, build_ensemble_presets
    import os

    presets = build_ensemble_presets()
    assert len(presets) == 30, f"Expected 30 presets, got {len(presets)}"

    all_16_impellers = set(ImpellerType)
    assert len(all_16_impellers) == 16

    covered_impellers = set()
    for p in presets:
        imp_type = p.tank.impellers[0].impeller_type
        covered_impellers.add(imp_type)

        assert p.is_cached is True, f"Preset {p.preset_id} should be cached"
        assert p.provenance.get("label") is not None

        run_dir = os.path.join(RUNS_BASE_DIR, p.run_id)
        assert os.path.isdir(run_dir), f"Run directory missing: {run_dir}"
        prov = inspect_run_provenance(run_dir)
        assert "label" in prov

    missing = all_16_impellers - covered_impellers
    assert not missing, f"Missing impellers in presets: {missing}"
    assert len(covered_impellers) == 16, f"Expected 16 covered impellers, got {len(covered_impellers)}"


def test_instant_similarity_scaled_fluent_surrogate(client):
    """Verify /api/ensemble/preview-geometry returns scaled Fluent surrogate when parameters deviate."""
    payload = {
        "tank": {
            "diameter_m": 0.40,
            "liquid_height_m": 0.45,
            "bottom_type": "flat",
            "is_baffled": False,
            "baffle_count": 0,
            "impellers": [{"impeller_type": "helical_ribbon", "diameter_m": 0.36, "clearance_m": 0.04}],
        },
        "fluid": {"name": "Polymer Broth", "density_kg_m3": 1050.0, "viscosity_pa_s": 25.0},
        "ops": {
            "rpm": 50.0,  # base is 35.0 RPM
            "rheology_model": "power_law",
            "consistency_k_pa_s_n": 25.0,
            "flow_behavior_index_n": 0.60,
        },
    }
    resp = client.post("/api/ensemble/preview-geometry", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["is_surrogate"] is True
    assert data["base_run_id"] == "fluent_heli_flat_35rpm_c45f087adfac"
    assert data["provenance"]["classification"] == "ansys_fluent_surrogate_scaled"
    assert data["provenance"]["label"] == "Scaled from Verified Fluent Base (Instant Surrogate)"
    assert len(data["streamlines"]) > 0
    assert len(data["vectors_3d"]) > 0
    assert "xz" in data["cross_sections"]


def test_post_simulate_background_thread_no_signal_crash(client):
    """Verify gmsh and background simulate worker never raise ValueError: signal only works in main thread."""
    import threading
    from biomix.cad_mesher import BioreactorCADMesher
    from biomix.models import BottomType, ImpellerSpec, ImpellerType, TankGeometry

    error_holder = []

    def run_worker():
        try:
            tank = TankGeometry(
                diameter_m=0.30,
                liquid_height_m=0.30,
                bottom_type=BottomType.FLAT,
                baffle_count=0,
                impellers=[ImpellerSpec(impeller_type=ImpellerType.HELICAL_RIBBON, diameter_m=0.26, clearance_m=0.03)],
            )
            mesher = BioreactorCADMesher(terminal_output=False)
            mesh = mesher.generate_fluent_mesh(tank, mesh_density="fast")
            assert mesh.n_cells > 0
        except Exception as exc:
            error_holder.append(exc)

    thread = threading.Thread(target=run_worker)
    thread.start()
    thread.join(timeout=30.0)

    assert not error_holder, f"Worker thread raised exception: {error_holder}"



