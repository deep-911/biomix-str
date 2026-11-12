"""Parametric 3D Bioreactor CAD & MRF Tetrahedral Mesher for Ansys Fluent 2026 R1.

Generates conformal, watertight 3D tetrahedral computational meshes of stirred-tank
bioreactors with Multiple Reference Frame (MRF) rotating zones, agitator shafts,
parametric impeller geometries (Rushton, Pitched Blade, Marine Propeller), and wall baffles
using Gmsh and OpenCASCADE. Exports Nastran BDF volumetric meshes for Ansys Fluent
and visual surface VTP meshes for interactive 3D web streaming.
"""

from __future__ import annotations

import math
import os
import time
from typing import Any, Dict, List, Literal, Optional, Tuple

import gmsh
import numpy as np
from pydantic import BaseModel, Field
try:
    import pyvista as pv
except (ImportError, Exception):
    pv = None

from biomix.models import (
    BottomType,
    ImpellerClearanceClass,
    ImpellerSpec,
    ImpellerType,
    TankGeometry,
)


class MeshedBioreactorArtifact(BaseModel):
    """Artifact metadata and file references for an automated 3D bioreactor mesh."""

    bdf_mesh_path: str = Field(description="Path to Nastran BDF volumetric mesh for Ansys Fluent")
    cad_vtp_path: str = Field(description="Path to VTP surface mesh for 3D web viewer")
    n_nodes: int = Field(ge=0, description="Total number of mesh nodes")
    n_cells: int = Field(ge=0, description="Total number of 3D tetrahedral fluid cells")
    n_cells_mrf: int = Field(default=0, ge=0, description="Number of cells in MRF rotating zone")
    n_cells_stationary: int = Field(default=0, ge=0, description="Number of cells in stationary zone")
    mrf_zone_names: List[str] = Field(description="Deterministic Fluent cell zone names for MRF rotating zones")
    stationary_zone_names: List[str] = Field(description="Deterministic Fluent cell zone names for stationary fluid")
    impeller_wall_names: List[str] = Field(description="Fluent boundary wall names on impeller blades/hub")
    vessel_wall_names: List[str] = Field(default_factory=list, description="Fluent boundary wall names on vessel walls")
    interface_wall_names: List[str] = Field(default_factory=list, description="Fluent boundary wall names on MRF fluid interfaces")
    meshing_time_s: float = Field(ge=0.0, description="Mesh generation and export execution time (s)")


class BioreactorCADMesher:
    """Parametric OpenCASCADE 3D CAD modeling and conformal meshing engine."""

    def __init__(self, terminal_output: bool = False):
        self.terminal_output = terminal_output

    def generate_fluent_mesh(
        self,
        tank: TankGeometry,
        mesh_density: Literal["fast", "medium", "fine"] = "fast",
        output_dir: Optional[str] = None,
        prefix: str = "bioreactor_3d",
        mrf_radius_factor: float = 0.62,
    ) -> MeshedBioreactorArtifact:
        """Construct parametric CAD geometry and generate a conformal 3D tetrahedral mesh.

        Parameters
        ----------
        tank : TankGeometry
            Validated reactor vessel anatomy and impeller specifications.
        mesh_density : Literal["fast", "medium", "fine"]
            Discretization level ('fast' for live web interactive solves, 'medium' or 'fine').
        output_dir : Optional[str]
            Target directory for .bdf and .vtp files (defaults to 'outputs/').
        prefix : str
            File name prefix for the generated artifacts.

        Returns
        -------
        MeshedBioreactorArtifact
            Mesh metadata including file paths and exact Fluent zone names.
        """
        start_time = time.perf_counter()

        if output_dir is None:
            output_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "outputs")
            )
        os.makedirs(output_dir, exist_ok=True)

        bdf_mesh_path = os.path.join(output_dir, f"{prefix}_mrf.bdf")
        cad_vtp_path = os.path.join(output_dir, f"{prefix}_surface.vtp")

        # 1. Initialize Gmsh (interruptible=False prevents signal.signal error on worker threads)
        gmsh.initialize(interruptible=False)
        gmsh.option.setNumber("General.Terminal", 1 if self.terminal_output else 0)
        gmsh.option.setNumber("General.Verbosity", 2 if self.terminal_output else 0)
        gmsh.option.setNumber("Mesh.SaveElementTagType", 2)  # Export Physical Group IDs (101, 102, 201, 202, 203) as Nastran PIDs
        gmsh.model.add("Bioreactor_MRF")

        try:
            # 2. Build Outer Vessel Solid
            vessel_solid_dimtags, dish_depth = self._build_vessel_cad(tank)

            # 3. Build Central Agitator Shaft
            shaft_solid_dimtag, shaft_radius = self._build_shaft_cad(tank)

            # 4. Build Wall Baffles (if vessel is baffled)
            baffle_solid_dimtags = self._build_baffles_cad(tank, dish_depth)

            # 5. Check if any close-clearance impeller is present (Anchor, Helical Ribbon, Auger, Gate, Sigma)
            is_close_clearance = any(
                (imp.impeller_type.clearance_class == ImpellerClearanceClass.CLOSE_CLEARANCE)
                for imp in tank.impellers
            )

            if is_close_clearance:
                if tank.baffle_count > 0:
                    raise ValueError(
                        f"Stationary wall baffles ({tank.baffle_count}) are physically invalid in a single-zone "
                        "rotating MRF domain for close-clearance impellers. Close-clearance impellers "
                        "require an unbaffled vessel (baffle_count = 0)."
                    )
                # Close-clearance: do not build separate inner MRF cylinder that collides with vessel wall
                # Instead, make the entire fluid volume a single rotating MRF zone
                tools_to_cut = list(baffle_solid_dimtags)
                if shaft_solid_dimtag is not None:
                    tools_to_cut.append(shaft_solid_dimtag)
                for imp in tank.impellers:
                    imp_solid = self._build_impeller_solid(tank, imp)
                    tools_to_cut.extend(imp_solid)

                vessel_cut, _ = gmsh.model.occ.cut(
                    vessel_solid_dimtags, tools_to_cut, removeTool=True
                )
                gmsh.model.occ.synchronize()

                # Keep the main fluid domain volume, remove any stray dead interior metal fragments
                if len(vessel_cut) > 1:
                    vol_masses = []
                    for dim, v_tag in vessel_cut:
                        mass = gmsh.model.occ.getMass(3, v_tag)
                        vol_masses.append((mass, v_tag))
                    vol_masses.sort(reverse=True)
                    main_vol_tag = vol_masses[0][1]
                    dead_vols = [(3, v_tag) for mass, v_tag in vol_masses[1:]]
                    if dead_vols:
                        gmsh.model.occ.remove(dead_vols, recursive=True)
                        gmsh.model.occ.synchronize()
                    mrf_tags = [main_vol_tag]
                else:
                    mrf_tags = [tag for dim, tag in vessel_cut]
                stationary_tags = []
            else:
                # 5b. Standard MRF Rotating Cylinders & Impellers
                mrf_volumes_info: List[Dict[str, Any]] = []
                for k, imp in enumerate(tank.impellers):
                    mrf_info = self._build_single_mrf_and_impeller(tank, imp, k, shaft_solid_dimtag, mrf_radius_factor=mrf_radius_factor)
                    mrf_volumes_info.append(mrf_info)

                # 6. Boolean Cuts on Vessel
                # Cut shaft and wall baffles from the outer vessel fluid solid
                tools_to_cut = list(baffle_solid_dimtags)
                if shaft_solid_dimtag is not None:
                    tools_to_cut.append(shaft_solid_dimtag)

                if tools_to_cut:
                    vessel_cut, _ = gmsh.model.occ.cut(
                        vessel_solid_dimtags, tools_to_cut, removeTool=True
                    )
                else:
                    vessel_cut = vessel_solid_dimtags

                # 7. Conformal Boolean Fragmentation
                # Fragment outer vessel fluid with all MRF fluid cylinder cuts
                all_mrf_cuts = [info["mrf_cut_dimtag"] for info in mrf_volumes_info]
                frag_solids, frag_map = gmsh.model.occ.fragment(vessel_cut, all_mrf_cuts)

                # Identify and remove dead metal solids left inside impeller voids from vessel_cut
                # These solids originate from vessel_cut but sit entirely inside the impeller cavity.
                # Removing them ensures the impeller is a true hollow void whose surfaces form the rotating wall!
                dead_solids = []
                for dim, tag in frag_map[0]:
                    bb = gmsh.model.occ.getBoundingBox(3, tag)
                    xmin, ymin, zmin, xmax, ymax, zmax = bb
                    max_xy = max(abs(xmin), abs(xmax), abs(ymin), abs(ymax))
                    for imp in tank.impellers:
                        Wb = imp.blade_width_m or (imp.diameter_m / 5.0)
                        W_eff = max(Wb, 0.50 * imp.diameter_m if imp.impeller_type == ImpellerType.INTERMIG_EKATO else Wb)
                        if max_xy <= 0.52 * imp.diameter_m and zmin >= (imp.clearance_m - 0.75 * W_eff) and zmax <= (imp.clearance_m + 0.75 * W_eff):
                            dead_solids.append((3, tag))

                if dead_solids:
                    gmsh.model.occ.remove(dead_solids, recursive=False)
                gmsh.model.occ.synchronize()

                # 8. Deterministic Zone Identification
                # Map index 0 is from vessel_cut; map indices 1..N are from each MRF cylinder
                mrf_tags = []
                for k in range(len(tank.impellers)):
                    mrf_tags_k = [tag for dim, tag in frag_map[1 + k]]
                    mrf_tags.extend(mrf_tags_k)

                stationary_tags = [tag for dim, tag in frag_map[0] if (3, tag) not in dead_solids and tag not in mrf_tags]

            # Assign Physical Groups for 3D fluid zones
            if mrf_tags:
                gmsh.model.addPhysicalGroup(3, mrf_tags, tag=101, name="fluid-mrf")
            if stationary_tags:
                gmsh.model.addPhysicalGroup(3, stationary_tags, tag=102, name="fluid-stationary")

            # 8b. Adjacency-Based 2D Surface Classification
            # Query all 2D surfaces to eliminate internal MRF CTRIA3 elements
            all_2d_surfs = gmsh.model.getEntities(2)
            internal_surf_tags: List[int] = []
            impeller_surf_tags: List[int] = []
            vessel_surf_tags: List[int] = []

            H = tank.liquid_height_m
            max_di = max(imp.diameter_m for imp in tank.impellers)

            for s_dim, s_tag in all_2d_surfs:
                upward, downward = gmsh.model.getAdjacencies(2, s_tag)
                if len(upward) == 2:
                    # Internal fluid interface between MRF cylinder and stationary tank volume!
                    # Must NEVER be exported as a CTRIA3 wall element in the .bdf file!
                    internal_surf_tags.append(s_tag)
                elif len(upward) == 1:
                    adj_vol = upward[0]
                    bb = gmsh.model.occ.getBoundingBox(2, s_tag)
                    xmin, ymin, zmin, xmax, ymax, zmax = bb
                    r_box_max = math.sqrt(max(abs(xmin), abs(xmax))**2 + max(abs(ymin), abs(ymax))**2)

                    is_impeller_wall = False
                    if is_close_clearance:
                        # Close-clearance: inner impeller framework, crossbars, and shaft
                        # Outer cylinder wall has r_box_max >= 0.495 * T.
                        # Surfaces with r_box_max < 0.490 * T are inner impeller members and shaft.
                        # Exclude vessel bottom head apex (zmax < 0.02 * H)
                        if r_box_max < 0.490 * tank.diameter_m and zmax >= 0.02 * H:
                            if not (zmin >= H - 0.002 and r_box_max > shaft_radius * 1.5):
                                is_impeller_wall = True
                    else:
                        # Open impellers: within 0.60 Di, or rotating shaft
                        if r_box_max <= shaft_radius * 1.5:
                            is_impeller_wall = True
                        else:
                            for imp in tank.impellers:
                                if r_box_max < 0.60 * imp.diameter_m and abs(zmin - imp.clearance_m) < 0.55 * imp.diameter_m:
                                    is_impeller_wall = True
                                    break

                    # Verify that the wall belongs to the MRF fluid or is an impeller member
                    if is_impeller_wall and (adj_vol in mrf_tags or (is_close_clearance and r_box_max < 0.490 * tank.diameter_m) or r_box_max <= shaft_radius * 1.5):
                        impeller_surf_tags.append(s_tag)
                    else:
                        vessel_surf_tags.append(s_tag)

            impeller_surf_tags = sorted(list(set(impeller_surf_tags)))
            vessel_surf_tags = sorted(list(set(vessel_surf_tags)))

            # Define 2D Physical Groups for walls and internal MRF interfaces (Task 1)
            # Gmsh exports CTRIA3 elements belonging to Physical Groups with their PID tag:
            # PID 201: wall-impeller, PID 202: wall-vessel, PID 203: interface-mrf
            if impeller_surf_tags:
                gmsh.model.addPhysicalGroup(2, impeller_surf_tags, tag=201, name="wall-impeller")
            if vessel_surf_tags:
                gmsh.model.addPhysicalGroup(2, vessel_surf_tags, tag=202, name="wall-vessel")
            if internal_surf_tags:
                gmsh.model.addPhysicalGroup(2, internal_surf_tags, tag=203, name="interface-mrf")

            # Deterministic zone names produced in Ansys Fluent Nastran BDF import
            # PID 101 -> solid-101, PID 102 -> solid-102
            # PID 201 -> wall-201, PID 202 -> wall-202, PID 203 -> wall-203 (and wall-203-shadow)
            mrf_zone_names = ["solid-101"] if mrf_tags else []
            stationary_zone_names = ["solid-102"] if stationary_tags else []
            impeller_wall_names = ["wall-201"] if impeller_surf_tags else []
            vessel_wall_names = ["wall-202"] if vessel_surf_tags else []
            interface_wall_names = ["wall-203"] if internal_surf_tags else []

            # 9. Mesh Sizing Controls
            density_key = str(mesh_density).lower().strip()
            density_aliases = {
                "coarse": "coarse",
                "fast": "fast",
                "standard": "medium",
                "medium": "medium",
                "med": "medium",
                "fine": "fine",
            }
            norm_density = density_aliases.get(density_key, "medium")
            lc_factors = {
                "coarse": (0.095, 0.130),
                "fast": (0.065, 0.090),
                "medium": (0.065, 0.090),
                "fine": (0.048, 0.068),
            }
            imp_scale, tank_scale = lc_factors.get(norm_density, (0.065, 0.090))

            min_imp_di = min(imp.diameter_m for imp in tank.impellers)
            lc_imp = imp_scale * min_imp_di
            lc_tank = tank_scale * tank.diameter_m

            gmsh.option.setNumber("Mesh.MeshSizeMin", lc_imp * 0.70)
            gmsh.option.setNumber("Mesh.MeshSizeMax", lc_tank * 1.25)
            gmsh.option.setNumber("Mesh.Algorithm", 6)  # Frontal-Delaunay for 2D
            gmsh.option.setNumber("Mesh.Algorithm3D", 1)  # Delaunay for 3D
            gmsh.option.setNumber("Mesh.Optimize", 1)
            gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)

            # Apply local sizing to boundary points of MRF vs outer tank vs impeller blades
            mrf_dimtags = [(3, t) for t in mrf_tags]
            stat_dimtags = [(3, t) for t in stationary_tags]
            imp_dimtags = [(2, t) for t in impeller_surf_tags]

            mrf_pts = gmsh.model.getBoundary(mrf_dimtags, combined=False, recursive=True) if mrf_dimtags else []
            stat_pts = gmsh.model.getBoundary(stat_dimtags, combined=False, recursive=True) if stat_dimtags else []
            imp_pts = gmsh.model.getBoundary(imp_dimtags, combined=False, recursive=True) if imp_dimtags else []

            if stat_pts:
                gmsh.model.mesh.setSize(stat_pts, lc_tank)
            if mrf_pts:
                gmsh.model.mesh.setSize(mrf_pts, lc_imp)
            if imp_pts:
                gmsh.model.mesh.setSize(imp_pts, lc_imp)

            # 10. Generate 3D Tetrahedral Mesh
            gmsh.model.mesh.generate(3)

            # 10b. Optimize 3D tetrahedral elements to eliminate slivers at blade edges
            try:
                gmsh.model.mesh.optimize("Netgen")
            except Exception:
                try:
                    gmsh.model.mesh.optimize("")
                except Exception:
                    pass

            # 11. Query Mesh Statistics
            node_tags, coords, _ = gmsh.model.mesh.getNodes()
            elem_types, elem_tags, _ = gmsh.model.mesh.getElements(3)
            n_cells = sum(len(x) for x in elem_tags)
            n_nodes = len(node_tags)

            n_cells_mrf = 0
            for t in mrf_tags:
                try:
                    _, e_tags, _ = gmsh.model.mesh.getElements(3, t)
                    n_cells_mrf += sum(len(x) for x in e_tags)
                except Exception:
                    pass
            n_cells_stationary = max(0, n_cells - n_cells_mrf)

            # Ansys Student 512k cell ceiling pre-flight guard
            if n_cells > 500_000:
                raise ValueError(
                    f"Generated mesh with {n_cells:,} cells exceeds Ansys Student ceiling of 512,000 cells (safety limit 500,000). "
                    f"Please select 'Fast' or 'Medium' mesh density or reduce vessel aspect ratio."
                )

            # 12. Export Visual Surface Mesh (VTP) for 3D Web Viewer
            self._export_visual_vtp(coords, cad_vtp_path)

            # 13. Export Nastran BDF Mesh for Ansys Fluent
            gmsh.write(bdf_mesh_path)

        finally:
            gmsh.finalize()

        meshing_time = time.perf_counter() - start_time

        return MeshedBioreactorArtifact(
            bdf_mesh_path=bdf_mesh_path,
            cad_vtp_path=cad_vtp_path,
            n_nodes=n_nodes,
            n_cells=n_cells,
            n_cells_mrf=n_cells_mrf,
            n_cells_stationary=n_cells_stationary,
            mrf_zone_names=mrf_zone_names,
            stationary_zone_names=stationary_zone_names,
            impeller_wall_names=impeller_wall_names,
            vessel_wall_names=vessel_wall_names,
            interface_wall_names=interface_wall_names,
            meshing_time_s=meshing_time,
        )

    # -------------------------------------------------------------------------
    # Internal CAD Component Builders
    # -------------------------------------------------------------------------

    def _build_vessel_cad(self, tank: TankGeometry) -> Tuple[List[Tuple[int, int]], float]:
        """Construct the outer vessel fluid volume based on bottom dish geometry."""
        T = tank.diameter_m
        R = T / 2.0
        H = tank.liquid_height_m

        if tank.bottom_type == BottomType.FLAT:
            dish_depth = 0.0
            cyl = gmsh.model.occ.addCylinder(0, 0, 0, 0, 0, H, R)
            return [(3, cyl)], dish_depth

        elif tank.bottom_type == BottomType.HEMISPHERICAL:
            dish_depth = R
            s = gmsh.model.occ.addSphere(0, 0, R, R)
            # Cut away the top half (z > R) so only the bottom hemisphere remains
            cutter = gmsh.model.occ.addBox(-R * 1.5, -R * 1.5, R, R * 3.0, R * 3.0, R * 1.5)
            cut_s, _ = gmsh.model.occ.cut([(3, s)], [(3, cutter)], removeTool=True)
            cyl = gmsh.model.occ.addCylinder(0, 0, R, 0, 0, H - R, R)
            fused, _ = gmsh.model.occ.fuse(cut_s, [(3, cyl)])
            return fused, dish_depth

        elif tank.bottom_type == BottomType.ELLIPTICAL_2_1:
            dish_depth = T / 4.0
            s = gmsh.model.occ.addSphere(0, 0, 0, R)
            # Affine transformation: scale z by 0.5 and translate by dish_depth
            gmsh.model.occ.affineTransform(
                [(3, s)],
                [1.0, 0.0, 0.0, 0.0,  0.0, 1.0, 0.0, 0.0,  0.0, 0.0, 0.5, dish_depth],
            )
            # Cut away the top half (z > dish_depth) so only the bottom dish head remains
            cutter = gmsh.model.occ.addBox(-R * 1.5, -R * 1.5, dish_depth, R * 3.0, R * 3.0, R * 1.5)
            cut_s, _ = gmsh.model.occ.cut([(3, s)], [(3, cutter)], removeTool=True)
            cyl = gmsh.model.occ.addCylinder(0, 0, dish_depth, 0, 0, H - dish_depth, R)
            fused, _ = gmsh.model.occ.fuse(cut_s, [(3, cyl)])
            return fused, dish_depth

        raise ValueError(f"Unsupported bottom type: {tank.bottom_type}")

    def _build_shaft_cad(self, tank: TankGeometry) -> Tuple[Optional[Tuple[int, int]], float]:
        """Construct central agitator shaft cylinder."""
        T = tank.diameter_m
        H = tank.liquid_height_m
        r_shaft = 0.04 * T

        c0 = tank.impellers[0].clearance_m
        w_b0 = tank.impellers[0].blade_width_m or (tank.impellers[0].diameter_m / 5.0)
        z_shaft_min = max(0.01 * T, c0 - 0.5 * w_b0)
        h_shaft = H - z_shaft_min

        shaft = gmsh.model.occ.addCylinder(0, 0, z_shaft_min, 0, 0, h_shaft, r_shaft)
        return (3, shaft), r_shaft

    def _build_baffles_cad(self, tank: TankGeometry, dish_depth: float) -> List[Tuple[int, int]]:
        """Construct wall baffle boxes along the outer vessel wall."""
        if not tank.is_baffled or tank.baffle_count <= 0:
            return []

        T = tank.diameter_m
        R = T / 2.0
        H = tank.liquid_height_m
        n_baffles = tank.baffle_count
        w_baf = tank.baffle_width_m
        t_baf = 0.015 * T

        z_baf_min = dish_depth + 0.04 * T
        h_baf = H - z_baf_min

        baffle_dimtags: List[Tuple[int, int]] = []
        d_theta = 2.0 * math.pi / float(n_baffles)

        for j in range(n_baffles):
            b_tag = gmsh.model.occ.addBox(
                R - w_baf, -0.5 * t_baf, z_baf_min, w_baf, t_baf, h_baf
            )
            theta = j * d_theta
            if abs(theta) > 1e-6:
                gmsh.model.occ.rotate([(3, b_tag)], 0, 0, 0, 0, 0, 1, theta)
            baffle_dimtags.append((3, b_tag))

        return baffle_dimtags

    def _build_single_mrf_and_impeller(
        self,
        tank: TankGeometry,
        imp: ImpellerSpec,
        stage_idx: int,
        shaft_dimtag: Optional[Tuple[int, int]],
        mrf_radius_factor: float = 0.62,
    ) -> Dict[str, Any]:
        """Construct MRF cylinder volume and boolean-cut impeller and shaft from it."""
        T = tank.diameter_m
        Di = imp.diameter_m
        Wb = imp.blade_width_m or (Di / 5.0)
        Ck = imp.clearance_m

        r_mrf = mrf_radius_factor * Di
        if tank.is_baffled and tank.baffle_count > 0:
            r_baf_inner = (T / 2.0) - tank.baffle_width_m
            r_mrf = min(r_mrf, r_baf_inner - 0.005 * T)
        h_mrf = max(1.8 * Wb, 0.55 * Di if imp.impeller_type == ImpellerType.INTERMIG_EKATO else 0.40 * Di)
        z_mrf_min = Ck - 0.5 * h_mrf

        # 1. MRF Cylinder Solid
        mrf_tag = gmsh.model.occ.addCylinder(0, 0, z_mrf_min, 0, 0, h_mrf, r_mrf)

        # 2. Impeller 3D Solid
        impeller_dimtags = self._build_impeller_solid(tank, imp)

        # 3. Cut Impeller from MRF
        mrf_cut, _ = gmsh.model.occ.cut([(3, mrf_tag)], impeller_dimtags, removeTool=True)

        # 4. Cut Shaft from MRF
        if shaft_dimtag is not None:
            mrf_cut, _ = gmsh.model.occ.cut(mrf_cut, [shaft_dimtag], removeTool=False)

        return {
            "stage_index": stage_idx,
            "clearance_m": Ck,
            "mrf_radius": r_mrf,
            "mrf_height": h_mrf,
            "mrf_cut_dimtag": mrf_cut[0] if len(mrf_cut) == 1 else mrf_cut,
        }

    def _build_impeller_solid(self, tank: TankGeometry, imp: ImpellerSpec) -> List[Tuple[int, int]]:
        """Construct 3D impeller geometry with finite blade thickness for clean meshing."""
        T = tank.diameter_m
        Di = imp.diameter_m
        Wb = imp.blade_width_m or (Di / 5.0)
        Ck = imp.clearance_m
        tb = max(0.008 * T, 0.025 * Di)

        if imp.impeller_type == ImpellerType.SMITH_CD6:
            # Smith CD-6: Center disk with 6 concave half-cylinder blades
            n_blades = imp.blade_count or 6
            r_disk = 0.36 * Di
            t_disk = 0.22 * Wb
            center_piece = gmsh.model.occ.addCylinder(
                0, 0, Ck - 0.5 * t_disk, 0, 0, t_disk, r_disk
            )
            d_theta = 2.0 * math.pi / float(n_blades)
            blades: List[Tuple[int, int]] = []
            Rc = 0.125 * Di
            xc = 0.375 * Di
            for i in range(n_blades):
                c_out = gmsh.model.occ.addCylinder(xc, 0, Ck - 0.5 * Wb, 0, 0, Wb, Rc)
                c_in = gmsh.model.occ.addCylinder(xc, 0, Ck - 0.5 * Wb, 0, 0, Wb, max(Rc - tb, 0.001))
                hollow, _ = gmsh.model.occ.cut([(3, c_out)], [(3, c_in)], removeTool=True)
                cutter = gmsh.model.occ.addBox(xc - Rc * 1.1, 0, Ck - 0.55 * Wb, Rc * 2.2, Rc * 1.5, Wb * 1.1)
                half, _ = gmsh.model.occ.cut(hollow, [(3, cutter)], removeTool=True)
                theta = i * d_theta
                if abs(theta) > 1e-6:
                    gmsh.model.occ.rotate(half, 0, 0, 0, 0, 0, 1, theta)
                blades.extend(half)
            fused, _ = gmsh.model.occ.fuse([(3, center_piece)], blades)
            return fused

        elif imp.impeller_type in (
            ImpellerType.RUSHTON_6_BLADE,
            ImpellerType.FLAT_BLADE_FBT,
            ImpellerType.PADDLE_R200,
            ImpellerType.CURVED_BACKSWEPT,
            ImpellerType.RETREAT_BLADE,
        ):
            # Radial Impeller: Hub/Disc + radial blades
            n_blades = imp.blade_count or 6
            has_disk = (imp.impeller_type == ImpellerType.RUSHTON_6_BLADE)

            if has_disk:
                r_disk = 0.36 * Di
                t_disk = 0.22 * Wb
                center_piece = gmsh.model.occ.addCylinder(
                    0, 0, Ck - 0.5 * t_disk, 0, 0, t_disk, r_disk
                )
                r_start = 0.25 * Di
                b_len = 0.25 * Di
            else:
                r_hub = 0.12 * Di
                center_piece = gmsh.model.occ.addCylinder(
                    0, 0, Ck - 0.5 * Wb, 0, 0, Wb, r_hub
                )
                r_start = r_hub
                b_len = 0.50 * Di - r_hub

            d_theta = 2.0 * math.pi / float(n_blades)
            blades: List[Tuple[int, int]] = []

            for i in range(n_blades):
                b_tag = gmsh.model.occ.addBox(
                    r_start, -0.5 * tb, Ck - 0.5 * Wb, b_len, tb, Wb
                )
                theta = i * d_theta
                if abs(theta) > 1e-6:
                    gmsh.model.occ.rotate([(3, b_tag)], 0, 0, 0, 0, 0, 1, theta)
                blades.append((3, b_tag))

            fused, _ = gmsh.model.occ.fuse([(3, center_piece)], blades)
            return fused

        elif imp.impeller_type == ImpellerType.HYDROFOIL_HE3:
            # Hydrofoil HE-3: Hub + 3 tapered blades pitched at 25 degrees
            r_hub = 0.14 * Di
            hub = gmsh.model.occ.addCylinder(0, 0, Ck - 0.5 * Wb, 0, 0, Wb, r_hub)
            n_blades = imp.blade_count or 3
            r_start = 0.60 * r_hub
            b_len = 0.50 * Di - r_start
            d_theta = 2.0 * math.pi / float(n_blades)
            blades: List[Tuple[int, int]] = []
            for i in range(n_blades):
                w_tag = gmsh.model.occ.addWedge(r_start, -0.5 * Wb, -0.5 * tb, b_len, Wb, tb, ltx=0.55 * Wb)
                gmsh.model.occ.rotate([(3, w_tag)], 0, 0, 0, 1, 0, 0, math.radians(25.0))
                gmsh.model.occ.translate([(3, w_tag)], 0, 0, Ck)
                theta = i * d_theta
                if abs(theta) > 1e-6:
                    gmsh.model.occ.rotate([(3, w_tag)], 0, 0, 0, 0, 0, 1, theta)
                blades.append((3, w_tag))
            fused, _ = gmsh.model.occ.fuse([(3, hub)], blades)
            return fused

        elif imp.impeller_type == ImpellerType.INTERMIG_EKATO:
            # Intermig EKATO: Hub + dual staggered stages (90 deg offset) with counter-pitched outer winglets
            r_hub = 0.14 * Di
            h_hub = 0.45 * Di
            hub = gmsh.model.occ.addCylinder(0, 0, Ck - 0.5 * h_hub, 0, 0, h_hub, r_hub)
            h_blade = 0.12 * Di
            span = 0.70 * Di
            # Stage 1: lower blade with positive winglet pitch
            b1 = gmsh.model.occ.addBox(-0.5 * span, -0.5 * tb, Ck - 0.10 * Di - 0.5 * h_blade, span, tb, h_blade)
            w1_a = gmsh.model.occ.addBox(0.5 * span - 0.08 * Di, -0.5 * tb, Ck - 0.10 * Di - 0.5 * h_blade, 0.08 * Di, tb, h_blade)
            gmsh.model.occ.rotate([(3, w1_a)], 0.5 * span - 0.08 * Di, 0, Ck - 0.10 * Di, 0, 0, 1, math.radians(40.0))
            w1_b = gmsh.model.occ.addBox(-0.5 * span, -0.5 * tb, Ck - 0.10 * Di - 0.5 * h_blade, 0.08 * Di, tb, h_blade)
            gmsh.model.occ.rotate([(3, w1_b)], -0.5 * span + 0.08 * Di, 0, Ck - 0.10 * Di, 0, 0, 1, math.radians(40.0))
            # Stage 2: upper blade rotated 90 deg with negative winglet pitch
            b2 = gmsh.model.occ.addBox(-0.5 * span, -0.5 * tb, Ck + 0.10 * Di - 0.5 * h_blade, span, tb, h_blade)
            w2_a = gmsh.model.occ.addBox(0.5 * span - 0.08 * Di, -0.5 * tb, Ck + 0.10 * Di - 0.5 * h_blade, 0.08 * Di, tb, h_blade)
            gmsh.model.occ.rotate([(3, w2_a)], 0.5 * span - 0.08 * Di, 0, Ck + 0.10 * Di, 0, 0, 1, math.radians(-40.0))
            w2_b = gmsh.model.occ.addBox(-0.5 * span, -0.5 * tb, Ck + 0.10 * Di - 0.5 * h_blade, 0.08 * Di, tb, h_blade)
            gmsh.model.occ.rotate([(3, w2_b)], -0.5 * span + 0.08 * Di, 0, Ck + 0.10 * Di, 0, 0, 1, math.radians(-40.0))
            stg2 = [(3, b2), (3, w2_a), (3, w2_b)]
            gmsh.model.occ.rotate(stg2, 0, 0, 0, 0, 0, 1, math.pi / 2.0)
            fused, _ = gmsh.model.occ.fuse([(3, hub)], [(3, b1), (3, w1_a), (3, w1_b)] + stg2)
            return fused

        elif imp.impeller_type in (
            ImpellerType.PITCHED_BLADE_45,
            ImpellerType.MARINE_PROPELLER,
            ImpellerType.MAXFLO_HIGH_SOLIDITY,
        ):
            # Axial & Mixed Impeller: Central hub + pitched/angled blades
            r_hub = 0.14 * Di
            hub = gmsh.model.occ.addCylinder(
                0, 0, Ck - 0.5 * Wb, 0, 0, Wb, r_hub
            )
            n_blades = imp.blade_count or (3 if imp.impeller_type == ImpellerType.MARINE_PROPELLER else 4)

            if imp.impeller_type == ImpellerType.PITCHED_BLADE_45:
                pitch_deg = 45.0
            elif imp.impeller_type == ImpellerType.MAXFLO_HIGH_SOLIDITY:
                pitch_deg = 35.0
            else:
                pitch_deg = 30.0

            d_theta = 2.0 * math.pi / float(n_blades)
            blades: List[Tuple[int, int]] = []
            r_start = 0.60 * r_hub
            b_len = 0.50 * Di - r_start

            for i in range(n_blades):
                if imp.impeller_type == ImpellerType.MARINE_PROPELLER:
                    b_tag = gmsh.model.occ.addWedge(r_start, -0.5 * Wb, -0.5 * tb, b_len, Wb, tb, ltx=0.60 * Wb)
                else:
                    b_tag = gmsh.model.occ.addBox(
                        r_start, -0.5 * Wb, -0.5 * tb, b_len, Wb, tb
                    )
                gmsh.model.occ.rotate([(3, b_tag)], 0, 0, 0, 1, 0, 0, math.radians(pitch_deg))
                gmsh.model.occ.translate([(3, b_tag)], 0, 0, Ck)
                theta = i * d_theta
                if abs(theta) > 1e-6:
                    gmsh.model.occ.rotate([(3, b_tag)], 0, 0, 0, 0, 0, 1, theta)
                blades.append((3, b_tag))

            fused, _ = gmsh.model.occ.fuse([(3, hub)], blades)
            return fused

        elif imp.impeller_type == ImpellerType.ANCHOR:
            # Anchor: Central hub + bottom sweeping crossbar + 2 vertical wall limbs
            r_hub = 0.12 * Di
            hub = gmsh.model.occ.addCylinder(0, 0, Ck - 0.5 * tb, 0, 0, tb, r_hub)
            bar_w = 0.04 * Di
            crossbar = gmsh.model.occ.addBox(-0.5 * Di, -0.5 * tb, Ck - 0.5 * bar_w, Di, tb, bar_w)
            limb1 = gmsh.model.occ.addBox(-0.5 * Di, -0.5 * tb, Ck, bar_w, tb, Wb)
            limb2 = gmsh.model.occ.addBox(0.5 * Di - bar_w, -0.5 * tb, Ck, bar_w, tb, Wb)
            fused, _ = gmsh.model.occ.fuse([(3, hub)], [(3, crossbar), (3, limb1), (3, limb2)])
            return fused

        elif imp.impeller_type == ImpellerType.GATE_IMPELLER:
            # Gate Anchor: Dished U-anchor outer frame with intermediate vertical grid limbs & mid crossbar
            # Open top (no top crossbar); mid-level tie-bar connects inner limbs only
            r_hub = 0.10 * Di
            bar_w = 0.038 * Di
            r_outer = 0.50 * Di
            r_inner = 0.24 * Di
            z_mid = Ck + 0.55 * Wb - 0.5 * bar_w

            # Hubs: lower at bottom crossbar, upper at mid tie-bar
            hub_bot = gmsh.model.occ.addCylinder(0, 0, Ck - 0.2 * bar_w, 0, 0, 1.4 * bar_w, r_hub)
            hub_top = gmsh.model.occ.addCylinder(0, 0, z_mid - 0.2 * bar_w, 0, 0, 1.4 * bar_w, r_hub)

            # Bottom sweeping crossbar
            b_bot = gmsh.model.occ.addBox(-r_outer, -0.5 * tb, Ck, 2.0 * r_outer, tb, bar_w)

            # Outer vertical wall limbs (open top)
            l_left = gmsh.model.occ.addBox(-r_outer, -0.5 * tb, Ck, bar_w, tb, Wb)
            l_right = gmsh.model.occ.addBox(r_outer - bar_w, -0.5 * tb, Ck, bar_w, tb, Wb)

            # Intermediate vertical limbs (open top)
            v_mid1 = gmsh.model.occ.addBox(-r_inner - 0.5 * bar_w, -0.5 * tb, Ck, bar_w, tb, Wb)
            v_mid2 = gmsh.model.occ.addBox(r_inner - 0.5 * bar_w, -0.5 * tb, Ck, bar_w, tb, Wb)

            # Mid-level tie crossbar (connects inner limbs only, does NOT reach outer wall)
            x_mid_len = 2.0 * r_inner + bar_w
            b_mid = gmsh.model.occ.addBox(-r_inner - 0.5 * bar_w, -0.5 * tb, z_mid, x_mid_len, tb, bar_w)

            fused, _ = gmsh.model.occ.fuse(
                [(3, hub_bot), (3, hub_top)],
                [(3, b_bot), (3, b_mid), (3, l_left), (3, l_right), (3, v_mid1), (3, v_mid2)]
            )
            return fused

        elif imp.impeller_type == ImpellerType.SIGMA_Z_KNEADER:
            # Sigma / Z-Blade: Hub + dual heavy pitched Z-arm kneading blades
            # Ck is bottom sweep clearance
            r_hub = 0.15 * Di
            hub = gmsh.model.occ.addCylinder(0, 0, Ck, 0, 0, Wb, r_hub)
            arm_len = 0.46 * Di - r_hub
            pitch_rad = math.radians(28.0)
            arm1 = gmsh.model.occ.addBox(r_hub, -0.5 * tb * 1.5, Ck + 0.1 * Wb, arm_len, tb * 1.5, Wb * 0.8)
            gmsh.model.occ.rotate([(3, arm1)], 0, 0, Ck + 0.5 * Wb, 1, 0, 0, pitch_rad)
            arm2 = gmsh.model.occ.addBox(-0.46 * Di, -0.5 * tb * 1.5, Ck + 0.1 * Wb, arm_len, tb * 1.5, Wb * 0.8)
            gmsh.model.occ.rotate([(3, arm2)], 0, 0, Ck + 0.5 * Wb, 1, 0, 0, -pitch_rad)
            fused, _ = gmsh.model.occ.fuse([(3, hub)], [(3, arm1), (3, arm2)])
            return fused

        elif imp.impeller_type == ImpellerType.HELICAL_RIBBON:
            # Helical Ribbon: Hub + top/bottom support crossbars + multi-segment outer helical ribbon
            # Ck is bottom sweep clearance
            r_hub = 0.12 * Di
            hub = gmsh.model.occ.addCylinder(0, 0, Ck, 0, 0, Wb, r_hub)
            bar_w = 0.04 * Di
            bar_bot = gmsh.model.occ.addBox(-0.48 * Di, -0.5 * tb, Ck, 0.96 * Di, tb, bar_w)
            bar_top = gmsh.model.occ.addBox(-0.5 * tb, -0.48 * Di, Ck + Wb - bar_w, tb, 0.96 * Di, bar_w)

            n_steps = 20
            d_theta = (2.0 * math.pi) / n_steps
            dz = Wb / n_steps
            t_ribbon = max(0.005, 0.035 * Di)
            w_ribbon = max(0.012, 0.08 * Di)
            r_outer = 0.48 * Di
            r_inner = r_outer - w_ribbon

            ribbon_segments = [(3, bar_bot), (3, bar_top)]
            for i in range(n_steps):
                th = i * d_theta
                z = Ck + i * dz
                seg = gmsh.model.occ.addBox(r_inner, -0.5 * t_ribbon, z, w_ribbon, t_ribbon, dz * 1.08)
                gmsh.model.occ.rotate([(3, seg)], 0, 0, 0, 0, 0, 1, th)
                ribbon_segments.append((3, seg))

            fused, _ = gmsh.model.occ.fuse([(3, hub)], ribbon_segments)
            return fused

        else:  # AUGER_SCREW
            # Archimedes Screw: Central core cylinder shaft + continuous helical flighting
            # Ck is bottom sweep clearance
            r_hub = 0.14 * Di
            hub = gmsh.model.occ.addCylinder(0, 0, Ck, 0, 0, Wb, r_hub)
            n_steps = 24
            n_turns = 2.0
            d_theta = (2.0 * math.pi * n_turns) / n_steps
            dz = Wb / n_steps
            t_flight = max(0.004, 0.025 * Di)
            r_out = 0.48 * Di
            slices = []
            for i in range(n_steps):
                th = i * d_theta
                z = Ck + i * dz
                box = gmsh.model.occ.addBox(r_hub * 0.95, -0.5 * t_flight, z, (r_out - r_hub * 0.95), t_flight, dz * 1.08)
                gmsh.model.occ.rotate([(3, box)], 0, 0, 0, 0, 0, 1, th)
                slices.append((3, box))
            fused, _ = gmsh.model.occ.fuse([(3, hub)], slices)
            return fused

    def _export_visual_vtp(self, coords: np.ndarray, cad_vtp_path: str) -> None:
        """Extract 2D boundary surface triangular mesh and save to VTP format."""
        node_tags, coords_arr, _ = gmsh.model.mesh.getNodes()
        node_map = {tag: i for i, tag in enumerate(node_tags)}
        pts = coords_arr.reshape(-1, 3)

        elem_types, elem_tags, elem_node_tags = gmsh.model.mesh.getElements(2)
        tri_conn: List[int] = []

        for etype, enodes in zip(elem_types, elem_node_tags):
            if etype == 2:  # 3-node linear triangle
                for j in range(0, len(enodes), 3):
                    tri_conn.extend([
                        3,
                        node_map[enodes[j]],
                        node_map[enodes[j + 1]],
                        node_map[enodes[j + 2]],
                    ])

        if pv is None:
            logger.warning("PyVista not available, skipping VTP export.")
            return

        if tri_conn:
            poly = pv.PolyData(pts, np.array(tri_conn, dtype=np.int64))
            poly.save(cad_vtp_path)
        else:
            poly = pv.PolyData(pts)
            poly.save(cad_vtp_path)
