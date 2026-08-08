"""
Data Loader and Persistence Module for visualize_subzone_3d
Handles user-selected tree detection run YAML files, segmented point clouds,
ground truth vector files, custom vector shapefiles, and DTM rasters.
"""

import os
import json
import yaml
import numpy as np
import pandas as pd
import geopandas as gpd
import laspy
from shapely.geometry import box, LineString, MultiLineString, GeometryCollection, Polygon, MultiPolygon


CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_config.json")


def log_info(msg):
    print(f"[INFO] {msg}")


def log_warn(msg):
    print(f"[WARNING] {msg}")


def log_err(msg):
    print(f"[ERROR] {msg}")


def load_last_config():
    """Load previously saved app configuration (paths, vector layers)."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                log_info(f"Loaded previous session configuration from: {CONFIG_FILE}")
                return cfg
        except Exception as e:
            log_warn(f"Failed to load last config: {e}")
    return {"run_yml": "", "gt_file": "", "dtm_file": "", "custom_vectors": []}


def save_last_config(config_dict):
    """Save app configuration to last_config.json."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, indent=2)
            log_info(f"Saved session configuration to {CONFIG_FILE}")
    except Exception as e:
        log_warn(f"Failed to save config: {e}")


class TreeRunDataLoader:
    """Loader for a user-selected Tree Detection Run directory or YAML config file."""

    def __init__(self, run_target):
        self.run_target = os.path.abspath(run_target) if run_target else ""
        self.run_folder = ""
        self.trees_gdf = None
        self.subzones = []

        if self.run_target and os.path.exists(self.run_target):
            if os.path.isfile(self.run_target):
                self.run_folder = os.path.dirname(self.run_target)
            else:
                self.run_folder = self.run_target
            log_info(f"Loading Tree Detection Run folder: {self.run_folder}")
            self._parse_run_folder()

    def _parse_run_folder(self):
        """Parse tree run folder and extract subzone list."""
        manifest_csv = os.path.join(self.run_folder, "tree_detection_manifest.csv")
        geojson_path = os.path.join(self.run_folder, "tree_locations.geojson")
        shp_path = os.path.join(self.run_folder, "tree_locations.shp")
        run_yml_path = os.path.join(self.run_folder, "tree_detection_run.yml")

        subzone_set = set()

        # 1. Read tree_detection_run.yml if present
        if os.path.exists(run_yml_path):
            try:
                with open(run_yml_path, "r", encoding="utf-8") as f:
                    ydata = yaml.safe_load(f) or {}
                if "feature_ids" in ydata and ydata["feature_ids"]:
                    fids = ydata["feature_ids"]
                    if isinstance(fids, list):
                        subzone_set.update([str(x) for x in fids])
                    elif isinstance(fids, str):
                        subzone_set.update([x.strip() for x in fids.split(",") if x.strip()])
                    log_info(f"Extracted {len(subzone_set)} subzones from tree_detection_run.yml")
            except Exception as e:
                log_warn(f"Failed to read tree_detection_run.yml: {e}")

        # 2. Read manifest CSV if available
        if not subzone_set and os.path.exists(manifest_csv):
            try:
                mdf = pd.read_csv(manifest_csv)
                for col in ["feature_id", "subzone_name", "subzone_id"]:
                    if col in mdf.columns:
                        subzone_set.update(mdf[col].dropna().astype(str).tolist())
                        log_info(f"Extracted {len(subzone_set)} subzones from manifest CSV")
                        break
            except Exception as e:
                log_warn(f"Failed to read manifest CSV: {e}")

        # 3. Read tree locations GeoDataFrame
        target_tree_file = geojson_path if os.path.exists(geojson_path) else (shp_path if os.path.exists(shp_path) else None)
        if target_tree_file and os.path.exists(target_tree_file):
            try:
                self.trees_gdf = gpd.read_file(target_tree_file)
                log_info(f"Loaded {len(self.trees_gdf)} tree locations from {os.path.basename(target_tree_file)} (CRS: {self.trees_gdf.crs})")
                if not subzone_set:
                    for col in ["subzone_name", "subzone_id", "feature_id"]:
                        if col in self.trees_gdf.columns:
                            subzone_set.update(self.trees_gdf[col].dropna().astype(str).tolist())
                            break
            except Exception as e:
                log_err(f"Failed loading tree locations file {target_tree_file}: {e}")

        # 4. Check segmented_point_clouds directory
        seg_dir = os.path.join(self.run_folder, "segmented_point_clouds")
        if os.path.exists(seg_dir):
            log_info(f"Segmented point cloud directory found at: {seg_dir}")
            if not subzone_set:
                for fname in os.listdir(seg_dir):
                    if fname.lower().endswith((".laz", ".las")):
                        base = os.path.splitext(fname)[0]
                        clean = (
                            base.replace("subzone_", "")
                            .replace("_tree_segments", "")
                            .replace("_segmented", "")
                            .replace("_veg", "")
                        )
                        subzone_set.add(clean)

        self.subzones = sorted(list(subzone_set))
        log_info(f"Total subzones registered for run: {len(self.subzones)} -> {self.subzones}")

    def load_point_cloud(self, subzone_name):
        """Load segmented point cloud for a subzone if segmented_point_clouds folder exists."""
        if not self.run_folder:
            return None, None, None

        seg_dir = os.path.join(self.run_folder, "segmented_point_clouds")
        if not os.path.exists(seg_dir):
            log_warn(f"No segmented_point_clouds directory in {self.run_folder}")
            return None, None, None

        candidates = [
            os.path.join(seg_dir, f"{subzone_name}_tree_segments.laz"),
            os.path.join(seg_dir, f"{subzone_name}_tree_segments.las"),
            os.path.join(seg_dir, f"subzone_{subzone_name}_tree_segments.laz"),
            os.path.join(seg_dir, f"subzone_{subzone_name}_tree_segments.las"),
            os.path.join(seg_dir, f"subzone_{subzone_name}_segmented.laz"),
            os.path.join(seg_dir, f"subzone_{subzone_name}_segmented.las"),
            os.path.join(seg_dir, f"{subzone_name}_segmented.laz"),
            os.path.join(seg_dir, f"subzone_{subzone_name}.laz"),
            os.path.join(seg_dir, f"{subzone_name}.laz"),
        ]

        target_file = None
        for c in candidates:
            if os.path.exists(c):
                target_file = c
                break

        if not target_file:
            log_warn(f"Segmented point cloud file not found for subzone {subzone_name} in {seg_dir}")
            return None, None, None

        try:
            las = laspy.read(target_file)
            if las.header.point_count == 0:
                log_warn(f"Point cloud file {target_file} has 0 points")
                return None, None, las

            xyz = np.column_stack((las.x, las.y, las.z))
            log_info(f"Loaded point cloud {os.path.basename(target_file)} ({las.header.point_count:,} points, Z: {las.z.min():.1f}-{las.z.max():.1f} ft)")

            # Color handling
            if hasattr(las, "red") and hasattr(las, "green") and hasattr(las, "blue"):
                max_val = 65535.0 if np.max(las.red) > 255 else 255.0
                rgb = np.column_stack((las.red, las.green, las.blue)).astype(np.float64) / max_val
            elif hasattr(las, "tree_uid") or hasattr(las, "TreeID"):
                tree_ids = las.tree_uid if hasattr(las, "tree_uid") else las.TreeID
                unique_ids = np.unique(tree_ids)
                np.random.seed(42)
                palette = np.random.uniform(0.2, 1.0, size=(len(unique_ids), 3))
                id_map = {tid: palette[i] for i, tid in enumerate(unique_ids)}
                rgb = np.array([id_map.get(tid, [0.5, 0.5, 0.5]) for tid in tree_ids])
            else:
                z_range = max(las.z.max() - las.z.min(), 1.0)
                z_norm = (las.z - las.z.min()) / z_range
                rgb = np.column_stack((0.2 + 0.6 * z_norm, 0.7 - 0.5 * z_norm, 0.3 * (1 - z_norm)))

            return xyz, rgb, las
        except Exception as e:
            log_err(f"Error reading point cloud file {target_file}: {e}")
            return None, None, None

    def load_subzone_trees(self, subzone_name):
        """Return detected trees GeoDataFrame for a subzone."""
        if self.trees_gdf is None or self.trees_gdf.empty:
            return None

        for col in ["subzone_name", "subzone_id", "feature_id"]:
            if col in self.trees_gdf.columns:
                match = self.trees_gdf[self.trees_gdf[col].astype(str) == str(subzone_name)]
                if not match.empty:
                    log_info(f"Loaded {len(match)} detected trees for subzone {subzone_name}")
                    return match.copy()
        log_warn(f"No detected trees found for subzone {subzone_name}")
        return None


def load_vector_file(file_path, target_crs=None, bounds=None, buffer=50):
    """Load any user shapefile or GeoJSON vector layer with automatic CRS reprojection."""
    if not file_path or not os.path.exists(file_path):
        return None

    try:
        gdf = gpd.read_file(file_path)
        if gdf.empty:
            return None

        log_info(f"Loaded vector file {os.path.basename(file_path)} ({len(gdf)} features, CRS: {gdf.crs})")

        # Automatic CRS Reprojection if target_crs is specified
        if target_crs is not None and gdf.crs is not None and gdf.crs != target_crs:
            log_info(f"Reprojecting {os.path.basename(file_path)} from {gdf.crs} -> {target_crs}")
            gdf = gdf.to_crs(target_crs)

        if bounds is not None:
            minx, miny, maxx, maxy = bounds
            clip_box = box(minx - buffer, miny - buffer, maxx + buffer, maxy + buffer)
            clipped = gdf[gdf.geometry.intersects(clip_box)].copy()
            if not clipped.empty:
                clipped["geometry"] = clipped.geometry.intersection(clip_box)
                log_info(f"Clipped {os.path.basename(file_path)} to subzone bounds: {len(clipped)} features intersect active subzone")
                return clipped[~clipped.geometry.is_empty]
            else:
                log_warn(f"0 features in {os.path.basename(file_path)} intersect active subzone bounds {bounds}")
                return None
        return gdf
    except Exception as e:
        log_err(f"Error reading vector file {file_path}: {e}")
        return None


def sample_dtm_elevation(tif_path, x_coords, y_coords):
    """Sample DTM ground elevation (in feet) at exact (X, Y) coordinates."""
    if not tif_path or not os.path.exists(tif_path):
        return None
    try:
        import rasterio
        with rasterio.open(tif_path) as src:
            data = src.read(1)
            row_indices, col_indices = rasterio.transform.rowcol(src.transform, x_coords, y_coords)
            row_indices = np.clip(row_indices, 0, data.shape[0] - 1)
            col_indices = np.clip(col_indices, 0, data.shape[1] - 1)
            z_vals = data[row_indices, col_indices].astype(np.float64)
            z_vals[np.isnan(z_vals) | (z_vals < -999)] = np.nan
            return z_vals
    except Exception as e:
        log_err(f"Error sampling DTM elevation: {e}")
        return None


def drape_geometry_on_dtm(geom, tif_path=None, z_offset=0.0, step_distance=5.0, default_z=0.0):
    """
    Subdivide LineString/MultiLineString/Polygon geometries and sample DTM elevation at every step,
    draping the 3D vector smoothly over the DTM terrain surface.
    Returns a list of 3D coordinate arrays [Nx3].
    """
    if geom is None or geom.is_empty:
        return []

    lines = []
    if isinstance(geom, LineString):
        lines.append(geom)
    elif isinstance(geom, Polygon):
        lines.append(geom.exterior)
    elif isinstance(geom, MultiLineString):
        lines.extend([g for g in geom.geoms if isinstance(g, LineString)])
    elif isinstance(geom, MultiPolygon):
        lines.extend([poly.exterior for poly in geom.geoms if isinstance(poly, Polygon)])
    elif isinstance(geom, GeometryCollection):
        for g in geom.geoms:
            if isinstance(g, LineString):
                lines.append(g)
            elif isinstance(g, Polygon):
                lines.append(g.exterior)

    draped_lines = []
    for line in lines:
        length = line.length
        if length <= 0:
            continue

        num_steps = max(int(np.ceil(length / step_distance)), 2)
        distances = np.linspace(0, length, num_steps)
        sub_pts = [line.interpolate(d) for d in distances]

        x_coords = np.array([p.x for p in sub_pts])
        y_coords = np.array([p.y for p in sub_pts])

        z_grounds = None
        if tif_path and os.path.exists(tif_path):
            z_grounds = sample_dtm_elevation(tif_path, x_coords, y_coords)

        xyz_3d = []
        for i in range(len(x_coords)):
            x, y = x_coords[i], y_coords[i]
            if z_grounds is not None and not np.isnan(z_grounds[i]):
                zg = z_grounds[i]
            else:
                zg = default_z
            xyz_3d.append([x, y, zg + z_offset])

        draped_lines.append(np.array(xyz_3d))
    return draped_lines


def load_dtm_surface(tif_path, bounds=None, sample_density=100):
    """Load DTM surface raster (.tif) and return 3D vertices/triangles mesh using actual elevation values."""
    if not tif_path or not os.path.exists(tif_path):
        return None, None, None

    try:
        import rasterio
        with rasterio.open(tif_path) as src:
            data = src.read(1)
            b = src.bounds
            transform = src.transform

        log_info(f"Loaded DTM surface raster {os.path.basename(tif_path)} ({src.width}x{src.height} grid, Z: {np.nanmin(data):.1f}-{np.nanmax(data):.1f} ft)")

        if bounds is not None:
            minx, miny, maxx, maxy = bounds
        else:
            minx, miny, maxx, maxy = b.left, b.bottom, b.right, b.top

        # Subsample grid for fast smooth rendering
        grid_x = np.linspace(minx, maxx, sample_density)
        grid_y = np.linspace(miny, maxy, sample_density)
        gx, gy = np.meshgrid(grid_x, grid_y)

        # Sample elevation values from raster grid
        row_indices, col_indices = rasterio.transform.rowcol(transform, gx.ravel(), gy.ravel())
        row_indices = np.clip(row_indices, 0, data.shape[0] - 1)
        col_indices = np.clip(col_indices, 0, data.shape[1] - 1)

        gz = data[row_indices, col_indices].astype(np.float64)

        # Replace nodata values with minimum valid elevation
        valid_mask = ~np.isnan(gz) & (gz > -999)
        min_valid = np.min(gz[valid_mask]) if np.any(valid_mask) else 0.0
        gz[~valid_mask] = min_valid

        verts = np.column_stack((gx.ravel(), gy.ravel(), gz))
        ny, nx = gx.shape

        tris = []
        for iy in range(ny - 1):
            for ix in range(nx - 1):
                i = iy * nx + ix
                tris.append([i, i + 1, i + nx])
                tris.append([i + 1, i + nx + 1, i + nx])

        return verts, np.array(tris), [minx, miny, maxx, maxy]
    except Exception as e:
        log_err(f"Error loading DTM raster {tif_path}: {e}")
        return None, None, None
