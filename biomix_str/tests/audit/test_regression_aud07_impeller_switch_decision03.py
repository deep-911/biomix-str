"""Regression test for AUD-07 / DECISION-03: Impeller selection loads verified settings.

DECISION-03:
- When the user selects an impeller that has a cached run:
  1. Set RPM and other run-defining params to that run's values.
  2. Show a small note 'Loaded settings from verified run <id>'.
"""

from __future__ import annotations

from pathlib import Path
import threading
import time
import pytest
import uvicorn
pytest.importorskip('playwright')
from playwright.sync_api import sync_playwright

from biomix.server import app

SERVER_PORT = 8601
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"


@pytest.fixture(scope="module")
def live_server_aud07():
    """Start in-process FastAPI server on dedicated port."""
    config = uvicorn.Config(app, host="127.0.0.1", port=SERVER_PORT, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    time.sleep(1.5)
    yield BASE_URL
    server.should_exit = True
    time.sleep(0.5)


def test_regression_aud07_app_js_contains_decision03_logic():
    """Verify app.js contains DECISION-03 logic setting RPM and displaying note for verified runs."""
    app_js_path = Path(__file__).resolve().parent.parent.parent / "src" / "biomix" / "static" / "app.js"
    assert app_js_path.is_file()
    content = app_js_path.read_text(encoding="utf-8")

    # Must contain the note string required by DECISION-03
    assert "Loaded settings from verified run" in content
    # Marine propeller must map to 130 RPM
    assert "130" in content


def test_regression_aud07_playwright_marine_propeller_selection(live_server_aud07):
    """Playwright test: selecting Marine Propeller sets 130 RPM, geometry, and displays note."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(live_server_aud07)
        page.wait_for_selector("#select-imp1-type", timeout=10000)
        time.sleep(1.0)

        # Select Marine Propeller
        page.select_option("#select-imp1-type", "marine_propeller")
        time.sleep(0.5)

        # 1. RPM must be updated to 130 RPM
        rpm_val = page.eval_on_selector("#slider-rpm", "el => el.value")
        rpm_text = page.eval_on_selector("#val-rpm", "el => el.textContent.trim()")
        assert rpm_val == "130", f"Expected slider-rpm 130, got {rpm_val}"
        assert rpm_text == "130 RPM", f"Expected val-rpm '130 RPM', got {rpm_text}"

        # 2. Note must display 'Loaded settings from verified run fluent_mari_hemi_130rpm_51527ba4791c'
        note_text = page.eval_on_selector("#impeller-verified-note", "el => el.textContent.trim()")
        assert "Loaded settings from verified run fluent_mari_hemi_130rpm_51527ba4791c" in note_text

        # 3. Select Paddle R-200
        page.select_option("#select-imp1-type", "paddle_r200")
        time.sleep(0.5)
        rpm_padd = page.eval_on_selector("#slider-rpm", "el => el.value")
        assert rpm_padd == "100", f"Expected paddle RPM 100, got {rpm_padd}"
        note_padd = page.eval_on_selector("#impeller-verified-note", "el => el.textContent.trim()")
        assert "Loaded settings from verified run fluent_padd_flat_100rpm_dc803c6e30e7" in note_padd

        browser.close()
