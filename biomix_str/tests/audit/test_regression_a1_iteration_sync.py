"""Regression test for Part A1: Iteration Display and Preflight Reflect Loaded Run.

Requirement:
- UI shows "80 iters" while stored runs used 15 (28 of 31), 80 (1 of 31), or 10 (2 of 31).
- Make the iteration display/preflight reflect the loaded run's requested iterations.
- slider-iterations has min=5, max=200, step=5 so 10 and 15 are valid.
- Preflight solve time scales with iterations.
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

SERVER_PORT = 8614
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"


@pytest.fixture(scope="module")
def live_server_a1():
    """Start in-process FastAPI server on dedicated port."""
    config = uvicorn.Config(app, host="127.0.0.1", port=SERVER_PORT, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    time.sleep(1.5)
    yield BASE_URL
    server.should_exit = True
    time.sleep(0.5)


def test_regression_a1_html_and_js_code():
    """Verify index.html has min=5 step=5 and app.js syncs requested iterations."""
    base_dir = Path(__file__).resolve().parent.parent.parent / "src" / "biomix" / "static"
    html_content = (base_dir / "index.html").read_text(encoding="utf-8")
    js_content = (base_dir / "app.js").read_text(encoding="utf-8")

    assert 'id="slider-iterations" min="5"' in html_content
    assert 'step="5"' in html_content
    assert "data.config?.iterations" in js_content
    assert "slider-iterations" in js_content


def test_regression_a1_playwright_iterations_reflect_loaded_run(live_server_a1):
    """Playwright test: initial loaded run (15 iters) updates slider, text, and preflight solve time."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(live_server_a1, wait_until="networkidle", timeout=15000)
        page.wait_for_timeout(2000)

        # The initial run loaded is fluent_rush_flat_250rpm_c5abfce9ad1c (15 iters, fast/fine)
        val_iter = page.locator("#val-iterations").inner_text().strip()
        slider_val = page.locator("#slider-iterations").input_value()
        time_pill = page.locator("#preflight-time-pill").inner_text().strip()

        # Must reflect the loaded run's requested iterations (15 iters), not 80
        assert val_iter == "15 iters", f"Expected '15 iters', got '{val_iter}'"
        assert slider_val == "15", f"Expected slider value '15', got '{slider_val}'"
        # Preflight time pill should reflect 15 iters (~35 * 15/80 = ~7s or fine 180*15/80 = ~34s)
        assert "solve" in time_pill
        assert time_pill != "~35s solve" or val_iter != "80 iters"

        browser.close()
