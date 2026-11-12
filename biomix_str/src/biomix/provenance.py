"""Result provenance and CFD verification gates for BioMix-STR.

The browser can render a fast engineering preview, a cached field bundle, or a
new Fluent solve.  These are useful at different stages, but they must never be
represented as the same kind of evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from biomix.models import ImpellerType, TankGeometry


class ResultClass(str, Enum):
    GEOMETRY_PREVIEW = "geometry_preview"
    ENGINEERING_REFERENCE = "engineering_reference"
    CACHED_FLUENT = "cached_fluent_result"
    VERIFIED_FLUENT = "verified_fluent_result"
    SURROGATE_FLUENT = "surrogate_fluent_result"
    ANSYS_FLUENT_SURROGATE_SCALED = "ansys_fluent_surrogate_scaled"


class ImpellerSupport(str, Enum):
    PREVIEW = "preview"
    EXPERIMENTAL = "experimental"
    VERIFIED = "verified"


# MVP Verified Impeller Set (Primary Benchmarks)
MVP_VERIFIED_IMPELLERS = {
    ImpellerType.RUSHTON_6_BLADE,
    ImpellerType.PITCHED_BLADE_45,
    ImpellerType.MARINE_PROPELLER,
}

# Open Radial & Axial Impellers in Experimental CFD State
EXPERIMENTAL_CFD_IMPELLERS = {
    ImpellerType.SMITH_CD6,
    ImpellerType.FLAT_BLADE_FBT,
    ImpellerType.PADDLE_R200,
    ImpellerType.CURVED_BACKSWEPT,
    ImpellerType.RETREAT_BLADE,
    ImpellerType.HYDROFOIL_HE3,
    ImpellerType.MAXFLO_HIGH_SOLIDITY,
    ImpellerType.INTERMIG_EKATO,
}

# Close-Clearance Impellers with Dedicated Laminar Solver Path and 3D CAD
CLOSE_CLEARANCE_IMPELLERS = {
    ImpellerType.ANCHOR,
    ImpellerType.HELICAL_RIBBON,
    ImpellerType.AUGER_SCREW,
    ImpellerType.GATE_IMPELLER,
    ImpellerType.SIGMA_Z_KNEADER,
}

# Preview Only Impellers pending true 3D non-box helical/swept solid CAD and volume mesh validation
PREVIEW_ONLY_IMPELLERS: set[ImpellerType] = set()


def impeller_support(impeller: ImpellerType) -> ImpellerSupport:
    if impeller in MVP_VERIFIED_IMPELLERS:
        return ImpellerSupport.VERIFIED
    if impeller in EXPERIMENTAL_CFD_IMPELLERS or impeller in CLOSE_CLEARANCE_IMPELLERS:
        return ImpellerSupport.EXPERIMENTAL
    return ImpellerSupport.PREVIEW


def simulation_readiness(
    tank: TankGeometry,
    aeration_vvm: float,
    fluid: Optional[Any] = None,
    ops: Optional[Any] = None,
) -> Dict[str, Any]:
    """Return a non-ambiguous live-solve gate for the Fluent solver."""
    supported_impellers = MVP_VERIFIED_IMPELLERS | EXPERIMENTAL_CFD_IMPELLERS | CLOSE_CLEARANCE_IMPELLERS
    unsupported = [
        imp.impeller_type.value
        for imp in tank.impellers
        if imp.impeller_type not in supported_impellers
    ]
    reasons: list[str] = []
    if unsupported:
        reasons.append(
            f"The following impellers are Preview Only pending true 3D non-box helical/swept volume meshing and validation: {', '.join(unsupported)}."
        )
    if aeration_vvm > 0.0:
        reasons.append(
            "The active Fluent model is single-phase liquid. Set aeration to 0 vvm "
            "before running; gas-liquid CFD is a separate validated model."
        )

    any_close = any(
        imp.impeller_type in CLOSE_CLEARANCE_IMPELLERS
        for imp in tank.impellers
    )
    if any_close and tank.baffle_count > 0:
        reasons.append(
            f"Stationary wall baffles ({tank.baffle_count}) are physically invalid in a single-zone "
            "rotating MRF domain for close-clearance impellers. Close-clearance impellers "
            "require an unbaffled vessel (baffle_count = 0)."
        )

    any_exp = any(imp.impeller_type in EXPERIMENTAL_CFD_IMPELLERS for imp in tank.impellers)

    if any_close:
        readiness_tier = "laminar_close_clearance"
        physics_scope = "single_phase_steady_mrf_laminar"
    elif any_exp:
        readiness_tier = "experimental_cfd"
        physics_scope = "single_phase_steady_mrf"
    else:
        readiness_tier = "live_cfd_mvp"
        physics_scope = "single_phase_steady_mrf"

    return {
        "ready": not reasons,
        "readiness_tier": readiness_tier,
        "physics_scope": physics_scope,
        "unsupported_impellers": unsupported,
        "reasons": reasons,
    }


def _has_any(run_dir: Path, patterns: Iterable[str]) -> bool:
    return any(any(run_dir.glob(pattern)) for pattern in patterns)


def artifact_inventory(run_dir: str | Path) -> Dict[str, bool]:
    """Inventory evidence required to certify a persisted Fluent result."""
    path = Path(run_dir)
    manifest_path = path / "run_manifest.json"
    native_written = False
    if manifest_path.is_file():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                mdata = json.load(f)
                native_written = (mdata.get("native_case_data_written") is True)
        except Exception:
            native_written = False
    has_web_bundle = (path / "web_3d_bundle.json").is_file()
    return {
        "configuration": (path / "config.json").is_file(),
        "metadata": (path / "metadata.json").is_file(),
        "web_bundle": has_web_bundle,
        "mesh": _has_any(path, ("*.msh", "*.msh.h5", "*.bdf")) or native_written,
        "case": _has_any(path, ("*.cas", "*.cas.h5")) or native_written,
        "data": _has_any(path, ("*.dat", "*.dat.h5")) or native_written,
        "field_export": _has_any(path, ("*field*.vtp", "*field*.vtk", "*field*.vtu")) or (has_web_bundle and native_written),
        "manifest": manifest_path.is_file(),
    }


def assess_run_provenance(run_dir: str | Path) -> Dict[str, Any]:
    """Classify a result solely from persisted evidence, never from marketing text."""
    path = Path(run_dir)
    inventory = artifact_inventory(path)
    required = ("configuration", "metadata", "web_bundle", "mesh", "case", "data", "field_export", "manifest")
    missing = [key for key in required if not inventory[key]]

    manifest_data: Dict[str, Any] = {}
    if inventory["manifest"]:
        try:
            with open(path / "run_manifest.json", "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
        except Exception:
            manifest_data = {}

    has_all_artifacts = not missing

    # Check torque source provenance (HIGH-01)
    metric_sources = manifest_data.get("metric_sources", {})
    cfd_metrics = manifest_data.get("cfd_metrics", {})
    torque_source = metric_sources.get("cfd_torque_n_m") or cfd_metrics.get("provenance")

    # Check convergence: manifest.get("convergence", {}).get("converged") or manifest.get("converged") (MED-02)
    if "convergence" in manifest_data and isinstance(manifest_data["convergence"], dict):
        is_converged = manifest_data["convergence"].get("converged") is True
    elif "convergence_monitoring" in manifest_data and isinstance(manifest_data["convergence_monitoring"], dict):
        is_converged = manifest_data["convergence_monitoring"].get("converged") is True
    else:
        is_converged = manifest_data.get("converged") is True

    readiness_tier = manifest_data.get("readiness_tier")
    if not readiness_tier:
        if (path / "config.json").is_file():
            try:
                with open(path / "config.json", "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                imp_types = [imp.get("impeller_type") for imp in cfg.get("tank", {}).get("impellers", [])]
                if any(t in [i.value for i in CLOSE_CLEARANCE_IMPELLERS] for t in imp_types):
                    readiness_tier = "laminar_close_clearance"
                elif any(t in [i.value for i in EXPERIMENTAL_CFD_IMPELLERS] for t in imp_types):
                    readiness_tier = "experimental_cfd"
                else:
                    readiness_tier = "live_cfd_mvp"
            except Exception:
                readiness_tier = "live_cfd_mvp"
        else:
            readiness_tier = "live_cfd_mvp"

    warnings = manifest_data.get("warnings", [])

    # Manifest config hash integrity
    sha_match = False
    if (path / "config.json").is_file() and inventory["manifest"]:
        try:
            with open(path / "config.json", "r", encoding="utf-8") as f:
                cfg_obj = json.load(f)
            computed_sha = hashlib.sha256(json.dumps(cfg_obj, sort_keys=True).encode("utf-8")).hexdigest()
            manifest_sha = manifest_data.get("config_sha256", "")
            sha_match = (computed_sha == manifest_sha)
        except Exception:
            sha_match = False

    # Torque drift check from metadata or manifest
    drift_pct = None
    if (path / "metadata.json").is_file():
        try:
            with open(path / "metadata.json", "r", encoding="utf-8") as f:
                meta_data = json.load(f)
            drift_pct = meta_data.get("torque_drift_pct")
        except Exception:
            pass
    if drift_pct is None:
        conv_drift = manifest_data.get("convergence", {}).get("torque_drift_pct")
        if conv_drift is not None:
            drift_pct = conv_drift
        else:
            drift_pct = manifest_data.get("torque_drift_pct")

    is_drift_valid = (drift_pct is not None and drift_pct <= 2.0)
    is_torque_valid = (torque_source == "fluent_solver")

    validation_chips = []
    if not sha_match:
        validation_chips.append("hash mismatch")
    if not is_converged:
        validation_chips.append("not converged")
    if drift_pct is not None and drift_pct > 2.0:
        validation_chips.append(f"drift {drift_pct:.1f}%")
    elif drift_pct is None:
        validation_chips.append("drift unknown")
    if not is_torque_valid:
        validation_chips.append("correlation torque fallback")

    # TODO: Implement stricter tier 2 "validated" tier.
    # Stricter tier requires:
    # 1. Mesh independence study: Grid Convergence Index (GCI) < 5.0% across 3 refined meshes.
    # 2. Scaled residuals: continuity < 1e-3, all momentum and turbulence equations < 1e-4.
    # 3. Energy dissipation balance: |P_shaft - P_eps| / P_shaft < 10.0%, where P_eps = int(rho * epsilon dV).
    # 4. Asymptotic convergence: torque drift < 0.5% over the final 100 iterations.
    # The current 4-gate check qualifies runs only as "passes basic checks" (tier 1 sanity check).

    chip_text = ", ".join(validation_chips) if validation_chips else "does not pass basic checks"

    if has_all_artifacts and sha_match and is_converged and is_drift_valid and is_torque_valid:
        result_class = ResultClass.VERIFIED_FLUENT
        if readiness_tier == "experimental_cfd":
            label = "Verified Fluent (Experimental CFD)"
        elif readiness_tier == "laminar_close_clearance":
            label = "Verified Fluent (Laminar Close-Clearance)"
        else:
            label = "Verified Fluent"
        verified = True
        message = "Saved Fluent case, data, mesh, fields, and run manifest are available with verified solver torque, manifest integrity, and convergence (passes basic checks)."
    elif has_all_artifacts:
        result_class = ResultClass.ENGINEERING_REFERENCE
        verified = False
        label = f"Fluent result - does not pass basic checks ({chip_text})"
        message = f"Native Fluent case/data files are stored, but run does not pass basic checks: {chip_text}."
    elif inventory["web_bundle"]:
        result_class = ResultClass.ENGINEERING_REFERENCE
        label = "Reference field artifact"
        verified = False
        message = "Visual field bundle is available, but the complete Fluent evidence set is not stored."
    else:
        result_class = ResultClass.GEOMETRY_PREVIEW
        label = "Geometry preview"
        verified = False
        message = "No persisted CFD evidence is available."

    return {
        "result_class": result_class.value,
        "classification": result_class.value,
        "label": label,
        "readiness_tier": readiness_tier,
        "verified": verified,
        "message": message,
        "artifacts": inventory,
        "missing_verification_artifacts": missing,
        "has_native_case": inventory["case"],
        "has_native_data": inventory["data"],
        "has_manifest": inventory["manifest"],
        "warnings": warnings,
        "converged": is_converged,
        "torque_source": torque_source,
        "torque_drift_pct": drift_pct,
        "sha_match": sha_match,
        "validation_chip": chip_text if not verified else None,
    }


inspect_run_provenance = assess_run_provenance

