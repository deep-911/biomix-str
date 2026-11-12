"""BioMix-STR: Bioprocess Engineering Stirred-Tank Bioreactor Simulation Suite."""

from biomix.correlations import (
    FlowRegime,
    METZNER_OTTO_KS,
    PUMPING_NUMBER_NQ,
    calc_aeration_number,
    calc_average_shear,
    calc_flooding_aeration_number,
    calc_froude_number,
    calc_gas_flow_rate_m3_s,
    calc_gassed_power,
    calc_kla_vant_riet,
    calc_kolmogorov_scales,
    calc_mixing_time_95,
    calc_power_number,
    calc_pumping_and_circulation,
    calc_reynolds_number,
    calc_superficial_gas_velocity,
    calc_tip_speed,
    calc_ungassed_power,
    classify_flow_regime,
)
from biomix.engine import (
    HydrodynamicEngine,
    ImpellerStageResult,
    ReactorSimulationResult,
)
from biomix.flow_solver_2d import (
    FlowField2DResult,
    FlowSolver2D,
)
from biomix.visualization_2d import (
    Plotter2D,
)
from biomix.visualization_3d import (
    Visualizer3D,
)
from biomix.cad_mesher import (
    BioreactorCADMesher,
    MeshedBioreactorArtifact,
)
from biomix.fluent_bridge import (
    CFDParityReport,
    FluentCFDVerifier,
    FluentJournalGenerator,
    FluentMRFConfig,
)
from biomix.fluent_runner import (
    FluentResidualStep,
    FluentRunMetadata,
    FluentSimulationRunner,
    backfill_run_configs,
    generate_run_id,
)
from biomix.server import app as server_app
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
try:
    from biomix.app import (
        PRESETS,
        build_simulation_from_params,
        compare_impeller_topologies,
        load_preset,
    )
except ImportError:
    PRESETS = {}
    build_simulation_from_params = None
    compare_impeller_topologies = None
    load_preset = None

__version__ = "0.1.0"

__all__ = [
    # Models & Enums
    "BottomType",
    "ImpellerType",
    "FlowDirection",
    "CellType",
    "ImpellerSpec",
    "TankGeometry",
    "FluidProperties",
    "OperatingConditions",
    # Correlations
    "FlowRegime",
    "METZNER_OTTO_KS",
    "PUMPING_NUMBER_NQ",
    "calc_reynolds_number",
    "classify_flow_regime",
    "calc_power_number",
    "calc_ungassed_power",
    "calc_gas_flow_rate_m3_s",
    "calc_aeration_number",
    "calc_froude_number",
    "calc_flooding_aeration_number",
    "calc_gassed_power",
    "calc_tip_speed",
    "calc_average_shear",
    "calc_kolmogorov_scales",
    "calc_pumping_and_circulation",
    "calc_mixing_time_95",
    "calc_superficial_gas_velocity",
    "calc_kla_vant_riet",
    # Simulation Engine
    "ImpellerStageResult",
    "ReactorSimulationResult",
    "HydrodynamicEngine",
    # 2D Flow Field Solver
    "FlowField2DResult",
    "FlowSolver2D",
    # 2D Visualization
    "Plotter2D",
    # 3D Visualization
    "Visualizer3D",
    # Ansys Fluent CFD Bridge & Live Runner
    "BioreactorCADMesher",
    "MeshedBioreactorArtifact",
    "FluentMRFConfig",
    "CFDParityReport",
    "FluentJournalGenerator",
    "FluentCFDVerifier",
    "FluentResidualStep",
    "FluentRunMetadata",
    "FluentSimulationRunner",
    "backfill_run_configs",
    "generate_run_id",
    "server_app",
    # App & Presets
    "PRESETS",
    "load_preset",
    "build_simulation_from_params",
    "compare_impeller_topologies",
]
