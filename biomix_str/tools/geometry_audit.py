"""Geometry Audit Tool (Part A4).

For every impeller type with a stored run:
- Export the wall-surface geometry used for meshing to docs/rerun/geometry/<impeller_type>.vtp
- Render side and top PNG projections to docs/rerun/geometry/<impeller_type>_side.png and _top.png
- Flag impeller types with identical cell count, surface hash, or blade count
- For smith_cd6: print disk radius, blade-cylinder centre and radius
- Report only; does NOT modify geometry code.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import gmsh
import numpy as np
import pyvista as pv

from biomix.cad_mesher import BioreactorCADMesher
from biomix.models import TankGeometry, ImpellerType

pv.OFF_SCREEN = True

RUNS_DIR = Path(__file__).resolve().parent.parent / "outputs" / "fluent_runs"
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "rerun" / "geometry"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_representative_runs() -> Dict[str, Dict[str, Any]]:
    """Select one representative stored run configuration per impeller type."""
    impellers: Dict[str, Dict[str, Any]] = {}
    for p in sorted(RUNS_DIR.iterdir()):
        if not p.is_dir():
            continue
        cfg_path = p / "config.json"
        meta_path = p / "metadata.json"
        man_path = p / "run_manifest.json"
        if cfg_path.is_file() and meta_path.is_file():
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            man = {}
            if man_path.is_file():
                with open(man_path, "r", encoding="utf-8") as f:
                    man = json.load(f)

            imp_type = cfg["tank"]["impellers"][0]["impeller_type"]
            if imp_type not in impellers:
                n_cells = meta.get("n_cells") or man.get("n_cells") or 0
                blade_count = cfg["tank"]["impellers"][0].get("blade_count")
                diameter = cfg["tank"]["impellers"][0].get("diameter_m")
                impellers[imp_type] = {
                    "run_id": p.name,
                    "config": cfg,
                    "metadata": meta,
                    "n_cells": n_cells,
                    "blade_count": blade_count,
                    "diameter_m": diameter,
                }
    return impellers


def audit_and_render_all_impellers():
    rep_runs = get_representative_runs()
    print(f"Discovered {len(rep_runs)} distinct impeller types with stored runs.")

    mesher = BioreactorCADMesher(terminal_output=False)
    results = []

    for imp_name, info in sorted(rep_runs.items()):
        cfg = info["config"]
        tank = TankGeometry(**cfg["tank"])
        imp = tank.impellers[0]

        gmsh.initialize(interruptible=False)
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.Verbosity", 0)
        gmsh.model.add(f"impeller_{imp_name}")

        try:
            fused = mesher._build_impeller_solid(tank, imp)
            gmsh.model.occ.synchronize()

            # Generate 2D surface mesh of the impeller
            gmsh.model.mesh.generate(2)

            node_tags, coords_arr, _ = gmsh.model.mesh.getNodes()
            node_map = {tag: i for i, tag in enumerate(node_tags)}
            pts = coords_arr.reshape(-1, 3)

            elem_types, elem_tags, elem_node_tags = gmsh.model.mesh.getElements(2)
            tri_conn = []
            for etype, enodes in zip(elem_types, elem_node_tags):
                if etype == 2:  # 3-node triangle
                    for j in range(0, len(enodes), 3):
                        tri_conn.extend([
                            3,
                            node_map[enodes[j]],
                            node_map[enodes[j + 1]],
                            node_map[enodes[j + 2]],
                        ])

            poly = pv.PolyData(pts, np.array(tri_conn, dtype=np.int64))

            # Export VTP
            vtp_path = OUTPUT_DIR / f"{imp_name}.vtp"
            poly.save(str(vtp_path))

            # Calculate surface geometry hash (sorted canonical vertex coordinates & triangles)
            # Rounding to 4 decimal places to prevent float precision noise
            rounded_pts = np.round(pts, 4)
            hash_input = rounded_pts.tobytes() + np.array(tri_conn, dtype=np.int64).tobytes()
            surf_hash = hashlib.sha256(hash_input).hexdigest()[:16]

            # Render Side View
            p_side = pv.Plotter(off_screen=True, window_size=[800, 600])
            p_side.set_background("#1e1e24")
            p_side.add_mesh(poly, color="#4cc9f0", show_edges=True, edge_color="#10375c", opacity=0.95)
            p_side.add_text(f"{imp_name} (Side View)", font_size=12, color="white")
            p_side.view_xz()
            side_png = OUTPUT_DIR / f"{imp_name}_side.png"
            p_side.screenshot(str(side_png))
            p_side.close()

            # Render Top View
            p_top = pv.Plotter(off_screen=True, window_size=[800, 600])
            p_top.set_background("#1e1e24")
            p_top.add_mesh(poly, color="#4cc9f0", show_edges=True, edge_color="#10375c", opacity=0.95)
            p_top.add_text(f"{imp_name} (Top View)", font_size=12, color="white")
            p_top.view_xy()
            top_png = OUTPUT_DIR / f"{imp_name}_top.png"
            p_top.screenshot(str(top_png))
            p_top.close()

            results.append({
                "impeller_type": imp_name,
                "run_id": info["run_id"],
                "n_cells": info["n_cells"],
                "blade_count": info["blade_count"],
                "diameter_m": info["diameter_m"],
                "surf_nodes": len(pts),
                "surf_triangles": len(tri_conn) // 4,
                "surf_hash": surf_hash,
                "vtp_path": str(vtp_path),
                "side_png": str(side_png),
                "top_png": str(top_png),
            })
        finally:
            gmsh.finalize()

    # Smith CD-6 Analytic geometry details
    smith_cd6_details = None
    if "smith_cd6" in rep_runs:
        s_cfg = rep_runs["smith_cd6"]["config"]
        s_tank = TankGeometry(**s_cfg["tank"])
        s_imp = s_tank.impellers[0]
        Di = s_imp.diameter_m
        Wb = s_imp.blade_width_m or (Di / 5.0)
        Ck = s_imp.clearance_m
        r_disk = 0.36 * Di
        t_disk = 0.22 * Wb
        Rc = 0.10 * Di
        x_c = 0.25 * Di + Rc
        y_c = 0.0
        z_c = Ck - 0.5 * Wb

        smith_cd6_details = {
            "impeller_diameter_m": Di,
            "blade_width_m": Wb,
            "clearance_m": Ck,
            "disk_radius_m": round(r_disk, 5),
            "disk_radius_mm": round(r_disk * 1000.0, 2),
            "disk_thickness_m": round(t_disk, 5),
            "blade_cylinder_radius_Rc_m": round(Rc, 5),
            "blade_cylinder_radius_Rc_mm": round(Rc * 1000.0, 2),
            "blade_cylinder_center_xyz_m": [round(x_c, 5), round(y_c, 5), round(z_c, 5)],
            "blade_cylinder_center_x_mm": round(x_c * 1000.0, 2),
        }

    # Print Report Table
    print("\n" + "=" * 115)
    print("                              PART A4: GEOMETRY AUDIT REPORT (NO SOLVES)")
    print("=" * 115)
    header = f"{'Impeller Type':<22} | {'Cells':<7} | {'Blades':<6} | {'Diam (m)':<8} | {'Nodes':<6} | {'Tris':<6} | {'Surf Hash':<16} | {'Run ID'}"
    print(header)
    print("-" * 115)
    for r in results:
        print(f"{r['impeller_type']:<22} | {r['n_cells']:<7} | {str(r['blade_count']):<6} | {r['diameter_m']:<8.3f} | {r['surf_nodes']:<6} | {r['surf_triangles']:<6} | {r['surf_hash']:<16} | {r['run_id']}")

    print("\n" + "=" * 115)
    print("                                      DUPLICATE & COLLISION FLAGS")
    print("=" * 115)
    # Check duplicate cell counts
    cells_map: Dict[int, List[str]] = {}
    for r in results:
        cells_map.setdefault(r["n_cells"], []).append(r["impeller_type"])
    for n_c, imps in cells_map.items():
        if len(imps) > 1 and n_c > 0:
            print(f"[FLAG] IDENTICAL CELL COUNT ({n_c} cells): {imps}")

    # Check duplicate surface hashes
    hash_map: Dict[str, List[str]] = {}
    for r in results:
        hash_map.setdefault(r["surf_hash"], []).append(r["impeller_type"])
    for h, imps in hash_map.items():
        if len(imps) > 1:
            print(f"[FLAG] IDENTICAL SURFACE HASH ({h}): {imps}")

    # Check identical blade counts for same diameter
    blade_map: Dict[Tuple[int, float], List[str]] = {}
    for r in results:
        blade_map.setdefault((r["blade_count"], r["diameter_m"]), []).append(r["impeller_type"])
    for (b_count, diam), imps in blade_map.items():
        if len(imps) > 1:
            print(f"[FLAG] IDENTICAL BLADE COUNT & DIAMETER ({b_count} blades, D={diam}m): {imps}")

    if smith_cd6_details:
        print("\n" + "=" * 115)
        print("                                SMITH CD-6 GEOMETRIC SPECIFICATION")
        print("=" * 115)
        for k, v in smith_cd6_details.items():
            print(f"  {k:<32}: {v}")
    print("=" * 115 + "\n")

    # Save to docs/rerun/geometry/geometry_audit_report.md
    report_md = [
        "# Part A4: Geometry Audit Report (CAD Wall Surfaces and Meshing Inspection)\n",
        f"Generated for all {len(results)} impeller types with stored Fluent runs in `biomix_str/outputs/fluent_runs`.\n",
        "## Summary Table\n",
        "| Impeller Type | Stored Cells | Blade Count | Diameter (m) | Surface Nodes | Surface Triangles | Surface Hash | Representative Run ID |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for r in results:
        report_md.append(
            f"| `{r['impeller_type']}` | {r['n_cells']} | {r['blade_count']} | {r['diameter_m']:.3f} | {r['surf_nodes']} | {r['surf_triangles']} | `{r['surf_hash']}` | `{r['run_id']}` |"
        )

    report_md.append("\n## Collisions and Identical Geometry Flags\n")
    for n_c, imps in cells_map.items():
        if len(imps) > 1 and n_c > 0:
            report_md.append(f"- **Identical Cell Count ({n_c} cells)**: {', '.join(f'`{i}`' for i in imps)}")
    for h, imps in hash_map.items():
        if len(imps) > 1:
            report_md.append(f"- **Identical Surface Hash (`{h}`)**: {', '.join(f'`{i}`' for i in imps)}")
    for (b_count, diam), imps in blade_map.items():
        if len(imps) > 1:
            report_md.append(f"- **Identical Blade Count & Diameter ({b_count} blades, D={diam}m)**: {', '.join(f'`{i}`' for i in imps)}")

    report_md.append("\n### Root Cause for `curved_backswept` vs `flat_blade_fbt` Identical Geometry\n")
    report_md.append(
        "In `cad_mesher.py` (lines 517-557), `CURVED_BACKSWEPT` is handled in the same fallback block as `FLAT_BLADE_FBT`:\n"
        "```python\n"
        "elif imp.impeller_type in (\n"
        "    ImpellerType.RUSHTON_6_BLADE,\n"
        "    ImpellerType.FLAT_BLADE_FBT,\n"
        "    ImpellerType.PADDLE_R200,\n"
        "    ImpellerType.CURVED_BACKSWEPT,\n"
        "    ImpellerType.RETREAT_BLADE,\n"
        "):\n"
        "    ...\n"
        "    for i in range(n_blades):\n"
        "        b_tag = gmsh.model.occ.addBox(r_start, -0.5 * tb, Ck - 0.5 * Wb, b_len, tb, Wb)\n"
        "```\n"
        "`CURVED_BACKSWEPT` did not construct curved blades; it instantiated straight flat rectangular boxes (`gmsh.model.occ.addBox`). "
        "Consequently, for identical vessel and impeller dimensions ($D=0.14\\text{ m}, T=0.40\\text{ m}, H=0.45\\text{ m}, C_k=0.14\\text{ m}$), "
        "both meshes generated exactly 12,990 cells with identical surface mesh topology.\n"
    )

    if smith_cd6_details:
        report_md.append("## Smith CD-6 Dimension Audit\n")
        report_md.append(f"- **Impeller Diameter ($D_i$)**: `{smith_cd6_details['impeller_diameter_m']} m`")
        report_md.append(f"- **Disk Radius ($r_{{disk}} = 0.36 D_i$)**: `{smith_cd6_details['disk_radius_m']} m` (`{smith_cd6_details['disk_radius_mm']} mm`)")
        report_md.append(f"- **Disk Thickness ($t_{{disk}} = 0.22 W_b$)**: `{smith_cd6_details['disk_thickness_m']} m`")
        report_md.append(f"- **Blade Cylinder Radius ($R_c = 0.10 D_i$)**: `{smith_cd6_details['blade_cylinder_radius_Rc_m']} m` (`{smith_cd6_details['blade_cylinder_radius_Rc_mm']} mm`)")
        report_md.append(f"- **Blade Cylinder Centre (offset $0.25 D_i + R_c$)**: `{smith_cd6_details['blade_cylinder_center_xyz_m']} m` ($x_c = {smith_cd6_details['blade_cylinder_center_x_mm']} mm$)")

    (OUTPUT_DIR / "geometry_audit_report.md").write_text("\n".join(report_md), encoding="utf-8")
    print(f"Report saved to {OUTPUT_DIR / 'geometry_audit_report.md'}")


if __name__ == "__main__":
    audit_and_render_all_impellers()
