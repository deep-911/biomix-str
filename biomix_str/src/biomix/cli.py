"""BioMix-STR Command-Line Interface (CLI).

Simulates standard stirred-tank bioreactor configurations and produces
bioprocess hydrodynamic, shear, and mass transfer comparison reports.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Tuple

# Ensure utf-8 output on Windows consoles if available
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from biomix.engine import HydrodynamicEngine, ReactorSimulationResult
from biomix.models import (
    BottomType,
    CellType,
    FluidProperties,
    ImpellerSpec,
    ImpellerType,
    OperatingConditions,
    TankGeometry,
)


def run_benchmark_simulations(rpm: float = 250.0, aeration_vvm: float = 0.5) -> List[Tuple[str, ReactorSimulationResult]]:
    """Run hydrodynamic simulations for 4 standard pilot-scale bioreactor configurations.

    Pilot Reactor Parameters:
    - Diameter T = 1.0 m, Liquid Height H = 1.5 m
    - ASME 2:1 Elliptical Bottom Dish Head
    - 4 Standard Wall Baffles (W/T = 0.10)
    - Broth: Water-like non-coalescing fermentation broth (rho = 1000 kg/m^3, mu = 1 cP)
    - Agitation: 250 RPM, Aeration: 0.5 vvm (sparged)
    """
    fluid = FluidProperties(
        name="Non-Coalescing Fermentation Broth",
        density_kg_m3=1000.0,
        viscosity_pa_s=0.001,
        coalescing_media=False,
    )

    ops = OperatingConditions(
        rpm=rpm,
        aeration_vvm=aeration_vvm,
        cell_type=CellType.MICROBIAL,
    )

    # Configuration 1: Single Rushton 6-Blade Disk Turbine
    tank_rushton = TankGeometry(
        diameter_m=1.0,
        liquid_height_m=1.5,
        bottom_type=BottomType.ELLIPTICAL_2_1,
        baffle_count=4,
        baffle_width_ratio=0.10,
        impellers=[
            ImpellerSpec(
                impeller_type=ImpellerType.RUSHTON_6_BLADE,
                diameter_m=0.33,
                clearance_m=0.33,
            )
        ],
    )

    # Configuration 2: Single 45° Pitched-Blade Turbine (PBT)
    tank_pbt = TankGeometry(
        diameter_m=1.0,
        liquid_height_m=1.5,
        bottom_type=BottomType.ELLIPTICAL_2_1,
        baffle_count=4,
        baffle_width_ratio=0.10,
        impellers=[
            ImpellerSpec(
                impeller_type=ImpellerType.PITCHED_BLADE_45,
                diameter_m=0.33,
                clearance_m=0.33,
            )
        ],
    )

    # Configuration 3: Single Marine Propeller
    tank_marine = TankGeometry(
        diameter_m=1.0,
        liquid_height_m=1.5,
        bottom_type=BottomType.ELLIPTICAL_2_1,
        baffle_count=4,
        baffle_width_ratio=0.10,
        impellers=[
            ImpellerSpec(
                impeller_type=ImpellerType.MARINE_PROPELLER,
                diameter_m=0.33,
                clearance_m=0.33,
            )
        ],
    )

    # Configuration 4: Dual-Impeller Hybrid (Bottom Rushton + Upper Axial PBT)
    tank_hybrid = TankGeometry(
        diameter_m=1.0,
        liquid_height_m=1.5,
        bottom_type=BottomType.ELLIPTICAL_2_1,
        baffle_count=4,
        baffle_width_ratio=0.10,
        impellers=[
            ImpellerSpec(
                impeller_type=ImpellerType.RUSHTON_6_BLADE,
                diameter_m=0.33,
                clearance_m=0.33,
            ),
            ImpellerSpec(
                impeller_type=ImpellerType.PITCHED_BLADE_45,
                diameter_m=0.33,
                clearance_m=0.90,
            ),
        ],
    )

    configs = [
        ("Single Rushton (6-Blade)", tank_rushton),
        ("Single Pitched-Blade (45 deg)", tank_pbt),
        ("Single Marine Propeller", tank_marine),
        ("Dual Hybrid (Rushton + PBT)", tank_hybrid),
    ]

    results = []
    for label, tank in configs:
        res = HydrodynamicEngine.run(tank, fluid, ops, gassed_method="michel")
        results.append((label, res))

    return results


def print_comparison_table(results: List[Tuple[str, ReactorSimulationResult]]) -> None:
    """Print an engineering comparison table in clean ASCII."""
    header = (
        f"{'Configuration':<28} | {'V_L (L)':>7} | {'Re_i (Stg 0)':>11} | {'N_p':>5} | "
        f"{'P_0 (W)':>8} | {'P_g (W)':>8} | {'P_g/V_L':>7} | {'v_tip':>6} | "
        f"{'lambda_K':>8} | {'theta_95':>8} | {'kLa (1/h)':>9} | {'Flooded?':>8}"
    )
    divider = "-" * len(header)

    print("\n" + "=" * len(header))
    print(" BioMix-STR: Pilot Bioreactor Multi-Impeller Hydrodynamics & Mass Transfer Benchmark")
    print(" Vessel: T=1.0m, H=1.5m (ASME 2:1 Dish, 4 Baffles W/T=0.10) | Media: Non-Coalescing Broth (1 cP, 1000 kg/m3)")
    print(" Agitation: 250 RPM (N = 4.17 rev/s) | Aeration: 0.50 vvm (Q_g = 9.27 L/s)")
    print("=" * len(header))
    print(header)
    print(divider)

    for label, res in results:
        v_l_liters = res.working_volume_m3 * 1000.0
        stg0 = res.stages[0]
        re_str = f"{stg0.re_i:.0f} ({stg0.flow_regime.value[:4]})"
        p0_str = f"{res.total_ungassed_power_w:.1f}"
        pg_str = f"{res.total_gassed_power_w:.1f}"
        spec_pg_str = f"{res.specific_gassed_power_w_m3:.1f}"
        v_tip_str = f"{res.max_tip_speed_m_s:.2f}"
        lambda_str = f"{res.lambda_k_min_um:.1f}um"
        theta_str = f"{res.mixing_time_95_s:.1f}s"
        kla_str = f"{res.kla_h_inv:.1f}"
        flood_str = "YES" if res.any_stage_flooded else "No"

        row = (
            f"{label:<28} | {v_l_liters:>7.1f} | {re_str:>11} | {stg0.np_val:>5.2f} | "
            f"{p0_str:>8} | {pg_str:>8} | {spec_pg_str:>7} | {v_tip_str:>6} | "
            f"{lambda_str:>8} | {theta_str:>8} | {kla_str:>9} | {flood_str:>8}"
        )
        print(row)

    print(divider)

    # Detailed warnings breakdown
    print("\nEngineering Diagnostics & Active Warnings:")
    for label, res in results:
        print(f" [{label}]")
        if not res.warnings:
            print("   [OK] All BPE hydrodynamic criteria passed within normal operating limits.")
        else:
            for w in res.warnings:
                print(f"   [WARN] {w}")
    print()


def main() -> None:
    """CLI entry point for BioMix-STR."""
    parser = argparse.ArgumentParser(
        description="BioMix-STR Bioprocess Stirred-Tank Bioreactor Hydrodynamic Simulation Suite"
    )
    parser.add_argument(
        "--rpm",
        type=float,
        default=250.0,
        help="Agitation speed in RPM (default: 250.0)",
    )
    parser.add_argument(
        "--vvm",
        type=float,
        default=0.5,
        help="Aeration rate in vvm (default: 0.5)",
    )
    args = parser.parse_args()

    results = run_benchmark_simulations(rpm=args.rpm, aeration_vvm=args.vvm)
    print_comparison_table(results)


if __name__ == "__main__":
    main()
