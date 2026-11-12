"""Oracle A v2: Surrogate Validation via Live Endpoint.

For pairs of cached runs differing in ONE parameter (e.g. RPM 120/250/400),
predict B from A by invoking the EXACT same endpoint the slider HUD uses:
POST /api/ensemble/preview-geometry (with force_surrogate=True and base_run_id=A).
Report % error in P, M, and u_max vs real cached B.
Saves results to docs/audit/oracle_A_v2.txt.
"""

import json
import math
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from biomix.server import app

RUNS_DIR = Path(__file__).resolve().parent.parent.parent / "outputs" / "fluent_runs"
AUDIT_DOCS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "docs" / "audit"


def find_single_param_pairs():
    """Discover all completed run pairs differing in exactly one parameter."""
    runs = {}
    for p in RUNS_DIR.iterdir():
        if not p.is_dir():
            continue
        cfg_f = p / "config.json"
        meta_f = p / "metadata.json"
        bundle_f = p / "web_3d_bundle.json"
        if cfg_f.exists() and meta_f.exists() and bundle_f.exists():
            with open(cfg_f, "r", encoding="utf-8") as f1, open(meta_f, "r", encoding="utf-8") as f2:
                runs[p.name] = (json.load(f1), json.load(f2))

    pairs = []
    keys = sorted(runs.keys())
    for i in range(len(keys)):
        for j in range(len(keys)):
            if i == j:
                continue
            r1 = keys[i]
            r2 = keys[j]
            c1, m1 = runs[r1]
            c2, m2 = runs[r2]
            imp1 = c1["tank"]["impellers"][0]["impeller_type"]
            imp2 = c2["tank"]["impellers"][0]["impeller_type"]
            if imp1 != imp2:
                continue

            diffs = []
            if c1["ops"]["rpm"] != c2["ops"]["rpm"]:
                diffs.append("rpm")
            v1 = c1["fluid"].get("viscosity_pa_s") or c1["fluid"].get("dynamic_viscosity_pa_s")
            v2 = c2["fluid"].get("viscosity_pa_s") or c2["fluid"].get("dynamic_viscosity_pa_s")
            if v1 != v2:
                diffs.append("viscosity")
            if c1["tank"]["diameter_m"] != c2["tank"]["diameter_m"]:
                diffs.append("tank_diameter")
            if c1["tank"]["liquid_height_m"] != c2["tank"]["liquid_height_m"]:
                diffs.append("liquid_height")
            b1 = c1["tank"].get("bottom_type") or c1["tank"].get("bottom_head_type")
            b2 = c2["tank"].get("bottom_type") or c2["tank"].get("bottom_head_type")
            if b1 != b2:
                diffs.append("bottom_head")
            bcount1 = c1["tank"].get("baffle_count")
            bcount2 = c2["tank"].get("baffle_count")
            if bcount1 != bcount2:
                diffs.append("baffle_count")
            if c1["tank"]["impellers"][0]["diameter_m"] != c2["tank"]["impellers"][0]["diameter_m"]:
                diffs.append("impeller_diameter")
            m1_iter = c1.get("mesh", {}).get("max_iterations") or c1.get("mesh", {}).get("iterations")
            m2_iter = c2.get("mesh", {}).get("max_iterations") or c2.get("mesh", {}).get("iterations")
            if m1_iter != m2_iter:
                diffs.append("iterations")
            m1_res = c1.get("mesh", {}).get("mesh_resolution") or c1.get("mesh", {}).get("resolution")
            m2_res = c2.get("mesh", {}).get("mesh_resolution") or c2.get("mesh", {}).get("resolution")
            if m1_res != m2_res:
                diffs.append("resolution")

            if len(diffs) == 1:
                pairs.append((r1, r2, diffs[0]))
    return pairs


def test_oracle_a_surrogate_prediction_errors():
    """Predict B from A via /api/ensemble/preview-geometry and report error vs real cached B."""
    pairs = find_single_param_pairs()
    assert len(pairs) > 0, "Expected at least one single-parameter run pair"

    client = TestClient(app)

    header = (
        f"{'Base Run (A)':<38} -> {'Target Run (B)':<38} | {'Param':<12} | "
        f"{'Pred P (W)':<10} | {'True P (W)':<10} | {'P err%':<8} | "
        f"{'Pred M (Nm)':<11} | {'True M (Nm)':<11} | {'M err%':<8} | "
        f"{'Pred u_max':<10} | {'True u_max':<10} | {'u_max err%':<10}"
    )
    divider = "-" * len(header)
    report_lines = [
        "\n================ ORACLE A v2: SURROGATE PREVIEW-GEOMETRY VALIDATION (PREDICT B FROM A) ================",
        header,
        divider,
    ]

    for r_base, r_target, param in pairs:
        base_dir = RUNS_DIR / r_base
        target_dir = RUNS_DIR / r_target

        with open(target_dir / "config.json", "r", encoding="utf-8") as f:
            cfg_target = json.load(f)
        with open(target_dir / "metadata.json", "r", encoding="utf-8") as f:
            meta_target = json.load(f)

        # Call the exact same endpoint the slider HUD uses
        resp = client.post(
            "/api/ensemble/preview-geometry",
            json={
                "tank": cfg_target["tank"],
                "fluid": cfg_target["fluid"],
                "ops": cfg_target["ops"],
                "force_surrogate": True,
                "base_run_id": r_base,
            },
        )
        assert resp.status_code == 200, f"preview-geometry failed with {resp.status_code}: {resp.text}"
        data = resp.json()
        surr_meta = data.get("metadata", {})

        pred_p = float(surr_meta.get("cfd_power_w", 0.0))
        pred_m = float(surr_meta.get("cfd_torque_n_m", 0.0))
        pred_u_max = float(surr_meta.get("cfd_max_velocity_m_s", 0.0))

        # True cached values in B
        true_p = float(meta_target.get("cfd_power_w", 0.0))
        true_m = float(meta_target.get("cfd_torque_n_m", 0.0))
        true_u_max = float(meta_target.get("cfd_max_velocity_m_s", 0.0))

        p_err = (abs(pred_p - true_p) / max(abs(true_p), 1e-6)) * 100.0
        m_err = (abs(pred_m - true_m) / max(abs(true_m), 1e-6)) * 100.0
        u_max_err = (abs(pred_u_max - true_u_max) / max(abs(true_u_max), 1e-6)) * 100.0 if true_u_max > 0 else 0.0

        line = (
            f"{r_base:<38} -> {r_target:<38} | {param:<12} | "
            f"{pred_p:10.2f} | {true_p:10.2f} | {p_err:7.1f}% | "
            f"{pred_m:11.4f} | {true_m:11.4f} | {m_err:7.1f}% | "
            f"{pred_u_max:10.4f} | {true_u_max:10.4f} | {u_max_err:9.1f}%"
        )
        report_lines.append(line)

    full_report = "\n".join(report_lines)
    print(full_report)

    # Save to docs/audit/oracle_A_v2.txt
    AUDIT_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = AUDIT_DOCS_DIR / "oracle_A_v2.txt"
    out_file.write_text(full_report + "\n", encoding="utf-8")
    assert out_file.is_file()
