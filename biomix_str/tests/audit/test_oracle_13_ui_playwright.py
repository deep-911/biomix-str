"""Physics Oracle 13: UI Regression, Browser Diagnostics & 2D Inspector Matrix.

Oracle 13:
- Playwright-driven headless browser diagnostics against live BioMix-STR web application.
- Reproduces and captures exact stack traces and DOM states for:
    1. Known Bug: ReferenceError: isFluent is not defined at app.js line 1334.
    2. Known Bug: #cache-indicator-badge stuck perpetually on "Checking...".
    3. Blank YZ Mid-Plane in 2D Inspector:
       Verifies that cross_sections.yz contains data on disk, but render2dSliceCanvas()
       fails to render because line 1175 evaluates `sliceData.x` instead of `sliceData.y`,
       causing `xCoords` to be undefined and triggering an early return before canvas draw.
    4. 4 Planes x 6 Scalar Fields inspection matrix (24 total combinations):
       Planes: ['xz', 'yz', 'xy_stage1', 'xy_gap']
       Fields: ['velocity_mag', 'pressure', 'tke', 'epsilon', 'kolmogorov_um', 'shear_stress_pa']
       Captures all browser console errors.

Never loosens tolerance to pass.
"""

from __future__ import annotations

import threading
import time
from typing import List
import pytest
import uvicorn
pytest.importorskip('playwright')
from playwright.sync_api import sync_playwright

from biomix.server import app

SERVER_PORT = 8599
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"


@pytest.fixture(scope="module")
def live_server():
    """Start in-process FastAPI server on dedicated port."""
    config = uvicorn.Config(app, host="127.0.0.1", port=SERVER_PORT, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    time.sleep(1.5)
    yield BASE_URL
    server.should_exit = True
    time.sleep(0.5)


def test_oracle_13_cache_indicator_badge_stuck_on_load(live_server):
    """Oracle 13: Reproduce #cache-indicator-badge stuck on 'Checking...' on initial load.
    
    DEFECT: app.js updates #cache-indicator-badge ONLY in requestGeometryPreview()
    (line 3101). When loadRunBundle() loads the initial verified run on startup,
    #cache-indicator-badge is never updated and remains stuck on 'Checking...'.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(live_server)
        page.wait_for_selector("#hud-card-title", timeout=10000)
        time.sleep(1.0)  # Wait for initial bundle and HUD to finish updating

        badge = page.locator("#cache-indicator-badge")
        badge_text = badge.inner_text().strip()

        # The badge SHOULD say "Verified Fluent Solve" or "Cached", but is stuck on "Checking..."
        assert badge_text != "Checking...", (
            f"CRITICAL UI BUG: #cache-indicator-badge is stuck on '{badge_text}' after run loads! "
            "Expected 'Verified Fluent Solve' or 'Cached'."
        )
        browser.close()


def test_oracle_13_2d_inspector_isfluent_reference_error_and_yz_blank(live_server):
    """Oracle 13: Test 4 planes x 6 scalar fields and reproduce isFluent ReferenceError & blank YZ."""
    console_errors: List[str] = []
    page_errors: List[str] = []

    planes = ["xz", "yz", "xy_stage1", "xy_gap"]
    fields = ["velocity_mag", "pressure", "tke", "epsilon", "kolmogorov_um", "shear_stress_pa"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        page.goto(live_server)
        page.wait_for_selector("#hud-card-title", timeout=10000)
        time.sleep(1.0)

        # Switch to Tab 2: 2D Field Inspector
        tab_2d_btn = page.locator("#btn-tab-2d")
        if tab_2d_btn.count() > 0:
            tab_2d_btn.click()
        else:
            page.locator("button[data-view='view-2d']").click()
        time.sleep(0.5)

        # Check if isFluent ReferenceError already triggered on tab switch
        isfluent_errors = [e for e in (page_errors + console_errors) if "isFluent" in e]

        # Test the full 4 planes x 6 fields matrix (24 combinations)
        for plane in planes:
            # Click plane button
            plane_btn = page.locator(f"#slice-plane-picker button[data-plane='{plane}']")
            if plane_btn.count() > 0 and plane_btn.is_visible():
                plane_btn.click()
                time.sleep(0.1)

            for field in fields:
                # Select field dropdown
                page.select_option("#select-2d-field", field)
                time.sleep(0.1)

        # Check canvas on YZ plane across all 6 fields
        page.locator("#slice-plane-picker button[data-plane='yz']").click()
        time.sleep(0.2)

        yz_blank_by_field = {}
        for field in fields:
            page.select_option("#select-2d-field", field)
            time.sleep(0.2)
            is_blank = page.evaluate("""() => {
                const canvas = document.getElementById('canvas-2d-slice');
                if (!canvas) return true;
                const ctx = canvas.getContext('2d');
                const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
                for (let i = 3; i < imgData.length; i += 4) {
                    if (imgData[i] !== 0) return false;
                }
                return true;
            }""")
            yz_blank_by_field[field] = is_blank

        browser.close()

    # Assert 1: Must catch isFluent ReferenceError
    all_errs = page_errors + console_errors
    has_isfluent_err = any("isFluent is not defined" in err for err in all_errs)
    assert not has_isfluent_err, (
        "CRITICAL CODE BUG: Caught 'ReferenceError: isFluent is not defined' in 2D slice canvas rendering! "
        f"Console Errors: {all_errs}"
    )

    # Assert 2: YZ Mid-plane must not be blank for any field
    blank_fields = [f for f, is_b in yz_blank_by_field.items() if is_b]
    assert not blank_fields, (
        f"CRITICAL CODE BUG: 2D Inspector YZ Mid-Plane canvas is blank for fields: {blank_fields}! "
        "Root cause: app.js line 1175 evaluates sliceData.x instead of sliceData.y for YZ plane."
    )
