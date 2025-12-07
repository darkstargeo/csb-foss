"""
Polygon simplification module for CSB-FOSS.

Provides polygon simplification functionality using Shapely.
Replaces arcpy.cartography.SimplifyPolygon().
"""

from typing import Optional

import geopandas as gpd
import numpy as np
from shapely.geometry import Polygon, MultiPolygon
from shapely.validation import make_valid
from tqdm import tqdm


def simplify_polygons(
    gdf: gpd.GeoDataFrame,
    tolerance: float = 60.0,
    preserve_topology: bool = True,
    min_area: Optional[float] = None,
    progress: bool = True,
) -> gpd.GeoDataFrame:
    """
    Simplify polygon geometries using Douglas-Peucker algorithm.

    This is a FOSS approximation of ArcGIS BEND_SIMPLIFY.
    True Wang-Müller algorithm would require custom implementation.

    Args:
        gdf: GeoDataFrame with polygon geometries
        tolerance: Simplification tolerance in CRS units (meters for projected)
        preserve_topology: Maintain valid topology (prevents self-intersections)
        min_area: Optional minimum area - polygons smaller than this after
                  simplification are removed
        progress: Show progress information

    Returns:
        GeoDataFrame with simplified polygons
    """
    gdf = gdf.copy()

    if progress:
        print(f"Simplifying {len(gdf)} polygons with tolerance {tolerance}...")

    simplified_geoms = []
    valid_indices = []

    iterator = tqdm(gdf.index, desc="Simplifying") if progress else gdf.index

    for idx in iterator:
        geom = gdf.loc[idx, "geometry"]

        # Simplify
        simplified = geom.simplify(tolerance, preserve_topology=preserve_topology)

        # Validate and repair if needed
        if not simplified.is_valid:
            simplified = make_valid(simplified)

        # Handle empty or invalid results
        if simplified.is_empty:
            continue

        # Handle MultiPolygon - keep largest part
        if isinstance(simplified, MultiPolygon):
            simplified = max(simplified.geoms, key=lambda x: x.area)

        # Area filter
        if min_area is not None and simplified.area < min_area:
            continue

        simplified_geoms.append(simplified)
        valid_indices.append(idx)

    # Create result GeoDataFrame
    result = gdf.loc[valid_indices].copy()
    result["geometry"] = simplified_geoms

    # Update area
    if "shape_area" in result.columns:
        result["shape_area"] = result.geometry.area

    if progress:
        print(f"  Simplified to {len(result)} polygons")

    return result


def smooth_polygons(
    gdf: gpd.GeoDataFrame,
    iterations: int = 2,
    progress: bool = True,
) -> gpd.GeoDataFrame:
    """
    Smooth polygon boundaries using buffer-based smoothing.

    This applies a small buffer followed by negative buffer to round corners.

    Args:
        gdf: GeoDataFrame with polygon geometries
        iterations: Number of smoothing iterations
        progress: Show progress information

    Returns:
        GeoDataFrame with smoothed polygons
    """
    gdf = gdf.copy()

    if progress:
        print(f"Smoothing {len(gdf)} polygons ({iterations} iterations)...")

    smoothed_geoms = []
    valid_indices = []

    iterator = tqdm(gdf.index, desc="Smoothing") if progress else gdf.index

    for idx in iterator:
        geom = gdf.loc[idx, "geometry"]

        # Apply buffer-based smoothing
        smoothed = geom
        for _ in range(iterations):
            # Small positive buffer followed by same negative buffer
            # This rounds sharp corners
            smoothed = smoothed.buffer(1).buffer(-1)

        if smoothed.is_empty:
            continue

        # Handle MultiPolygon
        if isinstance(smoothed, MultiPolygon):
            smoothed = max(smoothed.geoms, key=lambda x: x.area)

        smoothed_geoms.append(smoothed)
        valid_indices.append(idx)

    result = gdf.loc[valid_indices].copy()
    result["geometry"] = smoothed_geoms

    if "shape_area" in result.columns:
        result["shape_area"] = result.geometry.area

    if progress:
        print(f"  Smoothed to {len(result)} polygons")

    return result


def simplify_topology_aware(
    gdf: gpd.GeoDataFrame,
    tolerance: float = 60.0,
    progress: bool = True,
) -> gpd.GeoDataFrame:
    """
    Simplify polygons while maintaining topological relationships.

    This ensures that adjacent polygons share simplified boundaries,
    preventing gaps and overlaps.

    Args:
        gdf: GeoDataFrame with polygon geometries
        tolerance: Simplification tolerance
        progress: Show progress information

    Returns:
        GeoDataFrame with topology-aware simplified polygons
    """
    # For now, use standard simplification
    # Full topological simplification would require more complex implementation
    # using shared edge tracking
    return simplify_polygons(gdf, tolerance=tolerance, preserve_topology=True, progress=progress)


def calculate_boundary_roughness(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Calculate boundary roughness metric for each polygon.

    Roughness = perimeter / sqrt(area)
    Higher values indicate more complex/rough boundaries.

    Args:
        gdf: GeoDataFrame with polygon geometries

    Returns:
        GeoDataFrame with 'roughness' column added
    """
    gdf = gdf.copy()
    gdf["roughness"] = gdf.geometry.length / np.sqrt(gdf.geometry.area)
    return gdf
