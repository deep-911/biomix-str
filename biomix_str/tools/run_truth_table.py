"""Generate truth table for all completed Fluent runs in outputs/fluent_runs.

Reads config.json, metadata.json, and run_manifest.json for every run.
Saves CSV to docs/audit/run_truth_table.csv.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path


def generate_truth_table(runs_dir: Path, output_csv: Path) -> list[dict]:
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    run_dirs = sorted([d for d in runs_dir.iterdir() if d.is_dir()])

    for d in run_dirs:
        cfg_file = d / "config.json"
        meta_file = d / "metadata.json"
        man_file = d / "run_manifest.json"

        # Skip incomplete run directories
        if not (cfg_file.is_file() and meta_file.is_file() and man_file.is_file()):
            continue

        with open(cfg_file, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
        with open(man_file, "r", encoding="utf-8") as f:
            man = json.load(f)

        run_id = d.name

        tank = cfg.get("tank", {})
        fluid = cfg.get("fluid", {})
        ops = cfg.get("operating") or cfg.get("ops", {})

        impellers = tank.get("impellers", [])
        if len(impellers) == 1:
            impeller_type = impellers[0].get("impeller_type", "")
            d_val = impellers[0].get("diameter_m", 0.0)
        elif len(impellers) > 1:
            impeller_type = "+".join(i.get("impeller_type", "") for i in impellers)
            d_val = impellers[0].get("diameter_m", 0.0)
        else:
            impeller_type = ""
            d_val = 0.0

        baffle_count = tank.get("baffle_count", 0)
        bottom = tank.get("bottom_type", "")
        t_val = tank.get("diameter_m", 0.0)
        h_val = tank.get("liquid_height_m", 0.0)

        n_rpm = ops.get("rpm", 0.0)
        mu_val = fluid.get("viscosity_pa_s", 0.0)
        rho_val = fluid.get("density_kg_m3", 1000.0)

        n_cells = meta.get("n_cells") or man.get("n_cells")
        req_iters = cfg.get("iterations") or man.get("iterations_requested")
        torque_drift_pct = meta.get("torque_drift_pct")
        converged = meta.get("converged")

        power_w = meta.get("cfd_power_w")
        torque_nm = meta.get("cfd_torque_n_m")

        raw_flow_regime = meta.get("flow_regime")
        raw_reynolds_number = meta.get("reynolds_number")

        # Computed Re = rho * N * D^2 / mu (with N in rev/s)
        n_rps = n_rpm / 60.0 if n_rpm else 0.0
        if mu_val and mu_val > 0 and n_rps > 0 and d_val > 0:
            computed_re = (rho_val * n_rps * (d_val ** 2)) / mu_val
        else:
            computed_re = 0.0

        # Computed Np = P / (rho * N^3 * D^5)
        if rho_val > 0 and n_rps > 0 and d_val > 0 and power_w is not None:
            computed_np = power_w / (rho_val * (n_rps ** 3) * (d_val ** 5))
        else:
            computed_np = 0.0

        # P/(2*pi*N) vs torque
        if n_rps > 0 and power_w is not None and torque_nm is not None:
            m_expected = power_w / (2.0 * math.pi * n_rps)
            diff_pct = ((m_expected - torque_nm) / torque_nm * 100.0) if torque_nm != 0 else 0.0
            p_vs_torque_str = f"{m_expected:.4f} vs {torque_nm} ({diff_pct:+.2f}%)"
        else:
            p_vs_torque_str = "N/A"

        # Manifest SHA vs Actual SHA (canonical sorted JSON encoding)
        actual_sha = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode("utf-8")).hexdigest()
        manifest_sha = man.get("config_sha256", "")
        sha_match = "yes" if actual_sha == manifest_sha else "no"

        row = {
            "run_id": run_id,
            "impeller_type": impeller_type,
            "baffle_count": baffle_count,
            "bottom": bottom,
            "T": t_val,
            "H": h_val,
            "D": d_val,
            "N_rpm": n_rpm,
            "mu": mu_val,
            "density": rho_val,
            "n_cells": n_cells,
            "requested_iterations": req_iters,
            "torque_drift_pct": torque_drift_pct,
            "converged": converged,
            "power_w": power_w,
            "torque_nm": torque_nm,
            "raw flow_regime": raw_flow_regime,
            "raw reynolds_number": raw_reynolds_number,
            "computed Re": round(computed_re, 2),
            "computed Np": round(computed_np, 4),
            "P/(2*pi*N) vs torque": p_vs_torque_str,
            "manifest_sha vs actual_sha": sha_match,
        }
        rows.append(row)

    # Save to CSV
    if rows:
        fieldnames = list(rows[0].keys())
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    return rows


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    runs_directory = base_dir / "outputs" / "fluent_runs"
    csv_dest = base_dir.parent / "docs" / "audit" / "run_truth_table.csv"
    data = generate_truth_table(runs_directory, csv_dest)
    print(f"Generated truth table with {len(data)} runs at {csv_dest}")
