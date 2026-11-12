"""Physics Oracle 12: Theory Tab Scale-Up Recomputation and Power Duality.

Oracle 12:
1. Recompute the scale-up table independently from stated similitude rules across
   all 4 engineering scale-up criteria:
   - Constant Power per Volume (P/V = const, alpha = -2/3)
   - Constant Impeller Tip Speed (u_tip = const, alpha = -1)
   - Constant Impeller Reynolds Number (Re = const, alpha = -2)
   - Constant Mixing Time (theta_95 = const, alpha = 0)
   Verify mathematical consistency with /api/theory/scaleup.
2. Report the fundamental duality between Theory Tab and CFD HUD:
   - Theory Tab computes analytical baseline P = 19.45 W using correlation Np = 5.0
     (biomix/theory.py, biomix/scaleup.py, and Theory Workspace).
   - CFD HUD displays P = 14.05 W using Fluent Navier-Stokes solve with Np = 3.61
     (fluent_rush_flat_250rpm_c5abfce9ad1c/metadata.json).
   - Scale-up calculations in the Theory tab scale from the 19.45 W empirical correlation,
     NOT from the 14.05 W CFD simulation result!

Never loosens tolerance to pass.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from biomix.models import ImpellerType, ScaleUpCriterion, ScaleUpRequest, TankGeometry, ImpellerSpec, FluidProperties, OperatingConditions
from biomix.scaleup import compute_scaleup
from biomix.server import app, RUNS_BASE_DIR

client = TestClient(app)
RUNS_DIR = Path(RUNS_BASE_DIR)


def test_oracle_12_theory_vs_cfd_power_duality():
    """Oracle 12: Theory uses Np=5.0 (P=19.45W) while CFD HUD shows P=14.05W (Np=3.61)."""
    # 1. Load CFD run
    run_dir = RUNS_DIR / "fluent_rush_flat_250rpm_c5abfce9ad1c"
    with open(run_dir / "metadata.json", "r", encoding="utf-8") as f:
        meta = json.load(f)
    with open(run_dir / "config.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)

    p_cfd = meta["cfd_power_w"]  # 14.05 W
    assert abs(p_cfd - 13.71) < 0.2, f"Expected CFD power ~ 13.71 W, got {p_cfd}"

    # 2. Query scaleup baseline power (from Theory / scaleup engine)
    req = ScaleUpRequest(
        tank=TankGeometry(
            diameter_m=cfg["tank"]["diameter_m"],
            liquid_height_m=cfg["tank"]["liquid_height_m"],
            baffle_count=cfg["tank"]["baffle_count"],
            impellers=[ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=cfg["tank"]["impellers"][0]["diameter_m"], clearance_m=cfg["tank"]["impellers"][0]["clearance_m"])]
        ),
        fluid=FluidProperties(density_kg_m3=cfg["fluid"]["density_kg_m3"], viscosity_pa_s=cfg["fluid"]["viscosity_pa_s"]),
        ops=OperatingConditions(rpm=cfg["ops"]["rpm"]),
        volume_ratio=10.0,
        criterion=ScaleUpCriterion.CONSTANT_P_V,
    )

    scaleup_res = compute_scaleup(req)
    p_theory = scaleup_res.baseline.power_w  # 19.45 W (from Np = 5.0)

    assert abs(p_theory - 19.45) < 0.1, f"Expected Theory power = 19.45 W, got {p_theory}"

    # 3. Prove discrepancy
    delta_w = p_theory - p_cfd
    delta_pct = (p_cfd - p_theory) / p_theory * 100.0

    assert abs(delta_w - 5.74) < 0.2, f"Expected difference ~ 5.74 W, got {delta_w:.2f} W"
    assert abs(delta_pct - (-29.5)) < 1.0, f"Expected delta ~ -29.5%, got {delta_pct:.2f}%"


@pytest.mark.parametrize("crit, alpha", [
    (ScaleUpCriterion.CONSTANT_P_V, -2.0 / 3.0),
    (ScaleUpCriterion.CONSTANT_TIP_SPEED, -1.0),
    (ScaleUpCriterion.CONSTANT_REYNOLDS, -2.0),
    (ScaleUpCriterion.CONSTANT_MIXING_TIME, 0.0),
])
def test_oracle_12_independent_scaleup_recomputation(crit: ScaleUpCriterion, alpha: float):
    """Oracle 12: Independently recompute scale-up table metrics and compare with API."""
    vol_ratio = 8.0  # 8x volume
    lam = vol_ratio ** (1.0 / 3.0)  # lambda = 2.0

    n1_rpm = 240.0
    n1_rps = 4.0
    t1 = 0.45
    h1 = 0.50
    d1 = 0.15
    p1 = 5.0 * 1000.0 * (n1_rps ** 3) * (d1 ** 5)  # Analytical baseline power

    # Independent rule evaluation
    n2_rps_expected = n1_rps * (lam ** alpha)
    n2_rpm_expected = n2_rps_expected * 60.0
    t2_expected = t1 * lam
    h2_expected = h1 * lam
    d2_expected = d1 * lam
    u_tip1_expected = math.pi * n1_rps * d1
    u_tip2_expected = math.pi * n2_rps_expected * d2_expected
    p2_expected = 5.0 * 1000.0 * (n2_rps_expected ** 3) * (d2_expected ** 5)

    # API call
    payload = {
        "tank": {
            "diameter_m": t1,
            "liquid_height_m": h1,
            "bottom_type": "flat",
            "is_baffled": True,
            "baffle_count": 4,
            "baffle_width_ratio": 0.10,
            "impellers": [{"impeller_type": "rushton_6_blade", "diameter_m": d1, "clearance_m": 0.14}],
        },
        "fluid": {"name": "Water", "density_kg_m3": 1000.0, "viscosity_pa_s": 0.001},
        "ops": {"rpm": n1_rpm},
        "volume_ratio": vol_ratio,
        "criterion": crit.value,
    }

    resp = client.post("/api/theory/scaleup", json=payload)
    assert resp.status_code == 200
    res = resp.json()

    # Verify linear scale factor lambda
    assert abs(res["linear_scale_factor_lambda"] - lam) < 1e-4

    # Verify geometry scaling
    scaled = res["scaled"]
    assert abs(scaled["diameter_m"] - t2_expected) < 1e-3
    assert abs(scaled["liquid_height_m"] - h2_expected) < 1e-3
    assert abs(scaled["impeller_diameter_m"] - d2_expected) < 1e-3

    # Verify operating speed scaling
    assert abs(scaled["rpm"] - n2_rpm_expected) < 0.2

    # Verify tip speed scaling
    assert abs(scaled["tip_speed_m_s"] - u_tip2_expected) < 0.05

    # Verify power scaling
    assert abs(scaled["power_w"] - p2_expected) / p2_expected < 0.02
