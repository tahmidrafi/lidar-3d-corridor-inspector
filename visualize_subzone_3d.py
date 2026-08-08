"""
Interactive 3D Subzone Visualizer (`visualize_subzone_3d`)
Open3D Desktop Application with subprocess-isolated native Windows Explorer file dialogs for
tree detection runs (YAML file picker), segmented point clouds, ground-truth trees, custom vector layers, and DTM rasters.

Usage:
    micromamba run -n gis python visualize_subzone_3d.py
"""

import sys
import os
import argparse
import subprocess
import json
import numpy as np
import open3d as o3d
import open3d.visualization.gui as gui
import open3d.visualization.rendering as rendering
from shapely.geometry import LineString, MultiLineString, GeometryCollection, Polygon, MultiPolygon

from data_loader import (
    TreeRunDataLoader,
    load_vector_file,
    load_dtm_surface,
    sample_dtm_elevation,
    drape_geometry_on_dtm,
    load_last_config,
    save_last_config,
    log_info,
    log_warn,
    log_err,
)

COLOR_MAP = {
    "Red": [1.0, 0.0, 0.0],
    "Green": [0.0, 1.0, 0.0],
    "Yellow": [1.0, 1.0, 0.0],
    "Cyan": [0.0, 1.0, 1.0],
    "Magenta": [1.0, 0.0, 1.0],
    "Orange": [1.0, 0.5, 0.0],
    "White": [1.0, 1.0, 1.0],
    "Gray": [0.7, 0.7, 0.7],
}


def open_native_file_picker(title="Select File", file_filter="*.yml;*.yaml"):
    """Open standard native Windows Explorer file picker dialog via subprocess isolation."""
    py_script = (
        "import tkinter as tk, tkinter.filedialog as fd; "
        "r=tk.Tk(); r.withdraw(); r.attributes('-topmost', True); "
        f"p=fd.askopenfilename(title='{title}', filetypes=[('Files', '{file_filter}'), ('All Files', '*.*')]); "
        "print(p)"
    )
    try:
        log_info(f"Opening native file dialog for: {title}")
        out = subprocess.check_output([sys.executable, "-c", py_script], text=True).strip()
        if out:
            log_info(f"User selected file: {out}")
        else:
            log_info("User cancelled file selection dialog.")
        return out
    except Exception as e:
        log_err(f"Error opening file picker: {e}")
        return ""


def open_unified_add_vector_dialog():
    """
    Open single unified dialog window containing file picker, layer display name,
    geometry style (Polyline vs Area), color, elevation offset, and Add button.
    """
    runner = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vector_dialog_runner.py")
    try:
        log_info("Opening unified vector configuration window...")
        out = subprocess.check_output([sys.executable, runner], text=True).strip()
        if out:
            res = json.loads(out)
            log_info(f"User configured vector layer: {res}")
            return res
    except Exception as e:
        log_err(f"Error opening unified vector dialog: {e}")
    return None


class SubzoneVisualizerApp:
    """Main Open3D Desktop GUI Application with Subprocess-Isolated File Dialogs."""

    def __init__(self, initial_run_target=None):
        log_info("============================================================")
        log_info("STARTING: 3D Subzone Visualizer Application")
        log_info("============================================================")

        self.config = load_last_config()

        if initial_run_target:
            self.config["run_yml"] = initial_run_target

        self.run_loader = None
        self.current_subzones = []
        self.current_index = 0

        # Custom Vector Layers: list of dicts {name, path, type, color, offset, visible, deleted}
        self.custom_vectors = [v for v in self.config.get("custom_vectors", []) if not v.get("deleted", False)]
        self.vector_row_widgets = []

        # Initialize Open3D GUI
        self.app = gui.Application.instance
        self.app.initialize()

        self.window = self.app.create_window("3D Subzone Inspector", 1500, 950)

        margin = 8
        self.panel = gui.Vert(margin, gui.Margins(margin, margin, margin, margin))
        self.panel.preferred_width = 360

        self.widget_3d = gui.SceneWidget()
        self.widget_3d.scene = rendering.Open3DScene(self.window.renderer)
        self.widget_3d.scene.set_background([0.15, 0.15, 0.18, 1.0])

        self.window.add_child(self.panel)
        self.window.add_child(self.widget_3d)

        self.window.set_on_layout(self._on_layout)

        # Rendering Materials
        self.mat_pcd = rendering.MaterialRecord()
        self.mat_pcd.shader = "defaultUnlit"
        self.mat_pcd.point_size = 2.5 * self.window.scaling

        self.mat_mesh = rendering.MaterialRecord()
        self.mat_mesh.shader = "defaultLit"

        self.mat_line = rendering.MaterialRecord()
        self.mat_line.shader = "unlitLine"
        self.mat_line.line_width = 2.0 * self.window.scaling

        # UI Setup
        self._build_sidebar_ui()

        # Load initial run target if available in config
        if self.config.get("run_yml") and os.path.exists(self.config["run_yml"]):
            self._load_run_target(self.config["run_yml"])

    def _on_layout(self, layout_context):
        r = self.window.content_rect
        if self.panel:
            self.panel.frame = gui.Rect(r.x, r.y, self.panel.preferred_width, r.height)
            self.widget_3d.frame = gui.Rect(
                r.x + self.panel.preferred_width, r.y, r.width - self.panel.preferred_width, r.height
            )

    def _build_sidebar_ui(self):
        """Construct the sidebar control panel with native Windows file pickers."""
        em = self.window.theme.font_size

        # Title Header
        lbl_title = gui.Label("3D Subzone Inspector")
        self.panel.add_child(lbl_title)
        self.panel.add_fixed(em * 0.5)

        # 1. Tree Detection Run File Picker (.yml)
        self.panel.add_child(gui.Label("1. Tree Detection Run Config (.yml)"))
        horiz_run = gui.Horiz(4)
        self.txt_run_path = gui.TextEdit()
        self.txt_run_path.text_value = self.config.get("run_yml", "")
        btn_browse_run = gui.Button("Browse...")
        btn_browse_run.set_on_clicked(self._on_browse_run_file)
        horiz_run.add_child(self.txt_run_path)
        horiz_run.add_child(btn_browse_run)
        self.panel.add_child(horiz_run)
        self.panel.add_fixed(em * 0.5)

        # 2. Subzone Navigation
        self.panel.add_child(gui.Label("2. Subzone Selection"))
        self.combo_subzones = gui.Combobox()
        self.combo_subzones.set_on_selection_changed(self._on_subzone_combo_changed)
        self.panel.add_child(self.combo_subzones)

        horiz_nav = gui.Horiz(4)
        btn_prev = gui.Button("< Previous")
        btn_prev.set_on_clicked(self._on_prev_subzone)
        btn_next = gui.Button("Next >")
        btn_next.set_on_clicked(self._on_next_subzone)
        horiz_nav.add_child(btn_prev)
        horiz_nav.add_child(btn_next)
        self.panel.add_child(horiz_nav)
        self.panel.add_fixed(em * 0.5)

        # 3. Ground Truth File Picker
        self.panel.add_child(gui.Label("3. Ground Truth Trees (.shp / .geojson)"))
        horiz_gt = gui.Horiz(4)
        self.txt_gt_path = gui.TextEdit()
        self.txt_gt_path.text_value = self.config.get("gt_file", "")
        btn_browse_gt = gui.Button("Browse...")
        btn_browse_gt.set_on_clicked(self._on_browse_gt_file)
        horiz_gt.add_child(self.txt_gt_path)
        horiz_gt.add_child(btn_browse_gt)
        self.panel.add_child(horiz_gt)
        self.panel.add_fixed(em * 0.5)

        # 4. DTM Surface Raster Picker
        self.panel.add_child(gui.Label("4. DTM Surface Raster (.tif)"))
        horiz_dtm = gui.Horiz(4)
        self.txt_dtm_path = gui.TextEdit()
        self.txt_dtm_path.text_value = self.config.get("dtm_file", "")
        btn_browse_dtm = gui.Button("Browse...")
        btn_browse_dtm.set_on_clicked(self._on_browse_dtm_file)
        horiz_dtm.add_child(self.txt_dtm_path)
        horiz_dtm.add_child(btn_browse_dtm)
        self.panel.add_child(horiz_dtm)
        self.panel.add_fixed(em * 0.5)

        # 5. Standard Layer Visibility Checkboxes
        self.panel.add_child(gui.Label("5. Standard Layers"))
        self.chk_pcd = gui.Checkbox("Point Cloud (Segmented / RGB)")
        self.chk_pcd.checked = True
        self.chk_pcd.set_on_checked(lambda chk: self._update_scene(reset_camera=False))
        self.panel.add_child(self.chk_pcd)

        self.chk_detected = gui.Checkbox("Detected Trees (Green Spheres)")
        self.chk_detected.checked = True
        self.chk_detected.set_on_checked(lambda chk: self._update_scene(reset_camera=False))
        self.panel.add_child(self.chk_detected)

        self.chk_gt = gui.Checkbox("Ground Truth Trees (Red Spheres)")
        self.chk_gt.checked = True
        self.chk_gt.set_on_checked(lambda chk: self._update_scene(reset_camera=False))
        self.panel.add_child(self.chk_gt)

        self.chk_dtm = gui.Checkbox("DTM Terrain Mesh Surface")
        self.chk_dtm.checked = True
        self.chk_dtm.set_on_checked(lambda chk: self._update_scene(reset_camera=False))
        self.panel.add_child(self.chk_dtm)
        self.panel.add_fixed(em * 0.5)

        # 6. Custom Vector Layer Manager
        self.panel.add_child(gui.Label("6. Custom Vector Layers"))
        btn_add_vector = gui.Button("+ Add Vector Layer (.shp)")
        btn_add_vector.set_on_clicked(self._on_add_vector_layer)
        self.panel.add_child(btn_add_vector)

        # Build dynamic custom vector rows
        self.vector_row_widgets = []
        for i, vec in enumerate(self.custom_vectors):
            row = gui.Horiz(4)
            label_name = f"{vec.get('name', 'Layer')} [{vec.get('color', 'Yellow')}, {vec.get('offset', '0ft')}]"
            chk = gui.Checkbox(label_name)
            chk.checked = vec.get("visible", True)
            chk.set_on_checked(lambda is_checked, idx=i: self._on_vector_toggle(idx, is_checked))

            btn_del = gui.Button(" X ")
            btn_del.set_on_clicked(lambda idx=i: self._on_remove_vector_layer(idx))

            row.add_child(chk)
            row.add_child(btn_del)
            self.vector_row_widgets.append(row)
            self.panel.add_child(row)

        self.panel.add_fixed(em * 0.5)

        # Metrics Sidebar Box
        self.panel.add_child(gui.Label("Subzone Metrics"))
        self.lbl_stats = gui.Label("Select a tree detection run .yml file...")
        self.panel.add_child(self.lbl_stats)

    def _on_vector_toggle(self, index, is_checked):
        if 0 <= index < len(self.custom_vectors):
            self.custom_vectors[index]["visible"] = is_checked
            log_info(f"Toggled vector layer '{self.custom_vectors[index]['name']}' visibility -> {is_checked}")
            save_last_config(self._get_clean_config())
            self._update_scene(reset_camera=False)

    def _on_remove_vector_layer(self, index):
        """Remove custom vector layer permanently when [X] is clicked."""
        if 0 <= index < len(self.custom_vectors):
            removed_name = self.custom_vectors[index].get("name", "Layer")
            log_info(f"Removing custom vector layer: {removed_name}")

            # Instantly hide widget row in Open3D GUI
            if index < len(self.vector_row_widgets):
                self.vector_row_widgets[index].visible = False

            self.custom_vectors[index]["visible"] = False
            self.custom_vectors[index]["deleted"] = True

            save_last_config(self._get_clean_config())
            self.window.set_needs_layout()
            self._update_scene(reset_camera=False)

    def _get_clean_config(self):
        return {
            "run_yml": self.config.get("run_yml", ""),
            "gt_file": self.txt_gt_path.text_value if hasattr(self, "txt_gt_path") else "",
            "dtm_file": self.txt_dtm_path.text_value if hasattr(self, "txt_dtm_path") else "",
            "custom_vectors": [
                {
                    "name": vec.get("name"),
                    "path": vec.get("path"),
                    "type": vec.get("type", "Polyline"),
                    "color": vec.get("color", "Yellow"),
                    "offset": vec.get("offset", "0.0 ft"),
                    "visible": vec.get("visible", True),
                }
                for vec in self.custom_vectors
                if not vec.get("deleted", False)
            ],
        }

    def _on_browse_run_file(self):
        path = open_native_file_picker("Select Tree Detection Run (.yml)", "*.yml;*.yaml")
        if path:
            self.txt_run_path.text_value = path
            self.config["run_yml"] = path
            save_last_config(self._get_clean_config())
            self._load_run_target(path)

    def _on_browse_gt_file(self):
        path = open_native_file_picker("Select Ground Truth File", "*.shp;*.geojson")
        if path:
            self.txt_gt_path.text_value = path
            save_last_config(self._get_clean_config())
            self._update_scene(reset_camera=False)

    def _on_browse_dtm_file(self):
        path = open_native_file_picker("Select DTM Surface Raster", "*.tif;*.tiff")
        if path:
            self.txt_dtm_path.text_value = path
            save_last_config(self._get_clean_config())
            self._update_scene(reset_camera=False)

    def _on_add_vector_layer(self):
        """Single unified workflow: click '+ Add Vector Layer' opens single configuration dialog window."""
        cfg = open_unified_add_vector_dialog()
        if cfg and cfg.get("path") and os.path.exists(cfg["path"]):
            new_vec = {
                "name": cfg.get("name", os.path.splitext(os.path.basename(cfg["path"]))[0]),
                "path": cfg["path"],
                "type": cfg.get("type", "Polyline"),
                "color": cfg.get("color", "Yellow"),
                "offset": f"{cfg.get('offset', '0.0')} ft",
                "visible": True,
            }
            idx = len(self.custom_vectors)
            self.custom_vectors.append(new_vec)
            save_last_config(self._get_clean_config())

            # Add row control dynamically
            row = gui.Horiz(4)
            label_name = f"{new_vec['name']} [{new_vec['color']}, {new_vec['offset']}]"
            chk = gui.Checkbox(label_name)
            chk.checked = True
            chk.set_on_checked(lambda is_checked, i=idx: self._on_vector_toggle(i, is_checked))

            btn_del = gui.Button(" X ")
            btn_del.set_on_clicked(lambda i=idx: self._on_remove_vector_layer(i))

            row.add_child(chk)
            row.add_child(btn_del)
            self.vector_row_widgets.append(row)
            self.panel.add_child(row)

            self.window.set_needs_layout()
            self._update_scene(reset_camera=False)

    def _load_run_target(self, run_target):
        """Load tree detection run config/folder and auto-render index 0 immediately."""
        try:
            log_info(f"Loading tree detection target: {run_target}")
            self.run_loader = TreeRunDataLoader(run_target)
            self.current_subzones = self.run_loader.subzones

            self.combo_subzones.clear_items()
            for sz in self.current_subzones:
                self.combo_subzones.add_item(sz)

            self.current_index = 0
            if self.current_subzones:
                self.combo_subzones.selected_index = 0
                log_info(f"Auto-selected initial subzone: {self.current_subzones[0]}")

            self._update_scene(reset_camera=True)
        except Exception as e:
            log_err(f"Error loading run target {run_target}: {e}")
            if hasattr(self, "lbl_stats"):
                self.lbl_stats.text = f"Error loading run:\n{e}"

    def _on_subzone_combo_changed(self, name, index):
        if 0 <= index < len(self.current_subzones):
            self.current_index = index
            log_info(f"Subzone dropdown changed to: {self.current_subzones[index]}")
            self._update_scene(reset_camera=True)

    def _on_prev_subzone(self):
        if self.current_index > 0:
            self.current_index -= 1
            if hasattr(self, "combo_subzones"):
                self.combo_subzones.selected_index = self.current_index
            log_info(f"Switched to Previous subzone: {self.current_subzones[self.current_index]}")
            self._update_scene(reset_camera=True)

    def _on_next_subzone(self):
        if self.current_index < len(self.current_subzones) - 1:
            self.current_index += 1
            if hasattr(self, "combo_subzones"):
                self.combo_subzones.selected_index = self.current_index
            log_info(f"Switched to Next subzone: {self.current_subzones[self.current_index]}")
            self._update_scene(reset_camera=True)

    def _update_scene(self, reset_camera=False):
        """Reload 3D scene geometries cleanly. Preserves camera unless switching subzones."""
        if not self.current_subzones or self.current_index >= len(self.current_subzones):
            return

        try:
            subzone_name = self.current_subzones[self.current_index]
            log_info(f"--- Rendering 3D Scene for Subzone: {subzone_name} ({self.current_index + 1}/{len(self.current_subzones)}) [Reset Camera: {reset_camera}] ---")

            # Clear 3D scene safely
            self.widget_3d.scene.clear_geometry()

            all_xyz = []
            all_z_mins = []
            tree_coords = []
            total_pts = 0
            total_det_trees = 0
            total_gt_trees = 0
            geom_counter = 0

            dtm_file = self.txt_dtm_path.text_value if hasattr(self, "txt_dtm_path") else ""

            # Active Target CRS (for vector reprojection)
            target_crs = None
            if self.run_loader and self.run_loader.trees_gdf is not None and self.run_loader.trees_gdf.crs is not None:
                target_crs = self.run_loader.trees_gdf.crs
            else:
                target_crs = "EPSG:6529"  # Default NM Central Feet

            # 1. Point Cloud (from segmented_point_clouds/)
            if self.run_loader:
                xyz, rgb, las = self.run_loader.load_point_cloud(subzone_name)
                if xyz is not None and len(xyz) > 0:
                    all_xyz.append(xyz)
                    z_min_cloud = float(las.z.min())
                    all_z_mins.append(z_min_cloud)
                    total_pts += len(xyz)

                    if hasattr(self, "chk_pcd") and self.chk_pcd.checked:
                        pcd = o3d.geometry.PointCloud()
                        pcd.points = o3d.utility.Vector3dVector(xyz)
                        pcd.colors = o3d.utility.Vector3dVector(rgb)

                        self.widget_3d.scene.add_geometry(f"pcd_{geom_counter}", pcd, self.mat_pcd)
                        geom_counter += 1

            # 2. Detected Trees (from tree_detection_run)
            det_gdf = None
            if self.run_loader:
                det_gdf = self.run_loader.load_subzone_trees(subzone_name)

            if all_z_mins:
                z_min = min(all_z_mins)
            elif det_gdf is not None and not det_gdf.empty:
                ground_vals = []
                for _, r in det_gdf.iterrows():
                    g_val = r.get("ground_elevation", None)
                    if g_val is not None and not np.isnan(g_val):
                        ground_vals.append(float(g_val))
                    else:
                        zm = r.get("z_max", None)
                        h = r.get("height_max", 15.0)
                        if zm is not None and not np.isnan(zm):
                            ground_vals.append(float(zm) - float(h))
                z_min = min(ground_vals) if ground_vals else 0.0
            else:
                z_min = 0.0

            # Determine EXACT spatial bounding box of active subzone (buffer=0.0) for strict clipping
            subzone_bounds = None
            if all_xyz:
                combined_xyz = np.vstack(all_xyz)
                subzone_bounds = (
                    np.min(combined_xyz[:, 0]),
                    np.min(combined_xyz[:, 1]),
                    np.max(combined_xyz[:, 0]),
                    np.max(combined_xyz[:, 1]),
                )
            elif det_gdf is not None and not det_gdf.empty:
                subzone_bounds = (
                    float(det_gdf.geometry.x.min()),
                    float(det_gdf.geometry.y.min()),
                    float(det_gdf.geometry.x.max()),
                    float(det_gdf.geometry.y.max()),
                )

            if det_gdf is not None and not det_gdf.empty and hasattr(self, "chk_detected") and self.chk_detected.checked:
                total_det_trees += len(det_gdf)
                for _, row in det_gdf.iterrows():
                    geom = row.geometry
                    if geom is None or geom.is_empty:
                        continue
                    tx, ty = geom.x, geom.y

                    height = float(row.get("height_max", 15.0) or 15.0)
                    tz_top = float(row.get("z_max", z_min + height) or (z_min + height))
                    tz_ground = float(row.get("ground_elevation", tz_top - height) or (tz_top - height))

                    if np.isnan(tz_ground):
                        tz_ground = z_min
                    if np.isnan(tz_top):
                        tz_top = tz_ground + height

                    tree_coords.append([tx, ty, tz_top])

                    # Green Sphere at treetop
                    sphere = o3d.geometry.TriangleMesh.create_sphere(radius=2.0)
                    sphere.translate([tx, ty, tz_top])
                    sphere.paint_uniform_color([0.0, 1.0, 0.0])
                    sphere.compute_vertex_normals()

                    self.widget_3d.scene.add_geometry(f"det_sphere_{geom_counter}", sphere, self.mat_mesh)
                    geom_counter += 1

                    # Vertical Stem Line
                    line = o3d.geometry.LineSet()
                    line.points = o3d.utility.Vector3dVector([[tx, ty, tz_ground], [tx, ty, tz_top]])
                    line.lines = o3d.utility.Vector2iVector([[0, 1]])
                    line.colors = o3d.utility.Vector3dVector([[0.0, 1.0, 0.0]])

                    self.widget_3d.scene.add_geometry(f"det_line_{geom_counter}", line, self.mat_line)
                    geom_counter += 1

            # 3. Ground Truth Trees Layer (Strictly Clipped to Subzone Tile Box buffer=0.0)
            gt_file = self.txt_gt_path.text_value if hasattr(self, "txt_gt_path") else ""

            if hasattr(self, "chk_gt") and self.chk_gt.checked and gt_file and os.path.exists(gt_file):
                gt_gdf = load_vector_file(gt_file, target_crs=target_crs, bounds=subzone_bounds, buffer=0.0)
                if gt_gdf is not None and not gt_gdf.empty:
                    total_gt_trees += len(gt_gdf)

                    # Extract X, Y coordinates in projected target CRS to sample DTM ground elevation
                    gx_arr = np.array([row.geometry.x for _, row in gt_gdf.iterrows() if row.geometry is not None and not row.geometry.is_empty])
                    gy_arr = np.array([row.geometry.y for _, row in gt_gdf.iterrows() if row.geometry is not None and not row.geometry.is_empty])

                    sampled_z_ground = None
                    if dtm_file and os.path.exists(dtm_file) and len(gx_arr) > 0:
                        sampled_z_ground = sample_dtm_elevation(dtm_file, gx_arr, gy_arr)

                    valid_idx = 0
                    for _, row in gt_gdf.iterrows():
                        geom = row.geometry
                        if geom is None or geom.is_empty:
                            continue
                        gx, gy = geom.x, geom.y

                        # Search for tree height across all truncated and full field names
                        ht = None
                        for hkey in ["est_ht_ft", "est_ht_", "est_ht", "height", "est_height", "ht_ft", "ht"]:
                            hval = row.get(hkey, None)
                            if hval is not None and not np.isnan(float(hval)):
                                ht = float(hval)
                                break
                        if ht is None or ht <= 0:
                            ht = 15.0

                        # Check if GT point geometry has 3D Z coordinates
                        if getattr(geom, "has_z", False):
                            gt_top = float(geom.z)
                            gt_ground = gt_top - ht
                        else:
                            # Use DTM ground elevation at (gx, gy) if available, else z_min
                            if sampled_z_ground is not None and valid_idx < len(sampled_z_ground) and not np.isnan(sampled_z_ground[valid_idx]):
                                gt_ground = sampled_z_ground[valid_idx]
                            else:
                                gt_ground = z_min
                            gt_top = gt_ground + ht

                        valid_idx += 1
                        tree_coords.append([gx, gy, gt_top])

                        # Red Sphere at treetop head
                        sphere = o3d.geometry.TriangleMesh.create_sphere(radius=2.0)
                        sphere.translate([gx, gy, gt_top])
                        sphere.paint_uniform_color([1.0, 0.0, 0.0])
                        sphere.compute_vertex_normals()

                        self.widget_3d.scene.add_geometry(f"gt_sphere_{geom_counter}", sphere, self.mat_mesh)
                        geom_counter += 1

                        # Red Stem Line connecting ground base (DTM) to treetop head (DTM + est_ht_ft)
                        line = o3d.geometry.LineSet()
                        line.points = o3d.utility.Vector3dVector([[gx, gy, gt_ground], [gx, gy, gt_top]])
                        line.lines = o3d.utility.Vector2iVector([[0, 1]])
                        line.colors = o3d.utility.Vector3dVector([[1.0, 0.0, 0.0]])

                        self.widget_3d.scene.add_geometry(f"gt_line_{geom_counter}", line, self.mat_line)
                        geom_counter += 1

            # 4. Custom User-Added Vector Layers (DTM Terrain Draping: Polyline vs Area Polygon)
            active_custom_count = 0
            for vec_idx, vec in enumerate(self.custom_vectors):
                if vec.get("deleted", False) or not vec.get("visible", True) or not vec.get("path") or not os.path.exists(vec["path"]):
                    continue

                active_custom_count += 1
                v_gdf = load_vector_file(vec["path"], target_crs=target_crs, bounds=subzone_bounds, buffer=0.0)
                if v_gdf is None or v_gdf.empty:
                    continue

                col_name = vec.get("color", "Yellow")
                color_rgb = COLOR_MAP.get(col_name, [1.0, 1.0, 0.0])
                offset_str = vec.get("offset", "0.0 ft")
                try:
                    offset_val = float(offset_str.replace("ft", "").replace("+", "").strip())
                except Exception:
                    offset_val = 0.0

                is_area = (vec.get("type", "Polyline") == "Area")

                # Combine all cylinder segment meshes into ONE single TriangleMesh per layer to prevent Filament scene object overflow crash!
                layer_mesh = o3d.geometry.TriangleMesh()

                for _, row in v_gdf.iterrows():
                    geom = row.geometry
                    if geom is None or geom.is_empty:
                        continue

                    # Drape vector geometry smoothly over DTM surface
                    draped_lines_3d = drape_geometry_on_dtm(
                        geom, tif_path=dtm_file, z_offset=offset_val, step_distance=5.0, default_z=z_min
                    )

                    for coords_3d in draped_lines_3d:
                        if len(coords_3d) < 2:
                            continue
                        for i in range(len(coords_3d) - 1):
                            p0 = coords_3d[i]
                            p1 = coords_3d[i + 1]
                            seg_len = float(np.linalg.norm(p1 - p0))
                            if seg_len < 0.05:
                                continue

                            rad = 1.4 if is_area else 0.8
                            cyl = o3d.geometry.TriangleMesh.create_cylinder(radius=rad, height=seg_len, resolution=8)
                            cyl.translate([0, 0, seg_len / 2.0], relative=False)

                            direction = (p1 - p0) / seg_len
                            z_axis = np.array([0, 0, 1.0])
                            v = np.cross(z_axis, direction)
                            s = np.linalg.norm(v)
                            c = np.dot(z_axis, direction)

                            if s < 1e-8:
                                R = np.eye(3) if c > 0 else -np.eye(3)
                            else:
                                v_x = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
                                R = np.eye(3) + v_x + v_x @ v_x * ((1.0 - c) / (s * s))

                            cyl.rotate(R, center=[0, 0, 0])
                            cyl.translate(p0)
                            layer_mesh += cyl

                if len(layer_mesh.vertices) > 0:
                    layer_mesh.paint_uniform_color(color_rgb)
                    layer_mesh.compute_vertex_normals()
                    self.widget_3d.scene.add_geometry(f"custom_vec_{vec_idx}", layer_mesh, self.mat_mesh)
                    geom_counter += 1

            # 5. DTM Terrain Surface Raster (Mesh sampled at true 3D raster elevation!)
            if hasattr(self, "chk_dtm") and self.chk_dtm.checked and dtm_file and os.path.exists(dtm_file):
                verts, tris, raster_bounds = load_dtm_surface(dtm_file, bounds=subzone_bounds)
                if verts is not None:
                    mesh = o3d.geometry.TriangleMesh()
                    mesh.vertices = o3d.utility.Vector3dVector(verts)
                    mesh.triangles = o3d.utility.Vector3iVector(tris)
                    mesh.paint_uniform_color([0.3, 0.45, 0.3])
                    mesh.compute_vertex_normals()

                    self.widget_3d.scene.add_geometry(f"dtm_{geom_counter}", mesh, self.mat_mesh)
                    geom_counter += 1

            # Update Metrics Text
            stat_text = (
                f"Active Subzone: {subzone_name}\n"
                f"Subzone Index: {self.current_index + 1} of {len(self.current_subzones)}\n"
                f"Segmented LiDAR Points: {total_pts:,}\n"
                f"Detected Trees: {total_det_trees}\n"
                f"Ground Truth Trees: {total_gt_trees}\n"
                f"Custom Vector Layers: {active_custom_count}"
            )
            if hasattr(self, "lbl_stats"):
                self.lbl_stats.text = stat_text

            # Camera Setup (ONLY reset camera when switching subzones, NOT on layer toggles!)
            if reset_camera:
                camera_points = []
                if all_xyz:
                    camera_points.append(np.vstack(all_xyz))
                elif tree_coords:
                    camera_points.append(np.array(tree_coords))

                if camera_points:
                    combined_pts = np.vstack(camera_points)
                    if len(combined_pts) > 0:
                        min_b = np.min(combined_pts, axis=0)
                        max_b = np.max(combined_pts, axis=0)
                        for axis in range(3):
                            if max_b[axis] - min_b[axis] < 1.0:
                                min_b[axis] -= 5.0
                                max_b[axis] += 5.0
                        bbox = o3d.geometry.AxisAlignedBoundingBox(min_b, max_b)
                        self.widget_3d.setup_camera(60.0, bbox, bbox.get_center())

            self.widget_3d.force_redraw()
            log_info(f"Successfully rendered subzone {subzone_name} ({total_pts:,} pts, {total_det_trees} det trees, {total_gt_trees} GT trees)")
        except Exception as e:
            log_err(f"Error rendering scene: {e}")

    def run(self):
        """Run desktop application loop."""
        self.app.run()


def main():
    parser = argparse.ArgumentParser(description="Interactive 3D Subzone Visualizer")
    parser.add_argument("--run-yml", default=None, help="Optional tree detection run .yml file")
    args = parser.parse_args()

    app = SubzoneVisualizerApp(initial_run_target=args.run_yml)
    app.run()


if __name__ == "__main__":
    main()
