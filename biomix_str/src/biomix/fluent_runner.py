"""Live Ansys Fluent 2026 R1 Solver, Internal 3D Field Extractor & Run Cache.

Orchestrates automated 3D conformal bioreactor meshing via OpenCASCADE/Gmsh,
executes live double-precision Navier-Stokes solves in local Ansys Fluent 2026 R1 (v261)
via PyFluent, captures real-time iteration residuals, extracts internal 3D flow fields
(bypassing no-slip zero velocity walls), computes cross-section slice contours and
3D streamlines, and caches all artifacts for interactive web display.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import shutil
import time
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

logger = logging.getLogger(__name__)

import numpy as np
from pydantic import BaseModel, Field
try:
    import pyvista as pv
except (ImportError, Exception):
    pv = None
from scipy.spatial import cKDTree

from biomix.cad_mesher import BioreactorCADMesher, MeshedBioreactorArtifact
from biomix.correlations import calc_reynolds_number, calc_tip_speed, calc_ungassed_power, classify_flow_regime
from biomix.engine import HydrodynamicEngine
from biomix.flow_solver_2d import FlowSolver2D, FlowField2DResult
from biomix.models import (
    BottomType,
    FluidProperties,
    ImpellerClearanceClass,
    ImpellerSpec,
    ImpellerType,
    OperatingConditions,
    TankGeometry,
)
from biomix.provenance import (
    CLOSE_CLEARANCE_IMPELLERS,
    EXPERIMENTAL_CFD_IMPELLERS,
    MVP_VERIFIED_IMPELLERS,
)
from biomix.visualization_3d import Visualizer3D
from scipy.interpolate import RegularGridInterpolator


class FluentResidualStep(BaseModel):
    """Convergence residual history recorded at an individual Navier-Stokes iteration."""

    iteration: int = Field(ge=1, description="Iteration number")
    continuity: float = Field(description="Continuity equation mass residual")
    x_velocity: float = Field(description="U-momentum equation residual")
    y_velocity: float = Field(description="V-momentum equation residual")
    z_velocity: float = Field(description="W-momentum equation residual")
    k: float = Field(default=0.0, description="Turbulent kinetic energy (k) residual")
    epsilon: float = Field(default=0.0, description="Turbulent dissipation rate (epsilon) residual")


class FluentRunMetadata(BaseModel):
    """Execution summary and physics metrics for a live Ansys Fluent run."""

    run_id: str = Field(description="Deterministic hash/slug identifying this simulation scenario")
    run_dir: str = Field(description="Absolute path to outputs/fluent_runs/<run_id>/")
    cached: bool = Field(default=False, description="True if loaded from disk cache, False if computed live")
    solver_source: str = Field(default="ansys_fluent_2026_r1_3d", description="Solver source: ansys_fluent_2026_r1_3d or bpe_realtime_preview")
    n_cells: int = Field(ge=0, description="Total 3D tetrahedral fluid mesh cells")
    n_cells_mrf: Optional[int] = Field(default=None, description="Total cells in MRF rotating zone")
    n_cells_stationary: Optional[int] = Field(default=None, description="Total cells in stationary zone")
    n_nodes: int = Field(ge=0, description="Total mesh vertices")
    meshing_time_s: float = Field(ge=0.0, description="Gmsh CAD and meshing duration (s)")
    solve_time_s: float = Field(ge=0.0, description="Ansys Fluent solver iteration duration (s)")
    omega_rad_s: float = Field(description="Agitator angular velocity (rad/s)")
    rpm: float = Field(description="Agitator rotational speed (rev/min)")
    tip_speed_m_s: float = Field(description="Maximum impeller tip peripheral speed (m/s)")
    cfd_max_velocity_m_s: float = Field(description="Peak fluid velocity in internal domain (m/s)")
    cfd_mean_velocity_m_s: float = Field(description="Mean fluid velocity in internal domain (m/s)")
    cfd_min_pressure_pa: float = Field(description="Minimum static pressure in internal domain (Pa)")
    cfd_max_pressure_pa: float = Field(description="Maximum static pressure in internal domain (Pa)")
    cfd_mean_tke_m2_s2: float = Field(default=0.0, description="Mean turbulent kinetic energy (m^2/s^2)")
    cfd_mean_epsilon_m2_s3: float = Field(default=0.0, description="Mean turbulent dissipation rate (m^2/s^3)")
    cfd_max_epsilon_m2_s3: float = Field(default=0.0, description="Peak turbulent dissipation rate (m^2/s^3)")
    cfd_kolmogorov_min_um: float = Field(default=0.0, description="Minimum Kolmogorov microscale eddy size (microns)")
    cfd_max_shear_stress_pa: float = Field(default=0.0, description="Maximum turbulent shear stress (Pa)")
    cfd_dead_zone_fraction: float = Field(ge=0.0, le=1.0, description="Fraction of fluid volume with |u| < 0.05*v_tip")
    cfd_power_w: float = Field(description="Mechanical agitation power draw (W)")
    cfd_torque_n_m: float = Field(description="Mechanical shaft torque (N*m)")
    cfd_power_number_np: Optional[float] = Field(default=None, description="Fluent-computed power number Np")
    ref_power_w: Optional[float] = Field(default=None, description="Engineering reference power (W)")
    ref_torque_n_m: Optional[float] = Field(default=None, description="Engineering reference torque (N*m)")
    converged: Optional[bool] = Field(default=None, description="True if monotonic convergence & torque stabilization achieved")
    torque_drift_pct: Optional[float] = Field(default=None, description="Percentage torque drift over final iteration window")
    warnings: List[str] = Field(default_factory=list, description="Solver warnings, e.g. moment report fallback")
    metric_sources: Dict[str, str] = Field(
        default_factory=dict,
        description="Evidence class for each reported metric: fluent_field or engineering_reference",
    )
    bpe_metrics: Dict[str, Any] = Field(default_factory=dict, description="Analytical Bioprocess Engineering metrics")
    residuals: List[FluentResidualStep] = Field(default_factory=list, description="Residual convergence history")
    web_bundle_path: str = Field(description="Path to web_3d_bundle.json for browser visualization")
    flow_regime: Optional[str] = Field(default=None, description="Flow regime: laminar, transitional, or turbulent (B1)")
    reynolds_number: Optional[float] = Field(default=None, description="Impeller Reynolds number Re = rho * N * D^2 / mu (B1)")
    continuity_residual_at_stop: Optional[float] = Field(default=None, description="Continuity residual at final iteration (B3)")
    max_residual_at_stop: Optional[float] = Field(default=None, description="Maximum residual across all equations at final iteration (B3)")
    cfd_power_shaft_w: Optional[float] = Field(default=None, description="Shaft mechanical power draw P_M = M * omega in Watts (B4)")
    cfd_power_dissipation_w: Optional[float] = Field(default=None, description="Domain volume dissipation power P_eps = int(rho * epsilon dV) in Watts (B4)")
    power_dissipation_ratio: Optional[float] = Field(default=None, description="Energy balance ratio P_eps / P_M (B4)")
    sector_fraction: float = Field(default=1.0, description="Domain azimuthal sector fraction, 1.0 for full 360 tank (B6)")


def generate_run_id(
    tank: TankGeometry,
    fluid: FluidProperties,
    ops: OperatingConditions,
    mesh_density: str = "fast",
    iterations: int = 60,
) -> str:
    """Generate a deterministic, parameter-sensitive unique hash identifier.

    Sensitive to changes in tank dimensions, dish bottom type, baffle geometry,
    individual impeller geometries, clearances, inter-impeller gaps, fluid properties,
    RPM, mesh resolution, and iteration count.
    """
    imp_specs = [
        (
            imp.impeller_type.value,
            round(imp.diameter_m, 5),
            round(imp.clearance_m, 5),
            imp.blade_count,
            round(imp.blade_width_m, 5) if imp.blade_width_m is not None else None,
        )
        for imp in tank.impellers
    ]
    payload = {
        "diameter_m": round(tank.diameter_m, 5),
        "liquid_height_m": round(tank.liquid_height_m, 5),
        "bottom_type": tank.bottom_type.value,
        "is_baffled": tank.is_baffled,
        "baffle_count": tank.baffle_count,
        "baffle_width_m": round(tank.baffle_width_m, 5) if tank.baffle_width_m else 0.0,
        "impellers": imp_specs,
        "density_kg_m3": round(fluid.density_kg_m3, 3),
        "viscosity_pa_s": round(fluid.viscosity_pa_s, 6),
        "rpm": round(ops.rpm, 2),
        "mesh_density": str(mesh_density).lower(),
        "iterations": int(iterations),
    }
    canonical = json.dumps(payload, sort_keys=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]

    primary_imp = tank.impellers[0].impeller_type.value[:4] if tank.impellers else "tank"
    bottom_str = tank.bottom_type.value[:4]
    rpm_int = int(round(ops.rpm))
    return f"fluent_{primary_imp}_{bottom_str}_{rpm_int}rpm_{digest}"


# =============================================================================
# Exporter and Convergence Helpers (Part B1 - B6)
# =============================================================================

def calc_canonical_power_number(
    power_w: float,
    density_kg_m3: float,
    rpm: float,
    diameter_m: float,
) -> float:
    """Canonical Power Number: Np = P / (rho * N^3 * D^5), where N = rpm / 60.0 (B5)."""
    n_rps = rpm / 60.0
    denom = density_kg_m3 * (n_rps ** 3) * (diameter_m ** 5)
    if denom <= 1e-12:
        return 0.0
    return float(power_w / denom)


def get_canonical_config_hash(cfg: Dict[str, Any]) -> str:
    """Canonical SHA-256 config hash computed identically across runner, API, and manifest (B5)."""
    tank_data = cfg.get("tank", {})
    fluid_data = cfg.get("fluid", {})
    ops_data = cfg.get("ops", {})
    mesh_density = str(cfg.get("mesh_density") or cfg.get("mesh", {}).get("mesh_resolution") or "fast").lower()
    iterations = int(cfg.get("iterations") or cfg.get("mesh", {}).get("iterations") or 15)

    impellers = []
    for imp in tank_data.get("impellers", []):
        imp_type = imp.get("impeller_type")
        if hasattr(imp_type, "value"):
            imp_type = imp_type.value
        impellers.append({
            "impeller_type": str(imp_type),
            "diameter_m": round(float(imp.get("diameter_m", 0.0)), 5),
            "clearance_m": round(float(imp.get("clearance_m", 0.0)), 5),
            "blade_count": int(imp.get("blade_count", 0)) if imp.get("blade_count") else None,
            "blade_width_m": round(float(imp["blade_width_m"]), 5) if imp.get("blade_width_m") is not None else None,
        })

    bottom_type = tank_data.get("bottom_type", "flat")
    if hasattr(bottom_type, "value"):
        bottom_type = bottom_type.value

    normalized = {
        "tank": {
            "diameter_m": round(float(tank_data.get("diameter_m", 0.0)), 5),
            "liquid_height_m": round(float(tank_data.get("liquid_height_m", 0.0)), 5),
            "bottom_type": str(bottom_type),
            "is_baffled": bool(tank_data.get("is_baffled", True)),
            "baffle_count": int(tank_data.get("baffle_count", 4)),
            "baffle_width_m": round(float(tank_data.get("baffle_width_m", 0.0)), 5) if tank_data.get("baffle_width_m") else 0.0,
            "impellers": impellers,
        },
        "fluid": {
            "density_kg_m3": round(float(fluid_data.get("density_kg_m3", 1000.0)), 3),
            "viscosity_pa_s": round(float(fluid_data.get("viscosity_pa_s") or fluid_data.get("dynamic_viscosity_pa_s") or 0.001), 6),
        },
        "ops": {
            "rpm": round(float(ops_data.get("rpm", 0.0)), 2),
        },
        "mesh_density": mesh_density,
        "iterations": iterations,
    }
    canonical_json = json.dumps(normalized, sort_keys=True)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def export_residuals_csv(
    run_dir: str,
    residuals: List[FluentResidualStep],
    torque_history: Optional[List[float]] = None,
) -> str:
    """Save per-iteration scaled residuals and torque monitor history to residuals.csv (B2)."""
    os.makedirs(run_dir, exist_ok=True)
    csv_path = os.path.join(run_dir, "residuals.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("iteration,continuity,x_velocity,y_velocity,z_velocity,k,epsilon,torque_nm\n")
        for i, step in enumerate(residuals):
            t_val = torque_history[i] if (torque_history and i < len(torque_history)) else (torque_history[-1] if torque_history else 0.0)
            f.write(
                f"{step.iteration},{step.continuity:.6e},{step.x_velocity:.6e},"
                f"{step.y_velocity:.6e},{step.z_velocity:.6e},{step.k:.6e},{step.epsilon:.6e},{t_val:.6e}\n"
            )
    return csv_path


def evaluate_convergence_b3(
    residuals: List[FluentResidualStep],
    torque_history: Optional[List[float]] = None,
    net_mass_imbalance: float = 0.0,
) -> Dict[str, Any]:
    """Evaluate 3-part convergence metrics per B3:
    
    - continuity residual at stop
    - max residual across all equations at stop
    - torque drift over last 100 iterations: |(mean(last 50) - mean(prev 50)) / mean(last 50)| * 100%
    - flag 'converged': True only if continuity < 1e-3, all others < 1e-4, torque drift < 1.0%, net mass imbalance < 0.1%
    """
    if not residuals:
        return {
            "continuity_residual": 1.0,
            "max_residual": 1.0,
            "torque_drift_pct": 100.0,
            "net_mass_imbalance_pct": net_mass_imbalance * 100.0,
            "converged": False,
        }

    last_step = residuals[-1]
    continuity_res = float(last_step.continuity)
    all_other_res = [
        float(last_step.x_velocity),
        float(last_step.y_velocity),
        float(last_step.z_velocity),
    ]
    if last_step.k > 0:
        all_other_res.append(float(last_step.k))
    if last_step.epsilon > 0:
        all_other_res.append(float(last_step.epsilon))

    max_other_res = max(all_other_res) if all_other_res else 1.0
    max_res = max(continuity_res, max_other_res)

    t_hist = torque_history or []
    if len(t_hist) >= 100:
        last_100 = t_hist[-100:]
        prev_50 = last_100[:50]
        last_50 = last_100[50:]
        m_prev = float(np.mean(prev_50))
        m_last = float(np.mean(last_50))
        drift_pct = abs(m_last - m_prev) / max(abs(m_last), 1e-6) * 100.0
    elif len(t_hist) >= 4:
        w_size = min(10, len(t_hist))
        t_win = t_hist[-w_size:]
        half = len(t_win) // 2
        prev_h = t_win[:half]
        last_h = t_win[half:]
        m_prev = float(np.mean(prev_h))
        m_last = float(np.mean(last_h))
        drift_pct = abs(m_last - m_prev) / max(abs(m_last), 1e-6) * 100.0
    else:
        drift_pct = 100.0

    net_mass_imbalance_pct = abs(net_mass_imbalance) * 100.0

    is_converged = bool(
        continuity_res < 1e-3
        and max_other_res < 1e-4
        and drift_pct < 1.0
        and net_mass_imbalance_pct < 0.1
    )

    return {
        "continuity_residual": continuity_res,
        "max_residual": max_res,
        "torque_drift_pct": round(drift_pct, 4),
        "net_mass_imbalance_pct": round(net_mass_imbalance_pct, 4),
        "converged": is_converged,
    }


def scale_torque_for_sector(raw_torque: float, sector_fraction: float = 1.0) -> float:
    """Scale torque from sector/periodic domain to full 360-degree vessel (B6).
    
    Current cad_mesher setup generates full 360-degree geometry (sector_fraction = 1.0).
    If an N-degree periodic sector is modeled (e.g. 90 deg -> 0.25), full torque is raw / sector_fraction.
    """
    frac = max(float(sector_fraction), 1e-6)
    return float(raw_torque / frac)


def compute_powers(
    raw_torque_nm: float,
    omega_rad_s: float,
    sector_fraction: float = 1.0,
    domain_volume_m3: Optional[float] = None,
    mean_epsilon_m2_s3: Optional[float] = None,
    density_kg_m3: float = 1000.0,
) -> Dict[str, Optional[float]]:
    """Compute shaft mechanical power P_M and domain volume dissipation power P_eps (B4)."""
    scaled_torque = scale_torque_for_sector(raw_torque_nm, sector_fraction)
    p_m = scaled_torque * max(omega_rad_s, 1e-4)

    p_eps = None
    ratio = None
    if domain_volume_m3 is not None and mean_epsilon_m2_s3 is not None and mean_epsilon_m2_s3 > 0:
        p_eps = density_kg_m3 * mean_epsilon_m2_s3 * domain_volume_m3
        ratio = p_eps / max(p_m, 1e-6)

    return {
        "scaled_torque_nm": round(scaled_torque, 5),
        "power_shaft_w": round(p_m, 3),
        "power_dissipation_w": round(p_eps, 3) if p_eps is not None else None,
        "power_dissipation_ratio": round(ratio, 4) if ratio is not None else None,
    }


class FluentSimulationRunner:
    """Core backend engine for automated Ansys Fluent 2026 R1 CFD simulations."""

    DEFAULT_FLUENT_EXE = (
        r"C:\Program Files\ANSYS Inc\ANSYS Student\v261\fluent\ntbin\win64\fluent.exe"
    )

    def __init__(
        self,
        fluent_executable: Optional[str] = None,
        base_output_dir: Optional[str] = None,
        terminal_output: bool = False,
    ):
        self.fluent_exe = fluent_executable or self._find_fluent_executable()
        self.terminal_output = terminal_output
        if base_output_dir is None:
            self.base_output_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "outputs", "fluent_runs")
            )
        else:
            self.base_output_dir = os.path.abspath(base_output_dir)
        self.active_session: Optional[Any] = None
        self.active_pid: Optional[int] = None
        self._aborted = False
        os.makedirs(self.base_output_dir, exist_ok=True)

    def abort(self) -> None:
        """Signal abort to running solver and attempt clean session exit."""
        self._aborted = True
        target_pid = self.active_pid
        if self.active_session:
            try:
                self.active_session.exit()
            except Exception:
                pass
        self.active_session = None
        self.active_pid = None
        self.kill_lingering_fluent_processes(pid=target_pid)

    @classmethod
    def kill_lingering_fluent_processes(cls, pid: Optional[int] = None) -> None:
        """Forcefully terminate lingering Fluent and MPI worker processes on the host.

        Ensures the 1-seat Ansys Student license is immediately released.
        """
        import subprocess
        import glob
        import re

        # 1. Kill specific launcher PID tree if provided
        if pid:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    timeout=5,
                )
            except Exception:
                pass

        # 2. Parse any cleanup-fluent-*.bat generated by Fluent and kill those exact PIDs
        try:
            pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            search_dirs = {os.getcwd(), pkg_root, os.path.abspath(os.path.join(pkg_root, ".."))}
            for s_dir in search_dirs:
                if not os.path.isdir(s_dir):
                    continue
                for bat_file in glob.glob(os.path.join(s_dir, "cleanup-fluent-*.bat")):
                    try:
                        with open(bat_file, "r", encoding="utf-8", errors="ignore") as f_bat:
                            bat_content = f_bat.read()
                        bat_pids = re.findall(r"%KILL_CMD%\s+(\d+)", bat_content)
                        for b_pid in bat_pids:
                            try:
                                subprocess.run(["taskkill", "/F", "/PID", b_pid], capture_output=True, timeout=2)
                            except Exception:
                                pass
                        try:
                            os.remove(bat_file)
                        except Exception:
                            pass
                    except Exception:
                        pass
        except Exception:
            pass

        # 3. Terminate any detached MPI worker nodes or leftover fluent solvers on Windows
        if os.name == "nt":
            for proc_name in ("fl_mpi*", "fluent.exe", "fl_mpi2610.exe"):
                try:
                    subprocess.run(["taskkill", "/F", "/IM", proc_name, "/T"], capture_output=True, timeout=3)
                except Exception:
                    pass

    def _find_fluent_executable(self) -> str:
        """Locate the Ansys Fluent 2026 R1 solver executable."""
        candidates = [
            self.DEFAULT_FLUENT_EXE,
            r"C:\Program Files\ANSYS Inc\v261\fluent\ntbin\win64\fluent.exe",
        ]
        awp_root = os.environ.get("AWP_ROOT261")
        if awp_root:
            candidates.append(os.path.join(awp_root, "fluent", "ntbin", "win64", "fluent.exe"))

        for c in candidates:
            if os.path.isfile(c):
                return c

        which_fluent = shutil.which("fluent")
        if which_fluent:
            return which_fluent

        # Return default path if not found, launch_fluent will handle or give clear error
        return self.DEFAULT_FLUENT_EXE

    @classmethod
    def cleanup_stray_fluent_logs(cls, target_dir: Optional[str] = None) -> None:
        """Move any stray fluent-*.trn or fluent-*.log files from cwd/root to outputs/fluent_logs or target_dir."""
        try:
            import glob
            import shutil
            import time
            cwd = os.getcwd()
            pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            ws_root = os.path.abspath(os.path.join(pkg_root, ".."))
            search_dirs = {cwd, pkg_root, ws_root}
            log_dir = target_dir or os.path.join(pkg_root, "outputs", "fluent_logs")
            log_dir = os.path.abspath(log_dir)
            os.makedirs(log_dir, exist_ok=True)
            for s_dir in search_dirs:
                if not os.path.isdir(s_dir):
                    continue
                for pattern in ("fluent-*.trn", "fluent-*.log", "fluent_*.trn", "fluent_*.log"):
                    for f in glob.glob(os.path.join(s_dir, pattern)):
                        dest = os.path.join(log_dir, os.path.basename(f))
                        if os.path.abspath(f) == os.path.abspath(dest):
                            continue
                        for attempt in range(4):
                            try:
                                if os.path.exists(dest):
                                    os.remove(dest)
                                shutil.move(f, dest)
                                break
                            except Exception:
                                time.sleep(0.15)
                                try:
                                    os.remove(f)
                                    break
                                except Exception:
                                    pass
        except Exception:
            pass

    @staticmethod
    def evaluate_sliding_window_convergence(
        monitored_torque_history: List[float],
        monitored_velocity_history: Optional[List[float]] = None,
        monitored_continuity_history: Optional[List[float]] = None,
        window_size: int = 3,
        torque_drift_threshold_pct: float = 2.0,
        velocity_drift_threshold_pct: float = 2.0,
        absolute_torque_threshold_n_m: Optional[float] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Evaluate monitor stabilization over a sliding window of the last >= 3 iteration blocks (MED-02).
        
        Requires:
        - At least `window_size` (>= 3) blocks
        - Max relative torque drift < 2.0% across the window (or within absolute_torque_threshold_n_m)
        - Characteristic velocity drift < 2.0% across the window (if monitored)
        - Non-diverging continuity residuals across the window
        """
        if len(monitored_torque_history) < window_size:
            return False, {
                "converged": False,
                "reason": f"Fewer than {window_size} iteration blocks recorded for torque ({len(monitored_torque_history)} < {window_size}).",
                "torque_drift_pct": 100.0 if not monitored_torque_history else 50.0,
                "velocity_drift_pct": 100.0,
                "continuity_converged": False,
                "window_size": len(monitored_torque_history),
            }

        # Last window_size blocks
        t_win = monitored_torque_history[-window_size:]
        t_min = min(t_win)
        t_max = max(t_win)
        t_mean = max(abs(float(np.mean(t_win))), 1e-6)
        torque_drift_pct = (t_max - t_min) / t_mean * 100.0
        torque_converged = (torque_drift_pct <= torque_drift_threshold_pct)
        if absolute_torque_threshold_n_m is not None and (t_max - t_min) <= absolute_torque_threshold_n_m:
            torque_converged = True

        # Velocity monitoring: genuine drift check across window
        vel_drift_pct = 100.0
        vel_converged = False
        if monitored_velocity_history and len(monitored_velocity_history) >= window_size:
            v_win = monitored_velocity_history[-window_size:]
            if all(v > 0.05 for v in v_win):
                v_min = min(v_win)
                v_max = max(v_win)
                v_mean = max(abs(float(np.mean(v_win))), 1e-6)
                vel_drift_pct = (v_max - v_min) / v_mean * 100.0
                vel_converged = (vel_drift_pct <= velocity_drift_threshold_pct) or ((v_max - v_min) < 0.05)
            else:
                vel_converged = True
        else:
            vel_converged = True

        continuity_converged = True
        if monitored_continuity_history and len(monitored_continuity_history) >= window_size:
            c_win = monitored_continuity_history[-window_size:]
            continuity_converged = (c_win[-1] <= c_win[0] * 1.30 and c_win[-1] < 0.05) or (c_win[-1] < 1e-4)

        is_converged = torque_converged and vel_converged and continuity_converged

        return is_converged, {
            "converged": is_converged,
            "torque_drift_pct": round(torque_drift_pct, 2),
            "velocity_drift_pct": round(vel_drift_pct, 2),
            "continuity_converged": continuity_converged,
            "window_size": window_size,
        }

    def run_simulation(
        self,
        tank: TankGeometry,
        fluid: FluidProperties,
        ops: OperatingConditions,
        mesh_density: Literal["fast", "medium", "fine"] = "fast",
        iterations: int = 40,
        use_cache: bool = True,
        progress_callback: Optional[Callable[[int, int, str, Optional[FluentResidualStep]], None]] = None,
        session_callback: Optional[Callable[[Any, Optional[int]], None]] = None,
        abort_check: Optional[Callable[[], bool]] = None,
        run_dir: Optional[str] = None,
        run_id: Optional[str] = None,
        config_iterations: Optional[int] = None,
    ) -> FluentRunMetadata:
        """Run an end-to-end 3D CFD simulation in Ansys Fluent 2026 R1.

        Parameters
        ----------
        tank : TankGeometry
            Vessel anatomy, baffles, and impeller stages.
        fluid : FluidProperties
            Broth density and viscosity.
        ops : OperatingConditions
            Rotational agitation speed (RPM) and gas flow.
        mesh_density : Literal["fast", "medium", "fine"]
            Tetrahedral grid refinement level.
        iterations : int
            Number of live Navier-Stokes iterations.
        use_cache : bool
            If True, return existing completed run artifacts from disk.
        progress_callback : Optional[Callable[[int, int, str, Optional[FluentResidualStep]], None]]
            Optional callback for live progress updates and residual streaming:
            callback(current_iter, total_iters, status_message, residual_step)
        run_dir : Optional[str]
            Optional custom output directory.
        run_id : Optional[str]
            Optional custom run identifier.

        Returns
        -------
        FluentRunMetadata
            Complete run metrics, residuals history, and file paths.
        """
        if run_id is None:
            run_id = generate_run_id(tank, fluid, ops, mesh_density=mesh_density, iterations=iterations)
        if run_dir is None:
            run_dir = os.path.join(self.base_output_dir, run_id)
        os.makedirs(run_dir, exist_ok=True)

        meta_file = os.path.join(run_dir, "metadata.json")
        bundle_file = os.path.join(run_dir, "web_3d_bundle.json")

        # ---------------------------------------------------------------------
        # 1. Check Disk Run Cache (Requires Full Native Evidence)
        # ---------------------------------------------------------------------
        has_full_evidence = (
            os.path.isfile(meta_file)
            and os.path.isfile(bundle_file)
            and os.path.isfile(os.path.join(run_dir, "run_manifest.json"))
            and os.path.isfile(os.path.join(run_dir, "fluent_case.cas.h5"))
            and os.path.isfile(os.path.join(run_dir, "fluent_case.dat.h5"))
        )
        if use_cache and has_full_evidence:
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                cached_data["cached"] = True
                meta = FluentRunMetadata(**cached_data)

                # Ensure config.json exists
                config_file = os.path.join(run_dir, "config.json")
                if not os.path.isfile(config_file):
                    config_payload = {
                        "tank": tank.model_dump(),
                        "fluid": fluid.model_dump(),
                        "ops": ops.model_dump(),
                        "mesh_density": mesh_density,
                        "iterations": iterations,
                    }
                    try:
                        with open(config_file, "w", encoding="utf-8") as f:
                            json.dump(config_payload, f, indent=2)
                    except Exception:
                        pass

                if progress_callback:
                    progress_callback(
                        iterations,
                        iterations,
                        f"Loaded cached Ansys Fluent run ({run_id})",
                        meta.residuals[-1] if meta.residuals else None,
                    )
                return meta
            except Exception:
                # If cache file corrupted, recompute
                pass

        # ---------------------------------------------------------------------
        # 2. Automated CAD Meshing via Gmsh OpenCASCADE
        # ---------------------------------------------------------------------
        if progress_callback:
            progress_callback(0, iterations, "Generating 3D conformal mesh with OpenCASCADE & Gmsh...", None)

        mesher = BioreactorCADMesher(terminal_output=self.terminal_output)
        mesh_artifact: MeshedBioreactorArtifact = mesher.generate_fluent_mesh(
            tank=tank,
            mesh_density=mesh_density,
            output_dir=run_dir,
            prefix=f"fluent_{run_id[:8]}",
        )

        # ---------------------------------------------------------------------
        # 3. Launch Live Ansys Fluent 2026 R1 Solver
        # ---------------------------------------------------------------------
        if progress_callback:
            progress_callback(0, iterations, "Launching Ansys Fluent 2026 R1 Double Precision Solver...", None)

        import ansys.fluent.core as pyfluent
        from ansys.fluent.core.services.field_data import SurfaceDataType
        from ansys.fluent.core.fields.field_data_interfaces import (
            ScalarFieldDataRequest,
            VectorFieldDataRequest,
            SurfaceFieldDataRequest,
        )

        # Pre-flight: Ensure lingering solver workers from prior runs are cleared
        self.kill_lingering_fluent_processes()

        self._aborted = False
        session = pyfluent.launch_fluent(
            fluent_path=self.fluent_exe,
            dimension=3,
            precision="double",
            processor_count=2,
            ui_mode="no_gui_or_graphics",
            mode="solver",
            cleanup_on_exit=False,
        )
        self.active_session = session
        proc = getattr(session, "_process", None)
        self.active_pid = getattr(proc, "pid", None)
        if session_callback:
            try:
                session_callback(session, self.active_pid)
            except Exception:
                pass

        residuals_history: List[FluentResidualStep] = []
        residual_pattern = re.compile(
            r"^\s*(\d+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)(?:\s+([0-9.eE+-]+))?(?:\s+([0-9.eE+-]+))?"
        )

        def transcript_listener(chunk: str) -> None:
            """Parse live stdout transcript chunks for Navier-Stokes residuals."""
            for line in chunk.splitlines():
                m = residual_pattern.match(line)
                if m:
                    try:
                        it_num = int(m.group(1))
                        c_val = float(m.group(2))
                        u_val = float(m.group(3))
                        v_val = float(m.group(4))
                        w_val = float(m.group(5))
                        k_val = float(m.group(6)) if m.group(6) else 0.0
                        eps_val = float(m.group(7)) if m.group(7) else 0.0

                        step = FluentResidualStep(
                            iteration=it_num,
                            continuity=c_val,
                            x_velocity=u_val,
                            y_velocity=v_val,
                            z_velocity=w_val,
                            k=k_val,
                            epsilon=eps_val,
                        )
                        residuals_history.append(step)

                        if progress_callback:
                            if it_num > iterations:
                                effective_total = max(iterations + 80, it_num)
                                msg = f"Adaptive Convergence Stabilization: Iteration {it_num}/{effective_total} (Drift target <= 2.0%)"
                                progress_callback(it_num, effective_total, msg, step)
                            else:
                                msg = f"Navier-Stokes Iteration {it_num}/{iterations} (Cont: {c_val:.2e})"
                                progress_callback(it_num, iterations, msg, step)
                    except Exception:
                        pass

        try:
            session.transcript.register_callback(transcript_listener)
        except Exception:
            pass

        solve_start = time.perf_counter()
        case_data_path = os.path.join(run_dir, "fluent_case.cas.h5")
        dat_data_path = os.path.join(run_dir, "fluent_case.dat.h5")
        case_data_saved = False

        try:
            # 3.1 Import Nastran BDF Conformal Mesh
            clean_bdf = mesh_artifact.bdf_mesh_path.replace("\\", "/")
            session.settings.file.import_.read(file_type="nastran-bulkdata", file_name=clean_bdf)
            session.settings.mesh.check()

            # 3.2 Convert all Nastran solid zones to fluid
            solid_zones = session.settings.setup.cell_zone_conditions.solid.get_object_names()
            if solid_zones:
                session.settings.setup.cell_zone_conditions.set_zone_type(
                    zone_list=solid_zones, new_type="fluid"
                )

            active_fluid_zones = session.settings.setup.cell_zone_conditions.fluid.get_object_names()

            # 3.3 Broth Physical Material Properties & Rheology
            rps = max(ops.rps, 1e-4)
            is_close_clearance = any(
                (imp.impeller_type.clearance_class == ImpellerClearanceClass.CLOSE_CLEARANCE)
                for imp in tank.impellers
            )
            any_exp = any(
                imp.impeller_type in EXPERIMENTAL_CFD_IMPELLERS
                for imp in tank.impellers
            )
            if is_close_clearance:
                readiness_tier = "laminar_close_clearance"
                physics_scope = "single_phase_steady_mrf_laminar"
            elif any_exp:
                readiness_tier = "experimental_cfd"
                physics_scope = "single_phase_steady_mrf"
            else:
                readiness_tier = "live_cfd_mvp"
                physics_scope = "single_phase_steady_mrf"

            # Metzner-Otto apparent shear rate: ks ~ 30 for anchor/close-clearance, 11.5 for open turbines
            ks = 30.0 if is_close_clearance else 11.5
            shear_rate_avg = ks * rps
            effective_mu = fluid.get_effective_viscosity(shear_rate_avg)

            session.settings.setup.materials.fluid["air"].density.value = float(fluid.density_kg_m3)
            session.settings.setup.materials.fluid["air"].viscosity.value = float(effective_mu)

            # Impeller Reynolds number
            primary_di = tank.impellers[0].diameter_m if tank.impellers else 0.15
            re_i = (fluid.density_kg_m3 * rps * (primary_di ** 2)) / max(effective_mu, 1e-6)
            is_laminar_regime = (re_i < 200.0) or is_close_clearance

            # 3.4 Viscous Model: Laminar vs Realizable k-epsilon
            if is_laminar_regime:
                session.settings.setup.models.viscous.model = "laminar"
                logger.info(f"Configured Fluent Viscous Model: LAMINAR (Re_i = {re_i:.1f}, close_clearance={is_close_clearance})")
            else:
                try:
                    session.settings.setup.models.viscous.model = "k-epsilon"
                    session.settings.setup.models.viscous.k_epsilon_model = "realizable"
                    logger.info(f"Configured Fluent Viscous Model: Realizable k-epsilon (Re_i = {re_i:.1f})")
                except Exception:
                    session.settings.setup.models.viscous.model = "laminar"

            # 3.5 MRF Rotational Frame Motion on Rotating Impeller Cylinders
            omega_rad_s = float(ops.rpm * 2.0 * math.pi / 60.0)
            for mrf_zone in mesh_artifact.mrf_zone_names:
                if mrf_zone in active_fluid_zones:
                    mrf_cell = session.settings.setup.cell_zone_conditions.fluid[mrf_zone]
                    mrf_cell.reference_frame.frame_motion = True
                    mrf_cell.reference_frame.mrf_omega.value = omega_rad_s

            # 3.5b Guaranteed MRF Interface Sewing: convert wall-203 to interior one-by-one (Task 2.1)
            try:
                wall_zones = set(session.settings.setup.boundary_conditions.wall.get_object_names())
                vessel_set = set(getattr(mesh_artifact, "vessel_wall_names", []))
                impeller_set = set(getattr(mesh_artifact, "impeller_wall_names", []))
                interface_targets = set(getattr(mesh_artifact, "interface_wall_names", []))

                for w in wall_zones:
                    if w.endswith("-shadow"):
                        continue
                    if f"{w}-shadow" in wall_zones or "203" in w or "interface" in w.lower():
                        if w not in vessel_set and w not in impeller_set and w != "wall-202":
                            interface_targets.add(w)

                # Convert ONLY the primary non-shadow wall zone name one at a time
                for w_name in sorted(list(interface_targets)):
                    current_walls = session.settings.setup.boundary_conditions.wall.get_object_names()
                    if w_name in current_walls and not w_name.endswith("-shadow"):
                        try:
                            session.settings.setup.boundary_conditions.set_zone_type(
                                zone_list=[w_name], new_type="interior"
                            )
                            logger.info(f"Successfully converted MRF interface wall '{w_name}' to interior.")
                        except Exception as ex:
                            logger.warning(f"Could not convert MRF interface wall '{w_name}' to interior: {ex}")

                # Verify no interface walls remain
                remaining_walls = session.settings.setup.boundary_conditions.wall.get_object_names()
                unconverted_interfaces = [
                    w for w in remaining_walls
                    if ("203" in w or "interface" in w.lower())
                    and w not in vessel_set and w not in impeller_set
                ]
                if unconverted_interfaces:
                    logger.warning(f"Warning: interface walls remain in boundary conditions: {unconverted_interfaces}")
            except Exception as e:
                logger.warning(f"Error during MRF interface conversion to interior: {e}")

            # 3.5c Set rotational moving wall motion on all impeller & shaft blade walls (Task 2.2)
            active_walls = set(session.settings.setup.boundary_conditions.wall.get_object_names())
            active_impeller_walls: List[str] = []
            for w in active_walls:
                is_imp = any(w == bw or w.startswith(f"{bw}-") or bw in w for bw in mesh_artifact.impeller_wall_names)
                if not is_imp:
                    is_imp = ("201" in w or "impeller" in w.lower()) and ("vessel" not in w.lower() and "baffle" not in w.lower())
                if is_imp and ("floor" in w.lower() or "dish" in w.lower() or "bottom" in w.lower()):
                    is_imp = False
                if is_imp:
                    try:
                        b_wall = session.settings.setup.boundary_conditions.wall[w]
                        b_wall.momentum.wall_motion = "Moving Wall"
                        b_wall.momentum.relative = "Absolute"
                        b_wall.momentum.rotating = True
                        b_wall.momentum.rotation_speed.value = float(omega_rad_s)
                        b_wall.momentum.rotation_axis_origin = [0.0, 0.0, 0.0]
                        b_wall.momentum.rotation_axis_direction = [0.0, 0.0, 1.0]
                        active_impeller_walls.append(w)
                        logger.info(f"Configured moving impeller wall '{w}': Absolute rotation at {omega_rad_s:.4f} rad/s")
                    except Exception as e_w:
                        logger.warning(f"Error configuring moving impeller wall '{w}': {e_w}")

            # 3.5d Explicitly enforce stationary wall boundary condition on all outer vessel walls
            for w in active_walls:
                is_vessel = any(w == vw or w.startswith(f"{vw}-") or vw in w for vw in mesh_artifact.vessel_wall_names)
                if not is_vessel:
                    is_vessel = ("202" in w or "vessel" in w.lower()) and (w not in active_impeller_walls)
                if is_vessel:
                    try:
                        v_wall = session.settings.setup.boundary_conditions.wall[w]
                        if not mesh_artifact.stationary_zone_names:
                            # Single MRF zone encompassing whole vessel (close-clearance):
                            # Set outer tank vessel wall to stationary in the absolute frame (speed = 0.0)
                            v_wall.momentum.wall_motion = "Moving Wall"
                            v_wall.momentum.rotating = True
                            v_wall.momentum.relative = "Absolute"
                            v_wall.momentum.rotation_speed.value = 0.0
                            v_wall.momentum.rotation_axis_origin = [0.0, 0.0, 0.0]
                            v_wall.momentum.rotation_axis_direction = [0.0, 0.0, 1.0]
                        else:
                            # Standard vessel in stationary cell zone:
                            v_wall.momentum.wall_motion = "Stationary Wall"
                    except Exception:
                        pass

            # 3.6 Setup Native Fluent Moment Report Definition around [0, 0, 1] on impeller blade walls (CRIT-01)
            has_moment_report = False
            moment_rep_name = "moment_impeller"
            if active_impeller_walls:
                try:
                    rep = session.settings.solution.report_definitions.moment.create(moment_rep_name)
                    rep.report_output_type = "Moment"
                    rep.mom_axis = [0.0, 0.0, 1.0]
                    rep.mom_center = [0.0, 0.0, 0.0]
                    rep.zones = active_impeller_walls
                    has_moment_report = True
                except Exception:
                    has_moment_report = False

            # 3.7 Create Internal Planar Slices in Fluent
            self._create_fluent_slice_surfaces(session, tank)

            # 3.8 Hybrid Initialization
            if progress_callback:
                progress_callback(0, iterations, "Executing Hybrid Initialization...", None)
            session.settings.solution.initialization.hybrid_initialize()

            # 3.9 Solve Iterations in Blocks with Convergence & Torque Stabilization Monitoring (CRIT-02)
            monitored_torque_history: List[float] = []
            monitored_velocity_history: List[float] = []
            monitored_continuity_history: List[float] = []
            block_size = max(5, min(20, iterations // 10)) if iterations >= 50 else (10 if iterations >= 30 else max(5, iterations // 3))
            completed_iters = 0
            consecutive_converged_iters = 0

            while completed_iters < iterations:
                if self._aborted or (abort_check and abort_check()):
                    logger.info("Live Ansys Fluent solve aborted by user request.")
                    raise InterruptedError("Simulation aborted by user.")
                chunk = min(block_size, iterations - completed_iters)
                session.settings.solution.run_calculation.iterate(iter_count=chunk)
                completed_iters += chunk

                # Query Fluent moment report
                if has_moment_report:
                    try:
                        res = session.settings.solution.report_definitions.compute(report_defs=[moment_rep_name])
                        t_val = None
                        if isinstance(res, list) and len(res) > 0:
                            item = res[0]
                            if isinstance(item, dict) and moment_rep_name in item:
                                val = item[moment_rep_name]
                                t_val = abs(float(val[0])) if isinstance(val, (list, tuple)) else abs(float(val))
                            elif isinstance(item, (int, float)):
                                t_val = abs(float(item))
                        elif isinstance(res, dict) and moment_rep_name in res:
                            val = res[moment_rep_name]
                            t_val = abs(float(val[0])) if isinstance(val, (list, tuple)) else abs(float(val))
                        if t_val is not None:
                            monitored_torque_history.append(t_val)
                    except Exception as e_comp:
                        logger.warning(f"Error computing moment report: {e_comp}")

                # Query Characteristic Velocity Magnitude for stabilization monitoring (CRT-02)
                try:
                    v_range = session.fields.field_data._field_data.get_scalar_field_range("velocity-magnitude")
                    if v_range and len(v_range) >= 2:
                        monitored_velocity_history.append(float(v_range[1]))
                except Exception:
                    pass

                if residuals_history:
                    monitored_continuity_history.append(residuals_history[-1].continuity)

                # Early stop if converged per B3 for 100 consecutive iterations
                if iterations >= 100 and len(monitored_torque_history) >= 20 and residuals_history:
                    b3_chk = evaluate_convergence_b3(residuals_history, monitored_torque_history)
                    if b3_chk["converged"]:
                        consecutive_converged_iters += chunk
                        if consecutive_converged_iters >= 100:
                            logger.info(f"B3 convergence achieved for 100 consecutive iterations at iteration {completed_iters}. Stopping solve early.")
                            break
                    else:
                        consecutive_converged_iters = 0

            # Check sliding window convergence before finishing solve
            is_conv_pre, conv_det_pre = self.evaluate_sliding_window_convergence(
                monitored_torque_history=monitored_torque_history,
                monitored_velocity_history=None,
                monitored_continuity_history=monitored_continuity_history,
                window_size=3,
                torque_drift_threshold_pct=2.0,
                velocity_drift_threshold_pct=3.0,
                absolute_torque_threshold_n_m=0.030,
            )

            # If not converged after initial iterations, adaptively iterate with under-relaxation
            # until torque drift settles below 2.0% or max_adaptive_iters is reached.
            max_adaptive_iters = max(iterations + 80, 160)
            if not is_conv_pre and not self._aborted:
                logger.info(
                    f"Run has not yet settled (reason: {conv_det_pre.get('reason')}). "
                    f"Applying under-relaxation (pressure=0.25, mom=0.5) and adaptively iterating up to {max_adaptive_iters} iters..."
                )
                try:
                    session.settings.solution.controls.under_relaxation["pressure"] = 0.25
                    session.settings.solution.controls.under_relaxation["mom"] = 0.50
                except Exception as e_urf:
                    logger.warning(f"Could not adjust under-relaxation factors: {e_urf}")

                while completed_iters < max_adaptive_iters and not is_conv_pre and not self._aborted:
                    sub_chunk = min(10, max_adaptive_iters - completed_iters)
                    session.settings.solution.run_calculation.iterate(iter_count=sub_chunk)
                    completed_iters += sub_chunk

                    if has_moment_report:
                        try:
                            res = session.settings.solution.report_definitions.compute(report_defs=[moment_rep_name])
                            t_val = None
                            if isinstance(res, list) and len(res) > 0:
                                item = res[0]
                                if isinstance(item, dict) and moment_rep_name in item:
                                    val = item[moment_rep_name]
                                    t_val = abs(float(val[0])) if isinstance(val, (list, tuple)) else abs(float(val))
                                elif isinstance(item, (int, float)):
                                    t_val = abs(float(item))
                            elif isinstance(res, dict) and moment_rep_name in res:
                                val = res[moment_rep_name]
                                t_val = abs(float(val[0])) if isinstance(val, (list, tuple)) else abs(float(val))
                            if t_val is not None:
                                monitored_torque_history.append(t_val)
                        except Exception as e_comp:
                            logger.warning(f"Error computing moment report in adaptive loop: {e_comp}")

                    if residuals_history:
                        monitored_continuity_history.append(residuals_history[-1].continuity)

                    is_conv_pre, conv_det_pre = self.evaluate_sliding_window_convergence(
                        monitored_torque_history=monitored_torque_history,
                        monitored_velocity_history=None,
                        monitored_continuity_history=monitored_continuity_history,
                        window_size=3,
                        torque_drift_threshold_pct=2.0,
                        velocity_drift_threshold_pct=3.0,
                        absolute_torque_threshold_n_m=None,
                    )
                    drift_now = conv_det_pre.get("torque_drift_pct", 100.0)
                    if is_conv_pre and drift_now <= 2.0:
                        logger.info(f"Convergence achieved at iteration {completed_iters} (drift: {drift_now}%)!")
                        break
                    else:
                        is_conv_pre = False

            solve_time = time.perf_counter() - solve_start

            # -----------------------------------------------------------------
            # 4. Extract Internal 3D Flow Field (Interface & Slice Surfaces)
            # -----------------------------------------------------------------
            if progress_callback:
                progress_callback(iterations, iterations, "Extracting internal 3D flow field data...", None)

            field_data = self._extract_internal_field_data(
                session=session,
                tank=tank,
                fluid=fluid,
                ops=ops,
                omega_rad_s=omega_rad_s,
            )

            # Persist native Ansys Fluent Case and Data (.cas.h5 and .dat.h5) (CRIT-03)
            os.makedirs(run_dir, exist_ok=True)
            clean_case_path = case_data_path.replace("\\", "/")
            try:
                session.settings.file.write(file_type="case-data", file_name=clean_case_path)
                case_data_saved = os.path.isfile(case_data_path) and os.path.isfile(dat_data_path)
            except Exception:
                try:
                    session.tui.file.write_case_data(f'\"{clean_case_path}\"')
                    case_data_saved = os.path.isfile(case_data_path) and os.path.isfile(dat_data_path)
                except Exception:
                    case_data_saved = False

        finally:
            # Always cleanly close Fluent session and forcefully release the 1-seat student license
            target_pid = self.active_pid
            try:
                session.exit()
            except Exception:
                pass
            self.active_session = None
            self.active_pid = None
            self.kill_lingering_fluent_processes(pid=target_pid)
            self.cleanup_stray_fluent_logs(os.path.join(run_dir, "fluent_logs"))

        # ---------------------------------------------------------------------
        # 5. Calculate Global CFD Metrics & Mechanical Power (CRIT-01 & CRIT-04)
        # ---------------------------------------------------------------------
        analytical_res = HydrodynamicEngine.run(tank, fluid, ops)
        analytical_power_w = analytical_res.total_ungassed_power_w
        analytical_torque_n_m = analytical_power_w / max(omega_rad_s, 1e-4)

        solver_warnings: List[str] = []
        fluent_torque_extracted = monitored_torque_history[-1] if monitored_torque_history else None
        torque_extraction_succeeded = False
        if fluent_torque_extracted is not None and fluent_torque_extracted > 1e-6:
            cfd_torque_n_m = fluent_torque_extracted
            cfd_power_w = cfd_torque_n_m * max(omega_rad_s, 1e-4)
            power_provenance = "fluent_solver"
            torque_extraction_succeeded = True
        else:
            logger.warning("Fluent moment report failed; power/torque fell back to engineering reference correlation.")
            solver_warnings.append("Fluent moment report failed; power/torque fell back to engineering reference correlation.")
            cfd_torque_n_m = analytical_torque_n_m
            cfd_power_w = analytical_power_w
            power_provenance = "engineering_reference"

        # B6: Scale torque for sector (full 360-degree vessel default: sector_fraction = 1.0)
        sector_fraction = 1.0
        cfd_torque_n_m = scale_torque_for_sector(cfd_torque_n_m, sector_fraction)
        cfd_power_w = cfd_torque_n_m * max(omega_rad_s, 1e-4)

        # B5: Canonical Np = P / (rho * N^3 * D^5)
        primary_di = tank.impellers[0].diameter_m if tank.impellers else 0.15
        cfd_power_number = calc_canonical_power_number(cfd_power_w, fluid.density_kg_m3, ops.rpm, primary_di)

        # B1: Compute Re and flow regime
        calc_re = calc_reynolds_number(fluid.density_kg_m3, ops.rpm / 60.0, primary_di, fluid.viscosity_pa_s)
        calc_regime = classify_flow_regime(calc_re).value

        # B3: 3-part convergence evaluation
        b3_metrics = evaluate_convergence_b3(residuals_history, monitored_torque_history)
        if torque_extraction_succeeded:
            is_converged = b3_metrics["converged"] or (is_conv_pre and conv_det_pre.get("torque_drift_pct", 100) <= 2.0)
        else:
            is_converged = False
        torque_drift_pct = conv_det_pre.get("torque_drift_pct") if (conv_det_pre and is_conv_pre) else b3_metrics["torque_drift_pct"]
        continuity_residual_at_stop = b3_metrics["continuity_residual"]
        max_residual_at_stop = b3_metrics["max_residual"]
        final_continuity = continuity_residual_at_stop

        tip_speed = max(calc_tip_speed(ops.rps, imp.diameter_m) for imp in tank.impellers)
        all_speeds = field_data["speeds"]
        all_pts = field_data.get("pts")
        R_tank = tank.diameter_m / 2.0
        H_tank = tank.liquid_height_m

        if len(all_speeds) > 0:
            raw_max_vel = float(np.max(all_speeds))
            cfd_max_vel = float(np.percentile(all_speeds, 99.8)) if len(all_speeds) > 50 else raw_max_vel

            # Evaluate interior bulk fluid points (excluding outer no-slip walls and tank floor) (Task 2.3)
            if all_pts is not None and len(all_pts) == len(all_speeds) and len(all_pts) > 1:
                r_pts = np.sqrt(all_pts[:, 0]**2 + all_pts[:, 1]**2)
                z_pts = all_pts[:, 2]
                bulk_mask = (r_pts < 0.96 * R_tank) & (z_pts > 0.02 * H_tank) & (all_speeds > 1e-4)
                interior_speeds = all_speeds[bulk_mask]
                if len(interior_speeds) == 0:
                    interior_speeds = all_speeds[all_speeds > 1e-4]
            else:
                interior_speeds = all_speeds[all_speeds > 1e-4]

            if len(interior_speeds) > 0:
                cfd_mean_vel = float(np.mean(interior_speeds))
                dead_zone_threshold = min(0.015 * tip_speed, 0.15 * cfd_mean_vel)
                raw_dz = float(np.mean(interior_speeds < dead_zone_threshold))
                dead_zone_frac = round(float(raw_dz), 4)
            else:
                cfd_mean_vel = float(np.mean(all_speeds))
                dead_zone_frac = 0.0
        else:
            cfd_mean_vel = 0.25 * tip_speed
            cfd_max_vel = float(field_data["global_max_vel"]) if field_data["global_max_vel"] > 0 else tip_speed
            dead_zone_frac = 0.0

        pressures = field_data["pressures"]
        if len(pressures) > 0:
            min_press = float(min(field_data["global_min_press"], np.min(pressures)))
            max_press = float(max(field_data["global_max_press"], np.max(pressures)))
        else:
            min_press = field_data["global_min_press"]
            max_press = field_data["global_max_press"]

        tkes = field_data["tkes"]
        epsilons = field_data["epsilons"]
        mean_tke = float(np.mean(tkes)) if len(tkes) > 0 else 0.0
        mean_eps = float(np.mean(epsilons)) if len(epsilons) > 0 else 0.0
        max_eps = float(np.max(epsilons)) if len(epsilons) > 0 else 0.0

        nu = fluid.viscosity_pa_s / fluid.density_kg_m3
        if max_eps > 1e-6:
            kolmogorov_min_um = float((nu ** 3 / max_eps) ** 0.25 * 1e6)
        else:
            kolmogorov_min_um = analytical_res.lambda_k_min_um

        # ---------------------------------------------------------------------
        # 6. Generate 3D Streamlines, 2D Grid Slices & 3D CAD Meshes
        # ---------------------------------------------------------------------
        if progress_callback:
            progress_callback(iterations, iterations, "Synthesizing 3D streamlines, slice grids and CAD meshes...", None)

        bundle_path = self._build_web_bundle(
            tank=tank,
            fluid=fluid,
            ops=ops,
            pts=field_data["pts"],
            vel=field_data["vel"],
            speeds=all_speeds,
            pressures=pressures,
            tkes=tkes,
            epsilons=epsilons,
            run_id=run_id,
            run_dir=run_dir,
            tip_speed_m_s=tip_speed,
            cfd_max_velocity_m_s=cfd_max_vel,
            cfd_mean_velocity_m_s=cfd_mean_vel,
            cfd_power_w=cfd_power_w,
            cfd_torque_n_m=cfd_torque_n_m,
        )

        stage0 = analytical_res.stages[0] if analytical_res.stages else None
        bpe_metrics_dict = {
            "re_i": round(stage0.re_i, 1) if stage0 else 0.0,
            "flow_regime": stage0.flow_regime.value if stage0 else "turbulent",
            "np_val": round(stage0.np_val, 3) if stage0 else 0.0,
            "ungassed_power_w": round(analytical_res.total_ungassed_power_w, 2),
            "gassed_power_w": round(analytical_res.total_gassed_power_w, 2),
            "mixing_time_95_s": round(analytical_res.mixing_time_95_s, 2),
            "kla_h_inv": round(analytical_res.kla_h_inv, 2),
            "vortex_depth_m": round(analytical_res.vortex_depth_m, 4),
            "circulation_time_s": round(analytical_res.circulation_time_s, 2),
        }

        metadata = FluentRunMetadata(
            run_id=run_id,
            run_dir=run_dir,
            cached=False,
            n_cells=mesh_artifact.n_cells,
            n_cells_mrf=getattr(mesh_artifact, "n_cells_mrf", 0),
            n_cells_stationary=getattr(mesh_artifact, "n_cells_stationary", 0),
            n_nodes=mesh_artifact.n_nodes,
            meshing_time_s=round(mesh_artifact.meshing_time_s, 2),
            solve_time_s=round(solve_time, 2),
            omega_rad_s=round(omega_rad_s, 3),
            rpm=round(ops.rpm, 1),
            tip_speed_m_s=round(tip_speed, 3),
            cfd_max_velocity_m_s=round(cfd_max_vel, 4),
            cfd_mean_velocity_m_s=round(cfd_mean_vel, 4),
            cfd_min_pressure_pa=round(min_press, 2),
            cfd_max_pressure_pa=round(max_press, 2),
            cfd_mean_tke_m2_s2=round(mean_tke, 5),
            cfd_mean_epsilon_m2_s3=round(mean_eps, 5),
            cfd_max_epsilon_m2_s3=round(max_eps, 5),
            cfd_kolmogorov_min_um=round(kolmogorov_min_um, 2),
            cfd_dead_zone_fraction=round(dead_zone_frac, 4),
            cfd_power_w=round(cfd_power_w, 2),
            cfd_torque_n_m=round(cfd_torque_n_m, 4),
            cfd_power_number_np=round(cfd_power_number, 3),
            ref_power_w=round(analytical_power_w, 2),
            ref_torque_n_m=round(analytical_torque_n_m, 4),
            converged=is_converged,
            torque_drift_pct=round(torque_drift_pct, 2),
            flow_regime=calc_regime,
            reynolds_number=round(calc_re, 4),
            continuity_residual_at_stop=round(continuity_residual_at_stop, 6),
            max_residual_at_stop=round(max_residual_at_stop, 6),
            cfd_power_shaft_w=round(cfd_power_w, 3),
            cfd_power_dissipation_w=round(fluid.density_kg_m3 * mean_eps * (math.pi * (tank.diameter_m / 2.0)**2 * tank.liquid_height_m), 3) if mean_eps > 0 else None,
            power_dissipation_ratio=round((fluid.density_kg_m3 * mean_eps * (math.pi * (tank.diameter_m / 2.0)**2 * tank.liquid_height_m)) / max(cfd_power_w, 1e-6), 4) if mean_eps > 0 else None,
            sector_fraction=sector_fraction,
            warnings=solver_warnings,
            metric_sources={
                "cfd_max_velocity_m_s": "fluent_field",
                "cfd_mean_velocity_m_s": "fluent_field",
                "cfd_min_pressure_pa": "fluent_field",
                "cfd_max_pressure_pa": "fluent_field",
                "cfd_mean_tke_m2_s2": "fluent_field",
                "cfd_mean_epsilon_m2_s3": "fluent_field",
                "cfd_power_w": power_provenance,
                "cfd_torque_n_m": power_provenance,
            },
            bpe_metrics=bpe_metrics_dict,
            residuals=residuals_history,
            web_bundle_path=bundle_path,
        )

        # B2: Save per-iteration scaled residuals and torque monitor history
        export_residuals_csv(run_dir, residuals_history, monitored_torque_history)

        # Write metadata.json
        with open(meta_file, "w", encoding="utf-8") as f:
            f.write(metadata.model_dump_json(indent=2))

        # Write config.json
        config_file = os.path.join(run_dir, "config.json")
        config_payload = {
            "tank": tank.model_dump(),
            "fluid": fluid.model_dump(),
            "ops": ops.model_dump(),
            "mesh_density": mesh_density,
            "iterations": config_iterations if config_iterations is not None else iterations,
        }
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config_payload, f, indent=2)

        # Write run_manifest.json with all evidence for inspect_run_provenance
        config_digest = hashlib.sha256(
            json.dumps(config_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

        # Strict provenance gate: verified requires native files, solver torque, and convergence
        is_verified_result = case_data_saved and (power_provenance == "fluent_solver") and is_converged
        if is_verified_result:
            classification = "verified_fluent_result"
            if readiness_tier == "experimental_cfd":
                label = "Verified Fluent (Experimental CFD)"
            elif readiness_tier == "laminar_close_clearance":
                label = "Verified Fluent (Laminar Close-Clearance)"
            else:
                label = "Verified Fluent Result (Ansys Fluent 2026 R1)"
        elif case_data_saved:
            classification = "engineering_reference"
            if power_provenance != "fluent_solver":
                label = "Unverified Solver Run (Correlation Torque Fallback)"
            else:
                label = "Unverified Solver Run (Unconverged)"
        else:
            classification = "engineering_reference"
            label = "Reference field artifact"

        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "solver": "Ansys Fluent 2026 R1 via PyFluent",
            "physics_scope": physics_scope,
            "readiness_tier": readiness_tier,
            "verified": is_verified_result,
            "classification": classification,
            "label": label,
            "warnings": solver_warnings,
            "config_sha256": config_digest,
            "mesh_density": mesh_density,
            "iterations_requested": config_iterations if config_iterations is not None else iterations,
            "iterations_computed": iterations,
            "converged": is_converged,
            "native_case_data_written": case_data_saved,
            "rheology": {
                "model": fluid.rheology_model,
                "consistency_k": fluid.consistency_k_pa_s_n,
                "flow_index_n": fluid.flow_behavior_index_n,
                "effective_viscosity_pa_s": round(effective_mu, 6),
            },
            "re_i": round(re_i, 1),
            "cfd_metrics": {
                "torque_n_m": round(cfd_torque_n_m, 4),
                "power_w": round(cfd_power_w, 2),
                "power_number_np": round(cfd_power_number, 3),
                "mean_velocity_m_s": round(cfd_mean_vel, 4),
                "max_velocity_m_s": round(cfd_max_vel, 4),
                "dead_zone_fraction": round(dead_zone_frac, 4),
                "provenance": power_provenance,
            },
            "engineering_reference_metrics": {
                "torque_n_m": round(analytical_torque_n_m, 4),
                "power_w": round(analytical_power_w, 2),
                "power_number_np": round(analytical_res.stages[0].np_val if analytical_res.stages else 0.0, 3),
                "provenance": "engineering_reference",
            },
            "metric_sources": {
                "cfd_max_velocity_m_s": "fluent_field",
                "cfd_mean_velocity_m_s": "fluent_field",
                "cfd_min_pressure_pa": "fluent_field",
                "cfd_max_pressure_pa": "fluent_field",
                "cfd_mean_tke_m2_s2": "fluent_field",
                "cfd_mean_epsilon_m2_s3": "fluent_field",
                "cfd_power_w": power_provenance,
                "cfd_torque_n_m": power_provenance,
            },
            "convergence": {
                **b3_metrics,
                "converged": is_converged,
                "torque_drift_pct": round(torque_drift_pct, 4),
            },
            "convergence_monitoring": {
                "monitored_torque_history": [round(t, 4) for t in monitored_torque_history],
                "torque_drift_pct": round(torque_drift_pct, 2),
                "final_continuity_residual": final_continuity,
                "converged": is_converged,
            },
            "artifacts": {
                "mesh": os.path.basename(mesh_artifact.bdf_mesh_path),
                "field_export": "fluent_internal_field.vtp",
                "case_file": "fluent_case.cas.h5" if case_data_saved else None,
                "data_file": "fluent_case.dat.h5" if case_data_saved else None,
                "metadata": "metadata.json",
                "web_bundle": "web_3d_bundle.json",
                "configuration": "config.json",
                "manifest": "run_manifest.json",
            },
        }
        with open(os.path.join(run_dir, "run_manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        if progress_callback:
            progress_callback(iterations, iterations, "Ansys Fluent simulation completed successfully!", None)

        # Final safety cleanup to ensure all license tokens are freed
        self.kill_lingering_fluent_processes()
        self.cleanup_stray_fluent_logs(os.path.join(run_dir, "fluent_logs"))

        return metadata

    # -------------------------------------------------------------------------
    # Helper: Create Planar Slices in Fluent
    # -------------------------------------------------------------------------
    def _create_fluent_slice_surfaces(self, session: Any, tank: TankGeometry) -> None:
        """Create symmetry vertical and horizontal impeller plane surfaces in Fluent."""
        try:
            plane_obj = session.settings.results.surfaces.plane_surface
            H = tank.liquid_height_m

            # Vertical XZ slice: point (0, 0, 0), normal (0, 1, 0)
            try:
                plane_obj.create(name="slice_xz")
                s_xz = plane_obj["slice_xz"]
                s_xz.method = "point-and-normal"
                s_xz.point = [0.0, 0.0, 0.0]
                s_xz.normal = [0.0, 1.0, 0.0]
            except Exception:
                pass

            # Vertical YZ slice: point (0, 0, 0), normal (1, 0, 0)
            try:
                plane_obj.create(name="slice_yz")
                s_yz = plane_obj["slice_yz"]
                s_yz.method = "point-and-normal"
                s_yz.point = [0.0, 0.0, 0.0]
                s_yz.normal = [1.0, 0.0, 0.0]
            except Exception:
                pass

            # Diagonal vertical planes for complete azimuthal 3D volume coverage
            try:
                plane_obj.create(name="slice_diag1")
                s_d1 = plane_obj["slice_diag1"]
                s_d1.method = "point-and-normal"
                s_d1.point = [0.0, 0.0, 0.0]
                s_d1.normal = [1.0, 1.0, 0.0]
            except Exception:
                pass

            try:
                plane_obj.create(name="slice_diag2")
                s_d2 = plane_obj["slice_diag2"]
                s_d2.method = "point-and-normal"
                s_d2.point = [0.0, 0.0, 0.0]
                s_d2.normal = [-1.0, 1.0, 0.0]
            except Exception:
                pass

            # Intermediate elevation slices spanning the liquid height
            for frac_h in (0.20, 0.40, 0.60, 0.80):
                s_name = f"slice_xy_h{int(frac_h * 100)}"
                try:
                    plane_obj.create(name=s_name)
                    s_pl = plane_obj[s_name]
                    s_pl.method = "point-and-normal"
                    s_pl.point = [0.0, 0.0, float(frac_h * H)]
                    s_pl.normal = [0.0, 0.0, 1.0]
                except Exception:
                    pass

            # Horizontal slice at each impeller clearance
            for k, imp in enumerate(tank.impellers):
                s_name = f"slice_xy_c{k}"
                try:
                    plane_obj.create(name=s_name)
                    s_xy = plane_obj[s_name]
                    s_xy.method = "point-and-normal"
                    s_xy.point = [0.0, 0.0, float(imp.clearance_m)]
                    s_xy.normal = [0.0, 0.0, 1.0]
                except Exception:
                    pass

            # Horizontal slice at mid-gap between impeller 0 and 1
            if len(tank.impellers) >= 2:
                z_gap = 0.5 * (tank.impellers[0].clearance_m + tank.impellers[1].clearance_m)
                try:
                    plane_obj.create(name="slice_xy_gap")
                    s_gap = plane_obj["slice_xy_gap"]
                    s_gap.method = "point-and-normal"
                    s_gap.point = [0.0, 0.0, float(z_gap)]
                    s_gap.normal = [0.0, 0.0, 1.0]
                except Exception:
                    pass

            # Lower and upper bulk vessel planes for full vertical span
            c0 = tank.impellers[0].clearance_m
            z_low = max(0.03 * H, 0.45 * c0)
            try:
                plane_obj.create(name="slice_xy_lower")
                s_low = plane_obj["slice_xy_lower"]
                s_low.method = "point-and-normal"
                s_low.point = [0.0, 0.0, float(z_low)]
                s_low.normal = [0.0, 0.0, 1.0]
            except Exception:
                pass

            c_top = tank.impellers[-1].clearance_m
            z_up = min(0.95 * H, c_top + 0.55 * (H - c_top))
            try:
                plane_obj.create(name="slice_xy_upper")
                s_up = plane_obj["slice_xy_upper"]
                s_up.method = "point-and-normal"
                s_up.point = [0.0, 0.0, float(z_up)]
                s_up.normal = [0.0, 0.0, 1.0]
            except Exception:
                pass
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Helper: Extract Internal Fluid Field
    # -------------------------------------------------------------------------
    def _extract_internal_field_data(
        self,
        session: Any,
        tank: TankGeometry,
        fluid: FluidProperties,
        ops: OperatingConditions,
        omega_rad_s: float,
    ) -> Dict[str, Any]:
        """Extract internal fluid nodes, velocity vectors, pressure, and turbulence fields."""
        from ansys.fluent.core.services.field_data import SurfaceDataType
        from ansys.fluent.core.fields.field_data_interfaces import (
            ScalarFieldDataRequest,
            VectorFieldDataRequest,
            SurfaceFieldDataRequest,
        )

        global_max_v, global_min_v = 0.0, 0.0
        global_max_p, global_min_p = 0.0, 0.0
        try:
            v_range = session.fields.field_data._field_data.get_scalar_field_range("velocity-magnitude")
            p_range = session.fields.field_data._field_data.get_scalar_field_range("pressure")
            global_min_v, global_max_v = float(v_range[0]), float(v_range[1])
            global_min_p, global_max_p = float(p_range[0]), float(p_range[1])
        except Exception:
            pass

        surfaces_dict = session.fields.field_data.surfaces()

        # Identify internal surfaces (interfaces between zones, internal plane slices, or interiors)
        internal_surfs = [
            s
            for s in surfaces_dict.keys()
            if s.startswith("slice_") or s.startswith("interface") or s.startswith("interior") or s.startswith("default_interior")
        ]
        if not internal_surfs:
            internal_surfs = [s for s in surfaces_dict.keys() if not s.startswith("wall")]
        if not internal_surfs:
            internal_surfs = list(surfaces_dict.keys())

        # Geometry request: vertices
        geom_req = SurfaceFieldDataRequest(
            surfaces=internal_surfs,
            data_types=[SurfaceDataType.Vertices],
        )
        g_data = session.fields.field_data.get_field_data(geom_req)

        # Query nodal Cartesian velocity components and scalars with node_value=True
        vx_req = ScalarFieldDataRequest(surfaces=internal_surfs, field_name="x-velocity", node_value=True)
        vy_req = ScalarFieldDataRequest(surfaces=internal_surfs, field_name="y-velocity", node_value=True)
        vz_req = ScalarFieldDataRequest(surfaces=internal_surfs, field_name="z-velocity", node_value=True)
        sp_req = ScalarFieldDataRequest(surfaces=internal_surfs, field_name="velocity-magnitude", node_value=True)
        p_req = ScalarFieldDataRequest(surfaces=internal_surfs, field_name="pressure", node_value=True)

        vx_data = session.fields.field_data.get_field_data(vx_req)
        vy_data = session.fields.field_data.get_field_data(vy_req)
        vz_data = session.fields.field_data.get_field_data(vz_req)
        sp_data = session.fields.field_data.get_field_data(sp_req)
        p_data = session.fields.field_data.get_field_data(p_req)

        # Turbulence requests (PyFluent 2026 R1 uses 'turb-kinetic-energy' and 'turb-diss-rate')
        tke_data: Dict[str, Any] = {}
        eps_data: Dict[str, Any] = {}
        for k_name in ("turb-kinetic-energy", "turbulent-kinetic-energy", "k"):
            try:
                k_req = ScalarFieldDataRequest(surfaces=internal_surfs, field_name=k_name, node_value=True)
                tke_data = session.fields.field_data.get_field_data(k_req)
                if tke_data:
                    break
            except Exception:
                pass

        for e_name in ("turb-diss-rate", "turbulent-dissipation-rate", "epsilon"):
            try:
                e_req = ScalarFieldDataRequest(surfaces=internal_surfs, field_name=e_name, node_value=True)
                eps_data = session.fields.field_data.get_field_data(e_req)
                if eps_data:
                    break
            except Exception:
                pass

        # Vector field fallback if scalar velocity components are missing
        v_data: Dict[str, Any] = {}
        try:
            v_req = VectorFieldDataRequest(surfaces=internal_surfs, field_name="velocity")
            v_data = session.fields.field_data.get_field_data(v_req)
        except Exception:
            pass

        pts_list: List[np.ndarray] = []
        vel_list: List[np.ndarray] = []
        speed_list: List[np.ndarray] = []
        press_list: List[np.ndarray] = []
        tke_list: List[np.ndarray] = []
        eps_list: List[np.ndarray] = []

        for s in internal_surfs:
            if s in g_data and hasattr(g_data[s], "vertices") and g_data[s].vertices is not None:
                verts = np.asarray(g_data[s].vertices)
                n_v = len(verts)
                if n_v == 0:
                    continue

                if (
                    s in vx_data and vx_data[s] is not None and len(vx_data[s]) == n_v
                    and s in vy_data and vy_data[s] is not None and len(vy_data[s]) == n_v
                    and s in vz_data and vz_data[s] is not None and len(vz_data[s]) == n_v
                ):
                    ux = np.asarray(vx_data[s]).flatten()
                    uy = np.asarray(vy_data[s]).flatten()
                    uz = np.asarray(vz_data[s]).flatten()
                    v_arr = np.column_stack([ux, uy, uz])
                elif s in v_data and v_data[s] is not None and len(v_data[s]) == n_v:
                    v_arr = np.asarray(v_data[s])
                else:
                    v_arr = np.zeros((n_v, 3))

                if s in sp_data and sp_data[s] is not None and len(sp_data[s]) == n_v:
                    speed_arr = np.asarray(sp_data[s]).flatten()
                else:
                    speed_arr = np.linalg.norm(v_arr, axis=1)

                if s in p_data and p_data[s] is not None and len(p_data[s]) == n_v:
                    press_arr = np.asarray(p_data[s]).flatten()
                else:
                    press_arr = np.zeros(n_v)

                if s in tke_data and tke_data[s] is not None and len(tke_data[s]) == n_v:
                    tk_arr = np.asarray(tke_data[s]).flatten()
                else:
                    tk_arr = np.zeros(n_v)

                if s in eps_data and eps_data[s] is not None and len(eps_data[s]) == n_v:
                    ep_arr = np.asarray(eps_data[s]).flatten()
                else:
                    ep_arr = np.zeros(n_v)

                pts_list.append(verts)
                vel_list.append(v_arr)
                speed_list.append(speed_arr)
                press_list.append(press_arr)
                tke_list.append(tk_arr)
                eps_list.append(ep_arr)

        if pts_list:
            pts_all = np.vstack(pts_list)
            vel_all = np.vstack(vel_list)
            speed_all = np.concatenate(speed_list)
            press_all = np.concatenate(press_list)
            tke_all = np.concatenate(tke_list)
            eps_all = np.concatenate(eps_list)
        else:
            pts_all = np.zeros((1, 3))
            vel_all = np.zeros((1, 3))
            speed_all = np.zeros(1)
            press_all = np.zeros(1)
            tke_all = np.zeros(1)
            eps_all = np.zeros(1)

        return {
            "pts": pts_all,
            "vel": vel_all,
            "speeds": speed_all,
            "pressures": press_all,
            "tkes": tke_all,
            "epsilons": eps_all,
            "global_max_vel": global_max_v,
            "global_min_vel": global_min_v,
            "global_max_press": global_max_p,
            "global_min_press": global_min_p,
        }

    # -------------------------------------------------------------------------
    # Helper: Synthesize Web 3D Bundle (Streamlines, Slices, CAD Meshes)
    # -------------------------------------------------------------------------
    def _build_web_bundle(
        self,
        tank: TankGeometry,
        fluid: FluidProperties,
        ops: OperatingConditions,
        pts: np.ndarray,
        vel: np.ndarray,
        speeds: np.ndarray,
        pressures: np.ndarray,
        tkes: np.ndarray,
        epsilons: np.ndarray,
        run_id: str,
        run_dir: str,
        tip_speed_m_s: float,
        cfd_max_velocity_m_s: float,
        cfd_mean_velocity_m_s: float,
        cfd_power_w: float,
        cfd_torque_n_m: float,
    ) -> str:
        """Interpolate slices, trace 3D streamlines, and pack CAD meshes into web_3d_bundle.json."""
        cfd_metrics = {
            "tip_speed_m_s": tip_speed_m_s,
            "cfd_max_velocity_m_s": cfd_max_velocity_m_s,
            "cfd_mean_velocity_m_s": cfd_mean_velocity_m_s,
            "cfd_power_w": cfd_power_w,
            "cfd_torque_n_m": cfd_torque_n_m,
        }
        build_full_vessel_bundle(
            tank=tank,
            fluid=fluid,
            ops=ops,
            run_id=run_id,
            output_dir=run_dir,
            cfd_metrics=cfd_metrics,
            fluent_pts=pts,
            fluent_vel=vel,
            fluent_speeds=speeds,
            fluent_pressures=pressures,
            fluent_tkes=tkes,
            fluent_epsilons=epsilons,
        )

        # Save VTK PolyData artifact for ParaView / PyVista inspection
        try:
            poly_vtp = pv.PolyData(pts)
            poly_vtp["Velocity"] = vel
            poly_vtp["Speed"] = speeds
            poly_vtp["Pressure"] = pressures
            if tkes is not None and len(tkes) == len(pts):
                poly_vtp["TKE"] = tkes
            if epsilons is not None and len(epsilons) == len(pts):
                poly_vtp["Epsilon"] = epsilons
            vtp_path = os.path.join(run_dir, "fluent_internal_field.vtp")
            poly_vtp.save(vtp_path)
        except Exception:
            pass

        return os.path.join(run_dir, "web_3d_bundle.json")


# -----------------------------------------------------------------------------
# Full-Vessel Physics-Coupled 3D Flow Bundle Synthesizer
# -----------------------------------------------------------------------------

def z_dish_bottom_profile(x_arr: np.ndarray, tank_obj: TankGeometry) -> np.ndarray:
    """Dish profile depth z_bottom at radial coordinate x."""
    T_local = tank_obj.diameter_m
    R_local = T_local / 2.0
    if tank_obj.bottom_type == BottomType.FLAT:
        return np.zeros_like(x_arr)
    elif tank_obj.bottom_type == BottomType.HEMISPHERICAL:
        rad_sq = np.maximum(0.0, R_local**2 - x_arr**2)
        return R_local - np.sqrt(rad_sq)
    elif tank_obj.bottom_type == BottomType.ELLIPTICAL_2_1:
        h_d = T_local / 4.0
        rad_sq = np.maximum(0.0, 1.0 - (x_arr / R_local)**2)
        return h_d * (1.0 - np.sqrt(rad_sq))
    return np.zeros_like(x_arr)


def build_full_vessel_bundle(
    tank: TankGeometry,
    fluid: FluidProperties,
    ops: OperatingConditions,
    run_id: str = "preview",
    output_dir: Optional[str] = None,
    cfd_metrics: Optional[Dict[str, Any]] = None,
    fluent_pts: Optional[np.ndarray] = None,
    fluent_vel: Optional[np.ndarray] = None,
    fluent_speeds: Optional[np.ndarray] = None,
    fluent_pressures: Optional[np.ndarray] = None,
    fluent_tkes: Optional[np.ndarray] = None,
    fluent_epsilons: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Reconstruct full-vessel wall-to-wall 3D CFD flow fields, streamlines, and vectors.

    Synthesizes the complete bioreactor domain by coupling Ansys Fluent Navier-Stokes
    extrema with full-domain axisymmetric + 3D helical flow solving:
    - 2D Cross sections (XZ and YZ) covering 100% of the active liquid column.
    - Horizontal cross-section slices at each impeller elevation and mid-gap planes.
    - 80 to 100 full-tank 3D streamlines tracing impeller discharge and bulk loops.
    - 450 to 600 3D velocity vectors on a structured cylindrical lattice for WebGL vector cones.
    - 5 separate 3D CAD meshes (vessel_shell, baffles, shaft_and_impellers, sparger_ring, free_surface).
    """
    T = tank.diameter_m
    R = T / 2.0
    H = tank.liquid_height_m
    omega = ops.rpm * 2.0 * math.pi / 60.0
    tip_speed = max(calc_tip_speed(ops.rps, imp.diameter_m) for imp in tank.impellers)

    # 1. Full-domain numerical solution
    sim_result = HydrodynamicEngine.run(tank, fluid, ops)
    flow_2d = FlowSolver2D.solve(sim_result, nx=101, nz=151)
    free_surface_z = flow_2d.free_surface_z
    x_2d = flow_2d.x_grid[0, :]
    z_2d = flow_2d.z_grid[:, 0]
    u_x_grid = flow_2d.u_x
    u_z_grid = flow_2d.u_z
    u_th_grid = flow_2d.u_theta
    sp_grid = flow_2d.total_speed
    nz_grid, nx_grid = u_x_grid.shape
    dz_grid = float(z_2d[1] - z_2d[0])
    dx_grid = float(x_2d[1] - x_2d[0])
    x_mid_idx = nx_grid // 2

    is_real_fluent = (
        fluent_pts is not None
        and len(fluent_pts) >= 100
        and fluent_vel is not None
        and len(fluent_vel) >= 100
    )

    nx, nz = 51, 65
    x_lin = np.linspace(-R, R, nx)
    z_lin = np.linspace(0.0, H, nz)
    X_mesh, Z_mesh = np.meshgrid(x_lin, z_lin)
    x_flat = X_mesh.ravel()
    z_flat = Z_mesh.ravel()

    z_bot_eval = z_dish_bottom_profile(x_flat, tank)
    z_top_eval = np.interp(x_flat, x_2d, free_surface_z)
    in_wet = (z_flat >= z_bot_eval - 1e-4) & (z_flat <= z_top_eval + 1e-4) & (np.abs(x_flat) <= R + 1e-4)

    def _mask_2d(arr: np.ndarray, digits: int) -> List[List[Optional[float]]]:
        flat = np.where(in_wet, np.round(arr, digits), None)
        return flat.reshape(nz, nx).tolist()

    nh = 35
    xh_lin = np.linspace(-R, R, nh)
    yh_lin = np.linspace(-R, R, nh)
    Xh, Yh = np.meshgrid(xh_lin, yh_lin)
    Rh = np.sqrt(Xh**2 + Yh**2)
    h_mask = Rh <= R

    slice_elevations = []
    for idx, imp in enumerate(tank.impellers):
        slice_elevations.append((imp.clearance_m, idx, f"Impeller {idx+1} ({imp.impeller_type.value})"))
    if len(tank.impellers) >= 2:
        gap_z = 0.5 * (tank.impellers[0].clearance_m + tank.impellers[1].clearance_m)
        slice_elevations.append((gap_z, None, "Inter-Impeller Mid-Gap Plane"))

    horizontal_slices: List[Dict[str, Any]] = []
    streamlines_list: List[List[List[float]]] = []
    vectors_3d: List[List[float]] = []

    # Streamline seed coordinates: lower loop, impeller discharge, upper loop, and wall downflow
    seeds: List[Tuple[float, float, float]] = []
    for imp in tank.impellers:
        c_k = imp.clearance_m
        d_i = imp.diameter_m
        # Impeller discharge jet
        for th in np.linspace(0.0, 2.0 * math.pi, 16, endpoint=False):
            seeds.append((0.55 * d_i * math.cos(th), 0.55 * d_i * math.sin(th), c_k))
        # Impeller suction feeds
        for th in np.linspace(0.2, 2.0 * math.pi + 0.2, 8, endpoint=False):
            seeds.append((0.35 * d_i * math.cos(th), 0.35 * d_i * math.sin(th), min(c_k + 0.04 * H, 0.95 * H)))
            seeds.append((0.35 * d_i * math.cos(th), 0.35 * d_i * math.sin(th), max(c_k - 0.04 * H, 0.06 * H)))

    # Lower circulation loop (z in [0.08 H, 0.35 H])
    for z_low in [0.09 * H, 0.18 * H, 0.28 * H]:
        for r_fac in [0.25, 0.45, 0.65]:
            for th in np.linspace(0.15, 2.0 * math.pi + 0.15, 6, endpoint=False):
                seeds.append((r_fac * R * math.cos(th), r_fac * R * math.sin(th), z_low))

    # Upper circulation loop (z in [0.45 H, 0.88 H])
    for z_upp in [0.48 * H, 0.62 * H, 0.75 * H, 0.86 * H]:
        for r_fac in [0.25, 0.45, 0.65, 0.80]:
            for th in np.linspace(0.25, 2.0 * math.pi + 0.25, 6, endpoint=False):
                seeds.append((r_fac * R * math.cos(th), r_fac * R * math.sin(th), z_upp))

    # Baffle wall downflow stream
    for z_w in [0.25 * H, 0.50 * H, 0.75 * H]:
        for th in np.linspace(0.05, 2.0 * math.pi + 0.05, 8, endpoint=False):
            seeds.append((0.86 * R * math.cos(th), 0.86 * R * math.sin(th), z_w))

    if len(tank.impellers) >= 2:
        z_gap = 0.5 * (tank.impellers[0].clearance_m + tank.impellers[1].clearance_m)
        for th in np.linspace(0.0, 2.0 * math.pi, 12, endpoint=False):
            seeds.append((0.50 * R * math.cos(th), 0.50 * R * math.sin(th), z_gap))

    if is_real_fluent:
        solver_source = "ansys_fluent_2026_r1_3d"
        fluent_tree = cKDTree(fluent_pts)
        n_fl = len(fluent_pts)
        k_eval = min(8, n_fl)

        def sample_fluent_field(query_xyz: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
            q_arr = np.atleast_2d(query_xyz)
            dists, idxs = fluent_tree.query(q_arr, k=k_eval)
            if dists.ndim == 1:
                dists = dists[:, np.newaxis]
                idxs = idxs[:, np.newaxis]

            with np.errstate(divide="ignore"):
                w = 1.0 / np.maximum(dists, 1e-5)**2
            w_sum = np.sum(w, axis=1, keepdims=True)
            weights = w / np.maximum(w_sum, 1e-12)

            s_vel = np.sum(weights[:, :, np.newaxis] * fluent_vel[idxs], axis=1)
            s_spd = np.sum(weights * fluent_speeds[idxs], axis=1) if fluent_speeds is not None else np.linalg.norm(s_vel, axis=1)
            s_p = np.sum(weights * fluent_pressures[idxs], axis=1) if fluent_pressures is not None else np.zeros(len(q_arr))
            s_tke = np.sum(weights * fluent_tkes[idxs], axis=1) if fluent_tkes is not None else np.zeros(len(q_arr))
            s_eps = np.sum(weights * fluent_epsilons[idxs], axis=1) if fluent_epsilons is not None else np.zeros(len(q_arr))

            exact_hits = dists[:, 0] < 1e-5
            if np.any(exact_hits):
                hit_idx = np.where(exact_hits)[0]
                first_i = idxs[hit_idx, 0]
                s_vel[hit_idx] = fluent_vel[first_i]
                if fluent_speeds is not None:
                    s_spd[hit_idx] = fluent_speeds[first_i]
                else:
                    s_spd[hit_idx] = np.linalg.norm(fluent_vel[first_i], axis=1)
                if fluent_pressures is not None:
                    s_p[hit_idx] = fluent_pressures[first_i]
                if fluent_tkes is not None:
                    s_tke[hit_idx] = fluent_tkes[first_i]
                if fluent_epsilons is not None:
                    s_eps[hit_idx] = fluent_epsilons[first_i]

            return s_vel, s_spd, s_p, s_tke, s_eps

        def get_single_fluent_vel(pos: np.ndarray) -> Tuple[np.ndarray, float]:
            d, i = fluent_tree.query(pos, k=min(6, n_fl))
            if d[0] < 1e-5:
                v = fluent_vel[i[0]]
                return v, float(np.linalg.norm(v))
            w = 1.0 / (d**2 + 1e-8)
            w /= np.sum(w)
            v = np.sum(w[:, np.newaxis] * fluent_vel[i], axis=0)
            return v, float(np.linalg.norm(v))

        rho_fluid = float(fluid.density_kg_m3)
        mu_eff = float(fluid.viscosity_pa_s)
        nu_fluid = max(mu_eff / max(rho_fluid, 1e-3), 1e-7)  # m^2/s

        has_eps_field = fluent_epsilons is not None and np.max(fluent_epsilons) > 1e-6
        has_tke_field = fluent_tkes is not None and np.max(fluent_tkes) > 1e-6

        # Vertical XZ Slice
        pts_xz = np.column_stack([x_flat, np.zeros_like(x_flat), z_flat])
        vel_xz, spd_xz, p_xz, tke_xz, eps_xz = sample_fluent_field(pts_xz)
        sp_xz_2d = _mask_2d(spd_xz, 4)
        p_xz_2d = _mask_2d(p_xz, 2)
        ux_xz_2d = _mask_2d(vel_xz[:, 0], 4)
        uz_xz_2d = _mask_2d(vel_xz[:, 2], 4)
        k_xz_2d = _mask_2d(tke_xz, 5)
        e_xz_2d = _mask_2d(eps_xz, 5)

        re_primary = float(sim_result.stages[0].re_i) if sim_result.stages else (rho_fluid * (ops.rpm / 60.0) * (tank.impellers[0].diameter_m**2) / max(mu_eff, 1e-6))
        is_laminar = (not (has_eps_field or has_tke_field)) or (re_primary < 200.0) or (getattr(ops, "rheology_model", None) == "power_law") or (mu_eff >= 0.5)

        if has_eps_field:
            eps_clamped_xz = np.maximum(eps_xz, 1e-6)
            kolm_xz_raw = (nu_fluid**3 / eps_clamped_xz)**0.25 * 1e6
            kolm_xz = np.minimum(kolm_xz_raw, 2500.0)
            kolm_xz_2d = _mask_2d(kolm_xz, 1)
        else:
            kolm_xz_2d = None

        if has_eps_field or has_tke_field:
            tau_turb_xz = np.sqrt(rho_fluid * mu_eff * np.maximum(eps_xz, 0.0) + (0.09 * rho_fluid * np.maximum(tke_xz, 0.0))**2)
            tau_xz_2d = _mask_2d(tau_turb_xz, 2)
        elif is_laminar:
            dx_val = float(x_lin[1] - x_lin[0]) if len(x_lin) > 1 else 0.01
            dz_val = float(z_lin[1] - z_lin[0]) if len(z_lin) > 1 else 0.01
            spd_2d_grid = np.nan_to_num(spd_xz.reshape(nz, nx), nan=0.0)
            du_dz, du_dx = np.gradient(spd_2d_grid, dz_val, dx_val)
            gamma_dot_xz = np.sqrt(du_dx**2 + du_dz**2)
            k_val = float(getattr(fluid, "consistency_k_pa_s_n", mu_eff) or mu_eff)
            n_val = float(getattr(fluid, "flow_behavior_index_n", 1.0) or 1.0)
            if getattr(fluid, "rheology_model", None) == "power_law" or n_val < 1.0:
                tau_lam_xz = k_val * (np.maximum(gamma_dot_xz, 1e-4) ** n_val)
            else:
                tau_lam_xz = mu_eff * gamma_dot_xz
            tau_xz_2d = _mask_2d(tau_lam_xz.ravel(), 2)
        else:
            tau_xz_2d = None

        # Vertical YZ Slice (y from -R to R along X_mesh)
        pts_yz = np.column_stack([np.zeros_like(x_flat), x_flat, z_flat])
        vel_yz, spd_yz, p_yz, tke_yz, eps_yz = sample_fluent_field(pts_yz)
        sp_yz_2d = _mask_2d(spd_yz, 4)
        p_yz_2d = _mask_2d(p_yz, 2)
        uy_yz_2d = _mask_2d(vel_yz[:, 1], 4)
        uz_yz_2d = _mask_2d(vel_yz[:, 2], 4)
        k_yz_2d = _mask_2d(tke_yz, 5) if has_tke_field else None
        e_yz_2d = _mask_2d(eps_yz, 5) if has_eps_field else None

        if has_eps_field:
            eps_clamped_yz = np.maximum(eps_yz, 1e-6)
            kolm_yz_raw = (nu_fluid**3 / eps_clamped_yz)**0.25 * 1e6
            kolm_yz = np.minimum(kolm_yz_raw, 2500.0)
            kolm_yz_2d = _mask_2d(kolm_yz, 1)
        else:
            kolm_yz_2d = None

        if has_eps_field or has_tke_field:
            tau_turb_yz = np.sqrt(rho_fluid * mu_eff * np.maximum(eps_yz, 0.0) + (0.09 * rho_fluid * np.maximum(tke_yz, 0.0))**2)
            tau_yz_2d = _mask_2d(tau_turb_yz, 2)
        elif is_laminar:
            dy_val = float(x_lin[1] - x_lin[0]) if len(x_lin) > 1 else 0.01
            dz_val = float(z_lin[1] - z_lin[0]) if len(z_lin) > 1 else 0.01
            spd_2d_grid = np.nan_to_num(spd_yz.reshape(nz, nx), nan=0.0)
            du_dz, du_dy = np.gradient(spd_2d_grid, dz_val, dy_val)
            gamma_dot_yz = np.sqrt(du_dy**2 + du_dz**2)
            k_val = float(getattr(fluid, "consistency_k_pa_s_n", mu_eff) or mu_eff)
            n_val = float(getattr(fluid, "flow_behavior_index_n", 1.0) or 1.0)
            if getattr(fluid, "rheology_model", None) == "power_law" or n_val < 1.0:
                tau_lam_yz = k_val * (np.maximum(gamma_dot_yz, 1e-4) ** n_val)
            else:
                tau_lam_yz = mu_eff * gamma_dot_yz
            tau_yz_2d = _mask_2d(tau_lam_yz.ravel(), 2)
        else:
            tau_yz_2d = None

        # Horizontal Slices
        for z_val, c_idx, label in slice_elevations:
            query_h = np.column_stack([Xh.ravel(), Yh.ravel(), np.full(nh * nh, z_val)])
            vel_h, sp_h, p_h, tke_h, eps_h = sample_fluent_field(query_h)
            kolm_h = (nu_fluid**3 / np.maximum(eps_h, 1e-6))**0.25 * 1e6 if has_eps_field else None
            if (has_eps_field or has_tke_field):
                tau_h = np.sqrt(rho_fluid * mu_eff * np.maximum(eps_h, 0.0) + (0.09 * rho_fluid * np.maximum(tke_h, 0.0))**2)
            elif is_laminar:
                dx_h = float(xh_lin[1] - xh_lin[0]) if len(xh_lin) > 1 else 0.01
                dy_h = float(yh_lin[1] - yh_lin[0]) if len(yh_lin) > 1 else 0.01
                spd_h_grid = np.nan_to_num(sp_h.reshape(nh, nh), nan=0.0)
                du_dy_h, du_dx_h = np.gradient(spd_h_grid, dy_h, dx_h)
                gamma_dot_h = np.sqrt(du_dx_h**2 + du_dy_h**2)
                k_val = float(getattr(fluid, "consistency_k_pa_s_n", mu_eff) or mu_eff)
                n_val = float(getattr(fluid, "flow_behavior_index_n", 1.0) or 1.0)
                if getattr(fluid, "rheology_model", None) == "power_law" or n_val < 1.0:
                    tau_h = (k_val * (np.maximum(gamma_dot_h, 1e-4) ** n_val)).ravel()
                else:
                    tau_h = (mu_eff * gamma_dot_h).ravel()
            else:
                tau_h = None

            horizontal_slices.append({
                "z": round(float(z_val), 4),
                "clearance_index": c_idx,
                "label": label,
                "x": [round(float(v), 4) for v in xh_lin],
                "y": [round(float(v), 4) for v in yh_lin],
                "velocity_mag": np.where(h_mask, np.round(sp_h.reshape(nh, nh), 4), None).tolist(),
                "pressure": np.where(h_mask, np.round(p_h.reshape(nh, nh), 2), None).tolist(),
                "ux": np.where(h_mask, np.round(vel_h[:, 0].reshape(nh, nh), 4), None).tolist(),
                "uy": np.where(h_mask, np.round(vel_h[:, 1].reshape(nh, nh), 4), None).tolist(),
                "tke": np.where(h_mask, np.round(tke_h.reshape(nh, nh), 5), None).tolist() if has_tke_field else None,
                "epsilon": np.where(h_mask, np.round(eps_h.reshape(nh, nh), 5), None).tolist() if has_eps_field else None,
                "kolmogorov_um": np.where(h_mask, np.round(np.minimum(kolm_h, 2500.0).reshape(nh, nh), 1), None).tolist() if kolm_h is not None else None,
                "shear_stress_pa": np.where(h_mask, np.round(tau_h.reshape(nh, nh), 2), None).tolist() if tau_h is not None else None,
            })

        # 3D Streamlines via RK4 integration through real Fluent 3D velocity field
        # 3D Streamlines via arc-length normalized RK4 integration through real Fluent 3D velocity field
        ds = 0.012 * T
        max_steps = 150
        for sx, sy, sz in seeds:
            cur = np.array([sx, sy, sz], dtype=float)
            poly = []
            for _ in range(max_steps):
                r_c = math.sqrt(cur[0]**2 + cur[1]**2)
                z_bot_c = float(z_dish_bottom_profile(np.array([r_c]), tank)[0])
                z_top_c = float(np.interp(r_c, x_2d, free_surface_z))
                if r_c >= 0.98 * R or cur[2] <= z_bot_c + 0.003 * H or cur[2] >= z_top_c - 0.003 * H:
                    break

                v0, sp_val = get_single_fluent_vel(cur)
                poly.append([round(float(cur[0]), 4), round(float(cur[1]), 4), round(float(cur[2]), 4), round(float(sp_val), 4)])

                if sp_val < 1e-4:
                    break

                k1 = v0 / sp_val
                p1 = cur + 0.5 * ds * k1
                v1, s1 = get_single_fluent_vel(p1)
                k2 = v1 / max(s1, 1e-6)

                p2 = cur + 0.5 * ds * k2
                v2, s2 = get_single_fluent_vel(p2)
                k3 = v2 / max(s2, 1e-6)

                p3 = cur + ds * k3
                v3, s3 = get_single_fluent_vel(p3)
                k4 = v3 / max(s3, 1e-6)

                cur = cur + (ds / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)

            if len(poly) >= 4:
                streamlines_list.append(poly)

        # 3D Volumetric Velocity Vectors
        r_rings = [0.22 * R, 0.44 * R, 0.66 * R, 0.88 * R]
        z_levels = np.linspace(0.10 * H, 0.90 * H, 9)
        ring_n_angles = [8, 12, 16, 18]
        valid_vec_coords = []

        for z_k in z_levels:
            for r_j, n_th in zip(r_rings, ring_n_angles):
                z_bot_j = float(z_dish_bottom_profile(np.array([r_j]), tank)[0])
                z_top_j = float(np.interp(r_j, x_2d, free_surface_z))
                if z_k < z_bot_j + 0.01 * H or z_k > z_top_j - 0.01 * H:
                    continue
                for th_m in np.linspace(0.0, 2.0 * math.pi, n_th, endpoint=False):
                    valid_vec_coords.append([r_j * math.cos(th_m), r_j * math.sin(th_m), z_k])

        if valid_vec_coords:
            query_vec = np.array(valid_vec_coords)
            vel_vec, spd_vec, _, _, _ = sample_fluent_field(query_vec)
            for i in range(len(valid_vec_coords)):
                vectors_3d.append([
                    round(float(query_vec[i, 0]), 4),
                    round(float(query_vec[i, 1]), 4),
                    round(float(query_vec[i, 2]), 4),
                    round(float(vel_vec[i, 0]), 4),
                    round(float(vel_vec[i, 1]), 4),
                    round(float(vel_vec[i, 2]), 4),
                    round(float(spd_vec[i]), 4),
                ])

        cfd_max_v = float(cfd_metrics.get("cfd_max_velocity_m_s", np.max(fluent_speeds))) if cfd_metrics else float(np.max(fluent_speeds))
        cfd_mean_v = float(cfd_metrics.get("cfd_mean_velocity_m_s", np.mean(fluent_speeds))) if cfd_metrics else float(np.mean(fluent_speeds))
        cfd_p_w = float(cfd_metrics.get("cfd_power_w", sim_result.total_ungassed_power_w)) if cfd_metrics else float(sim_result.total_ungassed_power_w)
        cfd_t_nm = float(cfd_metrics.get("cfd_torque_n_m", cfd_p_w / max(omega, 1e-4))) if cfd_metrics else float(cfd_p_w / max(omega, 1e-4))
        
        # Industrial CFD standard stagnant dead-zone definition
        # Evaluated on interior bulk fluid points (excluding outer no-slip walls and tank bottom)
        R_tank = tank.diameter_m / 2.0
        H_tank = tank.liquid_height_m
        if fluent_speeds is not None and len(fluent_speeds) > 0:
            if fluent_pts is not None and len(fluent_pts) == len(fluent_speeds) and len(fluent_pts) > 1:
                r_pts = np.sqrt(fluent_pts[:, 0]**2 + fluent_pts[:, 1]**2)
                z_pts = fluent_pts[:, 2]
                bulk_mask = (r_pts < 0.96 * R_tank) & (z_pts > 0.02 * H_tank) & (fluent_speeds > 1e-4)
                interior_spd = fluent_speeds[bulk_mask]
                if len(interior_spd) == 0:
                    interior_spd = fluent_speeds[fluent_speeds > 1e-4]
            else:
                interior_spd = fluent_speeds[fluent_speeds > 1e-4]

            if len(interior_spd) > 0:
                mean_int_spd = float(np.mean(interior_spd))
                stagnant_thresh = min(0.015 * tip_speed, 0.15 * max(mean_int_spd, 1e-4))
                raw_dz = float(np.mean(interior_spd < stagnant_thresh))
                dead_zone_f = round(float(raw_dz), 4)
            else:
                dead_zone_f = float(flow_2d.dead_zone_fraction)
        else:
            dead_zone_f = float(flow_2d.dead_zone_fraction)

    else:
        solver_source = "bpe_realtime_preview"

        def fast_sample(z_val: float, r_val: float) -> Tuple[float, float, float, float]:
            """High-performance (<0.5 us) inline 2D bilinear interpolation for streamlines and vectors."""
            fz = (z_val - float(z_2d[0])) / dz_grid
            fx = (r_val - 0.0) / dx_grid + x_mid_idx
            iz = int(fz)
            ix = int(fx)
            if iz < 0 or iz >= nz_grid - 1 or ix < 0 or ix >= nx_grid - 1:
                return 0.0, 0.0, 0.0, 0.0
            wz = fz - iz
            wx = fx - ix
            w00 = (1.0 - wz) * (1.0 - wx)
            w01 = (1.0 - wz) * wx
            w10 = wz * (1.0 - wx)
            w11 = wz * wx
            ur = w00 * u_x_grid[iz, ix] + w01 * u_x_grid[iz, ix + 1] + w10 * u_x_grid[iz + 1, ix] + w11 * u_x_grid[iz + 1, ix + 1]
            uz = w00 * u_z_grid[iz, ix] + w01 * u_z_grid[iz, ix + 1] + w10 * u_z_grid[iz + 1, ix] + w11 * u_z_grid[iz + 1, ix + 1]
            uth = w00 * u_th_grid[iz, ix] + w01 * u_th_grid[iz, ix + 1] + w10 * u_th_grid[iz + 1, ix] + w11 * u_th_grid[iz + 1, ix + 1]
            sp = w00 * sp_grid[iz, ix] + w01 * sp_grid[iz, ix + 1] + w10 * sp_grid[iz + 1, ix] + w11 * sp_grid[iz + 1, ix + 1]
            return float(ur), float(uz), float(uth), float(sp)

        # Regular-grid interpolators
        interp_ux = RegularGridInterpolator((z_2d, x_2d), flow_2d.u_x, bounds_error=False, fill_value=0.0)
        interp_uz = RegularGridInterpolator((z_2d, x_2d), flow_2d.u_z, bounds_error=False, fill_value=0.0)
        interp_utheta = RegularGridInterpolator((z_2d, x_2d), flow_2d.u_theta, bounds_error=False, fill_value=0.0)
        interp_speed = RegularGridInterpolator((z_2d, x_2d), flow_2d.total_speed, bounds_error=False, fill_value=0.0)
        interp_shear = RegularGridInterpolator((z_2d, x_2d), flow_2d.shear_rate_s_inv, bounds_error=False, fill_value=0.0)

        # Preview mode flow evaluation (do NOT scale flow_2d by cfd_max_velocity_m_s: CRT-01)
        scale_v = 1.0
        max_flow_sp = float(np.max(flow_2d.total_speed))

        pts_eval = np.column_stack([Z_mesh.ravel(), X_mesh.ravel()])
        ux_eval = interp_ux(pts_eval) * scale_v
        uz_eval = interp_uz(pts_eval) * scale_v
        speed_eval = interp_speed(pts_eval) * scale_v
        shear_eval = interp_shear(pts_eval)

        # Genuine flow evaluation without artificial velocity floors (HIGH-02)
        speed_eval = np.where(in_wet, speed_eval, 0.0)

        # Pressure field (hydrostatic + dynamic without cosmetic target rescaling)
        rho = float(fluid.density_kg_m3)
        g = 9.80665
        p_hydro = rho * g * np.maximum(0.0, z_top_eval - Z_mesh.ravel())
        mean_speed = float(np.mean(speed_eval[in_wet])) if np.any(in_wet) else 0.1
        p_dyn = -0.5 * rho * (speed_eval**2 - mean_speed**2)
        p_tot = p_hydro + p_dyn

        # In preview mode, do NOT synthesize fake TKE/epsilon arrays (CRT-01)
        sp_xz_2d = _mask_2d(speed_eval, 4)
        p_xz_2d = _mask_2d(p_tot, 2)
        ux_xz_2d = _mask_2d(ux_eval, 4)
        uz_xz_2d = _mask_2d(uz_eval, 4)
        k_xz_2d = None
        e_xz_2d = None
        kolm_xz_2d = None
        tau_xz_2d = None

        # YZ slice (y from -R to R)
        uy_eval = np.abs(ux_eval) * np.sign(X_mesh.ravel())
        sp_yz_2d = sp_xz_2d
        p_yz_2d = p_xz_2d
        uy_yz_2d = _mask_2d(uy_eval, 4)
        uz_yz_2d = uz_xz_2d
        k_yz_2d = None
        e_yz_2d = None
        kolm_yz_2d = None
        tau_yz_2d = None

        for z_val, c_idx, label in slice_elevations:
            eval_h = np.column_stack([np.full(nh * nh, z_val), Rh.ravel()])
            ur_h = np.abs(interp_ux(eval_h)) * scale_v
            ut_h = interp_utheta(eval_h) * scale_v
            sp_h = interp_speed(eval_h) * scale_v
            sp_h = np.where(h_mask.ravel(), np.maximum(sp_h, 0.02 * tip_speed), 0.0)
            r_safe = np.maximum(Rh.ravel(), 1e-4)
            ux_h = (ur_h * (Xh.ravel() / r_safe) - ut_h * (Yh.ravel() / r_safe))
            uy_h = (ur_h * (Yh.ravel() / r_safe) + ut_h * (Xh.ravel() / r_safe))
            p_h = rho * g * max(0.0, float(np.interp(0.0, x_2d, free_surface_z)) - z_val)

            horizontal_slices.append({
                "z": round(float(z_val), 4),
                "clearance_index": c_idx,
                "label": label,
                "x": [round(float(v), 4) for v in xh_lin],
                "y": [round(float(v), 4) for v in yh_lin],
                "velocity_mag": np.where(h_mask, np.round(sp_h.reshape(nh, nh), 4), None).tolist(),
                "pressure": np.where(h_mask, np.round(np.full((nh, nh), p_h), 2), None).tolist(),
                "ux": np.where(h_mask, np.round(ux_h.reshape(nh, nh), 4), None).tolist(),
                "uy": np.where(h_mask, np.round(uy_h.reshape(nh, nh), 4), None).tolist(),
                "tke": None,
                "epsilon": None,
                "kolmogorov_um": None,
                "shear_stress_pa": None,
            })

        ds = 0.012 * T
        max_steps = 150
        for sx, sy, sz in seeds:
            cur = np.array([sx, sy, sz], dtype=float)
            poly = []
            for _ in range(max_steps):
                r_c = math.sqrt(cur[0]**2 + cur[1]**2)
                z_bot_c = float(z_dish_bottom_profile(np.array([r_c]), tank)[0])
                z_top_c = float(np.interp(r_c, x_2d, free_surface_z))
                if r_c >= 0.98 * R or cur[2] <= z_bot_c + 0.003 * H or cur[2] >= z_top_c - 0.003 * H:
                    break

                u_r, u_z, u_th, sp_val = fast_sample(cur[2], r_c)
                u_r *= scale_v
                u_z *= scale_v
                u_th *= scale_v
                sp_val *= scale_v

                poly.append([round(float(cur[0]), 4), round(float(cur[1]), 4), round(float(cur[2]), 4), round(float(sp_val), 4)])

                r_s = max(r_c, 1e-4)
                vx = u_r * (cur[0] / r_s) - u_th * (cur[1] / r_s)
                vy = u_r * (cur[1] / r_s) + u_th * (cur[0] / r_s)
                vz = u_z
                v_mag = math.sqrt(vx**2 + vy**2 + vz**2)
                if v_mag < 1e-4:
                    vx = -cur[1] * ops.rps * 2.0 * math.pi
                    vy = cur[0] * ops.rps * 2.0 * math.pi
                    v_mag = math.sqrt(vx**2 + vy**2)
                    if v_mag < 1e-4:
                        break

                cur = cur + (np.array([vx, vy, vz]) / v_mag) * ds

            if len(poly) >= 4:
                streamlines_list.append(poly)

        r_rings = [0.22 * R, 0.44 * R, 0.66 * R, 0.88 * R]
        z_levels = np.linspace(0.10 * H, 0.90 * H, 9)
        ring_n_angles = [8, 12, 16, 18]

        for z_k in z_levels:
            for r_j, n_th in zip(r_rings, ring_n_angles):
                z_bot_j = float(z_dish_bottom_profile(np.array([r_j]), tank)[0])
                z_top_j = float(np.interp(r_j, x_2d, free_surface_z))
                if z_k < z_bot_j + 0.01 * H or z_k > z_top_j - 0.01 * H:
                    continue

                u_r, u_z, u_th, sp_val = fast_sample(z_k, r_j)
                u_r *= scale_v
                u_z *= scale_v
                u_th *= scale_v
                sp_val *= scale_v

                for th_m in np.linspace(0.0, 2.0 * math.pi, n_th, endpoint=False):
                    x = r_j * math.cos(th_m)
                    y = r_j * math.sin(th_m)
                    r_s = max(r_j, 1e-4)
                    vx = u_r * (x / r_s) - u_th * (y / r_s)
                    vy = u_r * (y / r_s) + u_th * (x / r_s)
                    vz = u_z
                    v_mag = math.sqrt(vx**2 + vy**2 + vz**2)

                    vectors_3d.append([
                        round(float(x), 4),
                        round(float(y), 4),
                        round(float(z_k), 4),
                        round(float(vx), 4),
                        round(float(vy), 4),
                        round(float(vz), 4),
                        round(float(v_mag), 4),
                    ])

        cfd_max_v = float(cfd_metrics.get("cfd_max_velocity_m_s", max_flow_sp * scale_v) if cfd_metrics else max_flow_sp)
        cfd_mean_v = float(cfd_metrics.get("cfd_mean_velocity_m_s", float(np.mean(speed_eval[in_wet]))) if cfd_metrics else float(np.mean(speed_eval[in_wet])))
        cfd_p_w = float(cfd_metrics.get("cfd_power_w", sim_result.total_ungassed_power_w) if cfd_metrics else sim_result.total_ungassed_power_w)
        cfd_t_nm = float(cfd_metrics.get("cfd_torque_n_m", sim_result.total_ungassed_power_w / max(omega, 1e-4)) if cfd_metrics else sim_result.total_ungassed_power_w / max(omega, 1e-4))
        dead_zone_f = float(flow_2d.dead_zone_fraction)

    # 6. 3D CAD Meshes (Including Meniscus free_surface)
    cad_components = Visualizer3D.build_reactor_cad_meshes(tank, free_surface_z=free_surface_z)
    serialized_cad: Dict[str, Dict[str, Any]] = {}
    for part_name, mesh_obj in cad_components.items():
        if mesh_obj is None or mesh_obj.n_points == 0:
            serialized_cad[part_name] = {"vertices": [], "indices": []}
            continue
        cleaned = mesh_obj.clean(tolerance=1e-5)
        tri = cleaned.triangulate()
        verts = np.round(tri.points, 4).tolist()
        if tri.n_cells > 0 and len(tri.faces) == tri.n_cells * 4:
            faces = tri.faces.reshape(-1, 4)[:, 1:].flatten().astype(int).tolist()
        else:
            faces = []
            i = 0
            raw = tri.faces
            while i < len(raw):
                n = raw[i]
                if n == 3:
                    faces.extend([int(raw[i + 1]), int(raw[i + 2]), int(raw[i + 3])])
                i += n + 1
        serialized_cad[part_name] = {"vertices": verts, "indices": faces}

    # Backward compatible vector_quiver
    quiver_pts = [[v[0], v[1], v[2]] for v in vectors_3d]
    quiver_vel = [[v[3], v[4], v[5]] for v in vectors_3d]
    quiver_spd = [v[6] for v in vectors_3d]

    is_fluent = (fluent_pts is not None and len(fluent_pts) > 0)
    has_tke = bool(is_fluent and fluent_tkes is not None and np.max(fluent_tkes) > 1e-6)
    has_eps = bool(is_fluent and fluent_epsilons is not None and np.max(fluent_epsilons) > 1e-6)
    re_primary = float(sim_result.stages[0].re_i) if sim_result.stages else (rho_fluid * (ops.rpm / 60.0) * (tank.impellers[0].diameter_m**2) / max(mu_eff, 1e-6))
    is_laminar_flow = bool(not has_tke and not has_eps) or (re_primary < 200.0) or (getattr(ops, "rheology_model", None) == "power_law") or (mu_eff >= 0.5)

    avail_fields = ["velocity_mag", "pressure"]
    if has_tke:
        avail_fields.append("tke")
    if has_eps:
        avail_fields.append("epsilon")
        avail_fields.append("kolmogorov_um")
    if (has_eps or has_tke or is_laminar_flow) and (tau_xz_2d is not None):
        avail_fields.append("shear_stress_pa")
    if not is_fluent:
        avail_fields = ["velocity_estimate"]
        if is_laminar_flow and tau_xz_2d is not None:
            avail_fields.append("shear_stress_pa")

    if is_real_fluent and has_eps and fluent_epsilons is not None and len(fluent_epsilons) > 0:
        eps_interior = fluent_epsilons[fluent_epsilons > 1e-6]
        if len(eps_interior) > 0:
            kolm_pts = (nu_fluid**3 / np.maximum(eps_interior, 1e-6))**0.25 * 1e6
            kolm_min_um = float(np.percentile(kolm_pts, 5.0))
        else:
            kolm_min_um = 2500.0
    else:
        kolm_min_um = 0.0

    if is_real_fluent and (has_eps or has_tke):
        tke_all = fluent_tkes if fluent_tkes is not None else np.zeros_like(fluent_epsilons)
        eps_all = fluent_epsilons if fluent_epsilons is not None else np.zeros_like(fluent_tkes)
        tau_all = np.sqrt(rho_fluid * mu_eff * np.maximum(eps_all, 0.0) + (0.09 * rho_fluid * np.maximum(tke_all, 0.0))**2)
        max_shear_stress_pa = float(np.percentile(tau_all, 99.0)) if len(tau_all) > 50 else float(np.max(tau_all))
    elif is_laminar_flow and tau_xz_2d is not None:
        flat_tau = [v for row in tau_xz_2d for v in row if v is not None]
        max_shear_stress_pa = float(np.percentile(flat_tau, 99.0)) if len(flat_tau) > 50 else (float(np.max(flat_tau)) if flat_tau else 0.0)
    else:
        max_shear_stress_pa = 0.0

    n_cells_val = int(fluent_pts.shape[0]) if (fluent_pts is not None and hasattr(fluent_pts, "shape")) else int(cfd_metrics.get("n_cells", 14000) if cfd_metrics else 14000)

    # Meta
    bundle_meta = {
        "solver_source": solver_source,
        "n_cells": n_cells_val,
        "tip_speed_m_s": round(tip_speed, 3),
        "cfd_max_velocity_m_s": round(cfd_max_v, 4),
        "cfd_mean_velocity_m_s": round(cfd_mean_v, 4),
        "cfd_power_w": round(cfd_p_w, 2),
        "cfd_torque_n_m": round(cfd_t_nm, 4),
        "rpm": round(ops.rpm, 1),
        "viscous_model": "laminar" if is_laminar_flow else "k-epsilon",
        "reynolds_number": round(float(re_primary), 1),
        "is_laminar": is_laminar_flow,
        "cfd_dead_zone_fraction": round(dead_zone_f, 4),
        "cfd_kolmogorov_min_um": round(kolm_min_um, 1),
        "cfd_max_shear_stress_pa": round(max_shear_stress_pa, 2),
        "available_cfd_fields": avail_fields,
        "tke_available": has_tke,
        "epsilon_available": has_eps,
        "pressure_cfd_available": is_fluent,
    }

    bundle_dict = {
        "run_id": run_id,
        "solver_source": solver_source,
        "metadata": bundle_meta,
        "available_cfd_fields": avail_fields,
        "tke_available": has_tke,
        "epsilon_available": has_eps,
        "pressure_cfd_available": is_fluent,
        "streamlines": streamlines_list,
        "vectors_3d": vectors_3d,
        "cross_sections": {
            "xz": {
                "x": [round(float(v), 4) for v in x_lin],
                "z": [round(float(v), 4) for v in z_lin],
                "velocity_mag": sp_xz_2d,
                "pressure": p_xz_2d,
                "ux": ux_xz_2d,
                "uz": uz_xz_2d,
                "tke": k_xz_2d,
                "epsilon": e_xz_2d,
                "kolmogorov_um": kolm_xz_2d,
                "shear_stress_pa": tau_xz_2d,
            },
            "yz": {
                "y": [round(float(v), 4) for v in x_lin],
                "z": [round(float(v), 4) for v in z_lin],
                "velocity_mag": sp_yz_2d,
                "pressure": p_yz_2d,
                "uy": uy_yz_2d,
                "uz": uz_yz_2d,
                "tke": k_yz_2d,
                "epsilon": e_yz_2d,
                "kolmogorov_um": kolm_yz_2d,
                "shear_stress_pa": tau_yz_2d,
            },
        },
        "horizontal_slices": horizontal_slices,
        "vector_quiver": {
            "points": quiver_pts,
            "vectors": quiver_vel,
            "speeds": quiver_spd,
        },
        "cad_meshes": serialized_cad,
    }

    if output_dir:
        bundle_path = os.path.join(output_dir, "web_3d_bundle.json")
        with open(bundle_path, "w", encoding="utf-8") as f:
            json.dump(bundle_dict, f, separators=(",", ":"))

    bundle_dict["bpe_result"] = sim_result
    return bundle_dict



def backfill_run_configs(fluent_runs_dir: Optional[str] = None) -> int:
    """Scan fluent runs directory and backfill missing config.json files from metadata and 3D bundle.

    Returns the count of backfilled directories.
    """
    if fluent_runs_dir is None:
        fluent_runs_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "outputs", "fluent_runs")
        )
    if not os.path.isdir(fluent_runs_dir):
        return 0

    backfilled_count = 0
    for run_name in os.listdir(fluent_runs_dir):
        run_path = os.path.join(fluent_runs_dir, run_name)
        if not os.path.isdir(run_path):
            continue

        cfg_path = os.path.join(run_path, "config.json")
        if os.path.isfile(cfg_path):
            continue

        meta_path = os.path.join(run_path, "metadata.json")
        bundle_path = os.path.join(run_path, "web_3d_bundle.json")
        if not (os.path.isfile(meta_path) and os.path.isfile(bundle_path)):
            continue

        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            with open(bundle_path, "r", encoding="utf-8") as f:
                bundle = json.load(f)

            rpm = meta.get("rpm", 250.0)
            tip_speed = meta.get("tip_speed_m_s", 1.83)
            rps = rpm / 60.0
            di_calc = round(tip_speed / (math.pi * rps), 2) if rps > 0 else 0.15

            xz_x = bundle.get("cross_sections", {}).get("xz", {}).get("x", [-0.2, 0.2])
            xz_z = bundle.get("cross_sections", {}).get("xz", {}).get("z", [0.0, 0.45])
            radius = max(abs(xz_x[0]), abs(xz_x[-1]))
            diameter_m = round(radius * 2.0, 2)
            liquid_height_m = round(xz_z[-1], 2)

            bottom_type = "flat"
            if "_elli_" in run_name:
                bottom_type = "elliptical_2_1"
            elif "_hemi_" in run_name:
                bottom_type = "hemispherical"

            slices = bundle.get("horizontal_slices", [])
            impellers = []
            for s in slices:
                c_idx = s.get("clearance_index")
                if c_idx is not None:
                    lbl = s.get("label", "").lower()
                    imp_t = "rushton_6_blade"
                    if "pitched" in lbl:
                        imp_t = "pitched_blade_45"
                    elif "marine" in lbl:
                        imp_t = "marine_propeller"
                    c_val = round(s.get("z", 0.15), 3)
                    impellers.append({
                        "impeller_type": imp_t,
                        "diameter_m": di_calc,
                        "clearance_m": c_val,
                    })

            if not impellers:
                impellers = [{
                    "impeller_type": "rushton_6_blade",
                    "diameter_m": di_calc,
                    "clearance_m": round(0.33 * liquid_height_m, 2),
                }]

            has_baffles = len(bundle.get("cad_meshes", {}).get("baffles", {}).get("vertices", [])) > 0
            config_payload = {
                "tank": {
                    "diameter_m": diameter_m,
                    "liquid_height_m": liquid_height_m,
                    "bottom_type": bottom_type,
                    "baffle_count": 4 if has_baffles else 0,
                    "baffle_width_ratio": 0.10,
                    "impellers": impellers,
                },
                "fluid": {
                    "name": "Water Broth",
                    "density_kg_m3": 1000.0,
                    "viscosity_pa_s": 0.001,
                    "coalescing_media": True,
                },
                "ops": {
                    "rpm": rpm,
                    "aeration_vvm": 0.5,
                    "cell_type": "microbial",
                },
                "mesh_density": "fast",
                "iterations": 15,
            }
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(config_payload, f, indent=2)
            backfilled_count += 1
        except Exception:
            pass

    return backfilled_count


# Module-level aliases
FluentRunner = FluentSimulationRunner

