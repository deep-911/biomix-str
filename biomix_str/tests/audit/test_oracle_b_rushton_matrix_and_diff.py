"""Oracle B: Rushton Water Run Matrix & Pitched Blade Config Diff.

For every Rushton water run print D, T, H, N, mu, mesh cells, requested iterations, torque drift, and Np.
Also diff config.json of runs fluent_pitc_elli_220rpm_432bbc081267 and fluent_pitc_elli_220rpm_8c536769d748.
(Report only, do not assert-fail).
"""

import json
from pathlib import Path
import pytest

RUNS_DIR = Path(__file__).resolve().parent.parent.parent / "outputs" / "fluent_runs"


def test_oracle_b_rushton_water_matrix_and_diff(capsys):
    """Print the complete parameter matrix for all Rushton water runs and diff the two pitched runs."""
    rushton_runs = []
    for p in sorted(RUNS_DIR.iterdir()):
        if not p.is_dir() or not p.name.startswith("fluent_rush_"):
            continue
        cfg_f = p / "config.json"
        meta_f = p / "metadata.json"
        man_f = p / "run_manifest.json"
        if not (cfg_f.exists() and meta_f.exists() and man_f.exists()):
            continue
        with open(cfg_f, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        with open(meta_f, "r", encoding="utf-8") as f:
            meta = json.load(f)
        with open(man_f, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        # Check if fluid is water (viscosity approx 0.001 Pa.s)
        mu = cfg["fluid"].get("viscosity_pa_s") or cfg["fluid"].get("dynamic_viscosity_pa_s", 0.001)
        if abs(mu - 0.001) > 1e-4:
            continue

        d = cfg["tank"]["impellers"][0]["diameter_m"]
        t = cfg["tank"]["diameter_m"]
        h = cfg["tank"]["liquid_height_m"]
        n_rpm = cfg["ops"]["rpm"]
        cells = manifest.get("n_cells") or meta.get("mesh_cell_count", "N/A")
        req_iter = manifest.get("iterations_requested") or cfg.get("mesh", {}).get("max_iterations", "N/A")
        drift = manifest.get("convergence", {}).get("torque_drift_pct") or meta.get("convergence_torque_drift_pct", "N/A")
        np_val = manifest.get("cfd_metrics", {}).get("power_number_np") or meta.get("power_number_np")
        if np_val is None:
            # compute Np = P / (rho * N^3 * D^5)
            p_w = meta.get("cfd_power_w", 0.0)
            n_rev_s = n_rpm / 60.0
            rho = cfg["fluid"]["density_kg_m3"]
            denom = rho * (n_rev_s ** 3) * (d ** 5)
            np_val = round(p_w / denom, 4) if denom > 0 else "N/A"

        rushton_runs.append({
            "run_id": p.name,
            "D": d,
            "T": t,
            "H": h,
            "N": n_rpm,
            "mu": mu,
            "cells": cells,
            "req_iter": req_iter,
            "drift": drift,
            "Np": np_val,
        })

    print("\n============================== RUSHTON WATER RUNS PARAMETER MATRIX ==============================")
    print(f"{'Run ID':<36} | {'D (m)':<6} | {'T (m)':<6} | {'H (m)':<6} | {'N(rpm)':<6} | {'mu (Pa.s)':<9} | {'Cells':<8} | {'Iter':<5} | {'Drift %':<8} | {'Np':<6}")
    print("-" * 115)
    for r in rushton_runs:
        print(f"{r['run_id']:<36} | {r['D']:<6.2f} | {r['T']:<6.2f} | {r['H']:<6.2f} | {r['N']:<6} | {r['mu']:<9.4f} | {r['cells']:<8} | {r['req_iter']:<5} | {str(r['drift']):<8} | {str(r['Np']):<6}")

    # Diff config.json of runs fluent_pitc_elli_220rpm_432bbc081267 and fluent_pitc_elli_220rpm_8c536769d748
    r1 = "fluent_pitc_elli_220rpm_432bbc081267"
    r2 = "fluent_pitc_elli_220rpm_8c536769d748"
    p1 = RUNS_DIR / r1 / "config.json"
    p2 = RUNS_DIR / r2 / "config.json"

    print("\n================= DIFF: fluent_pitc_elli_220rpm_432bbc081267 vs 8c536769d748 =================")
    assert p1.exists() and p2.exists(), "Both pitched blade configs must exist"
    with open(p1, "r", encoding="utf-8") as f:
        c1 = json.load(f)
    with open(p2, "r", encoding="utf-8") as f:
        c2 = json.load(f)

    def compare_dicts(d1, d2, path=""):
        diffs = []
        all_keys = sorted(set(d1.keys()).union(set(d2.keys())))
        for k in all_keys:
            subpath = f"{path}.{k}" if path else k
            if k not in d1:
                diffs.append(f"+ {subpath}: {d2[k]}")
            elif k not in d2:
                diffs.append(f"- {subpath}: {d1[k]}")
            elif isinstance(d1[k], dict) and isinstance(d2[k], dict):
                diffs.extend(compare_dicts(d1[k], d2[k], subpath))
            elif isinstance(d1[k], list) and isinstance(d2[k], list):
                if d1[k] != d2[k]:
                    diffs.append(f"~ {subpath}:\n    Run 1 (432bbc): {d1[k]}\n    Run 2 (8c5367): {d2[k]}")
            elif d1[k] != d2[k]:
                diffs.append(f"~ {subpath}:\n    Run 1 (432bbc): {d1[k]}\n    Run 2 (8c5367): {d2[k]}")
        return diffs

    diffs = compare_dicts(c1, c2)
    if not diffs:
        print("Configurations are IDENTICAL across all keys!")
    else:
        for d in diffs:
            print(d)

    assert len(rushton_runs) > 0
