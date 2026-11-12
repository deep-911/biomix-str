"""Tests for Phase C: Scale-Up Similarity Engine & Reproducible Engineering Report Generator."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from biomix.models import (
    FluidProperties,
    ImpellerSpec,
    ImpellerType,
    OperatingConditions,
    ScaleUpCriterion,
    ScaleUpRequest,
    TankGeometry,
)
from biomix.report_generator import generate_run_report
from biomix.scaleup import compute_scaleup
from biomix.server import app

RUNS_DIR = Path(__file__).resolve().parent.parent / "outputs" / "fluent_runs"
RUSHTON_RUN_ID = "fluent_rush_flat_250rpm_c5abfce9ad1c"


def test_scaleup_constant_power_per_volume():
    """Verify constant P/V scaling criterion maintains volumetric power density."""
    req = ScaleUpRequest(
        volume_ratio=10.0,
        criterion=ScaleUpCriterion.CONSTANT_P_V,
    )
    res = compute_scaleup(req)

    assert res.volume_ratio == pytest.approx(10.0, rel=1e-3)
    lam = 10.0 ** (1.0 / 3.0)
    assert res.linear_scale_factor_lambda == pytest.approx(lam, rel=1e-3)

    # Volumetric power should be preserved exactly (P2/V2 == P1/V1)
    pv_ratio = res.scaled.power_per_volume_w_m3 / res.baseline.power_per_volume_w_m3
    assert pv_ratio == pytest.approx(1.0, rel=1e-2)

    # Speed follows N2 = N1 * lam^(-2/3)
    expected_rpm = res.baseline.rpm * (lam ** (-2.0 / 3.0))
    assert res.scaled.rpm == pytest.approx(expected_rpm, rel=1e-2)

    # Tip speed increases by lam^(1/3)
    expected_tip = res.baseline.tip_speed_m_s * (lam ** (1.0 / 3.0))
    assert res.scaled.tip_speed_m_s == pytest.approx(expected_tip, rel=1e-2)


def test_scaleup_constant_tip_speed():
    """Verify constant tip speed criterion preserves peripheral blade velocity."""
    req = ScaleUpRequest(
        volume_ratio=10.0,
        criterion=ScaleUpCriterion.CONSTANT_TIP_SPEED,
    )
    res = compute_scaleup(req)

    tip_ratio = res.scaled.tip_speed_m_s / res.baseline.tip_speed_m_s
    assert tip_ratio == pytest.approx(1.0, rel=1e-2)


def test_scaleup_constant_reynolds():
    """Verify constant Reynolds criterion preserves impeller Reynolds number."""
    req = ScaleUpRequest(
        volume_ratio=8.0,
        criterion=ScaleUpCriterion.CONSTANT_REYNOLDS,
    )
    res = compute_scaleup(req)

    re_ratio = res.scaled.re_i / res.baseline.re_i
    assert re_ratio == pytest.approx(1.0, rel=1e-2)


def test_generate_run_report_markdown_and_html():
    """Verify engineering report generation for verified Rushton run in MD and HTML formats."""
    run_path = RUNS_DIR / RUSHTON_RUN_ID
    if not run_path.is_dir():
        pytest.skip(f"Run directory {RUSHTON_RUN_ID} not found")

    # 1. Markdown
    report_md = generate_run_report(run_path, output_format="markdown")
    assert "BioMix-STR Bioreactor Hydrodynamic & CFD Engineering Report" in report_md
    assert "Run Identifier:" in report_md
    assert "Official Provenance Classification:" in report_md
    assert "Mechanical Shaft Power" in report_md
    assert "Active Bioprocess Engineering Theory" in report_md

    # 2. HTML
    report_html = generate_run_report(run_path, output_format="html")
    assert "<!DOCTYPE html>" in report_html
    assert "BioMix-STR Engineering Report" in report_html
    assert "64,172" in report_html or "cells" in report_html


def test_server_scaleup_and_report_endpoints():
    """Verify FastAPI endpoints for scale-up similarity and report download."""
    client = TestClient(app)

    # 1. Report endpoint
    resp_report = client.get(f"/api/runs/{RUSHTON_RUN_ID}/report?format=markdown")
    assert resp_report.status_code == 200
    assert "BioMix-STR" in resp_report.text
    assert resp_report.headers["content-type"].startswith("text/markdown")

    # 2. Scale-Up endpoint
    resp_scaleup = client.post(
        "/api/theory/scaleup",
        json={"volume_ratio": 10.0, "criterion": "constant_p_v"},
    )
    assert resp_scaleup.status_code == 200
    data = resp_scaleup.json()
    assert "baseline" in data
    assert "scaled" in data
    assert "ratios" in data
    assert data["linear_scale_factor_lambda"] > 1.0
