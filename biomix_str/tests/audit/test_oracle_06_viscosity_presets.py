"""Physics Oracle 6: Viscosity Presets and Low-Re Regime Labeling.

Oracle 6:
- Output metrics must differ significantly across viscosity presets where Reynolds
  number differs by orders of magnitude.
- 150 cP broth (Re ~ 544 at 250 RPM, D=0.15m) must NOT be labeled "Turbulent".
  The application's documented bioprocess boundaries designate 200 <= Re <= 10,000
  as the Transitional regime.
- High-viscosity presets (150 cP, 5,000 cP, 25,000 cP) must produce distinct
  hydrodynamic states (mixing time, Reynolds number, laminar power number scaling).

Never loosens tolerance to pass.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from biomix.correlations import calc_reynolds_number, classify_flow_regime, FlowRegime
from biomix.engine import HydrodynamicEngine
from biomix.models import FluidProperties, ImpellerSpec, ImpellerType, OperatingConditions, TankGeometry
from biomix.server import app

client = TestClient(app)


def test_oracle_06_viscosity_sweep_produces_differing_outputs():
    """Oracle 6: Hydrodynamic outputs must differ where viscosity changes significantly."""
    tank = TankGeometry(
        diameter_m=0.45,
        liquid_height_m=0.50,
        baffle_count=4,
        impellers=[ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.15, clearance_m=0.14)]
    )
    ops = OperatingConditions(rpm=250.0)

    viscosities = [0.001, 0.150, 5.0, 25.0]  # 1 cP, 150 cP, 5000 cP, 25000 cP
    results = []

    for mu in viscosities:
        fluid = FluidProperties(name=f"Broth_{mu}Pa_s", density_kg_m3=1000.0, viscosity_pa_s=mu)
        res = HydrodynamicEngine.run(tank, fluid, ops)
        results.append(res)

    # Check Reynolds number differs by orders of magnitude
    re_values = [r.stages[0].re_i for r in results]
    assert re_values[0] > 10000.0  # ~81,667
    assert 200.0 <= re_values[1] < 10000.0  # ~544.4
    assert re_values[2] < 200.0  # ~16.3
    assert re_values[3] < 10.0  # ~3.3

    # Check that mixing time theta_95 changes significantly
    mix_times = [r.mixing_time_95_s for r in results]
    assert len(set(mix_times)) == len(viscosities), "Mixing times must differ across viscosity regimes"


def test_oracle_06_150cp_must_not_be_labeled_turbulent_in_correlations():
    """Oracle 6: 150 cP broth at 250 RPM (D=0.14m) has Re ~ 544 and must classify as Transitional, not Turbulent."""
    rho = 1000.0
    n_rps = 250.0 / 60.0
    d_m = 0.14  # Yields Re = 544.44
    mu_150cp = 0.150

    re = calc_reynolds_number(rho, n_rps, d_m, mu_150cp)
    assert 540.0 <= re <= 550.0, f"Expected Re ~ 544, got {re:.2f}"

    regime = classify_flow_regime(re)
    assert regime != FlowRegime.TURBULENT, f"150 cP broth (Re={re:.1f}) must not be Turbulent!"
    assert regime == FlowRegime.TRANSITIONAL, f"150 cP broth (Re={re:.1f}) must be Transitional!"


def test_oracle_06_150cp_ui_preview_regime_badge():
    """Oracle 6: When switching to 150 cP in preview, the flow regime badge must NOT say 'Turbulent'.
    
    DEFECT: app.js lines 3142 and 3268 fall back to 'Turbulent' when flow_regime is missing
    or when bpe_metrics is not returned at the top level of the API response.
    """
    payload = {
        "tank": {
            "diameter_m": 0.40,
            "liquid_height_m": 0.45,
            "bottom_type": "flat",
            "is_baffled": True,
            "baffle_count": 4,
            "baffle_width_ratio": 0.10,
            "impellers": [
                {"impeller_type": "rushton_6_blade", "diameter_m": 0.14, "clearance_m": 0.14}
            ]
        },
        "fluid": {"name": "150 cP Broth", "density_kg_m3": 1000.0, "viscosity_pa_s": 0.150},
        "ops": {"rpm": 250.0, "aeration_vvm": 0.0},
    }

    resp = client.post("/api/ensemble/preview-geometry", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    # Check flow regime returned
    bpe_stage = data.get("bpe_metrics", {}).get("stages", [{}])[0]
    regime = bpe_stage.get("flow_regime")

    assert regime is not None, "API geometry preview must return flow_regime in bpe_metrics"
    assert regime.lower() != "turbulent", (
        f"CRITICAL LABEL BUG: 150 cP broth (Re ~ 544) is assigned flow_regime = '{regime}' in preview! "
        "Expected 'transitional'."
    )


def test_oracle_06_cached_3000cp_rushton_bundle_regime_fallback():
    """Oracle 6: Cached 3000 cP Rushton run (Re = 28.0) must NOT fall back to 'Turbulent' in HUD.
    
    DEFECT: app.js lines 3142 and 3268 evaluate:
      const rawRegime = meta.flow_regime || (data.bpe_metrics?.stages?.[0]?.flow_regime) || 'Turbulent';
    Because meta.flow_regime is null and data.bpe_metrics is undefined in /bundle,
    the HUD labels a 3,000 cP laminar run (Re = 28.0) as 'Turbulent'.
    """
    resp = client.get("/api/runs/fluent_rush_flat_250rpm_37e0a7c99627/bundle")
    assert resp.status_code == 200
    data = resp.json()
    meta = data["metadata"]

    raw_regime = meta.get("flow_regime") or (data.get("bpe_metrics", {}).get("stages", [{}])[0].get("flow_regime")) or "Turbulent"
    displayed_regime = raw_regime.capitalize()

    assert displayed_regime != "Turbulent", (
        f"CRITICAL LABEL BUG: Cached 3,000 cP run fluent_rush_flat_250rpm_37e0a7c99627 (Re = 28.0) "
        f"is assigned HUD regime '{displayed_regime}' due to undefined bpe_metrics fallback! Expected 'Laminar'."
    )
