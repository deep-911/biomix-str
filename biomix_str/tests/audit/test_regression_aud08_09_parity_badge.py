"""Regression test for AUD-08 / AUD-09: Conditional Parity Badges.

Requirement:
- Parity badge conditional: |delta| <= 10% -> "Within ±10% band", else "Outside ±10% band".
- Same function for torque and power.
- Test with -27.8% and -5.0%.
"""

from __future__ import annotations

import re
from pathlib import Path
import threading
import time
import pytest
import uvicorn
pytest.importorskip('playwright')
from playwright.sync_api import sync_playwright

from biomix.server import app

SERVER_PORT = 8602
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"


@pytest.fixture(scope="module")
def live_server_aud08():
    """Start in-process FastAPI server on dedicated port."""
    config = uvicorn.Config(app, host="127.0.0.1", port=SERVER_PORT, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    time.sleep(1.5)
    yield BASE_URL
    server.should_exit = True
    time.sleep(0.5)


def test_regression_aud08_09_code_implementation():
    """Verify app.js defines and uses formatParityBadge for both torque and power."""
    app_js_path = Path(__file__).resolve().parent.parent.parent / "src" / "biomix" / "static" / "app.js"
    assert app_js_path.is_file()
    content = app_js_path.read_text(encoding="utf-8")

    assert "formatParityBadge" in content
    # Both elements must be updated via formatParityBadge
    assert "formatParityBadge(dTorquePct)" in content
    assert "formatParityBadge(dPowerPct)" in content


def test_regression_aud08_09_playwright_parity_badges(live_server_aud08):
    """Playwright test: Evidence tab displays conditional parity badge for -27.8% and -5.0%."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(live_server_aud08)
        page.wait_for_selector("#tab-btn-residuals", timeout=10000)

        # Switch to Evidence Tab (button #tab-btn-residuals / data-view="view-evidence")
        page.click("#tab-btn-residuals")
        time.sleep(0.5)

        # Default loaded run is baseline Rushton (fluent_rush_flat_250rpm_c5abfce9ad1c, delta ~ -27.8%)
        torque_text = page.eval_on_selector("#ev-parity-torque", "el => el.textContent.trim()")
        power_text = page.eval_on_selector("#ev-parity-power", "el => el.textContent.trim()")

        # For -27.8%, it must say Outside +-10% band (or Outside ±10% band)
        assert "Outside" in torque_text
        assert "Outside" in torque_text
        assert "Within" not in torque_text

        assert "Outside" in power_text
        assert "Outside" in power_text
        assert "Within" not in power_text

        # Test formatParityBadge logic directly in page context for -27.8% and -5.0%
        result_neg28 = page.evaluate("formatParityBadge(-27.8)")
        assert "-27.8%" in result_neg28
        assert "Outside" in result_neg28
        assert "Within" not in result_neg28

        result_neg5 = page.evaluate("formatParityBadge(-5.0)")
        assert "-5.0%" in result_neg5
        assert "Within" in result_neg5
        assert "Outside" not in result_neg5

        browser.close()
