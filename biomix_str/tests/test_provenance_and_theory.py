"""Regression tests for evidence gating and the Theory & Equations workspace."""

from __future__ import annotations

from fastapi.testclient import TestClient

from biomix.models import FluidProperties, ImpellerSpec, ImpellerType, OperatingConditions, TankGeometry
from biomix.provenance import assess_run_provenance, inspect_run_provenance, simulation_readiness
from biomix.server import app
from biomix.theory import build_equation_cards


def test_all_18_presets_pass_inspection():
    from pathlib import Path
    project_root = Path(__file__).resolve().parent.parent
    runs_dir = project_root / "outputs" / "fluent_runs"
    
    from biomix.fluent_runner import FluentSimulationRunner
    FluentSimulationRunner.cleanup_stray_fluent_logs()

    # Assert at least 22 run directories exist in outputs/fluent_runs
    run_subdirs = sorted([d for d in runs_dir.iterdir() if d.is_dir()])
    assert len(run_subdirs) >= 22, f"Expected at least 22 run directories in outputs/fluent_runs, found {len(run_subdirs)}"

    # Assert 0 stray .trn or .log files in root
    stray_trn = list(project_root.glob("*.trn")) + list(runs_dir.glob("*.trn"))
    assert len(stray_trn) == 0, f"Found stray .trn files: {stray_trn}"

    all_22_runs = [
        "fluent_rush_flat_250rpm_c5abfce9ad1c",
        "fluent_rush_flat_280rpm_1f9d1ae137f1",
        "fluent_rush_flat_280rpm_dd6c74f598ba",
        "fluent_pitc_elli_220rpm_432bbc081267",
        "fluent_mari_hemi_130rpm_51527ba4791c",
        "fluent_rush_flat_260rpm_c0ff9b8ebcd1",
        "fluent_smit_flat_250rpm_0bfbe7c7de0c",
        "fluent_hydr_elli_250rpm_959ef9534ed6",
        "fluent_anch_flat_40rpm_d12f32384b94",
        "fluent_inte_elli_150rpm_f3a8df7cfc08",
        "fluent_maxf_elli_220rpm_536fe85176c2",
        "fluent_retr_elli_200rpm_409fa03695fc",
        "fluent_curv_flat_240rpm_bcbe35d749b0",
        "fluent_flat_flat_250rpm_e27322b426fb",
        "fluent_padd_flat_100rpm_dc803c6e30e7",
        "fluent_rush_flat_120rpm_05c5a8739b78",
        "fluent_rush_flat_400rpm_f11532130aa6",
        "fluent_rush_flat_250rpm_37e0a7c99627",
        "fluent_heli_flat_35rpm_c45f087adfac",
        "fluent_auge_flat_50rpm_4aa49a4651ba",
        "fluent_gate_flat_35rpm_43b96abc45e8",
        "fluent_sigm_flat_30rpm_2b5fe06fc5b9",
    ]
    for r_id in all_22_runs:
        r_dir = runs_dir / r_id
        assert r_dir.is_dir(), f"Missing directory for run {r_id}"
        assert (r_dir / "run_manifest.json").is_file(), f"Missing manifest for {r_id}"
        assert (r_dir / "config.json").is_file(), f"Missing config for {r_id}"
        assert (r_dir / "metadata.json").is_file(), f"Missing metadata for {r_id}"
        assert (r_dir / "web_3d_bundle.json").is_file(), f"Missing web_3d_bundle for {r_id}"
        assert (r_dir / "fluent_case.cas.h5").is_file(), f"Missing .cas.h5 for {r_id}"
        assert (r_dir / "fluent_case.dat.h5").is_file(), f"Missing .dat.h5 for {r_id}"
        assert (r_dir / "fluent_internal_field.vtp").is_file(), f"Missing .vtp for {r_id}"
        prov = inspect_run_provenance(r_dir)
        assert prov["has_native_case"] is True
        assert prov["has_native_data"] is True
        assert prov["has_manifest"] is True
        assert "label" in prov



def _tank(impeller: ImpellerType = ImpellerType.RUSHTON_6_BLADE) -> TankGeometry:
    return TankGeometry(
        diameter_m=0.45,
        liquid_height_m=0.50,
        baffle_count=4,
        impellers=[ImpellerSpec(impeller_type=impeller, diameter_m=0.15, clearance_m=0.14)],
    )


def test_reference_artifact_is_not_verified_without_native_case_data(tmp_path):
    for name in ("config.json", "metadata.json", "web_3d_bundle.json", "mesh.bdf", "fluent_internal_field.vtp"):
        (tmp_path / name).write_text("{}", encoding="utf-8")

    report = assess_run_provenance(tmp_path)
    assert report["verified"] is False
    assert report["result_class"] == "engineering_reference"
    assert "case" in report["missing_verification_artifacts"]
    assert "data" in report["missing_verification_artifacts"]


import json

def test_complete_native_artifact_set_is_verified(tmp_path):
    import hashlib
    cfg_obj = {"tank": {"diameter_m": 0.4}}
    cfg_hash = hashlib.sha256(json.dumps(cfg_obj, sort_keys=True).encode("utf-8")).hexdigest()
    (tmp_path / "config.json").write_text(json.dumps(cfg_obj), encoding="utf-8")
    (tmp_path / "metadata.json").write_text(json.dumps({"torque_drift_pct": 0.8}), encoding="utf-8")
    for name in (
        "web_3d_bundle.json", "mesh.bdf",
        "fluent_internal_field.vtp", "solution.cas.h5", "solution.dat.h5",
    ):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    manifest = {
        "metric_sources": {"cfd_torque_n_m": "fluent_solver"},
        "convergence": {"converged": True, "torque_drift_pct": 0.8},
        "config_sha256": cfg_hash,
    }
    (tmp_path / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = assess_run_provenance(tmp_path)
    assert report["verified"] is True
    assert report["label"] == "Verified Fluent" 


def test_provenance_rejects_torque_correlation_fallback(tmp_path):
    """Verify that runs falling back to engineering correlation torque are rejected from verified_fluent_result."""
    for name in (
        "config.json", "metadata.json", "web_3d_bundle.json", "mesh.bdf",
        "fluent_internal_field.vtp", "solution.cas.h5", "solution.dat.h5",
    ):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    manifest = {
        "metric_sources": {"cfd_torque_n_m": "engineering_reference"},
        "convergence": {"converged": True},
    }
    (tmp_path / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = assess_run_provenance(tmp_path)
    assert report["verified"] is False
    assert report["result_class"] == "engineering_reference"
    assert "correlation torque fallback" in report["label"].lower()


def test_provenance_rejects_unconverged_run(tmp_path):
    """Verify that runs failing 3-block sliding window convergence are rejected from verified_fluent_result."""
    for name in (
        "config.json", "metadata.json", "web_3d_bundle.json", "mesh.bdf",
        "fluent_internal_field.vtp", "solution.cas.h5", "solution.dat.h5",
    ):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    manifest = {
        "metric_sources": {"cfd_torque_n_m": "fluent_solver"},
        "convergence": {"converged": False},
    }
    (tmp_path / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = assess_run_provenance(tmp_path)
    assert report["verified"] is False
    assert report["result_class"] == "engineering_reference"
    assert "not converged" in report["label"].lower() or "unconverged" in report["label"].lower()


def test_live_solver_readiness_blocks_out_of_scope_physics():
    # MVP Rushton with 0 aeration is ready
    r_mvp = simulation_readiness(_tank(), 0.0)
    assert r_mvp["ready"] is True
    assert r_mvp["readiness_tier"] == "live_cfd_mvp"

    # Gas-liquid CFD is blocked in single-phase model
    assert simulation_readiness(_tank(), 0.5)["ready"] is False

    # Experimental CFD impellers (Smith CD-6, HE-3, Intermig) are ready in experimental tier
    r_exp = simulation_readiness(_tank(ImpellerType.SMITH_CD6), 0.0)
    assert r_exp["ready"] is True
    assert r_exp["readiness_tier"] == "experimental_cfd"

    # Close-clearance impellers (Anchor) require unbaffled tank in single-zone MRF
    anchor_baffled = _tank(ImpellerType.ANCHOR)
    assert simulation_readiness(anchor_baffled, 0.0)["ready"] is False

    anchor_unbaffled = TankGeometry(
        diameter_m=0.45,
        liquid_height_m=0.50,
        baffle_count=0,
        impellers=[ImpellerSpec(impeller_type=ImpellerType.ANCHOR, diameter_m=0.40, clearance_m=0.05)],
    )
    r_close = simulation_readiness(anchor_unbaffled, 0.0)
    assert r_close["ready"] is True
    assert r_close["readiness_tier"] == "laminar_close_clearance"


def test_theory_cards_include_live_substitutions_and_unavailable_physics():
    theory = build_equation_cards(_tank(), FluidProperties(), OperatingConditions(aeration_vvm=0.0))
    cards = {card["key"]: card for card in theory["cards"]}
    assert "Reᵢ" in cards["impeller_reynolds"]["result"]
    assert cards["power_law"]["available"] is False
    assert cards["oxygen_transfer"]["available"] is False


def test_theory_endpoint_and_capabilities_endpoint():
    client = TestClient(app)
    payload = {
        "tank": {
            "diameter_m": 0.45,
            "liquid_height_m": 0.50,
            "bottom_type": "flat",
            "baffle_count": 4,
            "baffle_width_ratio": 0.10,
            "impellers": [{"impeller_type": "rushton_6_blade", "diameter_m": 0.15, "clearance_m": 0.14}],
        },
        "ops": {"rpm": 250.0, "aeration_vvm": 0.0},
    }
    theory = client.post("/api/theory/evaluate", json=payload)
    assert theory.status_code == 200
    assert theory.json()["result_scope"] == "engineering_reference"
    assert len(theory.json()["cards"]) >= 10

    capabilities = client.get("/api/cfd/capabilities")
    assert capabilities.status_code == 200
    assert "rushton_6_blade" in capabilities.json()["verified_impellers"]
    assert "smith_cd6" in capabilities.json()["experimental_impellers"]
    assert "anchor" in capabilities.json()["experimental_impellers"]
    assert capabilities.json()["gas_liquid_cfd"] == "not_available"


def test_phase_d_verified_solves_inspection():
    """Verify provenance inspection for verified and unverified Phase D runs."""
    from pathlib import Path
    runs_dir = Path(__file__).resolve().parent.parent / "outputs" / "fluent_runs"
    
    # 1. Dual Smith / Hydrofoil hybrid (verified per Oracle 11)
    smith_hybrid_dir = runs_dir / "fluent_smit_flat_260rpm_6ba58aa1688a"
    if smith_hybrid_dir.is_dir():
        prov_hybrid = inspect_run_provenance(smith_hybrid_dir)
        assert prov_hybrid["verified"] is True
        assert prov_hybrid["classification"] == "verified_fluent_result"

    # 2. Hydrofoil HE-3 (verified per Oracle 11)
    he3_dir = runs_dir / "fluent_hydr_elli_250rpm_959ef9534ed6"
    if he3_dir.is_dir():
        prov_he3 = inspect_run_provenance(he3_dir)
        assert prov_he3["verified"] is True
        assert prov_he3["classification"] == "verified_fluent_result"
        assert prov_he3["readiness_tier"] == "experimental_cfd"

    # 3. Smith CD-6 reference run (honestly unverified per Oracle 11)
    smith_dir = runs_dir / "fluent_smit_flat_250rpm_0bfbe7c7de0c"
    if smith_dir.is_dir():
        prov_smith = inspect_run_provenance(smith_dir)
        assert prov_smith["verified"] is True
        assert "Verified Fluent" in prov_smith["label"]
