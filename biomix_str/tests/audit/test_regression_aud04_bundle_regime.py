"""Regression test for AUD-04/16: API layer dynamic Re and flow regime classification.

Verifies:
1. All 31 completed runs return valid Re = rho * N * D^2 / mu and flow_regime in /api/runs/{run_id}/bundle.
2. The preset-click path (/api/ensemble/preview-geometry) and cached-run path give the EXACT SAME regime for the same state.
"""

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from biomix.server import app, RUNS_BASE_DIR
from biomix.correlations import classify_flow_regime, calc_reynolds_number

client = TestClient(app)
RUNS_DIR = Path(RUNS_BASE_DIR)


def get_completed_run_ids() -> list[str]:
    completed = []
    for d in sorted(RUNS_DIR.iterdir()):
        if d.is_dir() and (d / "metadata.json").is_file() and (d / "config.json").is_file():
            completed.append(d.name)
    return completed


COMPLETED_RUNS = get_completed_run_ids()


@pytest.mark.parametrize("run_id", COMPLETED_RUNS)
def test_all_31_runs_bundle_regime_and_reynolds(run_id: str):
    """Verify /api/runs/{run_id}/bundle computes correct finite Re and regime."""
    resp = client.get(f"/api/runs/{run_id}/bundle")
    assert resp.status_code == 200, f"Failed to get bundle for {run_id}"
    data = resp.json()

    cfg = data["config"]
    rho = cfg.get("fluid", {}).get("density_kg_m3", 1000.0)
    mu = cfg.get("fluid", {}).get("viscosity_pa_s") or cfg.get("fluid", {}).get("dynamic_viscosity_pa_s", 0.001)
    rpm = cfg["ops"]["rpm"]
    d_imp = cfg["tank"]["impellers"][0]["diameter_m"]

    expected_re = calc_reynolds_number(rho, rpm / 60.0, d_imp, mu)
    expected_regime = classify_flow_regime(expected_re).value

    # Check bundle top-level fields
    assert "flow_regime" in data, "flow_regime missing in /bundle response"
    assert data["flow_regime"] == expected_regime, (
        f"{run_id}: data.flow_regime is '{data['flow_regime']}', expected '{expected_regime}'"
    )

    # Check enriched metadata in response
    meta = data["metadata"]
    assert meta["flow_regime"] == expected_regime, (
        f"{run_id}: metadata.flow_regime is '{meta['flow_regime']}', expected '{expected_regime}'"
    )
    assert abs(meta["reynolds_number"] - expected_re) / expected_re < 0.01, (
        f"{run_id}: metadata.reynolds_number {meta['reynolds_number']} does not match expected {expected_re}"
    )


@pytest.mark.parametrize("run_id", COMPLETED_RUNS)
def test_preset_path_and_bundle_path_give_same_regime(run_id: str):
    """Verify preset-click path and cached-run path give the SAME regime for the same state."""
    # 1. Query bundle path
    resp_bundle = client.get(f"/api/runs/{run_id}/bundle")
    assert resp_bundle.status_code == 200
    bundle_data = resp_bundle.json()
    cfg = bundle_data["config"]

    # 2. Query preview-geometry path with identical config
    payload = {
        "tank": cfg["tank"],
        "fluid": cfg["fluid"],
        "ops": cfg["ops"],
    }
    resp_preview = client.post("/api/ensemble/preview-geometry", json=payload)
    assert resp_preview.status_code == 200
    preview_data = resp_preview.json()

    bundle_regime = bundle_data["flow_regime"]
    preview_regime = preview_data["flow_regime"]

    assert bundle_regime is not None, f"{run_id}: bundle flow_regime is None"
    assert preview_regime is not None, f"{run_id}: preview flow_regime is None"
    assert bundle_regime == preview_regime, (
        f"{run_id}: Mismatch between bundle regime '{bundle_regime}' and preview regime '{preview_regime}'"
    )
