"""Regression test for AUD-06: Duplicate FastAPI Routes."""

from fastapi.testclient import TestClient
from biomix.server import app

client = TestClient(app)


def test_no_duplicate_routes_in_fastapi():
    """Verify that every route (path + HTTP method) registered in FastAPI is unique."""
    route_signatures = set()
    duplicates = []

    for route in app.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            for method in route.methods:
                sig = (method, route.path)
                if sig in route_signatures:
                    duplicates.append(sig)
                route_signatures.add(sig)

    assert not duplicates, f"Found duplicate FastAPI routes: {duplicates}"


def test_scaleup_route_functional():
    """Verify POST /api/theory/scaleup is active and returns valid scaleup response."""
    resp = client.post("/api/theory/scaleup", json={"volume_ratio": 5.0, "criterion": "constant_p_v"})
    assert resp.status_code == 200
    data = resp.json()
    assert "baseline" in data
    assert "scaled" in data


def test_report_route_functional():
    """Verify GET /api/runs/{run_id}/report is active and returns valid markdown."""
    resp = client.get("/api/runs/fluent_rush_flat_250rpm_c5abfce9ad1c/report?format=markdown")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
