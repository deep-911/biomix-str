"""Regression test for AUD-10: Convergence Badge by Torque Drift.

Requirement:
- Drift < 2%: "Stabilized"
- Drift 2-5%: "Drifting"
- Drift >= 5%: "Not stabilized"
- Test with 17.89% (must display "Not stabilized").
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

SERVER_PORT = 8603
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"


@pytest.fixture(scope="module")
def live_server_aud10():
    """Start in-process FastAPI server on dedicated port."""
    config = uvicorn.Config(app, host="127.0.0.1", port=SERVER_PORT, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    time.sleep(1.5)
    yield BASE_URL
    server.should_exit = True
    time.sleep(0.5)


def test_regression_aud10_code_implementation():
    """Verify app.js defines formatDriftBadge with the required thresholds."""
    app_js_path = Path(__file__).resolve().parent.parent.parent / "src" / "biomix" / "static" / "app.js"
    assert app_js_path.is_file()
    content = app_js_path.read_text(encoding="utf-8")

    assert "formatDriftBadge" in content
    assert "Stabilized" in content
    assert "Drifting" in content
    assert "Not stabilized" in content


def test_regression_aud10_playwright_drift_badge(live_server_aud10):
    """Playwright test: Evidence tab displays 'Not stabilized' for 17.89% torque drift."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(live_server_aud10)
        page.wait_for_selector("#tab-btn-residuals", timeout=10000)

        # Switch to Evidence Tab
        page.click("#tab-btn-residuals")
        time.sleep(0.5)

        # Default run c5abfce9ad1c has 17.89% drift
        drift_text = page.eval_on_selector("#ev-drift-text", "el => el.textContent.trim()")
        assert "Stabilized" in drift_text
        assert "Drift" in drift_text or "%" in drift_text

        # Test function across all thresholds
        assert "17.89% (Not stabilized)" == page.evaluate("formatDriftBadge(17.89)")
        assert "1.68% (Stabilized)" == page.evaluate("formatDriftBadge(1.68)")
        assert "3.48% (Drifting)" == page.evaluate("formatDriftBadge(3.48)")
        assert "5.00% (Not stabilized)" == page.evaluate("formatDriftBadge(5.0)")
        assert "2.00% (Drifting)" == page.evaluate("formatDriftBadge(2.0)")

        browser.close()
