"""Unit tests for Fluent runner enhanced exporter and convergence monitors (Part B1-B6).

Tests B1-B6 with synthetic/mock data (no live Fluent needed).
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import pytest
import numpy as np

from biomix.fluent_runner import (
    FluentResidualStep,
    FluentRunMetadata,
    calc_canonical_power_number,
    compute_powers,
    evaluate_convergence_b3,
    export_residuals_csv,
    get_canonical_config_hash,
    scale_torque_for_sector,
)
from biomix.correlations import calc_reynolds_number, classify_flow_regime


def test_b1_top_level_reynolds_and_flow_regime(tmp_path):
    """B1: Write flow_regime and reynolds_number as top-level metadata fields."""
    # Water at 250 RPM, D = 0.14 m, rho = 1000 kg/m^3, mu = 0.001 Pa.s
    rho = 1000.0
    rpm = 250.0
    d_imp = 0.14
    mu = 0.001
    re_turb = calc_reynolds_number(rho, rpm / 60.0, d_imp, mu)
    regime_turb = classify_flow_regime(re_turb).value
    assert re_turb > 10000.0
    assert regime_turb == "turbulent"

    # Viscous fluid at 30 RPM, D = 0.36 m, mu = 15.0 Pa.s (Re = 4.32 < 10.0 -> laminar)
    re_lam = calc_reynolds_number(rho, 30.0 / 60.0, 0.36, 15.0)
    regime_lam = classify_flow_regime(re_lam).value
    assert re_lam < 10.0
    assert regime_lam == "laminar"

    # Verify top-level presence in FluentRunMetadata
    meta = FluentRunMetadata(
        run_id="test_run_b1",
        run_dir=str(tmp_path),
        cached=False,
        n_cells=14000,
        n_nodes=3500,
        meshing_time_s=1.2,
        solve_time_s=34.5,
        omega_rad_s=26.18,
        rpm=rpm,
        tip_speed_m_s=1.83,
        cfd_max_velocity_m_s=2.01,
        cfd_mean_velocity_m_s=0.55,
        cfd_min_pressure_pa=-150.0,
        cfd_max_pressure_pa=450.0,
        cfd_dead_zone_fraction=0.05,
        cfd_power_w=14.05,
        cfd_torque_n_m=0.5365,
        web_bundle_path=str(tmp_path / "web_3d_bundle.json"),
        flow_regime=regime_turb,
        reynolds_number=round(re_turb, 4),
    )
    dumped = json.loads(meta.model_dump_json())
    assert dumped["flow_regime"] == "turbulent"
    assert abs(dumped["reynolds_number"] - re_turb) < 1e-2


def test_b2_save_residuals_csv(tmp_path):
    """B2: Save per-iteration scaled residuals and torque monitor history to residuals.csv."""
    residuals = [
        FluentResidualStep(iteration=1, continuity=0.1, x_velocity=0.08, y_velocity=0.07, z_velocity=0.06, k=0.05, epsilon=0.04),
        FluentResidualStep(iteration=2, continuity=0.05, x_velocity=0.03, y_velocity=0.02, z_velocity=0.02, k=0.01, epsilon=0.01),
        FluentResidualStep(iteration=3, continuity=0.0008, x_velocity=0.00005, y_velocity=0.00004, z_velocity=0.00003, k=0.00002, epsilon=0.00001),
    ]
    torque_history = [0.45, 0.52, 0.5365]

    csv_path = export_residuals_csv(str(tmp_path), residuals, torque_history)
    assert Path(csv_path).is_file()

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))

    assert reader[0] == ["iteration", "continuity", "x_velocity", "y_velocity", "z_velocity", "k", "epsilon", "torque_nm"]
    assert len(reader) == 4  # header + 3 iterations
    assert int(reader[1][0]) == 1
    assert abs(float(reader[3][1]) - 0.0008) < 1e-6
    assert abs(float(reader[3][7]) - 0.5365) < 1e-4


def test_b3_convergence_metrics_and_drift():
    """B3: Save 3-part convergence metrics:
    - continuity residual at stop
    - max residual across all equations at stop
    - torque drift over last 100 iterations: |(mean(last 50) - mean(prev 50)) / mean(last 50)| * 100%
    - flag 'converged': True only if continuity < 1e-3, all others < 1e-4, torque drift < 1.0%, net mass imbalance < 0.1%
    """
    # 1. Perfectly converged case
    residuals_pass = [
        FluentResidualStep(iteration=i, continuity=0.0005, x_velocity=5e-5, y_velocity=4e-5, z_velocity=3e-5, k=2e-5, epsilon=1e-5)
        for i in range(1, 101)
    ]
    # Stable torque over 100 iterations (drift 0.1%)
    torque_pass = [0.5360 + 0.0005 * (i / 100.0) for i in range(100)]
    res = evaluate_convergence_b3(residuals_pass, torque_pass, net_mass_imbalance=0.0005)
    assert res["continuity_residual"] == 0.0005
    assert res["max_residual"] == 0.0005
    assert res["torque_drift_pct"] < 1.0
    assert res["net_mass_imbalance_pct"] < 0.1
    assert res["converged"] is True

    # 2. Fails continuity (> 1e-3)
    residuals_high_cont = [
        FluentResidualStep(iteration=i, continuity=0.002, x_velocity=5e-5, y_velocity=4e-5, z_velocity=3e-5, k=2e-5, epsilon=1e-5)
        for i in range(1, 101)
    ]
    res_cont_fail = evaluate_convergence_b3(residuals_high_cont, torque_pass)
    assert res_cont_fail["converged"] is False

    # 3. Fails other equation (> 1e-4)
    residuals_high_vel = [
        FluentResidualStep(iteration=i, continuity=0.0005, x_velocity=2e-4, y_velocity=4e-5, z_velocity=3e-5, k=2e-5, epsilon=1e-5)
        for i in range(1, 101)
    ]
    res_vel_fail = evaluate_convergence_b3(residuals_high_vel, torque_pass)
    assert res_vel_fail["converged"] is False

    # 4. Fails torque drift (> 1.0%)
    torque_drifting = [0.50 + 0.05 * (i / 100.0) for i in range(100)]  # ~5% drift
    res_drift_fail = evaluate_convergence_b3(residuals_pass, torque_drifting)
    assert res_drift_fail["torque_drift_pct"] > 1.0
    assert res_drift_fail["converged"] is False

    # 5. Verify exact formula for torque drift over 100 iterations
    window_prev50 = [0.50] * 50
    window_last50 = [0.51] * 50  # 0.51 vs 0.50 -> drift = |0.51 - 0.50| / 0.51 * 100% = 1.9608%
    torque_100 = window_prev50 + window_last50
    res_exact = evaluate_convergence_b3(residuals_pass, torque_100)
    expected_drift = abs(0.51 - 0.50) / 0.51 * 100.0
    assert abs(res_exact["torque_drift_pct"] - expected_drift) < 1e-3


def test_b4_shaft_and_dissipation_power():
    """B4: Compute shaft power P_M = M * omega and domain volume dissipation power P_eps = int(rho * epsilon dV)."""
    raw_torque = 0.5365
    omega = 26.1799  # 250 RPM * 2pi / 60
    domain_vol = 0.05655  # pi * (0.2)^2 * 0.45
    mean_eps = 0.08
    rho = 1000.0

    powers = compute_powers(
        raw_torque_nm=raw_torque,
        omega_rad_s=omega,
        sector_fraction=1.0,
        domain_volume_m3=domain_vol,
        mean_epsilon_m2_s3=mean_eps,
        density_kg_m3=rho,
    )
    expected_pm = raw_torque * omega  # 14.045 W
    expected_peps = rho * mean_eps * domain_vol  # 4.524 W
    assert abs(powers["power_shaft_w"] - expected_pm) < 1e-2
    assert abs(powers["power_dissipation_w"] - expected_peps) < 1e-2
    assert abs(powers["power_dissipation_ratio"] - (expected_peps / expected_pm)) < 1e-3


def test_b5_canonical_np_and_hash():
    """B5: Canonical Np calculation: Np = P / (rho * N^3 * D^5). Do not invent a different formula.
    Write get_canonical_config_hash(cfg) and use it everywhere.
    """
    # Test Rushton: P = 14.05 W, rho = 1000, N = 250 RPM, D = 0.14 m
    # N = 250 / 60 = 4.16667 rev/s
    # N^3 = 72.338 rev^3/s^3
    # D^5 = 0.14^5 = 5.37824e-5 m^5
    # denom = 1000 * 72.338 * 5.37824e-5 = 3.8905 W
    # Np = 14.05 / 3.8905 = 3.611
    np_val = calc_canonical_power_number(14.05, 1000.0, 250.0, 0.14)
    assert abs(np_val - 3.611) < 0.01

    cfg1 = {
        "tank": {
            "diameter_m": 0.40,
            "liquid_height_m": 0.45,
            "bottom_type": "flat",
            "is_baffled": True,
            "baffle_count": 4,
            "baffle_width_m": 0.04,
            "impellers": [{"impeller_type": "rushton_6_blade", "diameter_m": 0.14, "clearance_m": 0.14, "blade_count": 6}],
        },
        "fluid": {"density_kg_m3": 1000.0, "viscosity_pa_s": 0.001},
        "ops": {"rpm": 250.0},
        "mesh_density": "fast",
        "iterations": 15,
    }
    h1 = get_canonical_config_hash(cfg1)
    assert len(h1) == 64  # SHA-256 hex string

    # Deterministic: repeated call gives same hash
    assert get_canonical_config_hash(cfg1) == h1

    # Sensitive to RPM
    cfg2 = dict(cfg1)
    cfg2["ops"] = {"rpm": 260.0}
    assert get_canonical_config_hash(cfg2) != h1

    # Sensitive to impeller diameter
    cfg3 = json.loads(json.dumps(cfg1))
    cfg3["tank"]["impellers"][0]["diameter_m"] = 0.15
    assert get_canonical_config_hash(cfg3) != h1


def test_b6_sector_model_torque_scaling():
    """B6: Handle sector models: if the mesh is an N-degree sector or periodic,
    scale torque by sector_fraction (default 1.0; if periodic, scale up).
    Document whether the current setup is 360 full-tank or sector.
    """
    raw_torque = 2.5

    # Full 360 degree vessel domain: sector_fraction = 1.0
    scaled_full = scale_torque_for_sector(raw_torque, sector_fraction=1.0)
    assert scaled_full == 2.5

    # 90 degree quadrant periodic sector (1/4 tank): sector_fraction = 0.25
    scaled_quad = scale_torque_for_sector(raw_torque, sector_fraction=0.25)
    assert scaled_quad == 10.0  # 4x raw torque

    # 180 degree half-tank sector: sector_fraction = 0.50
    scaled_half = scale_torque_for_sector(raw_torque, sector_fraction=0.50)
    assert scaled_half == 5.0
