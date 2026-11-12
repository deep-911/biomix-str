"""BioMix-STR: Interactive Bioprocess Engineering Stirred-Tank Bioreactor Suite.

Streamlit web application providing:
- 5 industrial bioprocess engineering case presets (Microbial, Mammalian CHO, Vortex, Hybrid, Viscous)
- Full interactive reactor anatomy and operating condition controls
- Real-time hydrodynamic simulation (ungassed/gassed power, mixing time, kLa, Kolmogorov scales, dead zones)
- Active bioprocess engineering warning system (impeller flooding, shear damage, vortex air entrainment)
- 4 interactive workspace tabs:
  1. 2D Fluent-style velocity/shear contours, streamlines, and power curves
  2. 3D PyVista CAD anatomy, 3D swirling streamlines, and VTK/VTP export for ParaView
  3. Ansys Fluent 2026 R1 (v261) CFD verification bridge, parity comparator, and TUI journal generator
  4. Impeller topology side-by-side benchmark & engineering equations reference
"""

from __future__ import annotations

import io
import math
import os
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
import tempfile

from biomix.correlations import FlowRegime
from biomix.engine import HydrodynamicEngine, ReactorSimulationResult
from biomix.flow_solver_2d import FlowField2DResult, FlowSolver2D
from biomix.fluent_bridge import (
    FluentCFDVerifier,
    FluentJournalGenerator,
    FluentMRFConfig,
)
from biomix.models import (
    BottomType,
    CellType,
    FlowDirection,
    FluidProperties,
    ImpellerSpec,
    ImpellerType,
    OperatingConditions,
    TankGeometry,
)
from biomix.visualization_2d import Plotter2D
from biomix.visualization_3d import Visualizer3D

# =============================================================================
# INDUSTRIAL BENCHMARK PRESETS
# =============================================================================

PRESETS: Dict[str, Dict[str, Any]] = {
    "1. Standard Baffled Rushton Fermenter (Microbial)": {
        "description": "Industrial microbial fermentation with a single Rushton turbine and 4 baffles, operating in fully turbulent regime.",
        "diameter_m": 0.50,
        "liquid_height_m": 0.65,
        "bottom_type": BottomType.ELLIPTICAL_2_1.value,
        "baffle_count": 4,
        "baffle_width_ratio": 0.10,
        "num_stages": 1,
        "stages": [
            {
                "impeller_type": ImpellerType.RUSHTON_6_BLADE.value,
                "diameter_ratio": 0.36,
                "clearance_m": 0.20,
            }
        ],
        "density_kg_m3": 1020.0,
        "viscosity_cp": 1.8,
        "media_coalescence": "non_coalescing",
        "rpm": 220.0,
        "aeration_vvm": 0.5,
        "gassed_corr": "michel",
        "cell_type": CellType.MICROBIAL.value,
    },
    "2. Gentle Axial Propeller Bioreactor (Mammalian CHO)": {
        "description": "Shear-sensitive mammalian CHO cell culture using a low-shear Marine Propeller with gentle agitation and mild aeration.",
        "diameter_m": 0.40,
        "liquid_height_m": 0.55,
        "bottom_type": BottomType.HEMISPHERICAL.value,
        "baffle_count": 3,
        "baffle_width_ratio": 0.0833,
        "num_stages": 1,
        "stages": [
            {
                "impeller_type": ImpellerType.MARINE_PROPELLER.value,
                "diameter_ratio": 0.40,
                "clearance_m": 0.18,
            }
        ],
        "density_kg_m3": 1000.0,
        "viscosity_cp": 1.2,
        "media_coalescence": "coalescing",
        "rpm": 120.0,
        "aeration_vvm": 0.1,
        "gassed_corr": "michel",
        "cell_type": CellType.MAMMALIAN_CELL.value,
    },
    "3. Unbaffled Rankine Vortex Tank (Swirl & Air Entrainment)": {
        "description": "Unbaffled cylindrical vessel with pronounced central Rankine vortex funnel and solid-body liquid swirl.",
        "diameter_m": 0.45,
        "liquid_height_m": 0.55,
        "bottom_type": BottomType.FLAT.value,
        "baffle_count": 0,
        "baffle_width_ratio": 0.10,
        "num_stages": 1,
        "stages": [
            {
                "impeller_type": ImpellerType.RUSHTON_6_BLADE.value,
                "diameter_ratio": 0.40,
                "clearance_m": 0.18,
            }
        ],
        "density_kg_m3": 1000.0,
        "viscosity_cp": 1.0,
        "media_coalescence": "coalescing",
        "rpm": 280.0,
        "aeration_vvm": 0.0,
        "gassed_corr": "michel",
        "cell_type": CellType.MICROBIAL.value,
    },
    "4. Tall Dual-Impeller Hybrid (Bottom Rushton + Upper PBT)": {
        "description": "Multi-stage gas-dispersion bioreactor with bottom radial Rushton for gas breakup and upper Pitched-Blade Turbine for top axial circulation.",
        "diameter_m": 0.60,
        "liquid_height_m": 1.20,
        "bottom_type": BottomType.ELLIPTICAL_2_1.value,
        "baffle_count": 4,
        "baffle_width_ratio": 0.10,
        "num_stages": 2,
        "stages": [
            {
                "impeller_type": ImpellerType.RUSHTON_6_BLADE.value,
                "diameter_ratio": 0.367,
                "clearance_m": 0.25,
            },
            {
                "impeller_type": ImpellerType.PITCHED_BLADE_45.value,
                "diameter_ratio": 0.40,
                "clearance_m": 0.75,
            },
        ],
        "density_kg_m3": 1050.0,
        "viscosity_cp": 2.5,
        "media_coalescence": "non_coalescing",
        "rpm": 180.0,
        "aeration_vvm": 0.8,
        "gassed_corr": "bakker",
        "cell_type": CellType.MICROBIAL.value,
    },
    "5. Viscous Mycelial Fermentation (Laminar/Transitional Dead Zones)": {
        "description": "High-viscosity fungal broth in transitional flow, characterized by large hydraulic dead zones and cavernous flow.",
        "diameter_m": 0.50,
        "liquid_height_m": 0.70,
        "bottom_type": BottomType.ELLIPTICAL_2_1.value,
        "baffle_count": 4,
        "baffle_width_ratio": 0.10,
        "num_stages": 1,
        "stages": [
            {
                "impeller_type": ImpellerType.PITCHED_BLADE_45.value,
                "diameter_ratio": 0.50,
                "clearance_m": 0.25,
            }
        ],
        "density_kg_m3": 1080.0,
        "viscosity_cp": 850.0,
        "media_coalescence": "non_coalescing",
        "rpm": 90.0,
        "aeration_vvm": 0.3,
        "gassed_corr": "michel",
        "cell_type": CellType.MICROBIAL.value,
    },
}


def load_preset(preset_key: str) -> Dict[str, Any]:
    """Retrieve preset parameters dictionary for a given industrial case preset."""
    if preset_key not in PRESETS:
        preset_key = list(PRESETS.keys())[0]
    return PRESETS[preset_key]


def build_simulation_from_params(
    params: Dict[str, Any],
) -> Tuple[TankGeometry, FluidProperties, OperatingConditions, ReactorSimulationResult, FlowField2DResult]:
    """Instantiate and solve full hydrodynamic simulation from parameter dictionary."""
    T = float(params["diameter_m"])
    H = float(params["liquid_height_m"])
    bottom_type = BottomType(params["bottom_type"])
    baffle_count = int(params["baffle_count"])
    baffle_ratio = float(params.get("baffle_width_ratio", 0.10))
    baffle_width = round(baffle_ratio * T, 4) if baffle_count > 0 else None

    # Impellers
    impellers: List[ImpellerSpec] = []
    num_stages = int(params.get("num_stages", len(params.get("stages", []))))
    stages_data = params.get("stages", [])

    for i in range(num_stages):
        if i < len(stages_data):
            stg = stages_data[i]
            itype = ImpellerType(stg["impeller_type"])
            d_m = round(float(stg["diameter_ratio"]) * T, 4)
            c_m = float(stg["clearance_m"])
        else:
            itype = ImpellerType.RUSHTON_6_BLADE
            d_m = round(0.35 * T, 4)
            c_m = round((i + 1) * H / (num_stages + 1), 3)

        # Flow direction matching impeller type
        if itype == ImpellerType.RUSHTON_6_BLADE:
            fdir = FlowDirection.RADIAL
        elif itype == ImpellerType.PITCHED_BLADE_45:
            fdir = FlowDirection.MIXED_AXIAL
        else:
            fdir = FlowDirection.AXIAL

        impellers.append(
            ImpellerSpec(
                impeller_type=itype,
                diameter_m=d_m,
                clearance_m=c_m,
                
            )
        )

    tank = TankGeometry(
        diameter_m=T,
        liquid_height_m=H,
        bottom_type=bottom_type,
        baffle_count=baffle_count,
        baffle_width_ratio=baffle_ratio,
        impellers=impellers,
    )

    visc_pa_s = float(params["viscosity_cp"]) * 1e-3
    fluid = FluidProperties(
        name="Culture Broth",
        density_kg_m3=float(params["density_kg_m3"]),
        viscosity_pa_s=visc_pa_s,
        coalescing_media=(params.get("media_coalescence") == "coalescing"),
    )

    ops = OperatingConditions(
        rpm=float(params["rpm"]),
        aeration_vvm=float(params["aeration_vvm"]),
        cell_type=CellType(params["cell_type"]),
    )

    gassed_corr = params.get("gassed_corr", "michel")
    sim_result = HydrodynamicEngine.run(tank, fluid, ops, gassed_method=gassed_corr)
    field_2d = FlowSolver2D.solve(sim_result, nx=55, nz=65)

    return tank, fluid, ops, sim_result, field_2d


def compare_impeller_topologies(
    tank: TankGeometry,
    fluid: FluidProperties,
    ops: OperatingConditions,
) -> Tuple[pd.DataFrame, plt.Figure]:
    """Simulate Rushton, PBT, Marine Propeller, and Dual Hybrid side-by-side."""
    T = tank.diameter_m
    H = tank.liquid_height_m
    bottom = tank.bottom_type
    baffles = tank.baffle_count if tank.baffle_count > 0 else 4
    b_width = 0.10 * T

    dish_depth = tank.dish_depth_m
    c_single = max(dish_depth + 0.08, round(0.33 * H, 3))

    cases = [
        (
            "Rushton 6-Blade",
            "Radial Flow",
            TankGeometry(
                diameter_m=T,
                liquid_height_m=H,
                bottom_type=bottom,
                baffle_count=baffles,
                baffle_width_ratio=b_width / 0.45,
                impellers=[
                    ImpellerSpec(
                        impeller_type=ImpellerType.RUSHTON_6_BLADE,
                        diameter_m=round(0.35 * T, 3),
                        clearance_m=c_single,
                        
                    )
                ],
            ),
        ),
        (
            "Pitched-Blade 45°",
            "Mixed Axial",
            TankGeometry(
                diameter_m=T,
                liquid_height_m=H,
                bottom_type=bottom,
                baffle_count=baffles,
                baffle_width_ratio=b_width / 0.45,
                impellers=[
                    ImpellerSpec(
                        impeller_type=ImpellerType.PITCHED_BLADE_45,
                        diameter_m=round(0.35 * T, 3),
                        clearance_m=c_single,
                        
                    )
                ],
            ),
        ),
        (
            "Marine Propeller",
            "Axial Flow",
            TankGeometry(
                diameter_m=T,
                liquid_height_m=H,
                bottom_type=bottom,
                baffle_count=baffles,
                baffle_width_ratio=b_width / 0.45,
                impellers=[
                    ImpellerSpec(
                        impeller_type=ImpellerType.MARINE_PROPELLER,
                        diameter_m=round(0.35 * T, 3),
                        clearance_m=c_single,
                        
                    )
                ],
            ),
        ),
        (
            "Dual Hybrid (Rushton + PBT)",
            "Multi-Stage",
            TankGeometry(
                diameter_m=T,
                liquid_height_m=H,
                bottom_type=bottom,
                baffle_count=baffles,
                baffle_width_ratio=b_width / 0.45,
                impellers=[
                    ImpellerSpec(
                        impeller_type=ImpellerType.RUSHTON_6_BLADE,
                        diameter_m=round(0.35 * T, 3),
                        clearance_m=max(dish_depth + 0.08, round(0.25 * H, 3)),
                        
                    ),
                    ImpellerSpec(
                        impeller_type=ImpellerType.PITCHED_BLADE_45,
                        diameter_m=round(0.35 * T, 3),
                        clearance_m=min(H - 0.08, round(0.68 * H, 3)),
                        
                    ),
                ],
            ),
        ),
    ]

    records = []
    for name, flow_class, geom in cases:
        sim = HydrodynamicEngine.run(geom, fluid, ops)
        fld = FlowSolver2D.solve(sim, nx=45, nz=55)

        pg_vl = sim.total_gassed_power_w / max(1e-4, sim.working_volume_m3)
        records.append(
            {
                "Topology": name,
                "Flow Regime": sim.stages[0].flow_regime.value,
                "Power Pg (W)": round(sim.total_gassed_power_w, 1),
                "Pg/VL (W/m³)": round(pg_vl, 1),
                "v_tip (m/s)": round(sim.max_tip_speed_m_s, 2),
                "θ95 (s)": round(sim.mixing_time_95_s, 1),
                "kLa (1/h)": round(sim.kla_h_inv, 1),
                "Dead Zones (%)": round(fld.dead_zone_fraction * 100.0, 1),
                "Shear Status": "Safe" if not any("SHEAR" in w.upper() for w in sim.warnings) else "High Shear",
            }
        )

    df_comp = pd.DataFrame(records)

    # 4-panel comparison bar chart
    fig, axes = plt.subplots(1, 4, figsize=(15, 3.8), facecolor="#0f172a")
    topologies = df_comp["Topology"].tolist()
    short_names = ["Rushton", "PBT 45°", "Propeller", "Dual Hybrid"]
    colors = ["#3B82F6", "#10B981", "#F59E0B", "#8B5CF6"]

    # 1. Power Density
    axes[0].bar(short_names, df_comp["Pg/VL (W/m³)"], color=colors, edgecolor="white", alpha=0.9)
    axes[0].set_title("Gassed Power Density (W/m³)", color="white", fontsize=11, fontweight="bold")
    axes[0].set_ylabel("W / m³", color="white")

    # 2. Mixing Time
    axes[1].bar(short_names, df_comp["θ95 (s)"], color=colors, edgecolor="white", alpha=0.9)
    axes[1].set_title("95% Mixing Time θ₉₅ (s)", color="white", fontsize=11, fontweight="bold")
    axes[1].set_ylabel("Seconds", color="white")

    # 3. Mass Transfer kLa
    axes[2].bar(short_names, df_comp["kLa (1/h)"], color=colors, edgecolor="white", alpha=0.9)
    axes[2].set_title("Oxygen Transfer kLa (h⁻¹)", color="white", fontsize=11, fontweight="bold")
    axes[2].set_ylabel("1 / h", color="white")

    # 4. Dead Zones
    axes[3].bar(short_names, df_comp["Dead Zones (%)"], color=colors, edgecolor="white", alpha=0.9)
    axes[3].set_title("Hydraulic Dead Zones (%)", color="white", fontsize=11, fontweight="bold")
    axes[3].set_ylabel("Domain %", color="white")

    for ax in axes:
        ax.set_facecolor("#1e293b")
        ax.tick_params(colors="white", labelsize=9)
        ax.tick_params(axis="x", rotation=25)
        for spine in ax.spines.values():
            spine.set_color("#475569")
        ax.grid(True, linestyle="--", alpha=0.2, color="white")

    plt.tight_layout()
    return df_comp, fig


# =============================================================================
# STREAMLIT UI IMPLEMENTATION
# =============================================================================


def main():
    """Main execution point for the Streamlit interactive dashboard."""
    st.set_page_config(
        page_title="BioMix-STR | Bioprocess Engineering Suite",
        page_icon="🧪",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Custom styling
    st.markdown(
        """
        <style>
        .main {
            background-color: #0b0f19;
            color: #f1f5f9;
        }
        .metric-card {
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border: 1px solid #334155;
            border-radius: 10px;
            padding: 14px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
            text-align: center;
        }
        .metric-title {
            color: #94a3b8;
            font-size: 0.82rem;
            text-transform: uppercase;
            font-weight: 600;
            letter-spacing: 0.05em;
            margin-bottom: 4px;
        }
        .metric-value {
            color: #38bdf8;
            font-size: 1.45rem;
            font-weight: 700;
        }
        .metric-sub {
            color: #64748b;
            font-size: 0.76rem;
            margin-top: 3px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # -------------------------------------------------------------------------
    # SIDEBAR: PRESET SELECTOR & CONTROLS
    # -------------------------------------------------------------------------
    st.sidebar.title("🧪 BioMix-STR Control")
    st.sidebar.markdown("**Bioprocess Stirred-Tank Simulator**")

    preset_keys = list(PRESETS.keys())

    if "current_preset_key" not in st.session_state:
        st.session_state.current_preset_key = preset_keys[0]
        p0_data = PRESETS[preset_keys[0]]
        st.session_state.tank_diameter = p0_data["diameter_m"]
        st.session_state.liquid_height = p0_data["liquid_height_m"]
        st.session_state.bottom_type = p0_data["bottom_type"]
        st.session_state.baffle_count = p0_data["baffle_count"]
        st.session_state.baffle_ratio = p0_data["baffle_width_ratio"]
        st.session_state.num_stages = p0_data["num_stages"]
        st.session_state.density = p0_data["density_kg_m3"]
        st.session_state.viscosity_cp = p0_data["viscosity_cp"]
        st.session_state.coalescence = p0_data["media_coalescence"]
        st.session_state.rpm = p0_data["rpm"]
        st.session_state.aeration = p0_data["aeration_vvm"]
        st.session_state.gassed_corr = p0_data["gassed_corr"]
        st.session_state.cell_type = p0_data["cell_type"]

        # Stage 1 (Bottom)
        st.session_state.stg0_type = p0_data["stages"][0]["impeller_type"]
        st.session_state.stg0_d_ratio = p0_data["stages"][0]["diameter_ratio"]
        st.session_state.stg0_c = p0_data["stages"][0]["clearance_m"]

        # Stage 1 default
        st.session_state.stg1_type = ImpellerType.PITCHED_BLADE_45.value
        st.session_state.stg1_d_ratio = 0.38
        st.session_state.stg1_c = 0.50

        # Stage 2 default
        st.session_state.stg2_type = ImpellerType.MARINE_PROPELLER.value
        st.session_state.stg2_d_ratio = 0.35
        st.session_state.stg2_c = 0.75

    def sync_preset_callback():
        chosen = st.session_state.preset_select_widget
        st.session_state.current_preset_key = chosen
        p_data = PRESETS[chosen]
        st.session_state.tank_diameter = p_data["diameter_m"]
        st.session_state.liquid_height = p_data["liquid_height_m"]
        st.session_state.bottom_type = p_data["bottom_type"]
        st.session_state.baffle_count = p_data["baffle_count"]
        st.session_state.baffle_ratio = p_data["baffle_width_ratio"]
        st.session_state.num_stages = p_data["num_stages"]
        st.session_state.density = p_data["density_kg_m3"]
        st.session_state.viscosity_cp = p_data["viscosity_cp"]
        st.session_state.coalescence = p_data["media_coalescence"]
        st.session_state.rpm = p_data["rpm"]
        st.session_state.aeration = p_data["aeration_vvm"]
        st.session_state.gassed_corr = p_data["gassed_corr"]
        st.session_state.cell_type = p_data["cell_type"]

        # Sync stages
        stages = p_data["stages"]
        if len(stages) >= 1:
            st.session_state.stg0_type = stages[0]["impeller_type"]
            st.session_state.stg0_d_ratio = stages[0]["diameter_ratio"]
            st.session_state.stg0_c = stages[0]["clearance_m"]
        if len(stages) >= 2:
            st.session_state.stg1_type = stages[1]["impeller_type"]
            st.session_state.stg1_d_ratio = stages[1]["diameter_ratio"]
            st.session_state.stg1_c = stages[1]["clearance_m"]
        if len(stages) >= 3:
            st.session_state.stg2_type = stages[2]["impeller_type"]
            st.session_state.stg2_d_ratio = stages[2]["diameter_ratio"]
            st.session_state.stg2_c = stages[2]["clearance_m"]

    selected_preset = st.sidebar.selectbox(
        "Industrial Benchmark Presets",
        preset_keys,
        index=preset_keys.index(st.session_state.current_preset_key),
        key="preset_select_widget",
        on_change=sync_preset_callback,
    )
    st.sidebar.caption(PRESETS[selected_preset]["description"])

    # --- 1. Reactor Anatomy ---
    st.sidebar.subheader("1. Reactor Anatomy")
    tank_T = st.sidebar.slider("Tank Diameter T (m)", 0.20, 3.00, float(st.session_state.tank_diameter), 0.05)

    # Dish depth calculation for min liquid height
    bottom_type_str = st.sidebar.selectbox(
        "Bottom Head Geometry",
        [BottomType.ELLIPTICAL_2_1.value, BottomType.HEMISPHERICAL.value, BottomType.FLAT.value],
        index=[BottomType.ELLIPTICAL_2_1.value, BottomType.HEMISPHERICAL.value, BottomType.FLAT.value].index(
            st.session_state.bottom_type
        ),
    )
    dish_depth = 0.0
    if bottom_type_str == BottomType.ELLIPTICAL_2_1.value:
        dish_depth = tank_T / 4.0
    elif bottom_type_str == BottomType.HEMISPHERICAL.value:
        dish_depth = tank_T / 2.0

    min_H = round(dish_depth + 0.10, 2)
    tank_H = st.sidebar.slider(
        "Liquid Height H (m)",
        max(0.25, min_H),
        4.50,
        max(float(st.session_state.liquid_height), min_H),
        0.05,
    )

    baffle_options = [0, 3, 4, 6, 8]
    baffle_idx = baffle_options.index(st.session_state.baffle_count) if st.session_state.baffle_count in baffle_options else 2
    baffle_count = st.sidebar.selectbox("Baffle Count", baffle_options, index=baffle_idx)

    baffle_width_ratio = 0.10
    if baffle_count > 0:
        ratio_choice = st.sidebar.radio("Baffle Width Ratio", ["T / 10 (0.10)", "T / 12 (0.0833)"], index=0)
        baffle_width_ratio = 0.10 if "10" in ratio_choice else 0.0833

    # --- 2. Impeller Shaft Configuration ---
    st.sidebar.subheader("2. Impeller Shaft Configuration")
    num_stages = st.sidebar.selectbox("Number of Stages", [1, 2, 3], index=st.session_state.num_stages - 1)

    impeller_type_choices = [
        ImpellerType.RUSHTON_6_BLADE.value,
        ImpellerType.PITCHED_BLADE_45.value,
        ImpellerType.MARINE_PROPELLER.value,
    ]

    stages_config = []

    # Stage 1 (Bottom)
    with st.sidebar.expander("Stage 1 (Bottom Impeller)", expanded=True):
        stg0_type = st.selectbox(
            "Type (Stage 1)",
            impeller_type_choices,
            index=impeller_type_choices.index(st.session_state.stg0_type),
            key="stg0_type_widget",
        )
        stg0_dr = st.slider(
            "Di / T Ratio (Stage 1)",
            0.20,
            0.55,
            float(st.session_state.stg0_d_ratio),
            0.01,
            key="stg0_dr_widget",
        )
        c0_min = round(dish_depth + 0.05, 3)
        c0_max = round(tank_H - 0.10, 3) if num_stages == 1 else round(tank_H - (num_stages * 0.15), 3)
        c0_max = max(c0_min + 0.05, c0_max)
        stg0_c = st.slider(
            "Clearance C0 (m)",
            c0_min,
            c0_max,
            min(max(float(st.session_state.stg0_c), c0_min), c0_max),
            0.01,
            key="stg0_c_widget",
        )
        stages_config.append({"impeller_type": stg0_type, "diameter_ratio": stg0_dr, "clearance_m": stg0_c})

    # Stage 1 (Middle)
    if num_stages >= 2:
        with st.sidebar.expander("Stage 1 (Middle Impeller)", expanded=True):
            stg1_type = st.selectbox(
                "Type (Stage 1)",
                impeller_type_choices,
                index=impeller_type_choices.index(st.session_state.stg1_type),
                key="stg1_type_widget",
            )
            stg1_dr = st.slider(
                "Di / T Ratio (Stage 1)",
                0.20,
                0.55,
                float(st.session_state.stg1_d_ratio),
                0.01,
                key="stg1_dr_widget",
            )
            c1_min = round(stg0_c + 0.12, 3)
            c1_max = round(tank_H - 0.08, 3) if num_stages == 2 else round(tank_H - 0.20, 3)
            c1_max = max(c1_min + 0.05, c1_max)
            stg1_c = st.slider(
                "Clearance C1 (m)",
                c1_min,
                c1_max,
                min(max(float(st.session_state.stg1_c), c1_min), c1_max),
                0.01,
                key="stg1_c_widget",
            )
            stages_config.append({"impeller_type": stg1_type, "diameter_ratio": stg1_dr, "clearance_m": stg1_c})

    # Stage 2 (Top)
    if num_stages >= 3:
        with st.sidebar.expander("Stage 2 (Top Impeller)", expanded=True):
            stg2_type = st.selectbox(
                "Type (Stage 2)",
                impeller_type_choices,
                index=impeller_type_choices.index(st.session_state.stg2_type),
                key="stg2_type_widget",
            )
            stg2_dr = st.slider(
                "Di / T Ratio (Stage 2)",
                0.20,
                0.55,
                float(st.session_state.stg2_d_ratio),
                0.01,
                key="stg2_dr_widget",
            )
            c2_min = round(stages_config[1]["clearance_m"] + 0.12, 3)
            c2_max = max(c2_min + 0.05, round(tank_H - 0.05, 3))
            stg2_c = st.slider(
                "Clearance C2 (m)",
                c2_min,
                c2_max,
                min(max(float(st.session_state.stg2_c), c2_min), c2_max),
                0.01,
                key="stg2_c_widget",
            )
            stages_config.append({"impeller_type": stg2_type, "diameter_ratio": stg2_dr, "clearance_m": stg2_c})

    # --- 3. Broth Properties & Operating Conditions ---
    st.sidebar.subheader("3. Broth & Operating Conditions")
    density = st.sidebar.slider("Broth Density ρ (kg/m³)", 900.0, 1200.0, float(st.session_state.density), 10.0)
    viscosity_cp = st.sidebar.number_input(
        "Broth Viscosity µ (cP)",
        min_value=0.5,
        max_value=5000.0,
        value=float(st.session_state.viscosity_cp),
        step=1.0,
    )
    coalescence = st.sidebar.radio(
        "Media Coalescence",
        ["Non-Coalescing (Ionic Broth/Antifoam)", "Coalescing (Pure Water/Salts)"],
        index=0 if st.session_state.coalescence == "non_coalescing" else 1,
    )
    is_coalescing = "Pure" in coalescence

    rpm = st.sidebar.slider("Agitation Speed (RPM)", 20.0, 600.0, float(st.session_state.rpm), 10.0)
    aeration = st.sidebar.slider("Aeration Rate (vvm)", 0.0, 2.0, float(st.session_state.aeration), 0.05)
    gassed_corr = st.sidebar.selectbox("Gassed Power Model", ["michel", "bakker"], index=0)

    cell_choices = [CellType.MICROBIAL.value, CellType.PLANT_CELL.value, CellType.MAMMALIAN_CELL.value]
    cell_type_str = st.sidebar.selectbox("Cell Culture Sensitivity", cell_choices, index=cell_choices.index(st.session_state.cell_type))

    # Assemble parameter dictionary
    sim_params = {
        "diameter_m": tank_T,
        "liquid_height_m": tank_H,
        "bottom_type": bottom_type_str,
        "baffle_count": baffle_count,
        "baffle_width_ratio": baffle_width_ratio,
        "num_stages": num_stages,
        "stages": stages_config,
        "density_kg_m3": density,
        "viscosity_cp": viscosity_cp,
        "media_coalescence": "coalescing" if is_coalescing else "non_coalescing",
        "rpm": rpm,
        "aeration_vvm": aeration,
        "gassed_corr": gassed_corr,
        "cell_type": cell_type_str,
    }

    # Solve simulation
    tank, fluid, ops, sim_result, field_2d = build_simulation_from_params(sim_params)

    # -------------------------------------------------------------------------
    # MAIN VIEW: KPI BANNER
    # -------------------------------------------------------------------------
    st.title("BioMix-STR Bioreactor Engineering Suite")
    st.markdown(
        "*Bioprocess engineering stirred-tank simulation with 2D/3D hydrodynamics, "
        "turbulent scales, and Ansys Fluent CFD bridge.*"
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-title">Working Volume VL</div>
                <div class="metric-value">{sim_result.working_volume_m3 * 1000.0:.1f} L</div>
                <div class="metric-sub">{sim_result.working_volume_m3:.3f} m³ | Aspect H/T = {tank_H/tank_T:.2f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        re_val = sim_result.stages[0].re_i
        regime_val = sim_result.stages[0].flow_regime.value.upper()
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-title">Impeller Re_i & Regime</div>
                <div class="metric-value">{re_val:,.0f}</div>
                <div class="metric-sub">Regime: {regime_val}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col3:
        p0_w = sim_result.total_ungassed_power_w
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-title">Ungassed Power P0</div>
                <div class="metric-value">{p0_w:.1f} W</div>
                <div class="metric-sub">{p0_w/1000.0:.2f} kW | Np = {sim_result.stages[0].np_val:.2f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col4:
        pg_w = sim_result.total_gassed_power_w
        pg_vl = pg_w / max(1e-4, sim_result.working_volume_m3)
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-title">Gassed Power Pg</div>
                <div class="metric-value">{pg_w:.1f} W</div>
                <div class="metric-sub">{pg_vl:.1f} W/m³ | Pg/P0 = {pg_w/max(1e-3, p0_w):.2f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    col5, col6, col7, col8 = st.columns(4)
    with col5:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-title">Max Tip Speed v_tip</div>
                <div class="metric-value">{sim_result.max_tip_speed_m_s:.2f} m/s</div>
                <div class="metric-sub">Shear Rate = {sim_result.stages[0].shear_rate_s_inv:.1f} s⁻¹</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col6:
        lam_k = sim_result.lambda_k_min_um
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-title">Min Kolmogorov Scale</div>
                <div class="metric-value">{lam_k:.1f} µm</div>
                <div class="metric-sub">Eddy Microscale λ_K</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col7:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-title">95% Mixing Time θ95</div>
                <div class="metric-value">{sim_result.mixing_time_95_s:.1f} s</div>
                <div class="metric-sub">Bulk Circulation = {sim_result.circulation_time_s:.2f} s</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col8:
        kla_h = sim_result.kla_h_inv
        dz_pct = field_2d.dead_zone_fraction * 100.0
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-title">Oxygen kLa & Dead Zones</div>
                <div class="metric-value">{kla_h:.1f} h⁻¹</div>
                <div class="metric-sub">{dz_pct:.1f}% Dead Zone Fraction</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # -------------------------------------------------------------------------
    # ACTIVE ENGINEERING WARNINGS
    # -------------------------------------------------------------------------
    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
    if sim_result.warnings:
        for w in sim_result.warnings:
            if any(term in w.upper() for term in ["DAMAGE", "CRITICAL", "FLOODING", "EXCEEDS"]):
                st.error(f"⚠️ **Engineering Failure:** {w}")
            else:
                st.warning(f"🔔 **Bioprocess Warning:** {w}")
    else:
        st.success(
            "✅ **All Bioprocess Engineering Criteria Satisfied:** "
            "No impeller flooding, shear rates remain within safe physiological cell thresholds, "
            "and vigorous turbulent circulation is established."
        )

    # -------------------------------------------------------------------------
    # FOUR WORKSPACE TABS
    # -------------------------------------------------------------------------
    tab1, tab2, tab3, tab4 = st.tabs(
        [
            "📊 2D Flow, Shear & Power Curves",
            "🌐 3D PyVista CAD & VTK Export",
            "🚀 Ansys Fluent 2026 R1 CFD Bridge",
            "🔬 Impeller Topology Comparator & Theory",
        ]
    )

    # =========================================================================
    # TAB 1: 2D FLOW, SHEAR & POWER CURVES
    # =========================================================================
    with tab1:
        st.subheader("Axisymmetric Hydrodynamic Contours & Power Curves")
        st.caption(
            "Calculated via stream function circulation loops, Rankine vortex kinematics, "
            "and Metzner-Otto shear fields."
        )

        fig_2d = Plotter2D.create_summary_dashboard(sim_result, field_2d)
        st.pyplot(fig_2d, use_container_width=True)
        plt.close(fig_2d)

        st.subheader("Impeller Stage Hydrodynamic Breakdown")
        stage_records = []
        for stg in sim_result.stages:
            stage_records.append(
                {
                    "Stage": f"Stage {stg.stage_index}",
                    "Impeller": stg.impeller_type.value,
                    "Flow Direction": stg.flow_direction.value,
                    "Diameter Di (m)": f"{stg.diameter_m:.3f}",
                    "Clearance C (m)": f"{stg.clearance_m:.3f}",
                    "Re_i": f"{stg.re_i:,.0f}",
                    "Regime": stg.flow_regime.value,
                    "Np": f"{stg.np_val:.2f}",
                    "Ungassed P0 (W)": f"{stg.ungassed_power_w:.1f}",
                    "Gassed Pg (W)": f"{stg.gassed_power_w:.1f}",
                    "Tip Speed (m/s)": f"{stg.tip_speed_m_s:.2f}",
                    "Shear Rate (s⁻¹)": f"{stg.shear_rate_s_inv:.1f}",
                    "Shear Stress (Pa)": f"{stg.shear_stress_pa:.2f}",
                    "Pumping Qp (m³/s)": f"{stg.pumping_rate_m3_s:.4f}",
                    "Flooded?": "YES" if stg.is_flooded else "No",
                }
            )
        st.dataframe(pd.DataFrame(stage_records), use_container_width=True)

    # =========================================================================
    # TAB 2: 3D PYVISTA CAD & VTK EXPORT
    # =========================================================================
    with tab2:
        st.subheader("3D Bioreactor CAD Anatomy & Circulation Streamlines")
        st.caption(
            "Ray-traced PyVista off-screen rendering displaying 3D dish heads, baffles, "
            "multi-stage impellers, toroidal spargers, and 3D velocity streamline tubes."
        )

        with st.spinner("Rendering high-resolution 3D PyVista scene..."):
            img_3d = Visualizer3D.render_3d_scene(sim_result, field_2d, window_size=(1000, 750))

        st.image(
            img_3d,
            use_container_width=True,
            caption="3D Stirred-Tank Bioreactor Anatomy & Streamlines (Colored by Circulation Speed)",
        )

        st.markdown("---")
        st.subheader("Export VTK / VTP Package for ParaView & Ansys EnSight")
        st.markdown(
            "Download standard CFD surface meshes (`.vtp`) and 3D structured flow vector grids (`.vtk`) "
            "for external inspection in ParaView, Tecplot, or Ansys EnSight."
        )

        output_dir = os.environ.get("BIOMIX_OUTPUT_DIR") or os.path.join(tempfile.gettempdir(), "biomix_exports")
        os.makedirs(output_dir, exist_ok=True)
        vtk_files = Visualizer3D.export_vtk_package(sim_result, field_2d, output_dir=output_dir)

        col_vtk1, col_vtk2 = st.columns(2)
        with col_vtk1:
            vtk_path = vtk_files.get("flow_field_3d", "")
            if os.path.exists(vtk_path):
                with open(vtk_path, "rb") as f:
                    st.download_button(
                        label="📥 Download 3D Flow Field (.vtk)",
                        data=f.read(),
                        file_name="flow_field_3d.vtk",
                        mime="application/octet-stream",
                        use_container_width=True,
                    )
        with col_vtk2:
            vtp_path = vtk_files.get("reactor_anatomy", "")
            if os.path.exists(vtp_path):
                with open(vtp_path, "rb") as f:
                    st.download_button(
                        label="📥 Download CAD Anatomy Mesh (.vtp)",
                        data=f.read(),
                        file_name="reactor_anatomy.vtp",
                        mime="application/octet-stream",
                        use_container_width=True,
                    )

    # =========================================================================
    # TAB 3: ANSYS FLUENT 2026 R1 CFD BRIDGE
    # =========================================================================
    with tab3:
        st.subheader("Ansys Fluent 2026 R1 (v261) CFD Verification Bridge")
        st.caption(
            "Direct bridge between fast empirical BPE design equations and 3D "
            "Multiple Reference Frame (MRF) Navier-Stokes CFD simulations."
        )

        # Environment detection
        fluent_status = FluentCFDVerifier.check_local_fluent_installation()
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            if fluent_status.get("fluent_exe_exists", False):
                st.success(f"✅ Ansys Fluent Detected: Version {fluent_status.get('ansys_version', '2026 R1')}")
                st.caption(f"Path: `{fluent_status.get('fluent_exe_path')}`")
            else:
                st.info("ℹ️ Local Ansys Fluent Executable: Standalone Mode (High-Fidelity Benchmark Active)")
        with col_c2:
            if fluent_status.get("pyfluent_installed", False):
                st.success(f"✅ PyFluent Active (v{fluent_status.get('pyfluent_version', 'unknown')})")
            else:
                st.info("ℹ️ PyFluent Driver: Automated TUI Journal Generation Active")

        # CFD Parity Plot & Integral Comparison
        parity = FluentCFDVerifier.compute_cfd_benchmark_comparison(sim_result, field_2d)

        fig_parity = FluentCFDVerifier.plot_cfd_parity_comparison(sim_result, field_2d)
        st.pyplot(fig_parity, use_container_width=True)
        plt.close(fig_parity)

        st.subheader("Integral Parity Comparison (BPE Correlations vs. Fluent MRF CFD)")
        df_parity = pd.DataFrame([
            {
                "Metric": "Power Number (Np)",
                "BPE Empirical": f"{parity.biomix_np:.3f}",
                "Fluent CFD": f"{parity.cfd_np:.3f}",
                "Parity (%)": f"{parity.np_parity_pct:.1f}%",
            },
            {
                "Metric": "Shaft Torque (N·m)",
                "BPE Empirical": f"{parity.biomix_torque_n_m:.3f}",
                "Fluent CFD": f"{parity.cfd_torque_n_m:.3f}",
                "Parity (%)": f"{parity.torque_parity_pct:.1f}%",
            },
            {
                "Metric": "Pumping Number (Nq)",
                "BPE Empirical": f"{parity.biomix_nq:.3f}",
                "Fluent CFD": f"{parity.cfd_nq:.3f}",
                "Parity (%)": f"{parity.nq_parity_pct:.1f}%",
            },
            {
                "Metric": "Peak Jet Velocity (ur/v_tip)",
                "BPE Empirical": f"{parity.peak_velocity_ratio_biomix:.3f}",
                "Fluent CFD": f"{parity.peak_velocity_ratio_cfd:.3f}",
                "Parity (%)": f"{abs(parity.peak_velocity_ratio_biomix - parity.peak_velocity_ratio_cfd)/max(1e-3, parity.peak_velocity_ratio_biomix)*100.0:.1f}%",
            },
        ])
        st.dataframe(df_parity, use_container_width=True)

        if parity.is_verified:
            st.success(
                "✅ **CFD Parity Passed:** All integral metrics fall within standard industrial "
                "tolerance of 15% relative error."
            )
        else:
            st.warning(
                "⚠️ **CFD Divergence Alert:** Parity metrics deviate beyond 15% threshold; "
                "verify MRF zone boundaries or grid refinement."
            )

        # MRF TUI Journal Generator
        st.markdown("---")
        st.subheader("Automated Ansys Fluent 2026 R1 MRF TUI Journal Generator")
        st.markdown(
            "Generate a production-ready Fluent batch journal (`.jou`) that configures the MRF fluid zones, "
            "boundary conditions, rotational velocities, and realizable k-epsilon turbulence model."
        )

        jou_path = os.path.join(output_dir, "biomix_str_mrf.jou")
        FluentJournalGenerator.generate_tui_journal(sim_result, output_path=jou_path)

        if os.path.exists(jou_path):
            with open(jou_path, "r") as f:
                jou_content = f.read()

            st.download_button(
                label="📥 Download Ansys Fluent TUI Journal (.jou)",
                data=jou_content,
                file_name="biomix_str_mrf.jou",
                mime="text/plain",
                use_container_width=True,
            )

            with st.expander("Preview Ansys Fluent TUI Journal Script", expanded=False):
                preview_lines = "\n".join(jou_content.splitlines()[:35])
                st.code(preview_lines + "\n; ... [Truncated: Full journal in download above] ...", language="scheme")

    # =========================================================================
    # TAB 4: IMPELLER TOPOLOGY COMPARATOR & THEORY
    # =========================================================================
    with tab4:
        st.subheader("Side-by-Side Impeller Topology Benchmark")
        st.caption(
            "Direct comparison of Rushton 6-Blade, Pitched-Blade 45°, Marine Propeller, and Dual Hybrid "
            "under identical tank geometry, broth rheology, and operating speed."
        )

        df_comp, fig_comp = compare_impeller_topologies(tank, fluid, ops)
        st.pyplot(fig_comp, use_container_width=True)
        plt.close(fig_comp)

        st.subheader("Comparative Topology Metrics Table")
        st.dataframe(df_comp, use_container_width=True)

        st.markdown("---")
        st.subheader("Governing Bioprocess Engineering Correlations & Theory")

        st.markdown(
            r"""
            ### 1. Power Draw in Stirred Tanks
            The ungassed power draw $P_0$ is governed by the dimensionless Power Number $N_p$:
            $$P_0 = N_p \rho N^3 D_i^5$$
            where:
            - Fully turbulent regime ($Re_i \ge 10^4$): $N_p \approx \text{const}$ ($5.2$ for Rushton, $1.27$ for PBT, $0.32$ for Propeller).
            - Laminar regime ($Re_i < 10$): $N_p = K_L / Re_i$.
            - Transitional regime ($10 \le Re_i < 10^4$): PCHIP monotonicity-preserving cubic spline interpolation.

            ### 2. Gassed Power Reduction
            Gas sparging lowers apparent broth density and forms gas cavities behind impeller blades:
            - **Michel & Miller (1962):**
              $$P_g = 0.081 \left( \frac{P_0^2 N D_i^3}{Q_g^{0.56}} \right)^{0.45}$$
            - **Bakker & van den Akker (1994):**
              $$\frac{P_g}{P_0} = 1.0 - (1.0 - \text{cavity\_factor}) \cdot \tanh(2.5 \cdot Fl_G)$$

            ### 3. Oxygen Mass Transfer Coefficient ($k_L a$)
            Governed by the classic van 't Riet (1979) empirical correlation:
            $$k_L a = C_1 \left( \frac{P_g}{V_L} \right)^\alpha v_s^\beta$$
            - Non-Coalescing Broth (Ionic / Media): $C_1 = 0.002$, $\alpha = 0.70$, $\beta = 0.20$
            - Coalescing Pure Water: $C_1 = 0.026$, $\alpha = 0.40$, $\beta = 0.50$

            ### 4. Turbulent Kolmogorov Microscale & Cell Damage
            The smallest turbulent eddy scale $\lambda_K$ in the impeller discharge stream:
            $$\lambda_K = \left( \frac{\nu^3}{\varepsilon_{\text{max}}} \right)^{1/4}$$
            For animal cell cultures (CHO, stem cells), shear sensitivity criteria dictate that $\lambda_K$
            must exceed the cell diameter ($\approx 15\text{--}25\,\mu\text{m}$) to prevent lethal shear rupture.

            ### 5. Rankine Vortex Funnel in Unbaffled Tanks
            Without baffles, tangential swirl dominates, producing a free-surface vortex depression:
            $$h_v = \frac{\Gamma^2}{8 \pi^2 g R^2}$$
            Deep vortex funnels that reach the top impeller blade cause catastrophic gas drawdown and motor destabilization.
            """
        )


if __name__ == "__main__":
    main()
