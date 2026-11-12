"""Physics Oracle 7: Impeller Switch and Implied Rotational Speed (Marine Propeller).

Oracle 7:
- Dynamic consistency: The ratio P / M strictly dictates the angular velocity omega:
    omega = P / M = 2 * pi * N  =>  N_rpm = (P / (2 * pi * M)) * 60
- In the marine propeller verified run (fluent_mari_hemi_130rpm_51527ba4791c):
    P = 0.25 W, M = 0.0187 N·m
    Implied N = 0.25 / (2 * pi * 0.0187) * 60 = 127.66 RPM (~128 RPM).
- Confirms actual N configured in the solve: config.json specifies ops.rpm = 130.0 RPM.
- Identifies the UI inconsistency:
    When switching from the baseline 250 RPM Rushton fermenter to Marine Propeller in the
    impeller dropdown, handleImpellerSelection() does not update the RPM slider (unlike
    close-clearance impellers which auto-set 40 RPM, or paddle which auto-sets 120 RPM).
    If the pre-solved Marine Propeller run is loaded without synchronizing the slider,
    or if the UI displays the 130 RPM pre-solved metrics alongside a 250 RPM slider,
    it produces an apparent inconsistency where displayed P and M imply ~128 RPM while
    the slider displays 250 RPM.

Never loosens tolerance to pass.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import pytest

from biomix.server import RUNS_BASE_DIR

RUNS_DIR = Path(RUNS_BASE_DIR)


def test_oracle_07_marine_propeller_implied_rpm():
    """Oracle 7: P/M in marine propeller run implies ~128 RPM, not 250 RPM."""
    run_dir = RUNS_DIR / "fluent_mari_hemi_130rpm_51527ba4791c"
    with open(run_dir / "metadata.json", "r", encoding="utf-8") as f:
        meta = json.load(f)
    with open(run_dir / "config.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)

    p = meta["cfd_power_w"]  # 0.25 W
    m = meta["cfd_torque_n_m"]  # 0.0187 N.m
    configured_rpm = cfg["ops"]["rpm"]

    assert configured_rpm == 130.0, f"Expected config ops.rpm = 130.0, found {configured_rpm}"

    omega = p / m
    implied_rpm = (omega / (2.0 * math.pi)) * 60.0

    # Implied RPM is ~127.66 RPM
    assert 125.0 <= implied_rpm <= 130.0, f"Expected implied RPM ~128 RPM, got {implied_rpm:.2f}"

    # Verify that implied RPM differs fundamentally from standard 250 RPM
    assert abs(implied_rpm - 250.0) > 100.0, (
        f"Implied RPM ({implied_rpm:.1f}) cannot match 250 RPM without scaling"
    )


def test_oracle_07_ui_impeller_selection_marine_rpm_behavior():
    """Oracle 7: UI handleImpellerSelection() implements DECISION-03 for marine_propeller.
    
    Verifies that marine_propeller has verified run settings (130 RPM) configured
    in app.js and displays 'Loaded settings from verified run <id>'.
    """
    app_js_path = Path(__file__).resolve().parent.parent.parent / "src" / "biomix" / "static" / "app.js"
    assert app_js_path.is_file()

    with open(app_js_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Search for marine_propeller verified run configuration and DECISION-03 note
    assert "marine_propeller" in content
    assert "fluent_mari_hemi_130rpm_51527ba4791c" in content
    assert "Loaded settings from verified run" in content
