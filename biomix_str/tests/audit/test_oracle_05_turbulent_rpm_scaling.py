"""Physics Oracle 5: Turbulent RPM Scaling Exponents (P ~ N^3, u_max ~ N).

Oracle 5:
- In turbulent baffled agitation, dynamic similitude dictates:
    * Mechanical shaft power: P ~ N^3  (alpha_P = 3.0)
    * Domain peak velocity: u_max ~ N  (alpha_u = 1.0)
    * Velocity ratio u_max / u_tip should be invariant with RPM under geometric similarity.
- Known suspect: Comparison between 250 RPM and 400 RPM Rushton runs gave:
    * P exponent ~ 2.717 (expected 3.0)
    * u_max exponent ~ 0.761 (expected 1.0)
    * u_max / u_tip dropped from 1.094 to 0.979
- Pinpoints root cause:
    * 250 RPM baseline (c5abfce9ad1c): D = 0.15 m, T = 0.45 m, H = 0.50 m
    * 400 RPM run (f11532130aa6): D = 0.14 m, T = 0.40 m, H = 0.45 m
    * The geometric scale changed without notifying the user, causing apparent scaling failure.

Never loosens tolerance to pass.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import pytest

from biomix.server import RUNS_BASE_DIR

RUNS_DIR = Path(RUNS_BASE_DIR)


def load_run(run_id: str):
    r_dir = RUNS_DIR / run_id
    with open(r_dir / "metadata.json", "r", encoding="utf-8") as f:
        meta = json.load(f)
    with open(r_dir / "config.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return meta, cfg


REASON_C = (
    "DATA-OPEN: 250 RPM run (64,202 cells, 15 iters, drift 17.89%, Np=3.61) "
    "and 400 RPM run (14,570 cells, 15 iters, drift 1.27%, Np=3.16) have vastly different "
    "grid densities and convergence states; pending grid-converged re-run"
)


@pytest.mark.data_pending
@pytest.mark.xfail(strict=True, reason=REASON_C)
def test_oracle_05_rushton_power_cubic_scaling():
    """Oracle 5: Turbulent power scaling P ~ N^3 between 250 RPM and 400 RPM.
    
    Expected exponent alpha_P in [2.90, 3.10].
    """
    m250, c250 = load_run("fluent_rush_flat_250rpm_c5abfce9ad1c")
    m400, c400 = load_run("fluent_rush_flat_400rpm_f11532130aa6")

    rpm1 = c250["ops"]["rpm"]
    rpm2 = c400["ops"]["rpm"]
    p1 = m250["cfd_power_w"]
    p2 = m400["cfd_power_w"]

    alpha_p = math.log(p2 / p1) / math.log(rpm2 / rpm1)

    assert 2.90 <= alpha_p <= 3.10, (
        f"Oracle 5 violation: Power exponent between {rpm1} RPM (P={p1} W) and {rpm2} RPM (P={p2} W) "
        f"is alpha_P = {alpha_p:.4f} (expected ~3.00). "
        f"Root Cause: Vessel geometry changed (250 RPM has D=0.15m, T=0.45m; 400 RPM has D=0.14m, T=0.40m)."
    )


@pytest.mark.data_pending
@pytest.mark.xfail(strict=True, reason=REASON_C)
def test_oracle_05_rushton_velocity_linear_scaling():
    """Oracle 5: Domain peak velocity scaling u_max ~ N between 250 RPM and 400 RPM.
    
    Expected exponent alpha_u in [0.95, 1.05].
    """
    m250, c250 = load_run("fluent_rush_flat_250rpm_c5abfce9ad1c")
    m400, c400 = load_run("fluent_rush_flat_400rpm_f11532130aa6")

    rpm1 = c250["ops"]["rpm"]
    rpm2 = c400["ops"]["rpm"]
    u1 = m250["cfd_max_velocity_m_s"]
    u2 = m400["cfd_max_velocity_m_s"]

    alpha_u = math.log(u2 / u1) / math.log(rpm2 / rpm1)

    assert 0.95 <= alpha_u <= 1.05, (
        f"Oracle 5 violation: Velocity exponent between {rpm1} RPM (u_max={u1} m/s) and {rpm2} RPM (u_max={u2} m/s) "
        f"is alpha_u = {alpha_u:.4f} (expected ~1.00)."
    )


@pytest.mark.data_pending
@pytest.mark.xfail(strict=True, reason=REASON_C)
def test_oracle_05_rushton_tip_speed_ratio_invariance():
    """Oracle 5: u_max / u_tip ratio must remain consistent within 3% between 250 RPM and 400 RPM."""
    m250, _ = load_run("fluent_rush_flat_250rpm_c5abfce9ad1c")
    m400, _ = load_run("fluent_rush_flat_400rpm_f11532130aa6")

    ratio_250 = m250["cfd_max_velocity_m_s"] / m250["tip_speed_m_s"]
    ratio_400 = m400["cfd_max_velocity_m_s"] / m400["tip_speed_m_s"]

    diff_pct = abs(ratio_400 - ratio_250) / ratio_250 * 100.0

    assert diff_pct <= 3.0, (
        f"Oracle 5 violation: u_max/u_tip drifted from {ratio_250:.4f} (250 RPM) to {ratio_400:.4f} (400 RPM) "
        f"(drift = {diff_pct:.1f}% > 3.0% tolerance)."
    )
