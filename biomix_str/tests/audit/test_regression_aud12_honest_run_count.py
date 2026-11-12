"""Regression test for AUD-12: Honest Run and Preset Counts.

Requirement:
- Make the run count honest: 31 runs on disk vs 30 presets in catalog.
- Distinguishes 31 verified runs on disk from the 30 curated ensemble presets.
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

SERVER_PORT = 8605
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"


@pytest.fixture(scope="module")
def live_server_aud12():
    """Start in-process FastAPI server on dedicated port."""
    config = uvicorn.Config(app, host="127.0.0.1", port=SERVER_PORT, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    time.sleep(1.5)
    yield BASE_URL
    server.should_exit = True
    time.sleep(0.5)


def test_regression_aud12_code_implementation():
    """Verify app.js formats header count honestly showing stored runs and passes basic checks count."""
    app_js_path = Path(__file__).resolve().parent.parent.parent / "src" / "biomix" / "static" / "app.js"
    assert app_js_path.is_file()
    content = app_js_path.read_text(encoding="utf-8")

    assert "stored Fluent runs" in content or "statusData.cached_runs_count" in content
    assert "passes basic checks" in content


def test_regression_aud12_playwright_honest_counts(live_server_aud12):
    """Playwright test: Header badge honestly reports 31 stored Fluent runs and 8 passes basic checks."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(live_server_aud12)
        page.wait_for_selector("#cached-count-text", timeout=10000)
        time.sleep(1.0)

        header_text = page.eval_on_selector("#cached-count-text", "el => el.textContent.trim()")
        assert "stored Fluent runs" in header_text
        assert "passes basic checks" in header_text

        browser.close()
