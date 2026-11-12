"""Transparent engineering equations for the active BioMix-STR configuration."""

from __future__ import annotations

import math
from typing import Any, Dict, List

from biomix.correlations import METZNER_OTTO_KS, calc_power_number, calc_reynolds_number, classify_flow_regime
from biomix.engine import HydrodynamicEngine
from biomix.models import FluidProperties, OperatingConditions, TankGeometry


def _card(
    key: str,
    title: str,
    equation: str,
    variables: List[Dict[str, str]],
    applicability: str,
    assumptions: str,
    worked: str,
    result: str,
    available: bool = True,
) -> Dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "equation": equation,
        "variables": variables,
        "applicability": applicability,
        "assumptions": assumptions,
        "worked_substitution": worked,
        "result": result,
        "available": available,
    }


def build_equation_cards(
    tank: TankGeometry,
    fluid: FluidProperties,
    ops: OperatingConditions,
) -> Dict[str, Any]:
    """Evaluate the transparent reference equations for an active configuration.

    These values are engineering references.  They complement a Fluent result;
    they never replace its field-derived quantities.
    """
    stage = tank.impellers[0]
    n = ops.rps
    rho = fluid.density_kg_m3
    mu = fluid.viscosity_pa_s
    d = stage.diameter_m
    volume = tank.working_volume_m3
    re_i = calc_reynolds_number(rho, n, d, mu)
    regime = classify_flow_regime(re_i).value
    np_val = calc_power_number(re_i, stage.impeller_type, tank.is_baffled)
    power = np_val * rho * n**3 * d**5
    omega = 2.0 * math.pi * n
    torque = power / omega if omega else 0.0
    tip_speed = math.pi * n * d
    sim = HydrodynamicEngine.run(tank, fluid, ops)
    gap = None
    if len(tank.impellers) > 1:
        gap = tank.impellers[1].clearance_m - tank.impellers[0].clearance_m

    rheo_model = getattr(ops, "rheology_model", None) or getattr(fluid, "rheology_model", "newtonian")
    K_input = getattr(ops, "consistency_k_pa_s_n", None) if getattr(ops, "consistency_k_pa_s_n", None) is not None else getattr(fluid, "consistency_k_pa_s_n", None)
    n_input = getattr(ops, "flow_behavior_index_n", None) if getattr(ops, "flow_behavior_index_n", None) is not None else getattr(fluid, "flow_behavior_index_n", None)

    is_power_law = (
        rheo_model == "power_law"
        and K_input is not None
        and n_input is not None
    )
    if is_power_law:
        K_val = float(K_input)
        n_val = float(n_input)
        ks = METZNER_OTTO_KS.get(stage.impeller_type, 30.0 if stage.impeller_type.is_close_clearance else 11.5)
        gamma_avg = ks * n
        mu_app = K_val * (max(gamma_avg, 1e-4) ** (n_val - 1.0))
        pl_assumptions = "Non-Newtonian power-law fluid evaluated using Metzner-Otto average shear rate."
        pl_worked = f"K = {K_val:.3g} Pa·sⁿ, n = {n_val:.3f}, kₛ = {ks:.1f}; γ̇_avg = kₛ·N = {gamma_avg:.2f} s⁻¹"
        pl_result = f"μ_app = {mu_app:.4g} Pa·s ({mu_app * 1000:,.1f} cP)"
        pl_available = True
    else:
        pl_assumptions = "Requires K and n measured for the specific material and temperature."
        pl_worked = "K and n have not been supplied for the active Newtonian model."
        pl_result = "Unavailable until a measured power-law rheology model is selected."
        pl_available = False

    cards = [
        _card(
            "newtonian_viscosity", "Newtonian constitutive relation", "τ = μγ̇",
            [{"symbol": "τ", "meaning": "shear stress", "unit": "Pa"}, {"symbol": "μ", "meaning": "dynamic viscosity", "unit": "Pa·s"}, {"symbol": "γ̇", "meaning": "shear rate", "unit": "s⁻¹"}],
            "Newtonian liquids with viscosity independent of shear rate.",
            "The active single-phase MVP treats the liquid as Newtonian." if not is_power_law else "Liquid rheology is set to Power-Law Non-Newtonian.",
            f"μ = {mu:.4g} Pa·s; local γ̇ is obtained from the CFD velocity gradient when a verified field is available.",
            "A local stress value requires a resolved velocity-gradient field.",
        ),
        _card(
            "power_law", "Power-law rheology", "τ = Kγ̇ⁿ",
            [{"symbol": "K", "meaning": "consistency index", "unit": "Pa·sⁿ"}, {"symbol": "n", "meaning": "flow behavior index", "unit": "-"}],
            "Shear-thinning or shear-thickening broths after rheology has been measured.",
            pl_assumptions,
            pl_worked,
            pl_result,
            pl_available,
        ),
        _card(
            "impeller_reynolds", "Impeller Reynolds number", "Reᵢ = ρNDᵢ² / μ",
            [{"symbol": "ρ", "meaning": "liquid density", "unit": "kg·m⁻³"}, {"symbol": "N", "meaning": "rotation rate", "unit": "s⁻¹"}, {"symbol": "Dᵢ", "meaning": "impeller diameter", "unit": "m"}],
            "Stirred-tank flow regime screening.", "Uses the primary impeller and bulk liquid viscosity.",
            f"({rho:.0f} × {n:.4f} × {d:.3f}²) / {mu:.4g}", f"Reᵢ = {re_i:,.0f} ({regime})",
        ),
        _card(
            "ungassed_power", "Ungassed power", "P = NₚρN³Dᵢ⁵",
            [{"symbol": "P", "meaning": "shaft power", "unit": "W"}, {"symbol": "Nₚ", "meaning": "power number", "unit": "-"}],
            "Single-phase stirred tank; compare with Fluent torque-derived power.",
            "Nₚ is correlation-based and depends on impeller, Reynolds number, and baffling.",
            f"{np_val:.3f} × {rho:.0f} × {n:.4f}³ × {d:.3f}⁵", f"P = {power:.3f} W (primary stage reference)",
        ),
        _card(
            "shaft_torque", "Shaft torque", "M = P / ω;  ω = 2πN",
            [{"symbol": "M", "meaning": "shaft torque", "unit": "N·m"}, {"symbol": "ω", "meaning": "angular speed", "unit": "rad·s⁻¹"}],
            "Rotating shaft design and CFD/result cross-check.", "Uses the ungassed power reference above.",
            f"{power:.3f} / (2π × {n:.4f})", f"M = {torque:.5f} N·m",
        ),
        _card(
            "tip_speed", "Impeller tip speed", "uᵗⁱᵖ = πNDᵢ",
            [{"symbol": "uᵗⁱᵖ", "meaning": "peripheral blade speed", "unit": "m·s⁻¹"}],
            "Shear-sensitive process screening and scale-up comparison.", "This is a blade-speed indicator, not a local cell-damage prediction.",
            f"π × {n:.4f} × {d:.3f}", f"uᵗⁱᵖ = {tip_speed:.3f} m·s⁻¹",
        ),
        _card(
            "power_density", "Power per liquid volume", "P/Vᴸ",
            [{"symbol": "Vᴸ", "meaning": "working liquid volume", "unit": "m³"}],
            "Scale-up comparison and energy-intensity screening.", "Uses the total engineering power reference across selected stages.",
            f"{sim.total_ungassed_power_w:.3f} / {volume:.5f}", f"P/Vᴸ = {sim.specific_ungassed_power_w_m3:.1f} W·m⁻³",
        ),
        _card(
            "mixing_time", "Mixing-time reference", "Nθ₉₅ ≈ 1.54Vᴸ / Dᵢ³",
            [{"symbol": "θ₉₅", "meaning": "95% blend time", "unit": "s"}],
            "High-Reynolds-number, baffled, single-phase reference relationship (Standard BPE correlation).",
            "Engine evaluates full vessel geometry & viscous effects via Ruszkowski correlation.",
            f"Reference tₘ = {1.54 * volume / max(1e-6, n * (d**3)):.2f} s; Ruszkowski θ₉₅ = {sim.mixing_time_95_s:.2f} s.",
            f"θ₉₅ ≈ {sim.mixing_time_95_s:.2f} s",
        ),
        _card(
            "impeller_spacing", "Inter-impeller spacing", "ΔC / Dᵢ",
            [{"symbol": "ΔC", "meaning": "centre-to-centre impeller spacing (stage clearance gap)", "unit": "m"}],
            "Multi-stage open-impeller arrangements.", "Compare with the lower impeller diameter; flow interaction remains configuration dependent.",
            (f"{gap:.3f} / {d:.3f}" if gap is not None else "Add a second impeller to evaluate spacing."),
            (f"ΔC/Dᵢ = {gap / d:.2f}" if gap is not None else "Unavailable for a single-stage configuration."),
            gap is not None,
        ),
        _card(
            "scale_up", "Scale-up criteria", "Hold selected engineering criterion constant",
            [{"symbol": "P/Vᴸ", "meaning": "power density", "unit": "W·m⁻³"}, {"symbol": "kᴸa", "meaning": "oxygen mass transfer", "unit": "s⁻¹"}, {"symbol": "uᵗⁱᵖ", "meaning": "tip speed", "unit": "m·s⁻¹"}],
            "Geometrically similar stirred tanks (Standard Bioprocess Similitude).", "Select constant P/V, kLa, tip speed, Reynolds number, or blend time.",
            f"Current: P/Vᴸ = {sim.specific_ungassed_power_w_m3:.1f} W·m⁻³; uᵗⁱᵖ = {sim.max_tip_speed_m_s:.3f} m·s⁻¹.",
            "Select one criterion in the scale-up comparison workspace.",
        ),
        _card(
            "oxygen_transfer", "Oxygen transfer rate", "OTR = kᴸa(C* − Cᴸ)",
            [{"symbol": "kᴸa", "meaning": "volumetric mass-transfer coefficient", "unit": "s⁻¹"}],
            "Gas-liquid systems with a validated aeration and mass-transfer model.",
            "The active MVP is single-phase liquid and does not calculate Fluent-derived kᴸa.",
            "Gas-liquid solver is not active.", "Unavailable for the single-phase Fluent MVP.", False,
        ),
    ]
    return {
        "title": "Theory & Equations",
        "result_scope": "engineering_reference",
        "notice": "Equation results are transparent engineering references. Field quantities remain authoritative only when loaded from a verified Fluent result.",
        "cards": cards,
    }
