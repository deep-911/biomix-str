"""Impeller and equipment engineering catalog.

Engineering reference data covering all 16 industrial
bioreactor impellers across Open Radial-Flow, Open Axial/Mixed-Flow, and
Close-Clearance classes. Incorporates dimensional ratios, viscosity operating
envelopes, hydrodynamic coefficients, and automated engineering suitability analysis.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from biomix.models import (
    CellType,
    FlowDirection,
    FluidProperties,
    ImpellerClearanceClass,
    ImpellerSpec,
    ImpellerType,
    OperatingConditions,
    TankGeometry,
)


class ImpellerEngineeringSpec(BaseModel):
    """Engineering reference entry for an industrial impeller."""

    impeller_type: ImpellerType
    display_name: str = Field(description="Full technical designation")
    model_code: str = Field(description="Standard industrial model designation or commercial trademark")
    clearance_class: ImpellerClearanceClass = Field(description="Open turbine vs Close clearance")
    flow_direction: FlowDirection = Field(description="Primary liquid discharge direction")
    construction: str = Field(description="Physical mechanical geometry and blade fabrication details")
    working_principle: str = Field(description="Hydrodynamic mechanism for gas dispersion and liquid pumping")
    applications: str = Field(description="Target biological expression systems and industrial fermentations")
    limitations_and_advantages: str = Field(description="Key hydrodynamic strengths, drawbacks, and failure modes")
    viscosity_min_cp: float = Field(ge=0.0, description="Minimum recommended viscosity in centipoise (cP)")
    viscosity_max_cp: float = Field(gt=0.0, description="Maximum operational viscosity in centipoise (cP)")
    viscosity_label: str = Field(description="Human-readable viscosity range description")
    recommended_di_dt_range: Tuple[float, float, float] = Field(
        description="(min_ratio, max_ratio, standard_ratio) of D_i / T"
    )
    standard_ratios: Dict[str, Any] = Field(
        description="Recommended geometric ratios: dt_di, hl_di, li_di, wi_di, hi_di, wb_dt, baffles"
    )
    turbulent_np: float = Field(gt=0.0, description="Fully turbulent Power Number N_p")
    laminar_kl: float = Field(gt=0.0, description="Laminar power coefficient K_L where N_p = K_L / Re_i")
    pumping_nq: float = Field(gt=0.0, description="Flow pumping number N_Q = Q_p / (N * D_i^3)")
    metzner_otto_ks: float = Field(gt=0.0, description="Metzner-Otto shear constant k_s for non-Newtonian broths")
    flooding_factor: float = Field(
        default=30.0,
        description="Nienow flooding aeration number scaling factor Fl_{g,flood} / ((Di/T)^3.5 * Fr)",
    )


# Backward-compatible alias
ImpellerCourseEntry = ImpellerEngineeringSpec


# =============================================================================
# Complete 16-Impeller Engineering Catalog
# =============================================================================

IMPELLER_ENGINEERING_CATALOG: Dict[ImpellerType, ImpellerEngineeringSpec] = {
    # -------------------------------------------------------------------------
    # A1. Open Radial-Flow Impellers
    # -------------------------------------------------------------------------
    ImpellerType.RUSHTON_6_BLADE: ImpellerEngineeringSpec(
        impeller_type=ImpellerType.RUSHTON_6_BLADE,
        display_name="Rushton 6-Blade Disc Turbine",
        model_code="R-100",
        clearance_class=ImpellerClearanceClass.OPEN_TURBINE,
        flow_direction=FlowDirection.RADIAL,
        construction=(
            "Central horizontal flat disc with 6 vertical rectangular blades welded along the perimeter. "
            "Standard dimensions: Disc diameter D_d = 0.75 D_i, Blade length L_i = 0.25 D_i, "
            "Blade width W_i = 0.20 D_i."
        ),
        working_principle=(
            "Discharges liquid radially outward at blade centerline into upper and lower recirculation loops. "
            "Gas sparged below is channeled along disc and sheared in trailing vortex cavities behind flat blades."
        ),
        applications=(
            "Aerobic microbial fermentations (E. coli, Pichia pastoris, Saccharomyces cerevisiae, Bacillus) "
            "requiring high oxygen mass transfer rates (k_L a > 100 h⁻¹) and intense gas dispersion."
        ),
        limitations_and_advantages=(
            "High power efficiency for gas dispersion. Disadvantage: intense peak shear stresses in trailing "
            "vortices (damages animal/plant cells); forms ventilated gas cavities causing 40-50% power drop upon gassing."
        ),
        viscosity_min_cp=0.5,
        viscosity_max_cp=1000.0,
        viscosity_label="Below 1,000 cP (Low viscosity Newtonian / thin broths)",
        recommended_di_dt_range=(0.25, 0.50, 0.333),
        standard_ratios={
            "dt_di": 3.0,
            "hl_di": 3.0,
            "li_di": 0.25,
            "wi_di": 0.20,
            "hi_di": 1.0,
            "wb_dt": 0.10,
            "baffles": 4,
            "note": "Standard Rushton turbine geometric proportions",
        },
        turbulent_np=5.0,
        laminar_kl=70.0,
        pumping_nq=0.72,
        metzner_otto_ks=11.5,
        flooding_factor=30.0,
    ),
    ImpellerType.SMITH_CD6: ImpellerEngineeringSpec(
        impeller_type=ImpellerType.SMITH_CD6,
        display_name="Smith Concave-Blade Disc Turbine",
        model_code="CD-6 / R-130",
        clearance_class=ImpellerClearanceClass.OPEN_TURBINE,
        flow_direction=FlowDirection.RADIAL,
        construction=(
            "Central horizontal disc with 6 semi-cylindrical concave (half-pipe) blades welded to perimeter. "
            "Parabolic hollow curvature faces direction of forward rotation."
        ),
        working_principle=(
            "Streamlined hollow blade profile guides sparged gas along concave inner contour to reduce "
            "low-pressure cavity formation behind blade edges. Retains high radial pumping."
        ),
        applications=(
            "High-aeration industrial antibiotic fermentations, secondary metabolite production, and large-scale "
            "aerobic bioreactors (>10 m³) operating under high gas sparging rates (>1.0 vvm)."
        ),
        limitations_and_advantages=(
            "Handles 2.5x to 3.0x higher gas loading before flooding compared to Rushton. Gassed power drop is only "
            "10-20% (vs 50% for Rushton). Slightly higher manufacturing cost due to contoured pressed blades."
        ),
        viscosity_min_cp=0.5,
        viscosity_max_cp=2000.0,
        viscosity_label="Below 2,000 cP",
        recommended_di_dt_range=(0.25, 0.45, 0.333),
        standard_ratios={
            "dt_di": 3.0,
            "hl_di": 3.0,
            "li_di": 0.25,
            "wi_di": 0.20,
            "hi_di": 1.0,
            "wb_dt": 0.10,
            "baffles": 4,
        },
        turbulent_np=3.2,
        laminar_kl=60.0,
        pumping_nq=0.76,
        metzner_otto_ks=11.0,
        flooding_factor=75.0,  # 2.5x higher than Rushton 30.0
    ),
    ImpellerType.FLAT_BLADE_FBT: ImpellerEngineeringSpec(
        impeller_type=ImpellerType.FLAT_BLADE_FBT,
        display_name="Open Flat-Blade Turbine",
        model_code="Open FBT",
        clearance_class=ImpellerClearanceClass.OPEN_TURBINE,
        flow_direction=FlowDirection.RADIAL,
        construction=(
            "6 vertical rectangular blades welded directly to a small central hub without any horizontal disc. "
            "Blades extend inwards to the shaft."
        ),
        working_principle=(
            "Pure radial discharge through open hub zone without disc flow restriction. Liquid flows freely into "
            "the impeller eye from both above and below."
        ),
        applications=(
            "Rapid liquid-liquid blending, solvent extraction in bioseparations, neutralization reactions, and "
            "ungassed or lightly aerated microbial wash steps."
        ),
        limitations_and_advantages=(
            "High turbulent shear and radial pumping. Disadvantage: prone to premature gas flooding when "
            "aerated, as rising gas bubbles rise directly through open hub without being forced into blade tips."
        ),
        viscosity_min_cp=0.5,
        viscosity_max_cp=1000.0,
        viscosity_label="Below 1,000 cP",
        recommended_di_dt_range=(0.25, 0.50, 0.333),
        standard_ratios={
            "dt_di": 3.0,
            "hl_di": 3.0,
            "li_di": 0.35,
            "wi_di": 0.20,
            "hi_di": 1.0,
            "wb_dt": 0.10,
            "baffles": 4,
            "note": "Section 6 comparison table: D_T/D_i = 3.0, H_L/D_T = 3.0",
        },
        turbulent_np=4.0,
        laminar_kl=65.0,
        pumping_nq=0.70,
        metzner_otto_ks=11.5,
        flooding_factor=30.0,
    ),
    ImpellerType.PADDLE_R200: ImpellerEngineeringSpec(
        impeller_type=ImpellerType.PADDLE_R200,
        display_name="Two-Blade / Four-Blade Flat Paddle",
        model_code="R-200",
        clearance_class=ImpellerClearanceClass.OPEN_TURBINE,
        flow_direction=FlowDirection.RADIAL,
        construction=(
            "Two or four wide flat vertical blades spanning a large fraction of vessel diameter (Di/T = 0.50 to 0.80). "
            "Large blade height: W_i / D_i = 0.25."
        ),
        working_principle=(
            "Rotates at moderate-to-low rotational speeds (20-150 RPM), pushing liquid outward radially and "
            "tangentially across a broad vessel swath."
        ),
        applications=(
            "Crystallization of biopharmaceuticals, starch gelatinization, enzymatic saccharification, and "
            "moderate-viscosity broths (1,000 to 10,000 cP) where low shear and gentle turnover are desired."
        ),
        limitations_and_advantages=(
            "Gentle shear profile, avoids cell attrition in shear-fragile suspensions. Disadvantage: poor axial "
            "top-to-bottom turnover unless used with wall baffles or tilted blades."
        ),
        viscosity_min_cp=100.0,
        viscosity_max_cp=10000.0,
        viscosity_label="100 to 10,000 cP (Medium viscosity broths)",
        recommended_di_dt_range=(0.40, 0.85, 0.60),
        standard_ratios={
            "dt_di": 1.67,
            "hl_di": 3.0,
            "li_di": 0.40,
            "wi_di": 0.25,
            "hi_di": 1.0,
            "wb_dt": 0.10,
            "baffles": 4,
            "note": "Section 6 comparison table: D_T/D_i = 1.67, W_i/D_i = 0.25",
        },
        turbulent_np=2.0,
        laminar_kl=50.0,
        pumping_nq=0.65,
        metzner_otto_ks=10.0,
        flooding_factor=22.0,
    ),
    ImpellerType.CURVED_BACKSWEPT: ImpellerEngineeringSpec(
        impeller_type=ImpellerType.CURVED_BACKSWEPT,
        display_name="Backswept / Curved-Blade Turbine",
        model_code="Backswept Turbine",
        clearance_class=ImpellerClearanceClass.OPEN_TURBINE,
        flow_direction=FlowDirection.RADIAL,
        construction=(
            "Central disc or hub with 6 backward-curving convex arc blades swept away from rotation direction. "
            "Curved profile sheds debris radially."
        ),
        working_principle=(
            "Produces radial flow with gentle velocity gradients along blade tips. The trailing curvature prevents "
            "fibrous or mycelial biomass from hooking onto the leading edge."
        ),
        applications=(
            "Filamentous fungal fermentations (Penicillium chrysogenum, Aspergillus oryzae, Streptomyces), "
            "cellulosic biomass hydrolysates, and media containing fibrous insoluble plant matter."
        ),
        limitations_and_advantages=(
            "Prevents mycelial ragging and clumping on impeller hub; operates with ~20% lower power consumption "
            "than Rushton (Np ~ 4.0). Disadvantage: lower gas dispersion efficiency than CD-6."
        ),
        viscosity_min_cp=1.0,
        viscosity_max_cp=3000.0,
        viscosity_label="Below 3,000 cP",
        recommended_di_dt_range=(0.25, 0.45, 0.333),
        standard_ratios={
            "dt_di": 3.0,
            "hl_di": 3.0,
            "li_di": 0.25,
            "wi_di": 0.20,
            "hi_di": 1.0,
            "wb_dt": 0.10,
            "baffles": 4,
        },
        turbulent_np=4.0,
        laminar_kl=55.0,
        pumping_nq=0.74,
        metzner_otto_ks=11.0,
        flooding_factor=30.0,
    ),
    ImpellerType.RETREAT_BLADE: ImpellerEngineeringSpec(
        impeller_type=ImpellerType.RETREAT_BLADE,
        display_name="Pfaudler Retreat-Blade Impeller",
        model_code="Retreat-Blade",
        clearance_class=ImpellerClearanceClass.OPEN_TURBINE,
        flow_direction=FlowDirection.RADIAL,
        construction=(
            "3 curved blades curved backward from the direction of rotation, positioned very close to bottom dish "
            "head (H_i/T = 0.04-0.10). Typically glass-lined steel construction."
        ),
        working_principle=(
            "Sweeps liquid along vessel bottom contour, discharging in a combined radial-tangential pattern. "
            "Operates with a single glass-lined beaver-tail or finger baffle suspended from vessel top nozzle."
        ),
        applications=(
            "Corrosive, acidic, or ultra-pure biopharmaceutical synthesis in glass-lined reactors, crystallization, "
            "and active pharmaceutical ingredient (API) precipitations."
        ),
        limitations_and_advantages=(
            "Glass-lined corrosion resistance; cleanable bottom sweep prevents solid caking on bottom apex. "
            "Disadvantage: lower mixing intensity and lower mass transfer rate than disc turbines."
        ),
        viscosity_min_cp=1.0,
        viscosity_max_cp=5000.0,
        viscosity_label="Below 5,000 cP",
        recommended_di_dt_range=(0.40, 0.70, 0.55),
        standard_ratios={
            "dt_di": 1.82,
            "hl_di": 2.5,
            "li_di": 0.30,
            "wi_di": 0.15,
            "hi_di": 0.25,
            "wb_dt": 0.08,
            "baffles": 1,
            "note": "Glass-lined vessel with single beaver-tail baffle",
        },
        turbulent_np=3.1,
        laminar_kl=48.0,
        pumping_nq=0.68,
        metzner_otto_ks=10.5,
        flooding_factor=22.0,
    ),

    # -------------------------------------------------------------------------
    # A2. Open Axial & Mixed-Flow Impellers
    # -------------------------------------------------------------------------
    ImpellerType.MARINE_PROPELLER: ImpellerEngineeringSpec(
        impeller_type=ImpellerType.MARINE_PROPELLER,
        display_name="Marine-Type Axial Propeller",
        model_code="JP-3",
        clearance_class=ImpellerClearanceClass.OPEN_TURBINE,
        flow_direction=FlowDirection.AXIAL,
        construction=(
            "3 tapered hydrofoil blades with constant helical pitch, cast as one solid piece. "
            "Standard square pitch ratio: pitch / D_i = 1.0."
        ),
        working_principle=(
            "Pumps liquid axially downward along shaft centerline toward vessel bottom, creating a primary "
            "circulation loop that rises along the walls. High axial velocity per unit power."
        ),
        applications=(
            "Low-viscosity blending, mobile pilot vessels, gentle mammalian cell suspension culture at low RPM, "
            "and media buffer preparation at high motor speeds (up to 1,750 RPM)."
        ),
        limitations_and_advantages=(
            "Low power number (Np = 0.35) and high pumping velocity. Disadvantage: strictly limited to low-viscosity "
            "fluids (< 200 cP). Above 200 cP, blades slip and cavitation/overheating occurs without bulk fluid turnover."
        ),
        viscosity_min_cp=0.3,
        viscosity_max_cp=200.0,
        viscosity_label="Below 200 cP (recommended upper operating limit)",
        recommended_di_dt_range=(0.15, 0.35, 0.25),
        standard_ratios={
            "dt_di": 4.0,
            "hl_di": 4.0,
            "li_di": 0.35,
            "wi_di": 0.25,
            "hi_di": 1.0,
            "wb_dt": 0.10,
            "baffles": 4,
            "note": "Section 6 comparison table: D_T/D_i = 4.0, H_L/D_T = 3.0",
        },
        turbulent_np=0.35,
        laminar_kl=40.0,
        pumping_nq=0.55,
        metzner_otto_ks=8.5,
        flooding_factor=15.0,
    ),
    ImpellerType.PITCHED_BLADE_45: ImpellerEngineeringSpec(
        impeller_type=ImpellerType.PITCHED_BLADE_45,
        display_name="45° Pitched-Blade Turbine (PBT)",
        model_code="PBT-45",
        clearance_class=ImpellerClearanceClass.OPEN_TURBINE,
        flow_direction=FlowDirection.MIXED_AXIAL,
        construction=(
            "Central hub with 4 to 6 flat blades inclined at 45° angle to the horizontal plane. "
            "Blade width W_i / D_i = 0.20."
        ),
        working_principle=(
            "Combines downward axial discharge with an outward radial component for off-bottom solid suspension "
            "and general liquid blending."
        ),
        applications=(
            "Suspension of solid microcarriers in mammalian cell bioprocesses, secondary upper impeller in dual-stage "
            "aerated fermenters, and general bioprocess broth blending."
        ),
        limitations_and_advantages=(
            "Versatile compromise between axial circulation and radial shear (Np = 1.5). Disadvantage: prone to "
            "flow reversal (downflow stalling) under heavy gas sparging if gas velocity exceeds pumping velocity."
        ),
        viscosity_min_cp=0.5,
        viscosity_max_cp=5000.0,
        viscosity_label="Below 5,000 cP",
        recommended_di_dt_range=(0.25, 0.50, 0.333),
        standard_ratios={
            "dt_di": 3.0,
            "hl_di": 3.0,
            "li_di": 0.35,
            "wi_di": 0.20,
            "hi_di": 1.0,
            "wb_dt": 0.10,
            "baffles": 4,
        },
        turbulent_np=1.5,
        laminar_kl=44.0,
        pumping_nq=0.79,
        metzner_otto_ks=10.5,
        flooding_factor=15.0,
    ),
    ImpellerType.HYDROFOIL_HE3: ImpellerEngineeringSpec(
        impeller_type=ImpellerType.HYDROFOIL_HE3,
        display_name="Chemineer HE-3 / Lightnin A-310 Fluidfoil",
        model_code="HE-3 / A-310",
        clearance_class=ImpellerClearanceClass.OPEN_TURBINE,
        flow_direction=FlowDirection.AXIAL,
        construction=(
            "3 cambered, variable-pitch narrow airfoil blades with low blade solidity ratio. "
            "Angle of attack twists from steep near hub to shallow (~25°) at the blade tip."
        ),
        working_principle=(
            "Generates downward axial flow with low boundary layer separation and small trailing vortices."
        ),
        applications=(
            "Shear-sensitive animal cell cultures (CHO, Vero, HEK293), monoclonal antibody (mAb) manufacturing, "
            "plant cell suspensions, and vaccine production."
        ),
        limitations_and_advantages=(
            "Low turbulent shear dissipation and minimal Power Number (Np ~ 0.29). High axial pumping "
            "efficiency per Watt. Disadvantage: very poor gas dispersion; sparged gas bypasses narrow hydrofoil."
        ),
        viscosity_min_cp=0.5,
        viscosity_max_cp=1500.0,
        viscosity_label="Below 1,500 cP",
        recommended_di_dt_range=(0.25, 0.45, 0.35),
        standard_ratios={
            "dt_di": 2.85,
            "hl_di": 3.0,
            "li_di": 0.35,
            "wi_di": 0.16,
            "hi_di": 1.0,
            "wb_dt": 0.10,
            "baffles": 4,
        },
        turbulent_np=0.29,
        laminar_kl=36.0,
        pumping_nq=0.52,
        metzner_otto_ks=7.5,
        flooding_factor=12.0,
    ),
    ImpellerType.MAXFLO_HIGH_SOLIDITY: ImpellerEngineeringSpec(
        impeller_type=ImpellerType.MAXFLO_HIGH_SOLIDITY,
        display_name="High-Solidity Hydrofoil (Lightnin A-320 / Maxflo)",
        model_code="A-320 / Maxflo",
        clearance_class=ImpellerClearanceClass.OPEN_TURBINE,
        flow_direction=FlowDirection.MIXED_AXIAL,
        construction=(
            "4 to 6 wide, overlapping high-solidity cambered hydrofoil blades covering >80% of projected swept area. "
            "Wide chord blades with aerodynamic twist."
        ),
        working_principle=(
            "Combines axial downflow pumping with high blade surface coverage, suppressing gas bubble bypass "
            "across blade passages."
        ),
        applications=(
            "Aerated fermentations with moderate gas flow (0.5-1.5 vvm), viscous non-Newtonian broths, and retrofitting "
            "existing Rushton bioreactors to reduce power consumption by 30-40%."
        ),
        limitations_and_advantages=(
            "Operates at ~66% the power draw of a Rushton turbine (Np ~ 3.3) while delivering exceptional gas dispersion "
            "without forming massive gas cavities. 1.8x higher gas flooding resistance than standard PBT."
        ),
        viscosity_min_cp=1.0,
        viscosity_max_cp=10000.0,
        viscosity_label="Below 10,000 cP",
        recommended_di_dt_range=(0.35, 0.55, 0.45),
        standard_ratios={
            "dt_di": 2.22,
            "hl_di": 2.5,
            "li_di": 0.35,
            "wi_di": 0.28,
            "hi_di": 1.0,
            "wb_dt": 0.10,
            "baffles": 4,
        },
        turbulent_np=3.3,
        laminar_kl=52.0,
        pumping_nq=0.85,
        metzner_otto_ks=10.0,
        flooding_factor=27.0,  # 1.8x higher than standard axial
    ),
    ImpellerType.INTERMIG_EKATO: ImpellerEngineeringSpec(
        impeller_type=ImpellerType.INTERMIG_EKATO,
        display_name="EKATO Intermig Multistage Agitator",
        model_code="EKATO Intermig",
        clearance_class=ImpellerClearanceClass.OPEN_TURBINE,
        flow_direction=FlowDirection.AXIAL,
        construction=(
            "Multistage agitator assembly: each stage consists of 2 inner axial pumping blades with slotted outer "
            "finger-tip winglets staggered 90° between consecutive stages (Di/T = 0.60 to 0.70)."
        ),
        working_principle=(
            "Inner blades pump liquid downward axially, while slotted tip winglets induce localized shear "
            "and outward radial jetting. Multi-stage counter-orientation breaks vertical staging dead zones."
        ),
        applications=(
            "Highly viscous, pseudoplastic mycelial fermentation broths (Aspergillus niger, Penicillium chrysogenum, "
            "actinomycetes) where standard impellers form cavern dead zones."
        ),
        limitations_and_advantages=(
            "Uniform power dissipation throughout vessel height; low power number (Np = 0.65 per stage). "
            "Disadvantage: requires multiple stages (2-4) along shaft; complex fabrication and cleaning validation."
        ),
        viscosity_min_cp=500.0,
        viscosity_max_cp=50000.0,
        viscosity_label="500 to 50,000 cP (Viscous mycelial fermentations)",
        recommended_di_dt_range=(0.55, 0.75, 0.65),
        standard_ratios={
            "dt_di": 1.54,
            "hl_di": 2.5,
            "li_di": 0.45,
            "wi_di": 0.22,
            "hi_di": 0.75,
            "wb_dt": 0.08,
            "baffles": 4,
            "note": "Requires 2+ stages on single shaft for inter-stage axial exchange",
        },
        turbulent_np=0.65,
        laminar_kl=35.0,
        pumping_nq=0.75,
        metzner_otto_ks=8.0,
        flooding_factor=18.0,
    ),

    # -------------------------------------------------------------------------
    # B. Close-Clearance Impellers (Unbaffled, High Viscosity)
    # -------------------------------------------------------------------------
    ImpellerType.ANCHOR: ImpellerEngineeringSpec(
        impeller_type=ImpellerType.ANCHOR,
        display_name="Anchor Wall-Sweeping Agitator",
        model_code="Anchor",
        clearance_class=ImpellerClearanceClass.CLOSE_CLEARANCE,
        flow_direction=FlowDirection.CLOSE_CLEARANCE_TANGENTIAL,
        construction=(
            "U-shaped frame conforming closely to vessel bottom dish profile and vertical walls. "
            "Wall clearance gap is only 1 to 5 cm (Di/T = 0.90 to 0.96). Operates in unbaffled vessels."
        ),
        working_principle=(
            "Rotates at 10 to 80 RPM to sweep the thermal boundary layer along vessel walls, generating "
            "tangential shear and upward boundary flow."
        ),
        applications=(
            "High-viscosity microbial broths (5,000 to 50,000 cP), fermentation jacket heat transfer, "
            "biopolymer concentration, and preventing wall scaling/biofilm accumulation."
        ),
        limitations_and_advantages=(
            "Exceptional heat transfer enhancement through vessel wall cooling jackets. Disadvantage: poor axial "
            "circulation; above 50,000 cP, central fluid core slips and remains stagnant without internal crossbars."
        ),
        viscosity_min_cp=5000.0,
        viscosity_max_cp=50000.0,
        viscosity_label="5,000 to 50,000 cP (High viscosity wall sweep)",
        recommended_di_dt_range=(0.85, 0.98, 0.92),
        standard_ratios={
            "dt_di": 1.08,
            "hl_di": 1.2,
            "li_di": 0.45,
            "wi_di": 0.60,
            "hi_di": 0.05,
            "wb_dt": 0.0,
            "baffles": 0,
            "note": "Unbaffled tank, 1-5 cm wall clearance for heat transfer scraping",
        },
        turbulent_np=0.45,
        laminar_kl=150.0,
        pumping_nq=0.35,
        metzner_otto_ks=25.0,
        flooding_factor=10.0,
    ),
    ImpellerType.HELICAL_RIBBON: ImpellerEngineeringSpec(
        impeller_type=ImpellerType.HELICAL_RIBBON,
        display_name="Double Helical Ribbon Agitator",
        model_code="Helical Ribbon",
        clearance_class=ImpellerClearanceClass.CLOSE_CLEARANCE,
        flow_direction=FlowDirection.CLOSE_CLEARANCE_TANGENTIAL,
        construction=(
            "Single or double continuous spiral ribbon flight running along inner vessel wall with small wall gap "
            "(Di/T = 0.92 to 0.96). Standard dimensionless pitch s / Di = 0.50."
        ),
        working_principle=(
            "Rotates at 5 to 40 RPM, lifting viscous fluid upward along walls and returning fluid downward "
            "along the central shaft."
        ),
        applications=(
            "Ultra-high viscosity pseudoplastic biopolymer broths (Xanthan gum, Gellan, Pullulan, Hyaluronic acid) "
            "and fermentation broths from 30,000 cP up to 25,000,000 cP in laminar regime."
        ),
        limitations_and_advantages=(
            "Gold standard for ultra-viscous biopolymer mixing. Top-to-bottom liquid circulation with zero dead zones. "
            "Disadvantage: high capital and fabrication cost; low rotational speed restricts oxygen transfer."
        ),
        viscosity_min_cp=30000.0,
        viscosity_max_cp=25000000.0,
        viscosity_label="30,000 to 25,000,000 cP (Ultra-high viscosity biopolymers)",
        recommended_di_dt_range=(0.88, 0.98, 0.94),
        standard_ratios={
            "dt_di": 1.06,
            "hl_di": 1.2,
            "li_di": 0.45,
            "wi_di": 0.80,
            "hi_di": 0.05,
            "wb_dt": 0.0,
            "baffles": 0,
            "pitch_di": 0.50,
            "note": "Standard pitch s/D_i = 0.50, unbaffled tank",
        },
        turbulent_np=0.40,
        laminar_kl=300.0,
        pumping_nq=0.45,
        metzner_otto_ks=30.0,
        flooding_factor=8.0,
    ),
    ImpellerType.AUGER_SCREW: ImpellerEngineeringSpec(
        impeller_type=ImpellerType.AUGER_SCREW,
        display_name="Archimedes Helical Auger Screw",
        model_code="Auger Screw",
        clearance_class=ImpellerClearanceClass.CLOSE_CLEARANCE,
        flow_direction=FlowDirection.CLOSE_CLEARANCE_TANGENTIAL,
        construction=(
            "Continuous 2.0-turn helical screw flight mounted on central rotating shaft with tapered "
            "blade thickness for high-solids axial positive displacement."
        ),
        working_principle=(
            "Displaces high-solids slurry and dense pastes axially along the core with continuous bulk recirculation."
        ),
        applications=(
            "High-solids lignocellulosic biomass hydrolysates, fungal mycelial pellet slurries, seed train paste "
            "inoculation, and non-flowing dense biological suspensions."
        ),
        limitations_and_advantages=(
            "Overcomes yield stress in thick non-Newtonian pastes without stagnant dead zones. High axial pumping efficiency."
        ),
        viscosity_min_cp=10000.0,
        viscosity_max_cp=500000.0,
        viscosity_label="10,000 to 500,000 cP (High-solids biomass slurries)",
        recommended_di_dt_range=(0.30, 0.60, 0.45),
        standard_ratios={
            "dt_di": 2.2,
            "hl_di": 2.0,
            "li_di": 0.45,
            "wi_di": 0.70,
            "hi_di": 0.08,
            "wb_dt": 0.0,
            "baffles": 0,
            "note": "Requires cylindrical draft tube for closed-loop axial displacement",
        },
        turbulent_np=0.80,
        laminar_kl=200.0,
        pumping_nq=0.50,
        metzner_otto_ks=22.0,
        flooding_factor=10.0,
    ),
    ImpellerType.GATE_IMPELLER: ImpellerEngineeringSpec(
        impeller_type=ImpellerType.GATE_IMPELLER,
        display_name="Gate Anchor",
        model_code="Gate Anchor",
        clearance_class=ImpellerClearanceClass.CLOSE_CLEARANCE,
        flow_direction=FlowDirection.CLOSE_CLEARANCE_TANGENTIAL,
        construction=(
            "Wide rectangular frame with multiple horizontal and vertical crossbars spanning the tank diameter. "
            "Outer frame sweeps close to tank walls."
        ),
        working_principle=(
            "Distributes shear and bulk displacement across the entire fluid cross section at low RPM. "
            "Horizontal crossbars disrupt cavern formation in pseudoplastic broths."
        ),
        applications=(
            "Wide, squat bioreactors (H/T ~ 1.0), biopolymer blending, cosmetic & pharmaceutical ointment bases, "
            "and viscous anaerobic digestions."
        ),
        limitations_and_advantages=(
            "High structural rigidity; effective shearing across entire diameter in shallow tanks. "
            "Disadvantage: very high torque requirement; poor performance in tall bioreactors (H/T > 1.5)."
        ),
        viscosity_min_cp=5000.0,
        viscosity_max_cp=100000.0,
        viscosity_label="5,000 to 100,000 cP (Squat tank biopolymer mixing)",
        recommended_di_dt_range=(0.80, 0.95, 0.90),
        standard_ratios={
            "dt_di": 1.11,
            "hl_di": 1.0,
            "li_di": 0.45,
            "wi_di": 0.65,
            "hi_di": 0.05,
            "wb_dt": 0.0,
            "baffles": 0,
            "note": "Optimized for squat tanks H/T <= 1.2",
        },
        turbulent_np=1.8,
        laminar_kl=180.0,
        pumping_nq=0.40,
        metzner_otto_ks=26.0,
        flooding_factor=10.0,
    ),
    ImpellerType.SIGMA_Z_KNEADER: ImpellerEngineeringSpec(
        impeller_type=ImpellerType.SIGMA_Z_KNEADER,
        display_name="Z-Blade & Sigma Counter-Rotating Kneader",
        model_code="Sigma / Z-Blade",
        clearance_class=ImpellerClearanceClass.CLOSE_CLEARANCE,
        flow_direction=FlowDirection.CLOSE_CLEARANCE_TANGENTIAL,
        construction=(
            "Two heavy counter-rotating Z-shaped or Sigma-shaped saddle arms rotating at differential speeds "
            "(typically 5:3 or 3:2 ratio) within a double-U trough."
        ),
        working_principle=(
            "Generates extreme compressive, elongational, and high-shear kneading forces between saddle arms and "
            "trough walls, pulling, folding, and masticating ultra-dense pastes."
        ),
        applications=(
            "Ultra-dense mycelial cakes, extrusion paste preparation, microbial wet biomass compounding, and "
            "viscous bio-doughs (up to 50,000,000 cP)."
        ),
        limitations_and_advantages=(
            "Only agitator topology capable of processing non-flowable biological pastes. Disadvantage: extremely "
            "high motor torque and energy input; discontinuous batch discharge."
        ),
        viscosity_min_cp=100000.0,
        viscosity_max_cp=50000000.0,
        viscosity_label="100,000 to 50,000,000 cP (Non-flowable bio-pastes & doughs)",
        recommended_di_dt_range=(0.80, 0.95, 0.88),
        standard_ratios={
            "dt_di": 1.14,
            "hl_di": 1.0,
            "li_di": 0.45,
            "wi_di": 0.40,
            "hi_di": 0.04,
            "wb_dt": 0.0,
            "baffles": 0,
            "note": "Dual counter-rotating shafts in saddle trough",
        },
        turbulent_np=3.5,
        laminar_kl=400.0,
        pumping_nq=0.30,
        metzner_otto_ks=35.0,
        flooding_factor=8.0,
    ),
}

# Backward-compatible catalog alias
IMPELLER_BPE_CATALOG = IMPELLER_ENGINEERING_CATALOG


def get_catalog_entry(imp_type: Any) -> Optional[ImpellerEngineeringSpec]:
    """Retrieve catalog specification supporting both ImpellerType and string keys."""
    if isinstance(imp_type, ImpellerType):
        return IMPELLER_ENGINEERING_CATALOG.get(imp_type)
    if isinstance(imp_type, str):
        try:
            return IMPELLER_ENGINEERING_CATALOG.get(ImpellerType(imp_type))
        except ValueError:
            for k, v in IMPELLER_ENGINEERING_CATALOG.items():
                if k.value == imp_type:
                    return v
    return None


# =============================================================================
# Automated Engineering Suitability Advisor
# =============================================================================

def evaluate_bpe_suitability(
    tank: TankGeometry,
    fluid: FluidProperties,
    ops: OperatingConditions,
) -> List[Dict[str, Any]]:
    """Evaluate a bioreactor configuration against engineering reference ranges.

    Checks:
    1. Broth viscosity (cP) vs. recommended operational limits.
    2. Wall baffle compatibility (Close-clearance vs. Open turbine).
    3. Impeller diameter ratio D_i / T against recommended design ranges.
    4. Tip speed and shear dissipation against cell line sensitivity (Microbial vs Plant vs Mammalian).
    5. Gas dispersion capacity and flooding risk under current aeration.

    Returns
    -------
    List[Dict[str, Any]]
        List of structured diagnostic alerts with 'level', 'code', 'title', and 'message'.
    """
    alerts: List[Dict[str, Any]] = []
    T = tank.diameter_m
    visc_cp = fluid.viscosity_pa_s * 1000.0

    for i, imp in enumerate(tank.impellers):
        entry = get_catalog_entry(imp.impeller_type)
        if entry is None:
            continue

        di = imp.diameter_m
        ratio = di / T
        tag = f"Stage {i + 1} ({entry.display_name})"

        # 1. Viscosity Envelope Check
        if visc_cp > entry.viscosity_max_cp:
            alerts.append({
                "level": "warning",
                "code": "ENG_VISCOSITY_EXCEEDED",
                "title": f"Viscosity Limit Exceeded for {entry.model_code}",
                "message": (
                    f"{tag}: Operating broth viscosity is {visc_cp:,.1f} cP, exceeding the recommended "
                    f"operational ceiling of {entry.viscosity_max_cp:,.0f} cP ({entry.viscosity_label}). "
                    f"Hydrodynamic slipping, severe flow cavern formation, and motor stalling may occur."
                ),
            })
        elif visc_cp < entry.viscosity_min_cp and entry.clearance_class == ImpellerClearanceClass.CLOSE_CLEARANCE:
            alerts.append({
                "level": "info",
                "code": "ENG_VISCOSITY_LOW_FOR_CLASS",
                "title": f"Low Viscosity for Close-Clearance Agitator",
                "message": (
                    f"{tag}: Broth viscosity is {visc_cp:,.1f} cP. Close-clearance {entry.model_code} is "
                    f"engineered for viscous fluids (> {entry.viscosity_min_cp:,.0f} cP). "
                    f"An open axial or radial turbine provides faster mixing kinetics at lower power draw."
                ),
            })

        # 2. Baffle Compatibility Check
        if entry.clearance_class == ImpellerClearanceClass.CLOSE_CLEARANCE and tank.is_baffled:
            alerts.append({
                "level": "warning",
                "code": "ENG_BAFFLE_OBSTRUCTION",
                "title": f"Close-Clearance Impeller in Baffled Tank",
                "message": (
                    f"{tag}: {entry.display_name} has outer diameter Di = {di:.3f} m (Di/T = {ratio:.2f}) "
                    f"and operates with a 1-5 cm wall sweep in UNBAFFLED vessels. Tank has {tank.baffle_count} baffles "
                    f"with width W = {tank.baffle_width_m:.3f} m, causing physical mechanical interference!"
                ),
            })
        elif entry.clearance_class == ImpellerClearanceClass.OPEN_TURBINE and not tank.is_baffled and ops.rpm > 120.0:
            alerts.append({
                "level": "info",
                "code": "ENG_UNBAFFLED_VORTEX_SWIRL",
                "title": f"Open Turbine in Unbaffled Vessel",
                "message": (
                    f"{tag}: Tangential swirl forms a central surface vortex and reduces shaft power draw by 30-50%."
                ),
            })

        # 3. Impeller Diameter Ratio Check
        min_r, max_r, std_r = entry.recommended_di_dt_range
        if ratio < min_r or ratio > max_r:
            alerts.append({
                "level": "warning",
                "code": "ENG_DIAMETER_RATIO_SUBOPTIMAL",
                "title": f"Non-Standard Di/T Ratio for {entry.model_code}",
                "message": (
                    f"{tag}: Selected Di/T ratio is {ratio:.3f}. Recommended design-envelope range is "
                    f"[{min_r:.2f}, {max_r:.2f}] (standard design ratio = {std_r:.3f})."
                ),
            })

        # 4. Tip Speed & Shear Sensitivity Check
        v_tip = 3.14159265 * ops.rps * di
        max_allowed_tip = ops.cell_type.max_tip_speed_m_s
        if v_tip > max_allowed_tip:
            alerts.append({
                "level": "warning",
                "code": "ENG_SHEAR_SENSITIVITY_EXCEEDED",
                "title": f"Impeller Tip Speed Exceeds {ops.cell_type.value.capitalize()} Limit",
                "message": (
                    f"{tag}: Peripheral tip speed is {v_tip:.2f} m/s, exceeding the critical shear "
                    f"damage threshold of {max_allowed_tip:.2f} m/s for {ops.cell_type.value}. "
                    f"Cell lysis, membrane rupture, or viability loss will occur."
                ),
            })

        # 5. Gas Flooding Risk Check
        if ops.aeration_vvm > 0 and ops.rps > 0 and i == 0:
            q_g = (ops.aeration_vvm * tank.working_volume_m3) / 60.0
            fl_g = q_g / (ops.rps * (di ** 3))
            fr = ((ops.rps ** 2) * di) / 9.81
            fl_flood = 30.0 * ((di / tank.diameter_m) ** 3.5) * fr
            if fl_g > fl_flood:
                alerts.append({
                    "level": "warning",
                    "code": "ENG_FLOODING_RISK",
                    "title": f"Gas Flooding Risk on Primary Disperser ({entry.model_code})",
                    "message": (
                        f"{tag}: Aeration flow number Fl_g = {fl_g:.4f} exceeds flooding limit "
                        f"Fl_flood = {fl_flood:.4f}. Impeller cavities are flooded; mass transfer "
                        f"will drop sharply and power draw will become unstable."
                    ),
                })

    # If no warnings triggered, provide positive confirmation
    if not any(a["level"] == "warning" for a in alerts):
        imp_names = [
            (get_catalog_entry(imp.impeller_type).display_name if get_catalog_entry(imp.impeller_type) else str(getattr(imp.impeller_type, "value", imp.impeller_type)))
            for imp in tank.impellers
        ]
        alerts.append({
            "level": "success",
            "code": "ENG_CONFIG_OPTIMAL",
            "title": "Engineering Configuration Within Design Envelope",
            "message": (
                f"Selected bioreactor geometry, impeller configuration ({', '.join(imp_names)}), "
                f"viscosity ({visc_cp:.1f} cP), and operating conditions conform to bioprocess engineering design standards."
            ),
        })

    return alerts


# =============================================================================
# Section 6: Standard Geometric Dimensions at HL / DT = 1.0 Comparison Table
# =============================================================================

SECTION_6_STANDARD_RATIOS_TABLE: Dict[str, Any] = {
    "title": "Recommended Geometric Design Dimensions",
    "hl_dt_reference": 1.0,
    "standard_rushton": {
        "dt_di": 3.0,
        "hl_di": 3.0,
        "li_di": 0.25,
        "wi_di": 0.20,
        "hi_di": 1.0,
        "wb_dt": 0.10,
        "baffles": 4,
    },
    "ratios": [

        {
            "parameter": "Tank Diameter to Impeller Ratio (D_T / D_i)",
            "symbol": "D_T / D_i",
            "rushton_r100": "3.0",
            "paddle_r200": "1.25 to 2.0 (std 1.67)",
            "marine_jp3": "3.0 to 5.0 (std 3.0)",
            "bpe_significance": "Defines swept core volume and discharge plume throw distance",
        },
        {
            "parameter": "Liquid Height to Impeller Ratio (H_L / D_i)",
            "symbol": "H_L / D_i",
            "rushton_r100": "3.0",
            "paddle_r200": "2.0 to 3.0",
            "marine_jp3": "3.0",
            "bpe_significance": "Determines requirement for multi-stage impeller staging (if H_L/D_T > 1.2)",
        },
        {
            "parameter": "Blade Length to Impeller Ratio (L_i / D_i)",
            "symbol": "L_i / D_i",
            "rushton_r100": "0.25 (1/4)",
            "paddle_r200": "0.25",
            "marine_jp3": "0.25",
            "bpe_significance": "Radial projection of blade from central horizontal disc or hub",
        },
        {
            "parameter": "Blade Width/Height to Impeller Ratio (W_i / D_i)",
            "symbol": "W_i / D_i",
            "rushton_r100": "0.20 (1/5)",
            "paddle_r200": "0.25 (1/4)",
            "marine_jp3": "0.20",
            "bpe_significance": "Vertical face area governing power draw and vortex cavity stability",
        },
        {
            "parameter": "Impeller Clearance to Impeller Ratio (H_i / D_i)",
            "symbol": "H_i / D_i",
            "rushton_r100": "1.0 (H_i = D_i = T/3)",
            "paddle_r200": "1.0",
            "marine_jp3": "1.0",
            "bpe_significance": "Bottom dish elevation to avoid stagnant settling or surface air entrainment",
        },
        {
            "parameter": "Baffle Width to Tank Diameter (W_b / D_T)",
            "symbol": "W_b / D_T",
            "rushton_r100": "0.10 (1/10)",
            "paddle_r200": "0.10",
            "marine_jp3": "0.10",
            "bpe_significance": "Full baffling suppresses tangential swirl and converts rotational kinetic energy to axial mixing",
        },
        {
            "parameter": "Standard Baffle Count",
            "symbol": "n_b",
            "rushton_r100": "4 (spaced 90°)",
            "paddle_r200": "4 (spaced 90°)",
            "marine_jp3": "4 (spaced 90°)",
            "bpe_significance": "Minimum 4 full-length vertical wall baffles for fully baffled operation",
        },
    ],
}


# =============================================================================
# Complete 16-Impeller Engineering Comparison Table
# =============================================================================

SECTION_7_QUICK_REVISION_TABLE: List[Dict[str, Any]] = [
    {
        "index": 1,
        "type": ImpellerType.RUSHTON_6_BLADE.value,
        "model_code": "R-100",
        "name": "Rushton 6-Blade Disc Turbine",
        "clearance_class": "Open Turbine",
        "flow": "Radial",
        "viscosity_range": "< 1,000 cP",
        "np": 5.20,
        "nq": 0.75,
        "primary_application": "High-aeration microbial fermentation (E. coli, yeast); intense gas dispersion",
    },
    {
        "index": 2,
        "type": ImpellerType.SMITH_CD6.value,
        "model_code": "CD-6 / R-130",
        "name": "Smith Concave Semi-Circular Turbine",
        "clearance_class": "Open Turbine",
        "flow": "Radial",
        "viscosity_range": "< 1,000 cP",
        "np": 3.20,
        "nq": 0.78,
        "primary_application": "Sparged gas fermentations; handles 2-3x gas flow before flooding vs Rushton",
    },
    {
        "index": 3,
        "type": ImpellerType.FLAT_BLADE_FBT.value,
        "model_code": "FBT",
        "name": "Open Flat-Blade Turbine",
        "clearance_class": "Open Turbine",
        "flow": "Radial",
        "viscosity_range": "< 1,000 cP",
        "np": 4.00,
        "nq": 0.70,
        "primary_application": "Radial mixing without central horizontal disc; sparged gas dispersion",
    },
    {
        "index": 4,
        "type": ImpellerType.PADDLE_R200.value,
        "model_code": "R-200",
        "name": "Two-Blade Paddle Impeller",
        "clearance_class": "Open Turbine",
        "flow": "Radial",
        "viscosity_range": "< 10,000 cP",
        "np": 2.50,
        "nq": 0.60,
        "primary_application": "Low-shear gentle liquid agitation, crystallization, moderate viscosity",
    },
    {
        "index": 5,
        "type": ImpellerType.CURVED_BACKSWEPT.value,
        "model_code": "Backswept",
        "name": "Curved-Blade Backswept Turbine",
        "clearance_class": "Open Turbine",
        "flow": "Radial",
        "viscosity_range": "< 5,000 cP",
        "np": 4.00,
        "nq": 0.72,
        "primary_application": "Prevents fibrous fungal mycelial buildup (Aspergillus, Penicillium)",
    },
    {
        "index": 6,
        "type": ImpellerType.RETREAT_BLADE.value,
        "model_code": "Pfaudler Retreat",
        "name": "Retreat-Blade Impeller",
        "clearance_class": "Open Turbine",
        "flow": "Radial",
        "viscosity_range": "< 5,000 cP",
        "np": 3.10,
        "nq": 0.55,
        "primary_application": "Glass-lined biopharma vessels; low dish clearance sweeping",
    },
    {
        "index": 7,
        "type": ImpellerType.MARINE_PROPELLER.value,
        "model_code": "JP-3",
        "name": "Marine-Type Axial Propeller",
        "clearance_class": "Open Turbine",
        "flow": "Axial",
        "viscosity_range": "< 200 cP",
        "np": 0.35,
        "nq": 0.50,
        "primary_application": "High-speed rapid top-to-bottom liquid circulation; thin broths only (<200 cP)",
    },
    {
        "index": 8,
        "type": ImpellerType.PITCHED_BLADE_45.value,
        "model_code": "PBT",
        "name": "45° Pitched-Blade Turbine",
        "clearance_class": "Open Turbine",
        "flow": "Mixed Axial",
        "viscosity_range": "< 25,000 cP",
        "np": 1.50,
        "nq": 0.79,
        "primary_application": "Bulk blending, solid suspension (microcarriers), heat transfer",
    },
    {
        "index": 9,
        "type": ImpellerType.HYDROFOIL_HE3.value,
        "model_code": "HE-3 / A-310",
        "name": "High-Efficiency Cambered Hydrofoil",
        "clearance_class": "Open Turbine",
        "flow": "Axial",
        "viscosity_range": "< 3,000 cP",
        "np": 0.29,
        "nq": 0.52,
        "primary_application": "Shear-sensitive animal/plant cell culture (CHO antibodies, viral vaccines)",
    },
    {
        "index": 10,
        "type": ImpellerType.MAXFLO_HIGH_SOLIDITY.value,
        "model_code": "A-320 / Maxflo",
        "name": "High-Solidity Wide-Blade Hydrofoil",
        "clearance_class": "Open Turbine",
        "flow": "Mixed Axial",
        "viscosity_range": "< 10,000 cP",
        "np": 3.30,
        "nq": 0.90,
        "primary_application": "Gas dispersion without severe cavity power drop; high gas holdup",
    },
    {
        "index": 11,
        "type": ImpellerType.INTERMIG_EKATO.value,
        "model_code": "EKATO Intermig",
        "name": "EKATO Intermig Multistage Agitator",
        "clearance_class": "Open Turbine",
        "flow": "Mixed Axial",
        "viscosity_range": "< 50,000 cP",
        "np": 0.65,
        "nq": 0.55,
        "primary_application": "High-aspect viscous mycelial fermentations; low power dissipation per stage",
    },
    {
        "index": 12,
        "type": ImpellerType.ANCHOR.value,
        "model_code": "Anchor",
        "name": "Close-Clearance Anchor Frame",
        "clearance_class": "Close Clearance",
        "flow": "Close Clearance Tangential",
        "viscosity_range": "5,000 to 50,000 cP",
        "np": 1.00,
        "nq": 0.20,
        "primary_application": "Jacketed wall heat transfer, eliminates boundary dead zones; unbaffled",
    },
    {
        "index": 13,
        "type": ImpellerType.HELICAL_RIBBON.value,
        "model_code": "Helical Ribbon",
        "name": "Helical Spiral Ribbon Impeller",
        "clearance_class": "Close Clearance",
        "flow": "Close Clearance Tangential",
        "viscosity_range": "30,000 to 25,000,000 cP",
        "np": 2.00,
        "nq": 0.40,
        "primary_application": "Non-Newtonian pseudoplastic biopolymers (Xanthan gum, hyaluronic acid)",
    },
    {
        "index": 14,
        "type": ImpellerType.AUGER_SCREW.value,
        "model_code": "Auger Screw",
        "name": "Helical Auger Screw Agitator",
        "clearance_class": "Close Clearance",
        "flow": "Close Clearance Tangential",
        "viscosity_range": "50,000 to 10,000,000 cP",
        "np": 1.80,
        "nq": 0.35,
        "primary_application": "High-viscosity pastes, heavy slurries, draft-tube axial Archimedean pumping",
    },
    {
        "index": 15,
        "type": ImpellerType.GATE_IMPELLER.value,
        "model_code": "Gate",
        "name": "Gate Frame Agitator",
        "clearance_class": "Close Clearance",
        "flow": "Close Clearance Tangential",
        "viscosity_range": "10,000 to 100,000 cP",
        "np": 2.20,
        "nq": 0.25,
        "primary_application": "Squat broad tanks, wide frame crossbar blending for viscous liquids",
    },
    {
        "index": 16,
        "type": ImpellerType.SIGMA_Z_KNEADER.value,
        "model_code": "Sigma / Z-Blade",
        "name": "Sigma / Z-Blade Kneader",
        "clearance_class": "Close Clearance",
        "flow": "Close Clearance Tangential",
        "viscosity_range": "100,000 to 50,000,000 cP",
        "np": 3.50,
        "nq": 0.30,
        "primary_application": "Non-flowable biological pastes, dense filter cakes, mycelial doughs",
    },
]

# Ensure SECTION_7_QUICK_REVISION_TABLE np and nq strictly match canonical catalog values
for _row in SECTION_7_QUICK_REVISION_TABLE:
    _it = ImpellerType(_row["type"])
    if _it in IMPELLER_ENGINEERING_CATALOG:
        _spec = IMPELLER_ENGINEERING_CATALOG[_it]
        _row["np"] = _spec.turbulent_np
        _row["nq"] = _spec.pumping_nq

