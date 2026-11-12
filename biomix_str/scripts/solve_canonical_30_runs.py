"""Solve and certify 8 additional canonical Fluent cases to complete the 30-Run Library.

Cases solved:
1. rushton_elliptical_250rpm (RUSHTON_6_BLADE, ASME 2:1 Elliptical Dish, Baffled, 250 RPM)
2. rushton_hemi_250rpm (RUSHTON_6_BLADE, Hemispherical Dish, Baffled, 250 RPM)
3. pbt_flat_220rpm (PITCHED_BLADE_45, Flat Bottom, Baffled, 220 RPM)
4. pbt_unbaffled_vortex_220rpm (PITCHED_BLADE_45, Unbaffled 0 Baffles, ASME 2:1 Dish, 220 RPM)
5. hydrofoil_he3_viscous_500cp (HYDROFOIL_HE3, ASME 2:1 Dish, Baffled, 500 cP Broth, 250 RPM)
6. smith_cd6_high_400rpm (SMITH_CD6, Flat Bottom, Baffled, 400 RPM)
7. dual_smith_hydrofoil_hybrid (Dual Stage: SMITH_CD6 + HYDROFOIL_HE3, Flat Bottom, Baffled, 260 RPM)
8. dual_pbt_axial_220rpm (Dual Stage: PITCHED_BLADE_45 + PITCHED_BLADE_45, ASME 2:1 Dish, Baffled, 220 RPM)
"""

import argparse
import json
import os
from pathlib import Path
import sys
import time

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from biomix.fluent_runner import FluentSimulationRunner, generate_run_id
from biomix.models import (
    BottomType,
    FluidProperties,
    ImpellerSpec,
    ImpellerType,
    OperatingConditions,
    TankGeometry,
)
from biomix.provenance import assess_run_provenance

def get_canonical_8_definitions():
    water = FluidProperties(name="Water Broth", density_kg_m3=1000.0, viscosity_pa_s=0.001)

    return [
        # 1. Rushton Elliptical Dish (250 RPM)
        {
            "key": "rushton_elliptical_250rpm",
            "name": "Rushton Turbine in ASME 2:1 Elliptical Dish",
            "preset_id": "rushton_elliptical_250rpm",
            "category": "radial",
            "tank": TankGeometry(
                diameter_m=0.40,
                liquid_height_m=0.45,
                bottom_type=BottomType.ELLIPTICAL_2_1,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.14, clearance_m=0.15),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=250.0),
            "solver_iters": 80,
        },
        # 2. Rushton Hemispherical Dish (250 RPM)
        {
            "key": "rushton_hemi_250rpm",
            "name": "Rushton Turbine in Hemispherical Dish",
            "preset_id": "rushton_hemi_250rpm",
            "category": "radial",
            "tank": TankGeometry(
                diameter_m=0.40,
                liquid_height_m=0.45,
                bottom_type=BottomType.HEMISPHERICAL,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.14, clearance_m=0.15),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=250.0),
            "solver_iters": 80,
        },
        # 3. Pitched Blade Flat Bottom (220 RPM)
        {
            "key": "pbt_flat_220rpm",
            "name": "Pitched-Blade Turbine in Flat-Bottom Tank",
            "preset_id": "pbt_flat_220rpm",
            "category": "axial",
            "tank": TankGeometry(
                diameter_m=0.45,
                liquid_height_m=0.50,
                bottom_type=BottomType.FLAT,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.PITCHED_BLADE_45, diameter_m=0.16, clearance_m=0.18),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=220.0),
            "solver_iters": 80,
        },
        # 4. Pitched Blade Unbaffled Vortex (220 RPM)
        {
            "key": "pbt_unbaffled_vortex_220rpm",
            "name": "Unbaffled Pitched-Blade Free-Vortex Tank",
            "preset_id": "pbt_unbaffled_vortex_220rpm",
            "category": "sweeps",
            "tank": TankGeometry(
                diameter_m=0.45,
                liquid_height_m=0.55,
                bottom_type=BottomType.ELLIPTICAL_2_1,
                is_baffled=False,
                baffle_count=0,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.PITCHED_BLADE_45, diameter_m=0.16, clearance_m=0.18),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=220.0),
            "solver_iters": 80,
        },
        # 5. Chemineer Hydrofoil in 500 cP Viscous Transitional Broth
        {
            "key": "hydrofoil_he3_viscous_500cp",
            "name": "Chemineer Hydrofoil in 500 cP Transitional Broth",
            "preset_id": "hydrofoil_he3_viscous_500cp",
            "category": "viscous",
            "tank": TankGeometry(
                diameter_m=0.45,
                liquid_height_m=0.55,
                bottom_type=BottomType.ELLIPTICAL_2_1,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.HYDROFOIL_HE3, diameter_m=0.16, clearance_m=0.15),
                ],
            ),
            "fluid": FluidProperties(
                name="500 cP Transitional Broth",
                density_kg_m3=1040.0,
                viscosity_pa_s=0.50,
            ),
            "ops": OperatingConditions(rpm=250.0),
            "solver_iters": 80,
        },
        # 6. Smith CD-6 High Speed 400 RPM
        {
            "key": "smith_cd6_high_400rpm",
            "name": "High-Speed Smith CD-6 Gas Dispersion Turbine (400 RPM)",
            "preset_id": "smith_cd6_high_400rpm",
            "category": "radial",
            "tank": TankGeometry(
                diameter_m=0.40,
                liquid_height_m=0.45,
                bottom_type=BottomType.FLAT,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.SMITH_CD6, diameter_m=0.14, clearance_m=0.15),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=400.0),
            "solver_iters": 80,
        },
        # 7. Dual Smith + Hydrofoil Hybrid
        {
            "key": "dual_smith_hydrofoil_hybrid",
            "name": "Dual-Stage Hybrid (Bottom Smith CD-6 + Top HE-3 Hydrofoil)",
            "preset_id": "dual_smith_hydrofoil_hybrid",
            "category": "sweeps",
            "tank": TankGeometry(
                diameter_m=0.45,
                liquid_height_m=0.55,
                bottom_type=BottomType.FLAT,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.SMITH_CD6, diameter_m=0.15, clearance_m=0.14),
                    ImpellerSpec(impeller_type=ImpellerType.HYDROFOIL_HE3, diameter_m=0.15, clearance_m=0.34),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=260.0),
            "solver_iters": 80,
        },
        # 8. Dual Pitched Blade Axial Downflow
        {
            "key": "dual_pbt_axial_220rpm",
            "name": "Dual Pitched-Blade Axial Pumping System (220 RPM)",
            "preset_id": "dual_pbt_axial_220rpm",
            "category": "axial",
            "tank": TankGeometry(
                diameter_m=0.45,
                liquid_height_m=0.55,
                bottom_type=BottomType.ELLIPTICAL_2_1,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.PITCHED_BLADE_45, diameter_m=0.16, clearance_m=0.15),
                    ImpellerSpec(impeller_type=ImpellerType.PITCHED_BLADE_45, diameter_m=0.16, clearance_m=0.36),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=220.0),
            "solver_iters": 80,
        },
    ]


def kill_stray_fluent():
    try:
        import subprocess
        subprocess.run(
            ["powershell", "-Command", "Stop-Process -Name fluent,fl_mpi* -Force -ErrorAction SilentlyContinue"],
            capture_output=True,
            timeout=10,
        )
        time.sleep(4)
    except Exception:
        pass


def solve_case(case_def: dict, force: bool = False):
    name = case_def["name"]
    tank = case_def["tank"]
    fluid = case_def["fluid"]
    ops = case_def["ops"]
    iters = case_def["solver_iters"]

    run_id = generate_run_id(tank, fluid, ops, mesh_density="fast", iterations=15)
    run_dir = project_root / "outputs" / "fluent_runs" / run_id

    print("\n" + "=" * 80)
    print(f"CASE: {name}")
    print(f"Key: {case_def['key']}")
    print(f"Run ID: {run_id}")
    print(f"Directory: {run_dir}")
    print("=" * 80)

    if not force and run_dir.is_dir():
        prov = assess_run_provenance(run_dir)
        bundle_file = run_dir / "web_3d_bundle.json"
        vtp_file = run_dir / "fluent_internal_field.vtp"
        if prov.get("verified") is True and bundle_file.is_file() and vtp_file.is_file():
            print(f"[SKIP] {name} is ALREADY VERIFIED on disk ({prov['classification']} - {prov['label']})!")
            return run_id, prov

    run_dir.mkdir(parents=True, exist_ok=True)

    max_retries = 3
    meta = None
    for attempt in range(1, max_retries + 1):
        kill_stray_fluent()
        try:
            print(f"Starting solver attempt {attempt}/{max_retries} for {name}...")
            runner = FluentSimulationRunner(terminal_output=True)
            t0 = time.time()
            meta = runner.run_simulation(
                tank=tank,
                fluid=fluid,
                ops=ops,
                mesh_density="fast",
                iterations=iters,
                config_iterations=15,
                use_cache=False,
                run_id=run_id,
                run_dir=str(run_dir),
            )
            t_elapsed = time.time() - t0
            break
        except Exception as err:
            print(f"Attempt {attempt} failed with error: {err}")
            kill_stray_fluent()
            if attempt == max_retries:
                raise err
            time.sleep(5)

    prov = assess_run_provenance(run_dir)
    print(f"\n--- Provenance Summary for {name} ({run_id}) ---")
    print(f"Elapsed Solve Time: {t_elapsed:.1f} s")
    print(f"Verified: {prov['verified']}")
    print(f"Classification: {prov['classification']}")
    print(f"Label: {prov['label']}")
    print(f"Torque Source: {prov['torque_source']}")
    print(f"Converged: {prov['converged']}")
    print(f"Cells: {meta.n_cells}")
    print(f"Power: {meta.cfd_power_w:.2f} W | Torque: {meta.cfd_torque_n_m:.4f} N*m | Peak U: {meta.cfd_max_velocity_m_s:.2f} m/s")

    # Hard assertions
    assert (run_dir / "fluent_case.cas.h5").is_file(), f"Missing .cas.h5 for {run_id}"
    assert (run_dir / "fluent_case.dat.h5").is_file(), f"Missing .dat.h5 for {run_id}"
    assert (run_dir / "fluent_internal_field.vtp").is_file(), f"Missing .vtp for {run_id}"
    assert (run_dir / "web_3d_bundle.json").is_file(), f"Missing web_3d_bundle.json for {run_id}"
    assert (run_dir / "run_manifest.json").is_file(), f"Missing run_manifest.json for {run_id}"
    assert (run_dir / "config.json").is_file(), f"Missing config.json for {run_id}"
    assert prov["verified"] is True, f"Failed verification for {run_id}: {prov}"

    print(f"SUCCESS: {name} certified and saved to {run_dir}!\n")
    kill_stray_fluent()
    return run_id, prov


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Solve 8 Canonical Fluent Cases for 30-Run Library")
    parser.add_argument("--force", action="store_true", help="Force re-running existing runs")
    parser.add_argument("--only", type=str, default=None, help="Solve only matching key")
    args = parser.parse_args()

    cases = get_canonical_8_definitions()
    if args.only:
        cases = [c for c in cases if c["key"] == args.only]
        if not cases:
            print(f"No cases found matching key '{args.only}'")
            return

    print("=" * 80)
    print(f"STARTING 8-CASE CANONICAL SOLVE SUITE ({len(cases)} cases queued)")
    print("=" * 80)

    results = []
    t_start = time.time()
    for idx, c in enumerate(cases, 1):
        print(f"\n>>> Running Case {idx}/{len(cases)}: {c['key']} ...")
        r_id, prov = solve_case(c, force=args.force)
        results.append((c["key"], r_id, prov))

    total_time = time.time() - t_start
    print("\n" + "=" * 80)
    print(f"CANONICAL SOLVE SUITE COMPLETE (Total Time: {total_time:.1f} s)")
    print("=" * 80)
    for key, r_id, prov in results:
        status = "VERIFIED" if prov.get("verified") else "FAILED"
        print(f" - {key:30s} -> {r_id} [{status}] ({prov.get('classification')})")

    # Output manifest map
    map_path = project_root / "outputs" / "canonical_8_runs_map.json"
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump({k: {"run_id": r_id, "verified": p.get("verified")} for k, r_id, p in results}, f, indent=2)
    print(f"\nWrote run map to {map_path}")


if __name__ == "__main__":
    main()
