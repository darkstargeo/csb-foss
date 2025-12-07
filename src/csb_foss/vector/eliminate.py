"""
Polygon elimination module for CSB-FOSS.

Implements small polygon elimination by merging to the neighbor
with the longest shared boundary. Replaces arcpy.management.Eliminate().
"""

from typing import Optional

import geopandas as gpd
import numpy as np
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from tqdm import tqdm


def find_longest_shared_boundary_neighbor(
    small_geom: Polygon,
    gdf: gpd.GeoDataFrame,
    small_idx: int,
    area_threshold: float,
) -> Optional[int]:
    """
    Find the neighbor with the longest shared boundary.

    Args:
        small_geom: Geometry of the small polygon
        gdf: GeoDataFrame containing all polygons
        small_idx: Index of the small polygon in gdf
        area_threshold: Only consider neighbors larger than this

    Returns:
        Index of best neighbor, or None if no suitable neighbor found
    """
    # Use spatial index to find potential neighbors
    possible_matches = list(gdf.sindex.intersection(small_geom.bounds))

    # Filter to actual neighbors (excluding self and other small polygons)
    best_neighbor = None
    max_shared_length = 0

    for neighbor_idx in possible_matches:
        if neighbor_idx == small_idx:
            continue

        neighbor_geom = gdf.iloc[neighbor_idx].geometry

        # Skip if neighbor is also small (will be processed later)
        if neighbor_geom.area <= area_threshold:
            continue

        # Check if geometries actually touch
        if not small_geom.touches(neighbor_geom) and not small_geom.intersects(neighbor_geom):
            continue

        # Calculate shared boundary length
        try:
            intersection = small_geom.boundary.intersection(neighbor_geom.boundary)
            shared_length = intersection.length if intersection else 0
        except Exception:
            continue

        if shared_length > max_shared_length:
            max_shared_length = shared_length
            best_neighbor = neighbor_idx

    return best_neighbor


def eliminate_small_polygons(
    gdf: gpd.GeoDataFrame,
    area_threshold: float,
    max_iterations: int = 10,
    progress: bool = True,
) -> gpd.GeoDataFrame:
    """
    Eliminate small polygons by merging to neighbor with longest shared boundary.

    Replicates ArcGIS Eliminate() with selection="LENGTH".

    Args:
        gdf: GeoDataFrame with polygon geometries
        area_threshold: Maximum area (in CRS units squared) for elimination
        max_iterations: Maximum number of merge iterations
        progress: Show progress information

    Returns:
        GeoDataFrame with small polygons eliminated
    """
    gdf = gdf.copy().reset_index(drop=True)

    for iteration in range(max_iterations):
        # Identify small polygons
        small_mask = gdf.geometry.area <= area_threshold
        n_small = small_mask.sum()

        if n_small == 0:
            if progress:
                print(f"  Iteration {iteration + 1}: No small polygons remaining")
            break

        if progress:
            print(f"  Iteration {iteration + 1}: {n_small} polygons <= {area_threshold} m²")

        # Rebuild spatial index
        gdf = gdf.reset_index(drop=True)

        # Build merge map: small_idx -> target_idx
        merge_map = {}
        small_indices = gdf[small_mask].index.tolist()

        iterator = tqdm(small_indices, desc=f"  Finding neighbors", leave=False) if progress else small_indices

        for idx in iterator:
            small_geom = gdf.loc[idx, "geometry"]

            best_neighbor = find_longest_shared_boundary_neighbor(
                small_geom, gdf, idx, area_threshold
            )

            if best_neighbor is not None:
                merge_map[idx] = best_neighbor

        if not merge_map:
            if progress:
                print(f"  No more polygons can be merged")
            break

        # Apply merges
        gdf = apply_merges(gdf, merge_map)

        if progress:
            print(f"  Merged {len(merge_map)} polygons, {len(gdf)} remaining")

    return gdf


def apply_merges(
    gdf: gpd.GeoDataFrame,
    merge_map: dict[int, int],
) -> gpd.GeoDataFrame:
    """
    Apply merge operations, combining geometries.

    Args:
        gdf: Input GeoDataFrame
        merge_map: Dictionary mapping source indices to target indices

    Returns:
        GeoDataFrame with merges applied
    """
    gdf = gdf.copy()

    # Group merges by target
    target_to_sources: dict[int, list[int]] = {}
    for source, target in merge_map.items():
        if target not in target_to_sources:
            target_to_sources[target] = []
        target_to_sources[target].append(source)

    # Track indices to drop
    indices_to_drop = set()

    # Apply merges
    for target, sources in target_to_sources.items():
        # Skip if target was itself merged
        if target in indices_to_drop:
            continue

        # Collect geometries to merge
        geoms = [gdf.loc[target, "geometry"]]
        for s in sources:
            if s not in indices_to_drop:
                geoms.append(gdf.loc[s, "geometry"])
                indices_to_drop.add(s)

        # Merge geometries
        merged = unary_union(geoms)

        # Handle potential MultiPolygon (take largest part)
        if isinstance(merged, MultiPolygon):
            merged = max(merged.geoms, key=lambda x: x.area)

        gdf.loc[target, "geometry"] = merged

    # Drop merged polygons
    gdf = gdf.drop(list(indices_to_drop))
    gdf = gdf.reset_index(drop=True)

    # Recalculate area
    if "shape_area" in gdf.columns:
        gdf["shape_area"] = gdf.geometry.area

    return gdf


def tiered_eliminate(
    gdf: gpd.GeoDataFrame,
    thresholds: Optional[list[float]] = None,
    progress: bool = True,
) -> gpd.GeoDataFrame:
    """
    Apply elimination in tiers matching the CSB workflow.

    Default thresholds: 100, 1000, 10000, 10000 square meters

    Args:
        gdf: GeoDataFrame with polygon geometries
        thresholds: List of area thresholds for each tier
        progress: Show progress information

    Returns:
        GeoDataFrame with small polygons eliminated
    """
    if thresholds is None:
        thresholds = [100.0, 1000.0, 10000.0, 10000.0]

    for i, threshold in enumerate(thresholds):
        if progress:
            print(f"Elimination tier {i + 1}: threshold = {threshold} m²")

        gdf = eliminate_small_polygons(
            gdf,
            area_threshold=threshold,
            max_iterations=10,
            progress=progress,
        )

        if progress:
            print(f"  After tier {i + 1}: {len(gdf)} polygons")

    return gdf


def eliminate_with_attribute_preservation(
    gdf: gpd.GeoDataFrame,
    area_threshold: float,
    preserve_field: str,
    max_iterations: int = 10,
    progress: bool = True,
) -> gpd.GeoDataFrame:
    """
    Eliminate small polygons, but only merge to neighbors with same attribute value.

    Args:
        gdf: GeoDataFrame with polygon geometries
        area_threshold: Maximum area for elimination
        preserve_field: Field name - only merge to neighbors with same value
        max_iterations: Maximum merge iterations
        progress: Show progress information

    Returns:
        GeoDataFrame with small polygons eliminated
    """
    gdf = gdf.copy().reset_index(drop=True)

    for iteration in range(max_iterations):
        small_mask = gdf.geometry.area <= area_threshold
        n_small = small_mask.sum()

        if n_small == 0:
            break

        if progress:
            print(f"  Iteration {iteration + 1}: {n_small} small polygons")

        gdf = gdf.reset_index(drop=True)
        merge_map = {}

        for idx in gdf[small_mask].index:
            small_geom = gdf.loc[idx, "geometry"]
            small_value = gdf.loc[idx, preserve_field]

            # Find neighbors
            possible_matches = list(gdf.sindex.intersection(small_geom.bounds))

            best_neighbor = None
            max_shared_length = 0

            for neighbor_idx in possible_matches:
                if neighbor_idx == idx:
                    continue

                neighbor_geom = gdf.iloc[neighbor_idx].geometry
                neighbor_value = gdf.iloc[neighbor_idx][preserve_field]

                # Check attribute match
                if neighbor_value != small_value:
                    continue

                # Check size
                if neighbor_geom.area <= area_threshold:
                    continue

                # Check adjacency
                if not small_geom.touches(neighbor_geom) and not small_geom.intersects(neighbor_geom):
                    continue

                # Calculate shared boundary
                try:
                    intersection = small_geom.boundary.intersection(neighbor_geom.boundary)
                    shared_length = intersection.length if intersection else 0
                except Exception:
                    continue

                if shared_length > max_shared_length:
                    max_shared_length = shared_length
                    best_neighbor = neighbor_idx

            if best_neighbor is not None:
                merge_map[idx] = best_neighbor

        if not merge_map:
            break

        gdf = apply_merges(gdf, merge_map)

    return gdf
