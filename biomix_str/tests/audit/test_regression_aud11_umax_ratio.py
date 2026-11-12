"""Regression test for AUD-11: Dynamic Peak Velocity Ratio Computation.

Requirement:
- Compute u_max / u_tip from the run's own numbers.
- No hardcoded template values (1.8327, 1.8330, or 1.00).
- Baseline Rushton (c5abfce9ad1c): u_max = 2.0061 m/s, u_tip = 1.8330 m/s -> ratio 1.09.
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

SERVER_PORT = 8604
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"


@pytest.fixture(scope="module")
def live_server_aud11():
    """Start in-process FastAPI server on dedicated port."""
    config = uvicorn.Config(app, host="127.0.0.1", port=SERVER_PORT, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    time.sleep(1.5)
    yield BASE_URL
    server.should_exit = True
    time.sleep(0.5)


def test_regression_aud11_code_implementation():
    """Verify app.js updates ev-parity-umax dynamically from u_max / u_tip."""
    app_js_path = Path(__file__).resolve().parent.parent.parent / "src" / "biomix" / "static" / "app.js"
    assert app_js_path.is_file()
    content = app_js_path.read_text(encoding="utf-8")

    assert "ev-parity-umax" in content
    assert "cfdUmax / utip" in content or "utip > 0" in content


def test_regression_aud11_playwright_umax_ratio(live_server_aud11):
    """Playwright test: Evidence tab displays true computed u_max / u_tip ratio (1.09)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(live_server_aud11)
        page.wait_for_selector("#tab-btn-residuals", timeout=10000)

        # Switch to Evidence Tab
        page.click("#tab-btn-residuals")
        time.sleep(0.5)

        # Baseline Rushton numbers
        cfd_umax = page.eval_on_selector("#ev-cfd-umax", "el => el.textContent.trim()")
        ref_umax = page.eval_on_selector("#ev-ref-umax", "el => el.textContent.trim()")
        parity_umax = page.eval_on_selector("#ev-parity-umax", "el => el.textContent.trim()")

        assert "2.00" in cfd_umax
        assert "1.8330" in ref_umax
        # True ratio is 2.0061 / 1.8330 = 1.094
        assert "1.09" in parity_umax
        assert "1.00" not in parity_umax

        browser.close()
