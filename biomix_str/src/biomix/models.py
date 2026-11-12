"""Reactor Anatomy & Impeller Topologies for BioMix-STR.

Physics-validated Pydantic v2 models representing stirred-tank bioreactor
geometries, impeller specifications, fluid physical properties, and operating
conditions following Bioprocess Engineering (BPE) standards.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import (
    BaseModel,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


class BottomType(str, Enum):
    """Vessel bottom dish heads."""
    FLAT = "flat"
    HEMISPHERICAL = "hemispherical"
    ELLIPTICAL_2_1 = "elliptical_2_1"  # Standard ASME 2:1 elliptical dish (h_d = T / 4)


class ImpellerClearanceClass(str, Enum):
    """Categorization of bioreactor impellers by wall clearance and operating regime."""
    OPEN_TURBINE = "open_turbine"  # Low-to-medium viscosity (<100,000 cP), Di/T ~ 1/3, baffled tanks
    CLOSE_CLEARANCE = "close_clearance"  # High-to-ultra-high viscosity (up to 25M cP), Di/T ~ 0.85-0.98, unbaffled


class FlowDirection(str, Enum):
    """Primary discharge flow direction created by impeller."""
    RADIAL = "radial"
    MIXED_AXIAL = "mixed_axial"
    AXIAL = "axial"
    CLOSE_CLEARANCE_TANGENTIAL = "close_clearance_tangential"


class ImpellerType(str, Enum):
    """All 16 Bioprocess Engineering bioreactor impeller configurations."""

    # A1. Open Radial-Flow Impellers
    RUSHTON_6_BLADE = "rushton_6_blade"  # Rushton R-100: 6 vertical flat blades on central disc, Np ~ 5.0
    SMITH_CD6 = "smith_cd6"  # Smith CD-6 / R-130: 6 concave half-pipe blades, Np ~ 3.2, 2.5x flooding threshold
    FLAT_BLADE_FBT = "flat_blade_fbt"  # Open Flat-Blade Turbine: 6 vertical blades without disc, Np ~ 4.0
    PADDLE_R200 = "paddle_r200"  # Paddle R-200: 2-4 wide vertical blades, W/Di ~ 0.25, Di/T ~ 0.5-0.8, Np ~ 2.5
    CURVED_BACKSWEPT = "curved_backswept"  # Curved-blade / backswept turbine: 6 swept arc blades, Np ~ 4.0
    RETREAT_BLADE = "retreat_blade"  # Pfaudler retreat-blade: 3 backward-retreating blades near bottom, Np ~ 3.1

    # A2. Open Axial & Mixed-Flow Impellers
    MARINE_PROPELLER = "marine_propeller"  # Marine propeller JP-3: 3 tapered constant-pitch blades, Np ~ 0.35, <200 cP
    PITCHED_BLADE_45 = "pitched_blade_45"  # Pitched-blade turbine PBT: 4 blades at 45°, Np ~ 1.5
    HYDROFOIL_HE3 = "hydrofoil_he3"  # Fluidfoil Chemineer HE-3 / Lightnin A-310: 3 cambered blades, Np ~ 0.29
    MAXFLO_HIGH_SOLIDITY = "maxflo_high_solidity"  # High-solidity hydrofoil A-320 / Maxflo: 4 wide blades, Np ~ 3.3
    INTERMIG_EKATO = "intermig_ekato"  # EKATO Intermig multistage agitator with slotted tip winglets, Np ~ 0.65

    # B. Close-Clearance Impellers (Unbaffled, High Viscosity)
    ANCHOR = "anchor"  # Anchor: U-frame with 1-5 cm wall clearance, Di/T ~ 0.90-0.96, 5k-50k cP, jacket heat transfer
    HELICAL_RIBBON = "helical_ribbon"  # Double helical ribbon: spiral along tank wall, pitch ~ 0.5, 30k-25M cP
    AUGER_SCREW = "auger_screw"  # Auger helical screw: central screw flight with draft tube for high solids
    GATE_IMPELLER = "gate_impeller"  # Gate impeller: multi-crossbar grid frame agitator for squat tanks
    SIGMA_Z_KNEADER = "sigma_z_kneader"  # Z-blade / Sigma kneader: high-torque saddle arms for heavy bio-pastes

    @property
    def clearance_class(self) -> ImpellerClearanceClass:
        """Categorize into OPEN_TURBINE vs CLOSE_CLEARANCE."""
        close_types = {
            ImpellerType.ANCHOR,
            ImpellerType.HELICAL_RIBBON,
            ImpellerType.AUGER_SCREW,
            ImpellerType.GATE_IMPELLER,
            ImpellerType.SIGMA_Z_KNEADER,
        }
        if self in close_types:
            return ImpellerClearanceClass.CLOSE_CLEARANCE
        return ImpellerClearanceClass.OPEN_TURBINE

    @property
    def is_close_clearance(self) -> bool:
        """True if close-clearance wall-sweeping impeller."""
        return self.clearance_class == ImpellerClearanceClass.CLOSE_CLEARANCE

    @property
    def default_flow_direction(self) -> FlowDirection:
        """Default bulk liquid discharge flow pattern."""
        radial_types = {
            ImpellerType.RUSHTON_6_BLADE,
            ImpellerType.SMITH_CD6,
            ImpellerType.FLAT_BLADE_FBT,
            ImpellerType.PADDLE_R200,
            ImpellerType.CURVED_BACKSWEPT,
            ImpellerType.RETREAT_BLADE,
        }
        mixed_types = {
            ImpellerType.PITCHED_BLADE_45,
            ImpellerType.MAXFLO_HIGH_SOLIDITY,
        }
        axial_types = {
            ImpellerType.MARINE_PROPELLER,
            ImpellerType.HYDROFOIL_HE3,
            ImpellerType.INTERMIG_EKATO,
        }
        if self in radial_types:
            return FlowDirection.RADIAL
        elif self in mixed_types:
            return FlowDirection.MIXED_AXIAL
        elif self in axial_types:
            return FlowDirection.AXIAL
        return FlowDirection.CLOSE_CLEARANCE_TANGENTIAL


class CellType(str, Enum):
    """Biological expression system sensitivity parameters."""
    MICROBIAL = "microbial"  # Bacteria/yeast/fungi: max tip speed = 7.0 m/s, critical eddy = 5 µm
    PLANT_CELL = "plant_cell"  # Plant suspension: max tip speed = 2.5 m/s, critical eddy = 100 µm
    MAMMALIAN_CELL = "mammalian_cell"  # Animal/CHO/hybridoma: max tip speed = 1.5 m/s, critical eddy = 20 µm

    @property
    def max_tip_speed_m_s(self) -> float:
        """Maximum recommended impeller tip speed to avoid shear damage (m/s)."""
        speeds = {
            CellType.MICROBIAL: 7.0,
            CellType.PLANT_CELL: 2.5,
            CellType.MAMMALIAN_CELL: 1.5,
        }
        return speeds[self]

    @property
    def critical_kolmogorov_m(self) -> float:
        """Critical Kolmogorov microscale eddy length scale threshold (m)."""
        sizes = {
            CellType.MICROBIAL: 5e-6,
            CellType.PLANT_CELL: 100e-6,
            CellType.MAMMALIAN_CELL: 20e-6,
        }
        return sizes[self]


class ImpellerSpec(BaseModel):
    """Physical specification for a single impeller on the agitator shaft.

    All geometric dimensions are specified in SI units (meters).
    """
    impeller_type: ImpellerType = ImpellerType.RUSHTON_6_BLADE
    diameter_m: float = Field(gt=0.0, description="Impeller outer diameter D_i (m)")
    clearance_m: float = Field(
        gt=0.0,
        description="Impeller off-bottom clearance from tank bottom C (m) to blade centerline for open proximity turbines, or to bottom sweep clearance C (m) for close-clearance impellers",
    )
    blade_width_m: Optional[float] = Field(default=None, gt=0.0, description="Impeller blade/strip width W_i (m)")
    blade_count: Optional[int] = Field(default=None, gt=0, description="Number of impeller blades")

    @model_validator(mode="after")
    def populate_defaults(self) -> "ImpellerSpec":
        """Auto-populate blade width and blade count defaults if not explicitly given."""
        if self.blade_width_m is None:
            if self.impeller_type in (ImpellerType.MARINE_PROPELLER, ImpellerType.PADDLE_R200):
                self.blade_width_m = self.diameter_m / 4.0
            elif self.impeller_type == ImpellerType.HYDROFOIL_HE3:
                self.blade_width_m = self.diameter_m / 6.0
            elif self.impeller_type == ImpellerType.MAXFLO_HIGH_SOLIDITY:
                self.blade_width_m = self.diameter_m / 3.5
            elif self.impeller_type == ImpellerType.INTERMIG_EKATO:
                self.blade_width_m = self.diameter_m / 4.5
            elif self.impeller_type == ImpellerType.ANCHOR:
                self.blade_width_m = self.diameter_m * 0.60
            elif self.impeller_type == ImpellerType.HELICAL_RIBBON:
                self.blade_width_m = self.diameter_m * 0.80
            elif self.impeller_type == ImpellerType.AUGER_SCREW:
                self.blade_width_m = self.diameter_m * 0.70
            elif self.impeller_type == ImpellerType.GATE_IMPELLER:
                self.blade_width_m = self.diameter_m * 0.65
            elif self.impeller_type == ImpellerType.SIGMA_Z_KNEADER:
                self.blade_width_m = self.diameter_m * 0.40
            else:
                self.blade_width_m = self.diameter_m / 5.0

        if self.blade_count is None:
            counts = {
                ImpellerType.RUSHTON_6_BLADE: 6,
                ImpellerType.SMITH_CD6: 6,
                ImpellerType.FLAT_BLADE_FBT: 6,
                ImpellerType.PADDLE_R200: 2,
                ImpellerType.CURVED_BACKSWEPT: 6,
                ImpellerType.RETREAT_BLADE: 3,
                ImpellerType.MARINE_PROPELLER: 3,
                ImpellerType.PITCHED_BLADE_45: 4,
                ImpellerType.HYDROFOIL_HE3: 3,
                ImpellerType.MAXFLO_HIGH_SOLIDITY: 4,
                ImpellerType.INTERMIG_EKATO: 2,
                ImpellerType.ANCHOR: 2,
                ImpellerType.HELICAL_RIBBON: 2,
                ImpellerType.AUGER_SCREW: 1,
                ImpellerType.GATE_IMPELLER: 4,
                ImpellerType.SIGMA_Z_KNEADER: 2,
            }
            self.blade_count = counts.get(self.impeller_type, 4)

        return self

    @computed_field
    @property
    def flow_direction(self) -> FlowDirection:
        """Primary flow discharge pattern generated by this impeller."""
        return self.impeller_type.default_flow_direction

    @computed_field
    @property
    def swept_volume_m3(self) -> float:
        """Swept cylinder volume of the impeller: (pi/4) * D_i^2 * W_b (m^3)."""
        width = self.blade_width_m if self.blade_width_m is not None else (self.diameter_m / 5.0)
        return (math.pi / 4.0) * (self.diameter_m ** 2) * width


class TankGeometry(BaseModel):
    """Bioreactor vessel anatomy, baffles, and agitator impeller configurations.

    Adheres to Bioprocess Engineering (BPE) and ASME-BPE design rules.
    """
    diameter_m: float = Field(gt=0.0, description="Tank internal diameter D_T (m)")
    liquid_height_m: float = Field(gt=0.0, description="Ungassed liquid fill height H_L (m)")
    bottom_type: BottomType = BottomType.ELLIPTICAL_2_1
    baffle_count: int = Field(default=4, ge=0, le=8, description="Number of wall baffles (0 for unbaffled, or 3-8)")
    baffle_width_ratio: float = Field(
        default=0.10,
        description="Baffle width relative to vessel diameter W_b/D_T (standard 0.10 or 1/12 ~ 0.0833)",
    )
    sparger_type: Literal["ring", "pipe", "none"] = Field(
        default="ring",
        description="Visual sparger internal geometry: ring (torus), pipe (open horizontal L-pipe), or none",
    )
    include_probes: bool = Field(
        default=False,
        description="Include vertical DO/pH sensor dip-tube probes in 3D CAD visualization",
    )
    include_cooling_jacket: bool = Field(
        default=False,
        description="Include external thermal cooling jacket shell in 3D CAD visualization",
    )
    impellers: List[ImpellerSpec] = Field(
        min_length=1,
        description="List of impeller specifications on the agitator shaft",
    )

    @field_validator("baffle_count")
    @classmethod
    def validate_baffle_count(cls, v: int) -> int:
        if v != 0 and v < 3:
            raise ValueError(f"baffle_count must be 0 (unbaffled) or between 3 and 8, got {v}")
        return v

    @field_validator("baffle_width_ratio")
    @classmethod
    def validate_baffle_width_ratio(cls, v: float) -> float:
        if v == 0.0:
            return v
        if v < 0.05 or v > 0.15:
            raise ValueError(f"baffle_width_ratio must be 0.0 (unbaffled) or between 0.05 and 0.15, got {v}")
        return v

    @model_validator(mode="after")
    def validate_and_sort_bioprocess_rules(self) -> "TankGeometry":
        T = self.diameter_m
        H = self.liquid_height_m

        # 1. Validate liquid height relative to bottom dish depth
        dish_depth = self.dish_depth_m
        if H <= dish_depth:
            raise ValueError(
                f"liquid_height_m ({H} m) must be strictly greater than bottom dish depth ({dish_depth} m)"
            )

        # Validate baffle_width_ratio when vessel is baffled
        if self.baffle_count > 0 and self.baffle_width_ratio < 0.05:
            raise ValueError(
                f"baffle_width_ratio must be between 0.05 and 0.15 when vessel has baffles, got {self.baffle_width_ratio}"
            )

        # 2. Automatically sort impellers ascending by clearance from bottom
        self.impellers = sorted(self.impellers, key=lambda imp: imp.clearance_m)

        # 3. Validate each impeller diameter and clearance against BPE standards
        for i, imp in enumerate(self.impellers):
            ratio = imp.diameter_m / T
            if imp.impeller_type.is_close_clearance:
                min_ratio, max_ratio = 0.15, 0.98
            elif imp.impeller_type == ImpellerType.PADDLE_R200:
                min_ratio, max_ratio = 0.15, 0.85
            elif imp.impeller_type == ImpellerType.RETREAT_BLADE:
                min_ratio, max_ratio = 0.15, 0.70
            else:
                min_ratio, max_ratio = 0.15, 0.65

            if ratio < min_ratio or ratio > max_ratio:
                range_str = "[0.15, 0.65]" if (min_ratio, max_ratio) == (0.15, 0.65) else f"[{min_ratio:.2f}, {max_ratio:.2f}]"
                raise ValueError(
                    f"Impeller {i + 1} diameter ratio Di/T = {ratio:.3f} is outside recommended BPE range {range_str}"
                )

            min_clearance = 0.015 * T if imp.impeller_type.is_close_clearance else 0.03 * T
            max_clearance = H - 0.03 * T
            if imp.clearance_m < min_clearance or imp.clearance_m >= max_clearance:
                min_label = "0.015*T" if imp.impeller_type.is_close_clearance else "0.03*T"
                raise ValueError(
                    f"Impeller {i + 1} clearance C = {imp.clearance_m} m violates allowable range "
                    f"[{min_label} = {min_clearance:.3f} m, H - 0.03*T = {max_clearance:.3f} m). "
                    f"Impeller would collide with bottom or breach the liquid surface."
                )

        # 4. Multi-impeller spacing rule: delta C >= 0.8 * Di (or 0.2 * Di for close-clearance)
        for i in range(len(self.impellers) - 1):
            lower = self.impellers[i]
            upper = self.impellers[i + 1]
            delta_c = upper.clearance_m - lower.clearance_m
            factor = 0.2 if (lower.impeller_type.is_close_clearance or upper.impeller_type.is_close_clearance) else 0.8
            min_sep = factor * lower.diameter_m
            if delta_c < min_sep:
                raise ValueError(
                    f"Adjacent impellers {i + 1} (C={lower.clearance_m} m) and {i + 2} (C={upper.clearance_m} m) "
                    f"have separation delta C = {delta_c:.3f} m, which is less than {factor} * D_i = {min_sep:.3f} m."
                )

        return self

    @computed_field
    @property
    def baffle_width_m(self) -> float:
        """Physical width of each wall baffle W (m). Returns 0.0 if unbaffled."""
        if self.baffle_count == 0:
            return 0.0
        return self.baffle_width_ratio * self.diameter_m

    @computed_field
    @property
    def is_baffled(self) -> bool:
        """True if the bioreactor vessel contains wall baffles."""
        return self.baffle_count > 0

    @computed_field
    @property
    def aspect_ratio(self) -> float:
        """Vessel liquid aspect ratio H / T."""
        return self.liquid_height_m / self.diameter_m

    @computed_field
    @property
    def total_height_m(self) -> float:
        """Total vessel construction height including 25% headspace H_total (m)."""
        return 1.25 * self.liquid_height_m

    @computed_field
    @property
    def dish_depth_m(self) -> float:
        """Depth of the vessel bottom head dish h_d (m)."""
        if self.bottom_type == BottomType.FLAT:
            return 0.0
        elif self.bottom_type == BottomType.ELLIPTICAL_2_1:
            return self.diameter_m / 4.0
        elif self.bottom_type == BottomType.HEMISPHERICAL:
            return self.diameter_m / 2.0
        raise ValueError(f"Unknown bottom type: {self.bottom_type}")

    @computed_field
    @property
    def working_volume_m3(self) -> float:
        """Total liquid working volume V_L (m^3).

        - FLAT: (pi/4) * T^2 * H
        - ELLIPTICAL_2_1: (pi/4) * T^2 * (H - T/4) + (pi/24) * T^3
        - HEMISPHERICAL: (pi/4) * T^2 * (H - T/2) + (pi/12) * T^3
        """
        T = self.diameter_m
        H = self.liquid_height_m

        if self.bottom_type == BottomType.FLAT:
            return (math.pi / 4.0) * (T ** 2) * H
        elif self.bottom_type == BottomType.ELLIPTICAL_2_1:
            cyl_vol = (math.pi / 4.0) * (T ** 2) * (H - T / 4.0)
            head_vol = (math.pi / 24.0) * (T ** 3)
            return cyl_vol + head_vol
        elif self.bottom_type == BottomType.HEMISPHERICAL:
            cyl_vol = (math.pi / 4.0) * (T ** 2) * (H - T / 2.0)
            head_vol = (math.pi / 12.0) * (T ** 3)
            return cyl_vol + head_vol
        raise ValueError(f"Unknown bottom type: {self.bottom_type}")

    @computed_field
    @property
    def cross_sectional_area_m2(self) -> float:
        """Vessel cylindrical cross-sectional area: (pi/4) * T^2 (m^2)."""
        return (math.pi / 4.0) * (self.diameter_m ** 2)


class FluidProperties(BaseModel):
    """Thermophysical and rheological properties of the fermentation broth."""
    name: str = Field(default="Water / Dilute Fermentation Broth", description="Fluid descriptor")
    density_kg_m3: float = Field(default=1000.0, gt=0.0, description="Broth density rho (kg/m^3)")
    viscosity_pa_s: float = Field(default=0.001, gt=0.0, description="Dynamic viscosity mu (Pa.s, 1 cP = 1e-3 Pa.s)")
    coalescing_media: bool = Field(
        default=True,
        description="True for coalescing systems (pure water/salts), False for non-coalescing (ionic/antifoam broths)",
    )

    rheology_model: Literal["newtonian", "power_law"] = "newtonian"
    consistency_k_pa_s_n: Optional[float] = Field(
        default=None, gt=0.0, description="Ostwald-de Waele consistency index K (Pa.s^n)"
    )
    flow_behavior_index_n: Optional[float] = Field(
        default=None, gt=0.0, description="Flow behavior index n (< 1 for pseudoplastic/shear-thinning)"
    )

    def get_effective_viscosity(self, shear_rate_s_1: float = 1.0) -> float:
        """Evaluate apparent dynamic viscosity (Pa.s) under specified shear rate."""
        if (
            self.rheology_model == "power_law"
            and self.consistency_k_pa_s_n is not None
            and self.flow_behavior_index_n is not None
        ):
            g_dot = max(shear_rate_s_1, 1e-3)
            return float(self.consistency_k_pa_s_n * (g_dot ** (self.flow_behavior_index_n - 1.0)))
        return float(self.viscosity_pa_s)

    @computed_field
    @property
    def kinematic_viscosity_m2_s(self) -> float:
        """Kinematic viscosity nu = mu / rho (m^2/s)."""
        return self.viscosity_pa_s / self.density_kg_m3


class OperatingConditions(BaseModel):
    """Bioreactor agitation, aeration, and cell culture operating parameters."""
    rpm: float = Field(default=250.0, gt=0.0, description="Agitator rotational speed (RPM)")
    aeration_vvm: float = Field(
        default=0.0,
        ge=0.0,
        description="Volumetric gas flow rate per unit liquid volume per minute (vvm)",
    )
    cell_type: CellType = Field(default=CellType.MICROBIAL, description="Biological cell line category")
    rheology_model: str = Field(
        default="newtonian",
        description="Rheology model: 'newtonian' or 'power_law'",
    )
    consistency_k_pa_s_n: float = Field(
        default=5.0,
        ge=0.01,
        le=100.0,
        description="Ostwald-de Waele Power-law consistency index K (Pa·s^n)",
    )
    flow_behavior_index_n: float = Field(
        default=0.85,
        ge=0.20,
        le=1.20,
        description="Power-law flow behavior index n (dimensionless)",
    )

    @computed_field
    @property
    def rps(self) -> float:
        """Agitator rotational frequency N (rev/s)."""
        return self.rpm / 60.0


class ScaleUpCriterion(str, Enum):
    """Classical chemical/bioprocess engineering scale-up similarity criteria."""
    CONSTANT_P_V = "constant_p_v"
    CONSTANT_TIP_SPEED = "constant_tip_speed"
    CONSTANT_REYNOLDS = "constant_reynolds"
    CONSTANT_MIXING_TIME = "constant_mixing_time"
    CONSTANT_KLA = "constant_kla"


class ScaleUpRequest(BaseModel):
    """Request payload for scale-up similarity evaluation."""
    tank: Optional[TankGeometry] = None
    fluid: Optional[FluidProperties] = None
    ops: Optional[OperatingConditions] = None
    target_volume_l: Optional[float] = None
    volume_ratio: Optional[float] = Field(default=10.0, gt=0.0, description="Target volume scale ratio V2 / V1")
    criterion: ScaleUpCriterion = Field(
        default=ScaleUpCriterion.CONSTANT_P_V,
        description="Preserved scale-up criterion (constant P/V, constant tip speed, constant Re, constant theta_95, or constant kLa)",
    )
    power_source: str = Field(
        default="correlation",
        description="Scale baseline power source: 'correlation' (Engineering correlation) or 'active_cfd' (Active CFD run)",
    )
    cfd_power_w: Optional[float] = Field(
        default=None,
        description="Active CFD run power in watts if scaling from Active CFD run",
    )


class VesselScaleMetrics(BaseModel):
    """Hydrodynamic metrics for one vessel scale."""
    scale_label: str
    diameter_m: float
    liquid_height_m: float
    working_volume_l: float
    working_volume_m3: float
    impeller_diameter_m: float
    rpm: float
    rps: float
    tip_speed_m_s: float
    power_w: float
    power_per_volume_w_m3: float
    torque_n_m: float
    re_i: float
    flow_regime: str
    mixing_time_95_s: float


class ScaleUpResponse(BaseModel):
    """Side-by-side comparison between baseline and scaled bioreactor vessels."""
    criterion: str
    criterion_label: str
    criterion_formula: str
    linear_scale_factor_lambda: float
    volume_ratio: float
    baseline: VesselScaleMetrics
    scaled: VesselScaleMetrics
    ratios: Dict[str, float]
    engineering_insights: List[str]
    baseline_power_source: str = Field(default="Engineering correlation", description="Source of baseline power")
    baseline_power_w: float = Field(default=0.0, description="Baseline agitator power in watts")


class PresetInfo(BaseModel):
    """Bioprocess Engineering Ensemble Preset descriptor."""
    preset_id: str
    name: str
    description: str
    category: str
    tank: TankGeometry
    fluid: FluidProperties
    ops: OperatingConditions
    mesh_density: str
    iterations: int
    run_id: str
    is_cached: bool
    provenance: Optional[Dict[str, Any]] = None

