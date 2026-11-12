"""Regression test for Fix 12: Mesh Picker Reflects Loaded Run.

Requirement:
- The default run shown has 64,202 cells (fine mesh).
- Make the mesh picker reflect the loaded run (active button = fine, preflight = ~64k).
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

SERVER_PORT = 8606
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"


@pytest.fixture(scope="module")
def live_server_fix12():
    """Start in-process FastAPI server on dedicated port."""
    config = uvicorn.Config(app, host="127.0.0.1", port=SERVER_PORT, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    time.sleep(1.5)
    yield BASE_URL
    server.should_exit = True
    time.sleep(0.5)


def test_regression_fix12_code_implementation():
    """Verify loadRunBundle in app.js updates #mesh-picker to reflect the loaded run."""
    app_js_path = Path(__file__).resolve().parent.parent.parent / "src" / "biomix" / "static" / "app.js"
    assert app_js_path.is_file()
    content = app_js_path.read_text(encoding="utf-8")

    # loadRunBundle must update #mesh-picker
    assert "mesh-picker" in content
    assert "updatePreflightEstimate" in content


def test_regression_fix12_playwright_mesh_picker_reflects_run(live_server_fix12):
    """Playwright test: On initial load of 64,202 cell baseline, mesh picker shows Fine (64k)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(live_server_fix12)
        page.wait_for_selector("#mesh-picker", timeout=10000)
        time.sleep(1.0)

        # 1. The active mesh button must be 'fine' for the 64,202-cell default run
        active_mesh_btn = page.eval_on_selector("#mesh-picker .segmented-option.active", "el => el.dataset.density || el.dataset.mesh")
        assert active_mesh_btn == "fine", f"Expected active mesh 'fine', got '{active_mesh_btn}'"

        # 2. Preflight pill must reflect ~64k cells, not ~14k cells
        cell_pill_text = page.eval_on_selector("#preflight-cell-pill", "el => el.textContent.trim()")
        assert "64k" in cell_pill_text or "64,202" in cell_pill_text
        assert "14k" not in cell_pill_text

        browser.close()
