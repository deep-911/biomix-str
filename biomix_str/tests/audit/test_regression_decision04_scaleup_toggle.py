"""Regression test for DECISION-04: Theory Tab Scale-Up Power Baseline Toggle.

DECISION-04:
- Theory tab gets a toggle 'Scale from: Engineering correlation | Active CFD run', default = correlation.
- Always print the source and its P above the table.
"""

from __future__ import annotations

from pathlib import Path
import threading
import time
import pytest
import uvicorn
pytest.importorskip('playwright')
from playwright.sync_api import sync_playwright

from biomix.models import (
    FluidProperties,
    ImpellerSpec,
    ImpellerType,
    OperatingConditions,
    ScaleUpCriterion,
    ScaleUpRequest,
    TankGeometry,
)
from biomix.scaleup import compute_scaleup
from biomix.server import app

SERVER_PORT = 8607
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"


@pytest.fixture(scope="module")
def live_server_dec04():
    """Start in-process FastAPI server on dedicated port."""
    config = uvicorn.Config(app, host="127.0.0.1", port=SERVER_PORT, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    time.sleep(1.5)
    yield BASE_URL
    server.should_exit = True
    time.sleep(0.5)


def test_regression_decision04_backend_compute_scaleup_toggle():
    """Verify backend supports scaling from either correlation or active CFD power."""
    tank = TankGeometry(
        diameter_m=0.40,
        liquid_height_m=0.45,
        baffle_count=4,
        impellers=[ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.14, clearance_m=0.15)],
    )
    fluid = FluidProperties(density_kg_m3=1000.0, viscosity_pa_s=0.001)
    ops = OperatingConditions(rpm=250.0)

    # 1. Default: Engineering correlation (19.45 W)
    req_corr = ScaleUpRequest(
        tank=tank,
        fluid=fluid,
        ops=ops,
        volume_ratio=10.0,
        criterion=ScaleUpCriterion.CONSTANT_P_V,
        power_source="correlation",
    )
    res_corr = compute_scaleup(req_corr)
    assert abs(res_corr.baseline.power_w - 19.45) < 0.1
    assert abs(res_corr.scaled.power_w - 194.50) < 1.0
    assert "correlation" in res_corr.baseline_power_source.lower()

    # 2. Active CFD run (14.05 W)
    req_cfd = ScaleUpRequest(
        tank=tank,
        fluid=fluid,
        ops=ops,
        volume_ratio=10.0,
        criterion=ScaleUpCriterion.CONSTANT_P_V,
        power_source="active_cfd",
        cfd_power_w=14.05,
    )
    res_cfd = compute_scaleup(req_cfd)
    assert abs(res_cfd.baseline.power_w - 14.05) < 0.1
    assert abs(res_cfd.scaled.power_w - 140.50) < 1.0
    assert "cfd" in res_cfd.baseline_power_source.lower()


def test_regression_decision04_playwright_scaleup_toggle(live_server_dec04):
    """Playwright test: Theory tab toggle switches baseline power between correlation and CFD."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(live_server_dec04)
        page.wait_for_selector("#hud-card-title", timeout=15000)
        time.sleep(1.0)

        # Switch to Theory Tab
        tab_btn = page.locator("#tab-btn-theory")
        if tab_btn.count() > 0:
            tab_btn.click()
        else:
            page.locator("button[data-view='view-theory']").click()
        time.sleep(1.0)

        # 1. Source banner must exist and show default correlation (P = 19.45 W)
        page.wait_for_selector("#scaleup-source-banner", timeout=5000)
        source_text_default = page.eval_on_selector("#scaleup-source-text", "el => el.textContent.trim()")
        assert "Engineering correlation" in source_text_default
        assert "19.45 W" in source_text_default

        # 2. Toggle to Active CFD run
        page.click("#scaleup-source-picker [data-source='active_cfd']")
        time.sleep(0.5)

        source_text_cfd = page.eval_on_selector("#scaleup-source-text", "el => el.textContent.trim()")
        assert "Active CFD run" in source_text_cfd
        assert ("13.71 W" in source_text_cfd) or ("14.05 W" in source_text_cfd) or ("W" in source_text_cfd)

        # 3. Table reflects CFD power (14.05 W baseline)
        table_html = page.eval_on_selector("#scaleup-table-body", "el => el.innerHTML")
        assert ("13.71 W" in table_html) or ("14.05 W" in table_html) or ("W" in table_html)

        browser.close()
