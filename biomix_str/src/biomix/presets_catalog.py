"""BioMix-STR Official Bioprocess Engineering Ensemble Presets & Similarity Surrogate Catalog.

Maintains the 30 Verified Fluent 2026 R1 canonical runs across all impeller types,
bottom dishes, baffle counts, fluid rheology regimes, and dual-stage configurations.
Provides multi-dimensional surrogate matching and boundary-clamped geometric scaling.
"""

import math
import os
from typing import Any, Dict, List, Optional

from biomix.models import (
    BottomType,
    CellType,
    FluidProperties,
    ImpellerSpec,
    ImpellerType,
    OperatingConditions,
    PresetInfo,
    TankGeometry,
)
from biomix.fluent_runner import generate_run_id
from biomix.provenance import assess_run_provenance

DEFAULT_RUNS_BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "outputs", "fluent_runs")
)


def z_dish_bottom(r: float, tank: TankGeometry) -> float:
    """Calculate bottom dish elevation z_bot(r) at radius r."""
    R = tank.diameter_m / 2.0
    r_c = min(r, R)
    if tank.bottom_type == BottomType.FLAT:
        return 0.0
    elif tank.bottom_type == BottomType.ELLIPTICAL_2_1:
        b = R / 2.0
        return float(b * (1.0 - math.sqrt(max(0.0, 1.0 - (r_c / R)**2))))
    elif tank.bottom_type == BottomType.HEMISPHERICAL:
        return float(R * (1.0 - math.sqrt(max(0.0, 1.0 - (r_c / R)**2))))
    return 0.0


def build_ensemble_presets(runs_base_dir: Optional[str] = None) -> List[PresetInfo]:
    """Build the official Bioprocess Engineering Ensemble Presets (30 Verified Fluent Runs)."""
    if runs_base_dir is None:
        runs_base_dir = DEFAULT_RUNS_BASE_DIR

    water = FluidProperties(name="Water Broth", density_kg_m3=1000.0, viscosity_pa_s=0.001)

    presets_data = [
        # =========================================================================
        # Category: Radial Flow Turbines (9 Presets)
        # =========================================================================
        # 1. Single Rushton Standard (250 RPM)
        {
            "preset_id": "rushton_single_standard",
            "name": "Standard Single Rushton Fermenter",
            "description": "Single Rushton 6-blade radial disk turbine in baffled cylindrical vessel with flat bottom.",
            "category": "radial",
            "tank": TankGeometry(
                diameter_m=0.40,
                liquid_height_m=0.45,
                bottom_type=BottomType.FLAT,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.14, clearance_m=0.15),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=250.0),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_rush_flat_250rpm_c5abfce9ad1c",
        },
        # 2. Smith CD-6 Concave Disc Turbine (250 RPM)
        {
            "preset_id": "smith_cd6_standard",
            "name": "Smith CD-6 Concave Disc Turbine",
            "description": "Concave-blade semi-circular radial disc turbine (Smith CD-6) with high gas-handling capacity and vortex suppression.",
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
            "ops": OperatingConditions(rpm=250.0),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_smit_flat_250rpm_0bfbe7c7de0c",
        },
        # 3. Flat Blade FBT Open Paddle (250 RPM)
        {
            "preset_id": "flat_blade_fbt_open",
            "name": "Open Flat-Blade Turbine (FBT)",
            "description": "Open 4-blade flat paddle turbine producing pure radial discharge jets and intense shear in a baffled flat-bottom tank.",
            "category": "radial",
            "tank": TankGeometry(
                diameter_m=0.40,
                liquid_height_m=0.45,
                bottom_type=BottomType.FLAT,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.FLAT_BLADE_FBT, diameter_m=0.14, clearance_m=0.15),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=250.0),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_flat_flat_250rpm_e27322b426fb",
        },
        # 4. Curved Backswept Radial (240 RPM)
        {
            "preset_id": "curved_backswept_radial",
            "name": "Curved / Backswept Radial Turbine",
            "description": "Logarithmic curved-blade radial impeller for gentle low-shear radial dispersion and anti-ragging performance.",
            "category": "radial",
            "tank": TankGeometry(
                diameter_m=0.40,
                liquid_height_m=0.45,
                bottom_type=BottomType.FLAT,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.CURVED_BACKSWEPT, diameter_m=0.14, clearance_m=0.15),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=240.0),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_curv_flat_240rpm_bcbe35d749b0",
        },
        # 5. Paddle R-200 Gentle (100 RPM)
        {
            "preset_id": "paddle_r200_gentle",
            "name": "Two-Blade Paddle R-200 Gentle Agitator",
            "description": "Large-diameter two-blade paddle (Di = 0.52 T) providing wide slow-speed blending and solid suspension.",
            "category": "radial",
            "tank": TankGeometry(
                diameter_m=0.40,
                liquid_height_m=0.45,
                bottom_type=BottomType.FLAT,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.PADDLE_R200, diameter_m=0.208, clearance_m=0.15),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=100.0),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_padd_flat_100rpm_dc803c6e30e7",
        },
        # 6. Retreat Blade Glass Lined (200 RPM)
        {
            "preset_id": "retreat_blade_glass_lined",
            "name": "Retreat-Blade Impeller (Pfaudler Glass-Lined)",
            "description": "Glass-lined 3-blade retreat curve agitator positioned close to the bottom dish for corrosive pharmaceutical blending.",
            "category": "radial",
            "tank": TankGeometry(
                diameter_m=0.45,
                liquid_height_m=0.50,
                bottom_type=BottomType.ELLIPTICAL_2_1,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.RETREAT_BLADE, diameter_m=0.16, clearance_m=0.12),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=200.0),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_retr_elli_200rpm_409fa03695fc",
        },
        # 7. Rushton in ASME 2:1 Elliptical Dish (250 RPM)
        {
            "preset_id": "rushton_elliptical_250rpm",
            "name": "Rushton Turbine in ASME 2:1 Elliptical Dish",
            "description": "Standard Rushton 6-blade radial disk turbine operating in an ASME 2:1 elliptical dish bottom vessel.",
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
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_rush_elli_250rpm_af88246294c0",
        },
        # 8. Rushton in Hemispherical Dish (250 RPM)
        {
            "preset_id": "rushton_hemi_250rpm",
            "name": "Rushton Turbine in Hemispherical Dish",
            "description": "Standard Rushton 6-blade radial disk turbine operating in a full hemispherical dish bottom vessel.",
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
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_rush_hemi_250rpm_685d06cfca27",
        },
        # 9. Smith CD-6 High-Speed 400 RPM
        {
            "preset_id": "smith_cd6_high_400rpm",
            "name": "High-Speed Smith CD-6 Gas Dispersion Turbine (400 RPM)",
            "description": "Concave-blade Smith CD-6 operating at intense agitation (400 RPM) for high gas handling and deep turbulence.",
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
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_smit_flat_400rpm_d0992a970257",
        },

        # =========================================================================
        # Category: Axial & Mixed-Flow Turbines (8 Presets)
        # =========================================================================
        # 10. Single Pitched-Blade 45 (220 RPM)
        {
            "preset_id": "pitched_blade_single_axial",
            "name": "Single Pitched-Blade Turbine (Mixed/Axial Downflow)",
            "description": "4-blade 45° pitched turbine producing strong downward axial pumping and bottom sweep in an ASME 2:1 elliptical dish vessel.",
            "category": "axial",
            "tank": TankGeometry(
                diameter_m=0.45,
                liquid_height_m=0.55,
                bottom_type=BottomType.ELLIPTICAL_2_1,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.PITCHED_BLADE_45, diameter_m=0.16, clearance_m=0.18),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=220.0),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_pitc_elli_220rpm_432bbc081267",
        },
        # 11. Gentle Marine Propeller (130 RPM)
        {
            "preset_id": "marine_propeller_mammalian",
            "name": "Gentle Marine Propeller (Mammalian CHO Culture)",
            "description": "3-blade marine propeller in hemispherical dish head vessel designed for shear-sensitive CHO cell suspension.",
            "category": "axial",
            "tank": TankGeometry(
                diameter_m=0.40,
                liquid_height_m=0.50,
                bottom_type=BottomType.HEMISPHERICAL,
                is_baffled=True,
                baffle_count=3,
                baffle_width_ratio=0.0833,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.MARINE_PROPELLER, diameter_m=0.16, clearance_m=0.16),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=130.0, cell_type=CellType.MAMMALIAN_CELL),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_mari_hemi_130rpm_51527ba4791c",
        },
        # 12. Chemineer Hydrofoil HE-3 (250 RPM)
        {
            "preset_id": "hydrofoil_he3_axial",
            "name": "Chemineer Hydrofoil HE-3 Fluidfoil",
            "description": "3-blade high-efficiency axial fluidfoil producing wide dish-bottom sweep with minimal power dissipation in an elliptical dish.",
            "category": "axial",
            "tank": TankGeometry(
                diameter_m=0.40,
                liquid_height_m=0.45,
                bottom_type=BottomType.ELLIPTICAL_2_1,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.HYDROFOIL_HE3, diameter_m=0.16, clearance_m=0.15),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=250.0),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_hydr_elli_250rpm_959ef9534ed6",
        },
        # 13. Maxflo High-Solidity (220 RPM)
        {
            "preset_id": "maxflo_high_solidity_axial",
            "name": "Maxflo High-Solidity Axial Hydrofoil",
            "description": "Wide-chord high-solidity hydrofoil designed for high gas dispersion and axial flow without flooding.",
            "category": "axial",
            "tank": TankGeometry(
                diameter_m=0.45,
                liquid_height_m=0.55,
                bottom_type=BottomType.ELLIPTICAL_2_1,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.MAXFLO_HIGH_SOLIDITY, diameter_m=0.17, clearance_m=0.18),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=220.0),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_maxf_elli_220rpm_536fe85176c2",
        },
        # 14. EKATO Intermig Multi-Stage (150 RPM)
        {
            "preset_id": "intermig_ekato_axial",
            "name": "EKATO Intermig Multi-Stage Impeller",
            "description": "Counter-pitched multi-stage EKATO Intermig blades producing high axial circulation at low shear and low power.",
            "category": "axial",
            "tank": TankGeometry(
                diameter_m=0.40,
                liquid_height_m=0.45,
                bottom_type=BottomType.ELLIPTICAL_2_1,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.INTERMIG_EKATO, diameter_m=0.24, clearance_m=0.16),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=150.0),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_inte_elli_150rpm_f3a8df7cfc08",
        },
        # 15. Pitched Blade in Flat-Bottom Tank (220 RPM)
        {
            "preset_id": "pbt_flat_220rpm",
            "name": "Pitched-Blade Turbine in Flat-Bottom Tank",
            "description": "4-blade 45° pitched downflow turbine operating in a standard flat-bottom baffled vessel.",
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
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_pitc_flat_220rpm_05afb991d9d4",
        },
        # 16. Dual Pitched-Blade Axial Pumping System (220 RPM)
        {
            "preset_id": "dual_pbt_axial_220rpm",
            "name": "Dual Pitched-Blade Axial Pumping System (220 RPM)",
            "description": "Dual 4-blade 45° pitched axial downflow impellers producing deep two-stage axial bulk circulation in an ASME 2:1 dish vessel.",
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
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_pitc_elli_220rpm_575975675a94",
        },

        # =========================================================================
        # Category: Viscous / Close-Clearance (6 Presets)
        # =========================================================================
        # 17. Anchor Agitator (40 RPM, 5,000 cP Power-Law)
        {
            "preset_id": "anchor_laminar_powerlaw",
            "name": "Anchor Wall-Sweeping Agitator (5,000 cP Power-Law)",
            "description": "Close-clearance anchor impeller in high-viscosity non-Newtonian broth (5,000 cP) with single-zone rotating MRF and laboratory-frame moving wall.",
            "category": "viscous",
            "tank": TankGeometry(
                diameter_m=0.40,
                liquid_height_m=0.45,
                bottom_type=BottomType.FLAT,
                is_baffled=False,
                baffle_count=0,
                impellers=[
                    ImpellerSpec(
                        impeller_type=ImpellerType.ANCHOR,
                        diameter_m=0.36,
                        clearance_m=0.012,
                        blade_width_m=0.25,
                    ),
                ],
            ),
            "fluid": FluidProperties(
                name="High-Viscosity Bio-Polymer Broth",
                density_kg_m3=1050.0,
                viscosity_pa_s=5.0,
                rheology_model="power_law",
                consistency_k_pa_s_n=5.0,
                flow_behavior_index_n=0.85,
            ),
            "ops": OperatingConditions(rpm=40.0),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_anch_flat_40rpm_d12f32384b94",
        },
        # 18. Helical Ribbon High-Viscosity Impeller (35 RPM, 25,000 cP)
        {
            "preset_id": "helical_ribbon_polymer",
            "name": "Helical Ribbon High-Viscosity Impeller (25,000 cP)",
            "description": "Close-clearance helical ribbon agitator in non-Newtonian polymer broth (25,000 cP) driving top-to-bottom laminar recirculation.",
            "category": "viscous",
            "tank": TankGeometry(
                diameter_m=0.40,
                liquid_height_m=0.45,
                bottom_type=BottomType.FLAT,
                is_baffled=False,
                baffle_count=0,
                impellers=[
                    ImpellerSpec(
                        impeller_type=ImpellerType.HELICAL_RIBBON,
                        diameter_m=0.36,
                        clearance_m=0.014,
                        blade_width_m=0.288,
                    ),
                ],
            ),
            "fluid": FluidProperties(
                name="25,000 cP Viscous Polymer Broth",
                density_kg_m3=1080.0,
                viscosity_pa_s=25.0,
                rheology_model="power_law",
                consistency_k_pa_s_n=25.0,
                flow_behavior_index_n=0.60,
            ),
            "ops": OperatingConditions(
                rpm=35.0,
                rheology_model="power_law",
                consistency_k_pa_s_n=25.0,
                flow_behavior_index_n=0.60,
            ),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_heli_flat_35rpm_c45f087adfac",
        },
        # 19. Archimedes Auger Screw Agitator (50 RPM, 25,000 cP)
        {
            "preset_id": "auger_screw_paste",
            "name": "Archimedes Auger Screw Agitator (25,000 cP)",
            "description": "Continuous helical flighting Archimedes auger in fermentation paste (25,000 cP) creating powerful axial core lift.",
            "category": "viscous",
            "tank": TankGeometry(
                diameter_m=0.40,
                liquid_height_m=0.45,
                bottom_type=BottomType.FLAT,
                is_baffled=False,
                baffle_count=0,
                impellers=[
                    ImpellerSpec(
                        impeller_type=ImpellerType.AUGER_SCREW,
                        diameter_m=0.24,
                        clearance_m=0.016,
                        blade_width_m=0.18,
                    ),
                ],
            ),
            "fluid": FluidProperties(
                name="25,000 cP Fermentation Bio-Paste",
                density_kg_m3=1100.0,
                viscosity_pa_s=25.0,
                rheology_model="power_law",
                consistency_k_pa_s_n=25.0,
                flow_behavior_index_n=0.55,
            ),
            "ops": OperatingConditions(
                rpm=50.0,
                rheology_model="power_law",
                consistency_k_pa_s_n=25.0,
                flow_behavior_index_n=0.55,
            ),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_auge_flat_50rpm_4aa49a4651ba",
        },
        # 20. Heavy-Duty Gate Impeller Frame (35 RPM, 10,000 cP)
        {
            "preset_id": "gate_impeller_slurry",
            "name": "Heavy-Duty Gate Impeller Frame (10,000 cP)",
            "description": "Structural gate frame with contour-hugging outer limbs and vertical grid bars for high-solids slurries (10,000 cP).",
            "category": "viscous",
            "tank": TankGeometry(
                diameter_m=0.40,
                liquid_height_m=0.45,
                bottom_type=BottomType.FLAT,
                is_baffled=False,
                baffle_count=0,
                impellers=[
                    ImpellerSpec(
                        impeller_type=ImpellerType.GATE_IMPELLER,
                        diameter_m=0.36,
                        clearance_m=0.012,
                        blade_width_m=0.234,
                    ),
                ],
            ),
            "fluid": FluidProperties(
                name="10,000 cP High-Solids Slurry Broth",
                density_kg_m3=1060.0,
                viscosity_pa_s=10.0,
                rheology_model="power_law",
                consistency_k_pa_s_n=10.0,
                flow_behavior_index_n=0.70,
            ),
            "ops": OperatingConditions(
                rpm=35.0,
                rheology_model="power_law",
                consistency_k_pa_s_n=10.0,
                flow_behavior_index_n=0.70,
            ),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_gate_flat_35rpm_43b96abc45e8",
        },
        # 21. Sigma / Z-Blade Heavy Kneader (30 RPM, 50,000 cP)
        {
            "preset_id": "sigma_kneader_biopolymer",
            "name": "Sigma / Z-Blade Heavy Kneader (50,000 cP)",
            "description": "Heavy pitched Z-arm blades in dense non-Newtonian biopolymer dough (50,000 cP) providing high-torque folding and kneading.",
            "category": "viscous",
            "tank": TankGeometry(
                diameter_m=0.40,
                liquid_height_m=0.45,
                bottom_type=BottomType.FLAT,
                is_baffled=False,
                baffle_count=0,
                impellers=[
                    ImpellerSpec(
                        impeller_type=ImpellerType.SIGMA_Z_KNEADER,
                        diameter_m=0.35,
                        clearance_m=0.016,
                        blade_width_m=0.14,
                    ),
                ],
            ),
            "fluid": FluidProperties(
                name="50,000 cP Dense Biopolymer Dough",
                density_kg_m3=1120.0,
                viscosity_pa_s=50.0,
                rheology_model="power_law",
                consistency_k_pa_s_n=50.0,
                flow_behavior_index_n=0.50,
            ),
            "ops": OperatingConditions(
                rpm=30.0,
                rheology_model="power_law",
                consistency_k_pa_s_n=50.0,
                flow_behavior_index_n=0.50,
            ),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_sigm_flat_30rpm_2b5fe06fc5b9",
        },
        # 22. Chemineer Hydrofoil in 500 cP Transitional Broth
        {
            "preset_id": "hydrofoil_he3_viscous_500cp",
            "name": "Chemineer Hydrofoil in 500 cP Transitional Broth",
            "description": "Chemineer HE-3 axial fluidfoil operating in viscous transitional fermentation broth (500 cP) with suppressed micro-eddies.",
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
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_hydr_elli_250rpm_43d61e397676",
        },

        # =========================================================================
        # Category: Parametric Operating & Rheology Sweeps (8 Presets)
        # =========================================================================
        # 23. Dual Impeller - Wide Gap (280 RPM, ΔC = 1.6 Di)
        {
            "preset_id": "dual_impeller_wide_gap",
            "name": "Dual Impeller (Wide Gap, ΔC = 1.6 Di)",
            "description": "Bottom Rushton + Upper Pitched Blade 45° with wide inter-impeller separation (ΔC = 0.24 m). Independent circulation loops.",
            "category": "sweeps",
            "tank": TankGeometry(
                diameter_m=0.45,
                liquid_height_m=0.50,
                bottom_type=BottomType.FLAT,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.15, clearance_m=0.14),
                    ImpellerSpec(impeller_type=ImpellerType.PITCHED_BLADE_45, diameter_m=0.15, clearance_m=0.38),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=280.0),
            "mesh_density": "fast",
            "iterations": 10,
            "run_id": "fluent_rush_flat_280rpm_1f9d1ae137f1",
        },
        # 24. Dual Impeller - Narrow Gap (280 RPM, ΔC = 0.93 Di)
        {
            "preset_id": "dual_impeller_narrow_gap",
            "name": "Dual Impeller (Narrow Gap, ΔC = 0.93 Di)",
            "description": "Bottom Rushton + Upper Pitched Blade 45° with tight inter-impeller separation (ΔC = 0.14 m). Strong inter-stage interaction.",
            "category": "sweeps",
            "tank": TankGeometry(
                diameter_m=0.45,
                liquid_height_m=0.50,
                bottom_type=BottomType.FLAT,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.15, clearance_m=0.14),
                    ImpellerSpec(impeller_type=ImpellerType.PITCHED_BLADE_45, diameter_m=0.15, clearance_m=0.28),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=280.0),
            "mesh_density": "fast",
            "iterations": 10,
            "run_id": "fluent_rush_flat_280rpm_dd6c74f598ba",
        },
        # 25. Unbaffled Rankine Vortex Tank (260 RPM)
        {
            "preset_id": "unbaffled_rankine_vortex",
            "name": "Unbaffled Rankine Vortex Tank",
            "description": "Cylindrical unbaffled tank exhibiting central surface vortex funnel and bulk rotational liquid swirl.",
            "category": "sweeps",
            "tank": TankGeometry(
                diameter_m=0.45,
                liquid_height_m=0.50,
                bottom_type=BottomType.FLAT,
                is_baffled=False,
                baffle_count=0,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.15, clearance_m=0.16),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=260.0),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_rush_flat_260rpm_c0ff9b8ebcd1",
        },
        # 26. Unbaffled Pitched-Blade Free-Vortex Tank (220 RPM)
        {
            "preset_id": "pbt_unbaffled_vortex_220rpm",
            "name": "Unbaffled Pitched-Blade Free-Vortex Tank",
            "description": "4-blade 45° pitched turbine in an unbaffled ASME 2:1 dish vessel producing swirl and deep central surface depression.",
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
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_pitc_elli_220rpm_8c536769d748",
        },
        # 27. Dual Smith + Hydrofoil Hybrid (260 RPM)
        {
            "preset_id": "dual_smith_hydrofoil_hybrid",
            "name": "Dual-Stage Hybrid (Bottom Smith CD-6 + Top HE-3 Hydrofoil)",
            "description": "Dual-stage hybrid: bottom high-solidity concave CD-6 gas-dispersion turbine plus upper high-efficiency axial downflow hydrofoil.",
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
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_smit_flat_260rpm_6ba58aa1688a",
        },
        # 28. Rushton RPM Sweep Low (120 RPM)
        {
            "preset_id": "rushton_sweep_low_120rpm",
            "name": "Rushton RPM Sweep (Low Speed, 120 RPM)",
            "description": "Standard Rushton geometry operated at low rotational agitation (120 RPM) for gentle microbial cell growth.",
            "category": "sweeps",
            "tank": TankGeometry(
                diameter_m=0.40,
                liquid_height_m=0.45,
                bottom_type=BottomType.FLAT,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.14, clearance_m=0.15),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=120.0),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_rush_flat_120rpm_05c5a8739b78",
        },
        # 29. Rushton RPM Sweep High (400 RPM)
        {
            "preset_id": "rushton_sweep_high_400rpm",
            "name": "Rushton RPM Sweep (High Shear, 400 RPM)",
            "description": "Standard Rushton geometry operated at high turbulent shear (400 RPM), producing Kolmogorov scales < 20 μm.",
            "category": "sweeps",
            "tank": TankGeometry(
                diameter_m=0.40,
                liquid_height_m=0.45,
                bottom_type=BottomType.FLAT,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.14, clearance_m=0.15),
                ],
            ),
            "fluid": water,
            "ops": OperatingConditions(rpm=400.0),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_rush_flat_400rpm_f11532130aa6",
        },
        # 30. Viscosity Cavern Sweep (3,000 cP Mycelial)
        {
            "preset_id": "rushton_cavern_3000cp",
            "name": "Viscosity Cavern Sweep (3,000 cP Mycelial Broth)",
            "description": "High-viscosity non-Newtonian mycelial broth (3,000 cP, Power-Law K=3.0, n=0.65) demonstrating viscous damping and cavern formation.",
            "category": "sweeps",
            "tank": TankGeometry(
                diameter_m=0.40,
                liquid_height_m=0.45,
                bottom_type=BottomType.FLAT,
                is_baffled=True,
                baffle_count=4,
                baffle_width_ratio=0.10,
                impellers=[
                    ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.14, clearance_m=0.15),
                ],
            ),
            "fluid": FluidProperties(
                name="3,000 cP Mycelial Fermentation Broth",
                density_kg_m3=1030.0,
                viscosity_pa_s=3.0,
                rheology_model="power_law",
                consistency_k_pa_s_n=3.0,
                flow_behavior_index_n=0.65,
            ),
            "ops": OperatingConditions(rpm=250.0),
            "mesh_density": "fast",
            "iterations": 15,
            "run_id": "fluent_rush_flat_250rpm_37e0a7c99627",
        },
    ]

    out_presets: List[PresetInfo] = []
    for p in presets_data:
        r_id = p.get("run_id") or generate_run_id(
            p["tank"], p["fluid"], p["ops"], mesh_density=p["mesh_density"], iterations=p["iterations"]
        )
        b_file = os.path.join(runs_base_dir, r_id, "web_3d_bundle.json")
        is_cached = os.path.isfile(b_file)
        provenance = assess_run_provenance(os.path.join(runs_base_dir, r_id)) if is_cached else None

        out_presets.append(
            PresetInfo(
                preset_id=p["preset_id"],
                name=p["name"],
                description=p["description"],
                category=p["category"],
                tank=p["tank"],
                fluid=p["fluid"],
                ops=p["ops"],
                mesh_density=p["mesh_density"],
                iterations=p["iterations"],
                is_cached=is_cached,
                run_id=r_id,
                provenance=provenance,
            )
        )

    return out_presets


def find_closest_base_preset(
    target_tank: TankGeometry,
    target_fluid: FluidProperties,
    target_ops: OperatingConditions,
    presets: List[PresetInfo],
) -> Optional[PresetInfo]:
    """Score and find the optimal verified base run matching geometric and operating state."""
    cached_candidates = [p for p in presets if p.is_cached]
    if not cached_candidates:
        return None

    target_stages = len(target_tank.impellers)
    target_primary_imp = target_tank.impellers[0].impeller_type if target_tank.impellers else None
    target_primary_d = target_tank.impellers[0].diameter_m if target_tank.impellers else 0.15
    target_re = (
        target_fluid.density_kg_m3 * (target_ops.rpm / 60.0) * (target_primary_d ** 2)
    ) / max(target_fluid.viscosity_pa_s, 1e-5)
    target_is_laminar = target_re < 200.0 or target_fluid.viscosity_pa_s >= 0.5 or getattr(target_ops, "rheology_model", None) == "power_law" or getattr(target_fluid, "rheology_model", None) == "power_law"

    best_preset = None
    best_score = -float("inf")

    for p in cached_candidates:
        score = 0.0
        cand_tank = p.tank
        cand_ops = p.ops
        cand_fluid = p.fluid

        # 1. Stage count match (1000 pts)
        cand_stages = len(cand_tank.impellers)
        if cand_stages == target_stages:
            score += 1000.0
        else:
            score -= 600.0

        # 2. Primary impeller type match (500 pts)
        cand_primary_imp = cand_tank.impellers[0].impeller_type if cand_tank.impellers else None
        if cand_primary_imp == target_primary_imp:
            score += 500.0

        # If dual-stage, check stage 2 impeller match (300 pts)
        if target_stages > 1 and cand_stages > 1:
            if cand_tank.impellers[1].impeller_type == target_tank.impellers[1].impeller_type:
                score += 300.0

        # 3. Baffled state match (250 pts)
        if cand_tank.is_baffled == target_tank.is_baffled:
            score += 250.0

        # 4. Bottom dish type match (200 pts)
        if cand_tank.bottom_type == target_tank.bottom_type:
            score += 200.0

        # 5. Viscous / Laminar regime match (150 pts)
        cand_d = cand_tank.impellers[0].diameter_m if cand_tank.impellers else 0.15
        cand_re = (
            cand_fluid.density_kg_m3 * (cand_ops.rpm / 60.0) * (cand_d ** 2)
        ) / max(cand_fluid.viscosity_pa_s, 1e-5)
        cand_is_laminar = cand_re < 200.0 or cand_fluid.viscosity_pa_s >= 0.5 or getattr(cand_ops, "rheology_model", None) == "power_law" or getattr(cand_fluid, "rheology_model", None) == "power_law"
        if cand_is_laminar == target_is_laminar:
            score += 150.0

        # 6. Proximity of RPM (up to 50 pts)
        rpm_diff = abs(cand_ops.rpm - target_ops.rpm)
        score += max(0.0, 50.0 - (rpm_diff / 5.0))

        if score > best_score:
            best_score = score
            best_preset = p

    return best_preset


def scale_surrogate_flow_field(
    base_preset: PresetInfo,
    base_bundle: Dict[str, Any],
    target_tank: TankGeometry,
    target_fluid: FluidProperties,
    target_ops: OperatingConditions,
) -> Dict[str, Any]:
    """Scale 3D streamlines, vectors, and 2D cross sections from base run to target reactor.

    Strictly clamps spatial coordinates within the target vessel dish bottom and free surface.
    """
    n_new = float(target_ops.rpm)
    d_new = float(target_tank.impellers[0].diameter_m) if target_tank.impellers else 0.15
    t_new = float(target_tank.diameter_m)
    h_new = float(target_tank.liquid_height_m)
    r_new = t_new / 2.0

    n_base = float(base_preset.ops.rpm)
    d_base = float(base_preset.tank.impellers[0].diameter_m) if base_preset.tank.impellers else 0.15
    t_base = float(base_preset.tank.diameter_m)
    h_base = float(base_preset.tank.liquid_height_m)

    u_tip_base = math.pi * n_base * d_base / 60.0
    u_tip_new = math.pi * n_new * d_new / 60.0

    s_u = (n_new * d_new) / max(n_base * d_base, 1e-6)
    s_r = t_new / max(t_base, 1e-6)
    s_z = h_new / max(h_base, 1e-6)
    s_tke = (u_tip_new / max(u_tip_base, 1e-6)) ** 2
    s_eps = ((u_tip_new ** 3) / max(d_new, 1e-6)) / max((u_tip_base ** 3) / max(d_base, 1e-6), 1e-6)
    rho_ratio = target_fluid.density_kg_m3 / max(base_preset.fluid.density_kg_m3, 1e-6)
    s_press = rho_ratio * (s_u ** 2)

    def clamp_pt(x: float, y: float, z: float) -> List[float]:
        r = math.sqrt(x**2 + y**2)
        if r >= 0.97 * r_new and r > 1e-6:
            scale_rad = (0.96 * r_new) / r
            x *= scale_rad
            y *= scale_rad
            r = 0.96 * r_new
        z_bot = z_dish_bottom(r, target_tank)
        z_clamped = max(z_bot + 0.005 * h_new, min(h_new - 0.005 * h_new, z))
        return [round(x, 4), round(y, 4), round(z_clamped, 4)]

    # 1. Scale and clamp 3D streamlines
    scaled_streamlines = []
    for line in base_bundle.get("streamlines", []):
        scaled_line = []
        for pt in line:
            if len(pt) >= 4:
                px, py, pz = pt[0] * s_r, pt[1] * s_r, pt[2] * s_z
                clamped = clamp_pt(px, py, pz)
                spd = round(pt[3] * s_u, 4)
                scaled_line.append([clamped[0], clamped[1], clamped[2], spd])
        if len(scaled_line) >= 4:
            scaled_streamlines.append(scaled_line)

    # 2. Scale and clamp 3D vectors
    scaled_vectors = []
    for vec in base_bundle.get("vectors_3d", []):
        if isinstance(vec, (list, tuple)) and len(vec) >= 7:
            px, py, pz = vec[0] * s_r, vec[1] * s_r, vec[2] * s_z
            clamped = clamp_pt(px, py, pz)
            scaled_vectors.append([
                clamped[0],
                clamped[1],
                clamped[2],
                round(vec[3] * s_u, 4),
                round(vec[4] * s_u, 4),
                round(vec[5] * s_u, 4),
                round(vec[6] * s_u, 4),
            ])

    # 3. Scale 2D cross sections
    scaled_cross = {}
    for plane, data in base_bundle.get("cross_sections", {}).items():
        scaled_plane = dict(data)
        coord_key = "x" if plane == "xz" else "y"
        if coord_key in data:
            scaled_plane[coord_key] = [round(v * s_r, 4) for v in data[coord_key]]
        if "z" in data:
            scaled_plane[z_key := "z"] = [round(v * s_z, 4) for v in data["z"]]
        for field, scale_factor in [
            ("velocity_mag", s_u),
            ("ux", s_u),
            ("uy", s_u),
            ("uz", s_u),
            ("pressure", s_press),
            ("tke", s_tke),
            ("epsilon", s_eps),
            ("shear_stress_pa", s_press),
        ]:
            if field in data and data[field] is not None:
                scaled_plane[field] = [
                    [round(v * scale_factor, 4) if v is not None else None for v in row]
                    if isinstance(row, list) else None
                    for row in data[field]
                ]
        scaled_cross[plane] = scaled_plane

    # 4. Scale horizontal slices
    scaled_slices = []
    for sl in base_bundle.get("horizontal_slices", []):
        s_sl = dict(sl)
        s_sl["z"] = round(sl["z"] * s_z, 4)
        if "x" in sl:
            s_sl["x"] = [round(v * s_r, 4) for v in sl["x"]]
        if "y" in sl:
            s_sl["y"] = [round(v * s_r, 4) for v in sl["y"]]
        for field, scale_factor in [
            ("velocity_mag", s_u),
            ("ux", s_u),
            ("uy", s_u),
            ("pressure", s_press),
            ("tke", s_tke),
            ("epsilon", s_eps),
            ("shear_stress_pa", s_press),
        ]:
            if field in sl and sl[field] is not None:
                s_sl[field] = [
                    [round(v * scale_factor, 4) if v is not None else None for v in row]
                    if isinstance(row, list) else None
                    for row in sl[field]
                ]
        scaled_slices.append(s_sl)

    return {
        "streamlines": scaled_streamlines,
        "vectors_3d": scaled_vectors,
        "cross_sections": scaled_cross,
        "horizontal_slices": scaled_slices,
        "scales": {
            "s_u": round(s_u, 4),
            "s_r": round(s_r, 4),
            "s_z": round(s_z, 4),
            "s_tke": round(s_tke, 4),
            "s_eps": round(s_eps, 4),
            "s_press": round(s_press, 4),
        },
    }
