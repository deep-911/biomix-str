"""FastAPI Backend, Cached Ensemble Library & Live WebSocket Fluent Streamer.

Provides REST and WebSocket endpoints for the BioMix-STR interactive 3D web studio:
- /api/status: Local Ansys Fluent 2026 R1 (v261) health, PyFluent version, cached runs count.
- /api/presets: Bioprocess Engineering Ensemble Presets with cached status.
- /api/runs: List all completed 3D Fluent CFD runs with metadata and configuration.
- /api/runs/{run_id}/bundle: Return 3D streamlines, slice planes, CAD meshes, and engineering reference comparison.
- /api/simulate: Start live Fluent simulation or return cached result immediately.
- /api/jobs/{job_id}: Poll job progress, current stage, and residuals.
- /ws/jobs/{job_id}: WebSocket streaming real-time Navier-Stokes residuals at 60 FPS.
- /api/ensemble/preview-geometry: Instant (<100 ms) 3D CAD mesh generation and BPE metrics.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import shutil
import threading
import time
import uuid
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger("biomix.server")

import ansys.fluent.core as pyfluent
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
import numpy as np
from pydantic import BaseModel, Field, model_validator

from biomix.bpe_catalog import (
    IMPELLER_BPE_CATALOG,
    SECTION_6_STANDARD_RATIOS_TABLE,
    SECTION_7_QUICK_REVISION_TABLE,
    evaluate_bpe_suitability,
)
from biomix.correlations import calc_reynolds_number, classify_flow_regime
from biomix.engine import HydrodynamicEngine, ReactorSimulationResult
from biomix.fluent_runner import (
    FluentResidualStep,
    FluentRunMetadata,
    FluentSimulationRunner,
    backfill_run_configs,
    build_full_vessel_bundle,
    generate_run_id,
)
from biomix.models import (
    BottomType,
    CellType,
    FlowDirection,
    FluidProperties,
    ImpellerClearanceClass,
    ImpellerSpec,
    ImpellerType,
    OperatingConditions,
    ScaleUpRequest,
    ScaleUpResponse,
    TankGeometry,
)
from biomix.provenance import assess_run_provenance, impeller_support, simulation_readiness
from biomix.report_generator import generate_run_report
from biomix.scaleup import compute_scaleup
from biomix.theory import build_equation_cards
from biomix.visualization_3d import Visualizer3D


# =============================================================================
# WebSocket Connection & Job Management
# =============================================================================

class ConnectionManager:
    """Thread-safe WebSocket connection manager for live job progress streaming."""

    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.lock = threading.Lock()

    async def connect(self, job_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        with self.lock:
            if job_id not in self.active_connections:
                self.active_connections[job_id] = []
            self.active_connections[job_id].append(websocket)

    def disconnect(self, job_id: str, websocket: WebSocket) -> None:
        with self.lock:
            if job_id in self.active_connections and websocket in self.active_connections[job_id]:
                self.active_connections[job_id].remove(websocket)
                if not self.active_connections[job_id]:
                    del self.active_connections[job_id]

    async def broadcast(self, job_id: str, message: Dict[str, Any]) -> None:
        with self.lock:
            sockets = list(self.active_connections.get(job_id, []))
        dead_sockets = []
        for ws in sockets:
            try:
                await ws.send_json(message)
            except Exception:
                dead_sockets.append(ws)
        for dead in dead_sockets:
            self.disconnect(job_id, dead)


manager = ConnectionManager()
main_loop: Optional[asyncio.AbstractEventLoop] = None

# Thread-safe in-memory job state store and solver concurrency lock
jobs_lock = threading.Lock()
jobs_store: Dict[str, Dict[str, Any]] = {}
SOLVER_SEMAPHORE = threading.Semaphore(1)
ACTIVE_RUNNERS: Dict[str, FluentSimulationRunner] = {}


from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Capture main asyncio event loop for thread-safe WebSocket broadcasts."""
    global main_loop
    main_loop = asyncio.get_running_loop()
    yield

app = FastAPI(
    title="BioMix-STR Fluent CFD Studio",
    description="Live Ansys Fluent 2026 R1 CFD Backend & Interactive 3D Bioreactor Studio",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Reference to default runs output directory
RUNS_BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "outputs", "fluent_runs")
)
os.makedirs(RUNS_BASE_DIR, exist_ok=True)

# Run initial backfill of missing config.json files on startup
backfill_run_configs(RUNS_BASE_DIR)

# Static files directory
STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "static"))
os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def serve_root():
    """Serve the single-page application entry point."""
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_file):
        return FileResponse(index_file)
    return {"message": "BioMix-STR Ansys Fluent Studio API"}


# =============================================================================
# Request / Response Models
# =============================================================================

class SimulationRequest(BaseModel):
    """Payload to trigger an Ansys Fluent 2026 R1 CFD simulation."""

    tank: TankGeometry
    fluid: FluidProperties = Field(default_factory=FluidProperties)
    ops: OperatingConditions = Field(default_factory=OperatingConditions)
    mesh_density: Literal["fast", "medium", "fine"] = "fast"
    iterations: int = Field(default=40, ge=5, le=600)
    force_recompute: bool = False

    @model_validator(mode="before")
    @classmethod
    def sanitize_payload(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if "tank" in data:
                data["tank"] = _sanitize_tank_data(data["tank"]).model_dump()
            if "mesh_density" in data and isinstance(data["mesh_density"], str):
                data["mesh_density"] = data["mesh_density"].lower()
            if "ops" in data and isinstance(data["ops"], dict):
                ops_copy = dict(data["ops"])
                if "aeration_vvm" not in ops_copy or ops_copy["aeration_vvm"] is None:
                    ops_copy["aeration_vvm"] = 0.0
                data["ops"] = ops_copy
        return data


def _sanitize_tank_data(raw_tank: Any) -> Any:
    """Defensively adjust minor geometric rounding or spacing discrepancies before validation."""
    if not isinstance(raw_tank, dict):
        return raw_tank
    t_copy = dict(raw_tank)
    T = float(t_copy.get("diameter_m", 0.45))
    H = float(t_copy.get("liquid_height_m", 0.50))
    impellers = t_copy.get("impellers", [])
    if isinstance(impellers, list) and len(impellers) > 0:
        cleaned = []
        for imp in impellers:
            if isinstance(imp, dict):
                imp_c = dict(imp)
                itype = str(imp_c.get("impeller_type", "rushton_6_blade")).lower()
                is_cc = any(k in itype for k in ("anchor", "helical", "auger", "gate", "sigma"))
                is_paddle = "paddle" in itype
                is_retreat = "retreat" in itype

                if is_cc:
                    min_r, max_r = 0.15, 0.98
                elif is_paddle:
                    min_r, max_r = 0.15, 0.85
                elif is_retreat:
                    min_r, max_r = 0.15, 0.70
                else:
                    min_r, max_r = 0.15, 0.65

                d = float(imp_c.get("diameter_m", 0.15))
                imp_c["diameter_m"] = round(max(min_r * T, min(max_r * T, d)), 4)

                min_c = 0.031 * T
                max_c = H - 0.031 * T
                c = float(imp_c.get("clearance_m", 0.15))
                imp_c["clearance_m"] = round(max(min_c, min(max_c, c)), 4)
                cleaned.append(imp_c)
            else:
                cleaned.append(imp)

        cleaned.sort(key=lambda x: float(x.get("clearance_m", 0)) if isinstance(x, dict) else x.clearance_m)

        for i in range(len(cleaned) - 1):
            low = cleaned[i]
            upp = cleaned[i + 1]
            if isinstance(low, dict) and isinstance(upp, dict):
                low_c = float(low["clearance_m"])
                upp_c = float(upp["clearance_m"])
                low_d = float(low["diameter_m"])
                low_type = str(low.get("impeller_type", "")).lower()
                upp_type = str(upp.get("impeller_type", "")).lower()
                is_cc = any(k in low_type or k in upp_type for k in ("anchor", "helical", "auger", "gate", "sigma"))
                min_sep = 0.2 * low_d if is_cc else 0.8 * low_d
                if upp_c - low_c < min_sep:
                    upp_c = min(H - 0.031 * T, low_c + min_sep)
                    if upp_c - low_c < min_sep:
                        low_c = max(0.031 * T, upp_c - min_sep)
                        low["clearance_m"] = round(low_c, 4)
                    upp["clearance_m"] = round(upp_c, 4)
        t_copy["impellers"] = cleaned
    return TankGeometry(**t_copy)


class GeometryPreviewRequest(BaseModel):
    """Payload for instant (<150 ms) 3D CAD mesh, flow field, and BPE preview."""

    tank: TankGeometry
    fluid: Optional[FluidProperties] = None
    ops: Optional[OperatingConditions] = None
    force_surrogate: bool = False
    base_run_id: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def sanitize_payload(cls, data: Any) -> Any:
        if isinstance(data, dict) and "tank" in data:
            data["tank"] = _sanitize_tank_data(data["tank"])
        return data


class BPESuitabilityRequest(BaseModel):
    """Payload to evaluate bioprocess engineering suitability."""

    tank: TankGeometry
    fluid: Optional[FluidProperties] = Field(default_factory=FluidProperties)
    ops: Optional[OperatingConditions] = Field(default_factory=OperatingConditions)

    @model_validator(mode="before")
    @classmethod
    def sanitize_payload(cls, data: Any) -> Any:
        if isinstance(data, dict) and "tank" in data:
            data["tank"] = _sanitize_tank_data(data["tank"])
        return data


# =============================================================================
# Curated Ensemble Presets Catalog & Similarity Scaling (Modular Re-Exports)
# =============================================================================
from biomix.presets_catalog import (
    PresetInfo,
    build_ensemble_presets,
    find_closest_base_preset,
    scale_surrogate_flow_field,
)


# =============================================================================
# Endpoints
# =============================================================================

@app.get("/api/status")
def get_system_status() -> Dict[str, Any]:
    """Return local Ansys Fluent 2026 R1 installation status and cached runs statistics."""
    fluent_exe = FluentSimulationRunner.DEFAULT_FLUENT_EXE
    exe_found = os.path.isfile(fluent_exe) or (shutil.which("fluent") is not None)

    backfill_run_configs(RUNS_BASE_DIR)

    cached_count = 0
    verified_count = 0
    if os.path.isdir(RUNS_BASE_DIR):
        for item in os.listdir(RUNS_BASE_DIR):
            item_path = os.path.join(RUNS_BASE_DIR, item)
            if os.path.isdir(item_path):
                bundle_path = os.path.join(item_path, "web_3d_bundle.json")
                if os.path.isfile(bundle_path):
                    cached_count += 1
                    if assess_run_provenance(item_path)["verified"]:
                        verified_count += 1

    with jobs_lock:
        active_jobs = [j_id for j_id, j_data in jobs_store.items() if j_data["status"] == "running"]

    return {
        "status": "healthy",
        "fluent_exe_found": exe_found,
        "fluent_exe_path": fluent_exe if os.path.isfile(fluent_exe) else (shutil.which("fluent") or "Not Found"),
        "fluent_version": "2026 R1 (v261)",
        "pyfluent_version": getattr(pyfluent, "__version__", "0.42.1"),
        "cached_runs_count": cached_count,
        "verified_runs_count": verified_count,
        "active_jobs_count": len(active_jobs),
        "active_jobs": active_jobs,
    }


@app.get("/api/presets")
def get_presets() -> List[Dict[str, Any]]:
    """Return structured Bioprocess Engineering Ensemble Presets with cached flags."""
    presets = build_ensemble_presets()
    return [p.model_dump() for p in presets]


@app.get("/api/runs")
def list_completed_runs() -> List[Dict[str, Any]]:
    """Scan outputs/fluent_runs/ and return all completed CFD runs with metadata."""
    backfill_run_configs(RUNS_BASE_DIR)

    runs_list: List[Dict[str, Any]] = []
    if not os.path.isdir(RUNS_BASE_DIR):
        return runs_list

    for run_name in os.listdir(RUNS_BASE_DIR):
        run_dir = os.path.join(RUNS_BASE_DIR, run_name)
        if not os.path.isdir(run_dir):
            continue

        meta_path = os.path.join(run_dir, "metadata.json")
        bundle_path = os.path.join(run_dir, "web_3d_bundle.json")
        cfg_path = os.path.join(run_dir, "config.json")

        if not (os.path.isfile(meta_path) and os.path.isfile(bundle_path)):
            continue

        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta_dict = json.load(f)

            config_dict = None
            if os.path.isfile(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    config_dict = json.load(f)

            created_time = os.path.getmtime(bundle_path)

            runs_list.append({
                "run_id": run_name,
                "created_time": created_time,
                "config": config_dict,
                "metadata": meta_dict,
                "provenance": assess_run_provenance(run_dir),
            })
        except Exception:
            pass

    # Sort descending by creation time
    runs_list.sort(key=lambda r: r["created_time"], reverse=True)
    return runs_list


@app.get("/api/runs/{run_id}/bundle")
def get_run_bundle(run_id: str) -> Dict[str, Any]:
    """Return complete 3D bundle, metadata, and side-by-side engineering reference metrics for run_id."""
    run_dir = os.path.join(RUNS_BASE_DIR, run_id)
    if not os.path.isdir(run_dir):
        raise HTTPException(status_code=404, detail=f"Fluent run '{run_id}' not found")

    meta_path = os.path.join(run_dir, "metadata.json")
    bundle_path = os.path.join(run_dir, "web_3d_bundle.json")
    cfg_path = os.path.join(run_dir, "config.json")

    if not (os.path.isfile(meta_path) and os.path.isfile(bundle_path)):
        raise HTTPException(status_code=404, detail=f"Missing artifacts for run '{run_id}'")

    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        with open(bundle_path, "r", encoding="utf-8") as f:
            bundle_3d = json.load(f)

        config_data: Optional[Dict[str, Any]] = None
        if os.path.isfile(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)

        # Compute engineering reference correlations side-by-side
        bpe_metrics = None
        computed_re = None
        computed_regime = None
        if config_data and "tank" in config_data:
            try:
                t_obj = TankGeometry(**config_data["tank"])
                f_obj = FluidProperties(**config_data.get("fluid", {}))
                o_obj = OperatingConditions(**config_data.get("ops", {}))
                bpe_res: ReactorSimulationResult = HydrodynamicEngine.run(t_obj, f_obj, o_obj)
                bpe_metrics = bpe_res.model_dump()

                # Dynamic Re and regime classification at API layer (AUD-04/16)
                rho = f_obj.density_kg_m3
                mu = getattr(f_obj, "viscosity_pa_s", None) or getattr(f_obj, "dynamic_viscosity_pa_s", 0.001)
                n_rev_s = o_obj.rpm / 60.0
                d_imp = t_obj.impellers[0].diameter_m if t_obj.impellers else 0.15
                computed_re = calc_reynolds_number(rho, n_rev_s, d_imp, mu)
                computed_regime = classify_flow_regime(computed_re).value
            except Exception as ex:
                logger.warning(f"Error computing BPE reference for bundle: {ex}")

        # Enrich metadata in response payload only (do NOT edit metadata.json on disk)
        enriched_metadata = dict(metadata)
        if computed_re is not None:
            enriched_metadata["reynolds_number"] = round(computed_re, 4)
        if computed_regime is not None:
            enriched_metadata["flow_regime"] = computed_regime

        return {
            "run_id": run_id,
            "metadata": enriched_metadata,
            "config": config_data,
            "bpe_metrics": bpe_metrics,
            "engineering_reference": bpe_metrics,
            "bpe_textbook": bpe_metrics,
            "reynolds_number": computed_re,
            "flow_regime": computed_regime,
            "provenance": assess_run_provenance(run_dir),
            "theory": (
                build_equation_cards(t_obj, f_obj, o_obj)
                if config_data and bpe_metrics is not None else None
            ),
            "bundle_3d": bundle_3d,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read bundle: {e}")


@app.get("/api/runs/{run_id}/report")
@app.get("/api/report/generate")
def get_run_report_endpoint(run_id: str, format: str = "markdown"):
    """Generate and return a reproducible engineering verification report."""
    run_dir = os.path.join(RUNS_BASE_DIR, run_id)
    if not os.path.isdir(run_dir):
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    fmt = format.lower()
    if fmt not in ("markdown", "html"):
        fmt = "markdown"

    try:
        report_text = generate_run_report(run_dir, output_format=fmt)
        media_type = "text/html; charset=utf-8" if fmt == "html" else "text/markdown; charset=utf-8"
        headers = {
            "Content-Disposition": f'attachment; filename="biomix_report_{run_id}.{"html" if fmt == "html" else "md"}"'
        }
        return Response(content=report_text, media_type=media_type, headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {e}")


@app.post("/api/theory/scaleup", response_model=ScaleUpResponse)
@app.post("/api/scaleup", response_model=ScaleUpResponse)
def post_scaleup_analysis(req: ScaleUpRequest) -> ScaleUpResponse:
    """Compute side-by-side scale-up metrics from baseline to target volume."""
    try:
        return compute_scaleup(req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to compute scaleup: {e}")


@app.get("/api/bpe/catalog")
def get_bpe_catalog() -> Dict[str, Any]:
    """Return the impeller engineering library and its live-CFD support state."""
    def serialize(entry: Any) -> Dict[str, Any]:
        data = entry.model_dump()
        data["support_status"] = impeller_support(entry.impeller_type).value
        return data

    return {
        "impellers": [serialize(entry) for entry in IMPELLER_BPE_CATALOG.values()],
        "by_class": {
            "open_turbine": [
                entry.model_dump()
                for entry in IMPELLER_BPE_CATALOG.values()
                if entry.clearance_class == ImpellerClearanceClass.OPEN_TURBINE
            ],
            "close_clearance": [
                entry.model_dump()
                for entry in IMPELLER_BPE_CATALOG.values()
                if entry.clearance_class == ImpellerClearanceClass.CLOSE_CLEARANCE
            ],
        },
        "by_flow": {
            "radial": [
                entry.model_dump()
                for entry in IMPELLER_BPE_CATALOG.values()
                if entry.flow_direction == FlowDirection.RADIAL
            ],
            "mixed_axial": [
                entry.model_dump()
                for entry in IMPELLER_BPE_CATALOG.values()
                if entry.flow_direction == FlowDirection.MIXED_AXIAL
            ],
            "axial": [
                entry.model_dump()
                for entry in IMPELLER_BPE_CATALOG.values()
                if entry.flow_direction == FlowDirection.AXIAL
            ],
            "close_clearance_tangential": [
                entry.model_dump()
                for entry in IMPELLER_BPE_CATALOG.values()
                if entry.flow_direction == FlowDirection.CLOSE_CLEARANCE_TANGENTIAL
            ],
        },
        "section_6_standard_ratios": SECTION_6_STANDARD_RATIOS_TABLE,
        "section_7_quick_revision": SECTION_7_QUICK_REVISION_TABLE,
    }


@app.get("/api/cfd/capabilities")
def get_cfd_capabilities() -> Dict[str, Any]:
    """Return the explicitly supported local Fluent boundary across MVP, Experimental, and Close-Clearance tiers."""
    return {
        "physics_scope": "single_phase_steady_mrf",
        "verified_impellers": [
            imp.value for imp in ImpellerType
            if impeller_support(imp).value == "verified"
        ],
        "experimental_impellers": [
            imp.value for imp in ImpellerType
            if impeller_support(imp).value == "experimental"
        ],
        "impeller_support": {
            imp.value: impeller_support(imp).value for imp in ImpellerType
        },
        "gas_liquid_cfd": "not_available",
        "message": "Only persisted runs with native Fluent case/data, mesh, field export, and manifest are labelled Verified Fluent.",
    }


@app.post("/api/theory/evaluate")
def evaluate_theory(req: GeometryPreviewRequest) -> Dict[str, Any]:
    """Evaluate transparent engineering references for the supplied configuration."""
    return build_equation_cards(req.tank, req.fluid or FluidProperties(), req.ops or OperatingConditions())

@app.post("/api/bpe/suitability")
def evaluate_suitability(req: BPESuitabilityRequest) -> Dict[str, Any]:
    """Evaluate bioreactor geometry, impeller configuration, and fluid properties against bioprocess engineering design standards."""
    fluid = req.fluid or FluidProperties()
    ops = req.ops or OperatingConditions()

    alerts = evaluate_bpe_suitability(tank=req.tank, fluid=fluid, ops=ops)
    sim_res = HydrodynamicEngine.run(tank=req.tank, fluid=fluid, ops=ops)

    return {
        "alerts": alerts,
        "has_warnings": any(a["level"] == "warning" for a in alerts),
        "recommended_adjustments": [a["message"] for a in alerts if a.get("level") == "warning"],
        "bpe_metrics": sim_res.model_dump(),
    }


@app.post("/api/ensemble/preview-geometry")
def preview_geometry(req: GeometryPreviewRequest) -> Dict[str, Any]:
    """Generate instant (<150 ms) 3D CAD meshes and similarity-scaled 3D Fluent surrogate fields."""
    tank = req.tank
    fluid = req.fluid or FluidProperties()
    ops = req.ops or OperatingConditions()

    # Dynamic Re and regime classification at API layer (AUD-04/16)
    rho_nom = fluid.density_kg_m3
    mu_nom = getattr(fluid, "viscosity_pa_s", None) or getattr(fluid, "dynamic_viscosity_pa_s", 0.001)
    n_rev_s = ops.rpm / 60.0
    d_imp = tank.impellers[0].diameter_m if tank.impellers else 0.15
    nominal_re = calc_reynolds_number(rho_nom, n_rev_s, d_imp, mu_nom)
    nominal_regime = classify_flow_regime(nominal_re).value

    # 1. Check if exact cached CFD solution exists
    run_id = generate_run_id(tank, fluid, ops, mesh_density="fast", iterations=15)
    bundle_file = os.path.join(RUNS_BASE_DIR, run_id, "web_3d_bundle.json")
    is_exact_cached = os.path.isfile(bundle_file)

    presets = build_ensemble_presets()

    if is_exact_cached and not req.force_surrogate:
        try:
            with open(bundle_file, "r", encoding="utf-8") as f:
                bundle = json.load(f)
            prov = assess_run_provenance(os.path.join(RUNS_BASE_DIR, run_id))
            bpe_res = HydrodynamicEngine.run(tank, fluid, ops)
            suitability_alerts = evaluate_bpe_suitability(tank, fluid, ops)
            meta = dict(bundle.get("metadata", {}))
            if bpe_res.stages:
                meta["reynolds_number"] = round(nominal_re, 4)
                meta["flow_regime"] = nominal_regime
            return {
                "metadata": meta,
                "cad_meshes": bundle["cad_meshes"],
                "streamlines": bundle["streamlines"],
                "vectors_3d": bundle["vectors_3d"],
                "cross_sections": bundle["cross_sections"],
                "horizontal_slices": bundle["horizontal_slices"],
                "vector_quiver": bundle.get("vector_quiver", []),
                "bpe_metrics": bpe_res.model_dump(),
                "flow_regime": nominal_regime,
                "reynolds_number": round(nominal_re, 4),
                "suitability_alerts": suitability_alerts,
                "deterministic_run_id": run_id,
                "is_cached": True,
                "is_surrogate": False,
                "provenance": prov,
                "theory": build_equation_cards(tank, fluid, ops),
            }
        except Exception as e:
            logger.warning(f"Failed to load exact cached bundle {run_id}: {e}")

    # 2. Similarity-Scaled Fluent Surrogate (Multi-Dimensional Matching & Clamped Scaling)
    base_preset = None
    if req.base_run_id:
        for p in presets:
            if p.run_id == req.base_run_id:
                base_preset = p
                break
        if base_preset is None:
            base_dir = os.path.join(RUNS_BASE_DIR, req.base_run_id)
            base_cfg_path = os.path.join(base_dir, "config.json")
            if os.path.isfile(base_cfg_path):
                with open(base_cfg_path, "r", encoding="utf-8") as f:
                    base_cfg = json.load(f)
                base_preset = PresetInfo(
                    preset_id=req.base_run_id,
                    name=req.base_run_id,
                    description=f"Surrogate base run {req.base_run_id}",
                    category="Standard",
                    tank=TankGeometry(**base_cfg["tank"]),
                    fluid=FluidProperties(**base_cfg["fluid"]),
                    ops=OperatingConditions(**base_cfg["ops"]),
                    mesh_density=base_cfg.get("mesh_density", "fast"),
                    iterations=base_cfg.get("iterations", 15),
                    is_cached=True,
                    run_id=req.base_run_id,
                )
    if base_preset is None:
        base_preset = find_closest_base_preset(tank, fluid, ops, presets)
    if base_preset and base_preset.run_id:
        base_bundle_path = os.path.join(RUNS_BASE_DIR, base_preset.run_id, "web_3d_bundle.json")
        if os.path.isfile(base_bundle_path):
            try:
                with open(base_bundle_path, "r", encoding="utf-8") as f:
                    base_bundle = json.load(f)

                scaled_fields = scale_surrogate_flow_field(base_preset, base_bundle, tank, fluid, ops)
                scales = scaled_fields["scales"]
                s_u = scales["s_u"]
                d_target = float(tank.impellers[0].diameter_m) if tank.impellers else 0.15
                u_tip_new = math.pi * float(ops.rpm) * d_target / 60.0

                cad_bundle = build_full_vessel_bundle(tank=tank, fluid=fluid, ops=ops, run_id=run_id)
                bpe_res = HydrodynamicEngine.run(tank, fluid, ops)
                suitability_alerts = evaluate_bpe_suitability(tank, fluid, ops)

                meta = dict(base_bundle.get("metadata", {}))
                meta["solver_source"] = "ansys_fluent_surrogate_scaled"
                meta["base_run_id"] = base_preset.run_id
                meta["base_preset_name"] = base_preset.name
                meta["tip_speed_m_s"] = round(u_tip_new, 2)
                meta["cfd_max_velocity_m_s"] = round(meta.get("cfd_max_velocity_m_s", u_tip_new) * s_u, 4)
                meta["cfd_mean_velocity_m_s"] = round(meta.get("cfd_mean_velocity_m_s", 0.3) * s_u, 4)
                meta["cfd_power_w"] = round(float(bpe_res.total_ungassed_power_w), 2)
                omega_new = ops.rpm * 2.0 * math.pi / 60.0
                meta["cfd_torque_n_m"] = round(float(bpe_res.total_ungassed_power_w) / max(omega_new, 1e-4), 4)
                if bpe_res.stages:
                    meta["reynolds_number"] = round(nominal_re, 4)
                    meta["flow_regime"] = nominal_regime

                return {
                    "metadata": meta,
                    "cad_meshes": cad_bundle["cad_meshes"],
                    "streamlines": scaled_fields["streamlines"],
                    "vectors_3d": scaled_fields["vectors_3d"],
                    "cross_sections": scaled_fields["cross_sections"],
                    "horizontal_slices": scaled_fields["horizontal_slices"],
                    "vector_quiver": cad_bundle.get("vector_quiver", []),
                    "bpe_metrics": bpe_res.model_dump(),
                    "flow_regime": nominal_regime,
                    "reynolds_number": round(nominal_re, 4),
                    "suitability_alerts": suitability_alerts,
                    "deterministic_run_id": run_id,
                    "is_cached": False,
                    "is_surrogate": True,
                    "base_run_id": base_preset.run_id,
                    "provenance": {
                        "result_class": "surrogate_fluent_result",
                        "classification": "ansys_fluent_surrogate_scaled",
                        "label": "Scaled from Verified Fluent Base (Instant Surrogate)",
                        "verified": False,
                        "is_surrogate": True,
                        "base_run_id": base_preset.run_id,
                        "base_preset_name": base_preset.name,
                        "message": f"Similarity-scaled from verified Fluent run '{base_preset.run_id}' ({base_preset.name}) via (N*D)/(N0*D0) = {s_u:.2f}x velocity ratio with vessel dish bottom boundary clamping.",
                    },
                    "theory": build_equation_cards(tank, fluid, ops),
                }
            except Exception as e:
                logger.error(f"Error in surrogate scaling: {e}", exc_info=True)

    # 3. Fallback to analytical 2D estimator if no base bundle available
    bundle = build_full_vessel_bundle(tank=tank, fluid=fluid, ops=ops, run_id=run_id)
    bpe_res = bundle.get("bpe_result") or HydrodynamicEngine.run(tank, fluid, ops)
    suitability_alerts = evaluate_bpe_suitability(tank, fluid, ops)
    meta = dict(bundle.get("metadata", {}))
    if bpe_res.stages:
        meta["reynolds_number"] = round(nominal_re, 4)
        meta["flow_regime"] = nominal_regime

    return {
        "metadata": meta,
        "cad_meshes": bundle["cad_meshes"],
        "streamlines": bundle["streamlines"],
        "vectors_3d": bundle["vectors_3d"],
        "cross_sections": bundle["cross_sections"],
        "horizontal_slices": bundle["horizontal_slices"],
        "vector_quiver": bundle["vector_quiver"],
        "bpe_metrics": bpe_res.model_dump(),
        "flow_regime": nominal_regime,
        "reynolds_number": round(nominal_re, 4),
        "suitability_alerts": suitability_alerts,
        "deterministic_run_id": run_id,
        "is_cached": False,
        "is_surrogate": False,
        "provenance": {
            "result_class": "geometry_preview",
            "classification": "geometry_preview",
            "label": "Geometry preview",
            "verified": False,
            "message": "Interactive geometry and engineering-reference display. Run or load Fluent for CFD evidence.",
        },
        "theory": build_equation_cards(tank, fluid, ops),
    }


# =============================================================================
# Background Simulation Worker & Endpoints
# =============================================================================

def _run_fluent_background_worker(
    job_id: str,
    req: SimulationRequest,
    run_id: str,
    target_loop: Optional[asyncio.AbstractEventLoop],
) -> None:
    """Execute live Fluent simulation in background worker thread and broadcast residuals."""
    runner = FluentSimulationRunner(base_output_dir=RUNS_BASE_DIR)
    with jobs_lock:
        ACTIVE_RUNNERS[job_id] = runner

    try:
        def progress_cb(it: int, total: int, msg: str, step: Optional[FluentResidualStep]) -> None:
            effective_total = max(int(total), int(it), 1)
            pct = min(100.0, round((float(it) / float(effective_total)) * 100.0, 1))
            stage = "solving" if it > 0 else "meshing"

            with jobs_lock:
                if job_id in jobs_store:
                    jobs_store[job_id]["progress_pct"] = pct
                    jobs_store[job_id]["current_iteration"] = it
                    jobs_store[job_id]["total_iterations"] = effective_total
                    jobs_store[job_id]["stage"] = stage
                    jobs_store[job_id]["message"] = msg
                    if step is not None:
                        jobs_store[job_id]["residuals"].append(step.model_dump())

            update_msg = {
                "type": "progress",
                "job_id": job_id,
                "run_id": run_id,
                "stage": stage,
                "iteration": it,
                "total_iterations": effective_total,
                "requested_iterations": req.iterations,
                "progress_pct": pct,
                "message": msg,
                "residual_step": step.model_dump() if step else None,
            }

            if target_loop and target_loop.is_running():
                asyncio.run_coroutine_threadsafe(manager.broadcast(job_id, update_msg), target_loop)

        def session_cb(session: Any, pid: Optional[int]) -> None:
            with jobs_lock:
                if job_id in jobs_store:
                    jobs_store[job_id]["pid"] = pid

        def abort_check() -> bool:
            with jobs_lock:
                job = jobs_store.get(job_id)
                return bool(job and job.get("status") == "aborted")

        meta = runner.run_simulation(
            tank=req.tank,
            fluid=req.fluid,
            ops=req.ops,
            mesh_density=req.mesh_density,
            iterations=req.iterations,
            use_cache=not req.force_recompute,
            progress_callback=progress_cb,
            session_callback=session_cb,
            abort_check=abort_check,
        )

        with jobs_lock:
            if job_id in jobs_store:
                if jobs_store[job_id].get("status") != "aborted":
                    jobs_store[job_id]["status"] = "completed"
                    jobs_store[job_id]["stage"] = "completed"
                    jobs_store[job_id]["progress_pct"] = 100.0
                    jobs_store[job_id]["message"] = "Simulation completed successfully!"
                    jobs_store[job_id]["completed_at"] = time.time()
                    jobs_store[job_id]["metadata"] = meta.model_dump()

        completion_msg = {
            "type": "completed",
            "job_id": job_id,
            "run_id": run_id,
            "progress_pct": 100.0,
            "message": "Simulation completed successfully!",
            "metadata": meta.model_dump(),
        }
        if target_loop and target_loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.broadcast(job_id, completion_msg), target_loop)

    except InterruptedError:
        with jobs_lock:
            if job_id in jobs_store:
                jobs_store[job_id]["status"] = "aborted"
                jobs_store[job_id]["stage"] = "aborted"
                jobs_store[job_id]["message"] = "Simulation aborted by user."
                jobs_store[job_id]["completed_at"] = time.time()
        abort_msg = {
            "type": "aborted",
            "job_id": job_id,
            "run_id": run_id,
            "message": "Simulation aborted by user.",
        }
        if target_loop and target_loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.broadcast(job_id, abort_msg), target_loop)

    except Exception as e:
        err_str = str(e)
        if "LaunchFluentError" in type(e).__name__ or "Fluent Launch command" in err_str:
            clean_err = "Ansys Fluent failed to start. Ensure Ansys Fluent 2026 R1 is installed and no other Fluent instances or license locks are running."
        else:
            clean_err = err_str

        is_aborted = False
        with jobs_lock:
            if job_id in jobs_store:
                if jobs_store[job_id].get("status") == "aborted":
                    is_aborted = True
                else:
                    jobs_store[job_id]["status"] = "failed"
                    jobs_store[job_id]["stage"] = "failed"
                    jobs_store[job_id]["error"] = clean_err
                    jobs_store[job_id]["raw_error"] = err_str
                    jobs_store[job_id]["message"] = f"Simulation failed: {clean_err}"
                    jobs_store[job_id]["completed_at"] = time.time()

        if not is_aborted:
            err_msg = {
                "type": "failed",
                "job_id": job_id,
                "run_id": run_id,
                "error": clean_err,
                "raw_error": err_str,
                "message": f"Simulation failed: {clean_err}",
            }
            if target_loop and target_loop.is_running():
                asyncio.run_coroutine_threadsafe(manager.broadcast(job_id, err_msg), target_loop)

    finally:
        with jobs_lock:
            ACTIVE_RUNNERS.pop(job_id, None)
        try:
            FluentSimulationRunner.kill_lingering_fluent_processes()
        except Exception:
            pass
        try:
            SOLVER_SEMAPHORE.release()
        except ValueError:
            pass


@app.post("/api/simulate")
@app.post("/api/simulate/fluent")
def start_simulation(req: SimulationRequest) -> Dict[str, Any]:
    """Trigger a live Ansys Fluent 2026 R1 CFD solve or return cached result immediately."""
    run_id = generate_run_id(
        tank=req.tank,
        fluid=req.fluid,
        ops=req.ops,
        mesh_density=req.mesh_density,
        iterations=req.iterations,
    )
    bundle_path = os.path.join(RUNS_BASE_DIR, run_id, "web_3d_bundle.json")
    meta_path = os.path.join(RUNS_BASE_DIR, run_id, "metadata.json")

    # Instant cache return
    if not req.force_recompute and os.path.isfile(bundle_path) and os.path.isfile(meta_path):
        return {
            "status": "completed",
            "cached": True,
            "run_id": run_id,
            "job_id": None,
            "message": f"Loaded cached result artifact ({run_id})",
            "provenance": assess_run_provenance(os.path.join(RUNS_BASE_DIR, run_id)),
        }

    # Check local Ansys Fluent availability for live CFD solving
    fluent_exe = FluentSimulationRunner.DEFAULT_FLUENT_EXE
    exe_found = os.path.isfile(fluent_exe) or (shutil.which("fluent") is not None)
    if not exe_found:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Cloud Demo Mode Active: Real-time 3D Navier-Stokes simulation requires a local Ansys Fluent installation (2024–2026 R1) and valid license. All 32 standard bioreactor configurations are pre-computed and available instantly from the Presets menu. To run custom live simulations on your workstation, follow the local setup guide on GitHub.",
                "is_cloud_demo": True,
                "github_url": "https://github.com/deep-911/biomix-str#local-setup-with-ansys-fluent",
            },
        )

    # Solver concurrency lock: prevent colliding Fluent solver processes
    acquired = SOLVER_SEMAPHORE.acquire(blocking=False)
    if not acquired:
        raise HTTPException(
            status_code=409,
            detail="Another Ansys Fluent simulation is currently active. Please wait or abort the active job.",
        )

    try:
        readiness = simulation_readiness(req.tank, req.ops.aeration_vvm, req.fluid, req.ops)
        if not readiness["ready"]:
            raise HTTPException(status_code=422, detail={
                "message": "Configuration is outside the supported live CFD boundary.",
                "readiness": readiness,
            })

        job_id = f"job_{uuid.uuid4().hex[:8]}"
        initial_job_state = {
            "job_id": job_id,
            "run_id": run_id,
            "status": "running",
            "stage": "meshing",
            "progress_pct": 0.0,
            "current_iteration": 0,
            "total_iterations": req.iterations,
            "message": "Initializing 3D conformal mesh and launching Fluent...",
            "residuals": [],
            "error": None,
            "pid": None,
            "created_at": time.time(),
            "completed_at": None,
        }

        with jobs_lock:
            jobs_store[job_id] = initial_job_state

        # Launch worker in daemon thread
        worker_thread = threading.Thread(
            target=_run_fluent_background_worker,
            args=(job_id, req, run_id, main_loop),
            daemon=True,
        )
        worker_thread.start()
    except Exception:
        SOLVER_SEMAPHORE.release()
        raise

    return {
        "status": "running",
        "cached": False,
        "run_id": run_id,
        "job_id": job_id,
        "message": "Ansys Fluent 2026 R1 CFD solve started in background.",
        "readiness": readiness,
    }


@app.post("/api/jobs/{job_id}/abort")
def abort_simulation_job(job_id: str) -> Dict[str, Any]:
    """Abort an active Ansys Fluent solve, cleanly terminate PyFluent or process tree, and release lock."""
    with jobs_lock:
        if job_id not in jobs_store:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
        job = jobs_store[job_id]
        if job.get("status") in ("completed", "failed", "aborted"):
            return {
                "status": job.get("status"),
                "job_id": job_id,
                "message": f"Job already {job.get('status')}.",
            }

        job["status"] = "aborted"
        job["stage"] = "aborted"
        job["message"] = "Simulation aborted by user."
        job["completed_at"] = time.time()
        pid = job.get("pid")
        runner = ACTIVE_RUNNERS.get(job_id)

    if runner:
        try:
            runner.abort()
        except Exception:
            pass

    if pid:
        try:
            import subprocess
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            pass

    abort_msg = {
        "type": "aborted",
        "job_id": job_id,
        "message": "Simulation aborted by user.",
    }
    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(manager.broadcast(job_id, abort_msg), main_loop)

    return {
        "status": "aborted",
        "job_id": job_id,
        "message": "Ansys Fluent simulation aborted successfully.",
    }


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str) -> Dict[str, Any]:
    """Poll job progress, current stage, and residuals history."""
    with jobs_lock:
        if job_id not in jobs_store:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
        job = dict(jobs_store[job_id])
        job["residuals"] = list(job.get("residuals", []))
        return job


@app.websocket("/ws/jobs/{job_id}")
async def websocket_job_stream(websocket: WebSocket, job_id: str):
    """Stream live Navier-Stokes residuals and completion notifications over WebSocket."""
    with jobs_lock:
        if job_id not in jobs_store:
            await websocket.close(code=4004, reason=f"Job '{job_id}' not found")
            return
    await manager.connect(job_id, websocket)

    # Immediately push current state
    with jobs_lock:
        current_state = dict(jobs_store.get(job_id, {}))
    if current_state:
        await websocket.send_json({
            "type": "state",
            "job_id": job_id,
            "data": current_state,
        })

    try:
        while True:
            # Keep socket open and receive any client pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(job_id, websocket)
    except Exception:
        manager.disconnect(job_id, websocket)


# =============================================================================
# One-Click Launcher Entrypoint
# =============================================================================

def main() -> None:
    """Launch the BioMix-STR Ansys Fluent CFD 3D Web Studio."""
    import webbrowser
    import uvicorn

    def _open_browser():
        time.sleep(1.5)
        try:
            webbrowser.open("http://127.0.0.1:8000")
        except Exception:
            pass

    opener = threading.Thread(target=_open_browser, daemon=True)
    opener.start()

    print("=" * 76)
    print(" BioMix-STR · Ansys Fluent 2026 R1 3D Bioreactor CFD Studio")
    print("=" * 76)
    print(" Starting local FastAPI server on http://127.0.0.1:8000...")
    print(" Opening 3D Fluent Web Studio in default browser in 1.5 seconds.")
    print(" Press Ctrl+C to stop.")
    print("=" * 76)

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    uvicorn.run("biomix.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()

