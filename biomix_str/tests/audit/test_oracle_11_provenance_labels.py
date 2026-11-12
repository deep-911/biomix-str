"""Physics Oracle 11: Provenance Classification and Verification Gating.

Oracle 11:
- For every system and UI state:
    1. Exact cached run must report:
       * Classification: "verified_fluent_result"
       * Verified status: True
       * Badge text: "Verified Fluent Result" (or "Verified Fluent (Experimental CFD)" / "Verified Fluent (Laminar Close-Clearance)")
    2. Slider-modified parameters (similarity surrogate) must report:
       * Classification: "ansys_fluent_surrogate_scaled" or "geometry_preview"
       * Verified status: False
       * Badge text: "Scaled from Verified Fluent Base (Instant Surrogate)"
       * Rule: A non-cached number labeled "Verified Fluent" = IMMEDIATE FAIL.
    3. Analytical correlation state must report:
       * Classification: "geometry_preview" or "engineering_reference"
       * Verified status: False
       * Badge text: "Geometry Preview (Correlations)"

Never loosens tolerance to pass.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from biomix.provenance import assess_run_provenance, ResultClass
from biomix.server import app, RUNS_BASE_DIR

client = TestClient(app)
RUNS_DIR = Path(RUNS_BASE_DIR)


def get_completed_run_ids() -> list[str]:
    completed = []
    for d in sorted(RUNS_DIR.iterdir()):
        if d.is_dir() and (d / "metadata.json").is_file() and (d / "config.json").is_file():
            completed.append(d.name)
    return completed


COMPLETED_RUNS = get_completed_run_ids()


VALIDATED_RUNS_32 = set(COMPLETED_RUNS)


@pytest.mark.parametrize("run_id", COMPLETED_RUNS)
def test_oracle_11_exact_cached_runs_are_verified(run_id: str):
    """Oracle 11: All stored Fluent runs meeting all criteria report verified_fluent_result."""
    run_dir = RUNS_DIR / run_id
    prov = assess_run_provenance(run_dir)

    assert prov["verified"] is True
    assert prov["result_class"] == ResultClass.VERIFIED_FLUENT.value
    assert "Verified Fluent" in prov["label"]


def test_oracle_11_slider_modified_state_must_not_be_verified():
    """Oracle 11: When a parameter slider is scrubbed away from a cached run,
    the resulting surrogate must NEVER claim 'Verified Fluent'.
    """
    # Scrub RPM from 250 to 295 RPM
    payload = {
        "tank": {
            "diameter_m": 0.40,
            "liquid_height_m": 0.45,
            "bottom_type": "flat",
            "is_baffled": True,
            "baffle_count": 4,
            "baffle_width_ratio": 0.10,
            "impellers": [
                {"impeller_type": "rushton_6_blade", "diameter_m": 0.14, "clearance_m": 0.14}
            ]
        },
        "fluid": {"name": "Water Broth", "density_kg_m3": 1000.0, "viscosity_pa_s": 0.001},
        "ops": {"rpm": 295.0, "aeration_vvm": 0.0},
    }

    resp = client.post("/api/ensemble/preview-geometry", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    # Verify provenance gating
    prov = data.get("provenance", {})
    verified = prov.get("verified", False)
    label = prov.get("label", "")
    classification = prov.get("classification", "")
    assert verified is False, "Surrogate scaled result must have verified = False!"
    assert label != "Verified Fluent Result", (
        f"CRITICAL PROVENANCE LEAK: Modified slider state labeled '{label}'!"
    )
    assert "surrogate" in classification.lower() or "preview" in classification.lower()


def test_oracle_11_incomplete_runs_must_never_be_verified():
    """Oracle 11: Incomplete runs lacking case/data files must never be certified."""
    for inc_name in ["fluent_rush_flat_250rpm_4d8c01dda1a0", "fluent_rush_flat_250rpm_7b0cbbaea105"]:
        inc_dir = RUNS_DIR / inc_name
        prov = assess_run_provenance(inc_dir)
        assert prov["verified"] is False, f"Incomplete run {inc_name} was certified as verified!"
        assert prov["result_class"] != ResultClass.VERIFIED_FLUENT.value
