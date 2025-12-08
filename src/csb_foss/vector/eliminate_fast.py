"""
Fast polygon elimination using parallel processing.

Optimized version of eliminate.py using joblib for parallel neighbor search.
"""

from typing import Optional
import numpy as np
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from shapely import STRtree
from tqdm import tqdm
from joblib import Parallel, delayed


def find_neighbor_batch(
    indices: list[int],
    geometries: list,
    areas: np.ndarray,
    area_threshold: float,
    tree: STRtree,
) -> dict[int, int]:
    """
    Find best neighbors for a batch of small polygons.

    Args:
        indices: Indices of small polygons to process
        geometries: All polygon geometries
        areas: All polygon areas
        area_threshold: Area threshold for merging
        tree: STRtree spatial index

    Returns:
        Dictionary mapping small_idx -> target_idx
    """
    merge_map = {}

    for idx in indices:
        small_geom = geometries[idx]

        # Query tree for potential neighbors
        candidate_indices = tree.query(small_geom, predicate="intersects")

        best_neighbor = None
        max_shared_length = 0

        for neighbor_idx in candidate_indices:
            if neighbor_idx == idx:
                continue

            # Skip small neighbors
            if areas[neighbor_idx] <= area_threshold:
                continue

            neighbor_geom = geometries[neighbor_idx]

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

    return merge_map


def eliminate_fast(
    gdf: gpd.GeoDataFrame,
    area_threshold: float,
    max_iterations: int = 10,
    n_jobs: int = -1,
    batch_size: int = 1000,
    progress: bool = True,
) -> gpd.GeoDataFrame:
    """
    Fast polygon elimination using parallel processing.

    Args:
        gdf: GeoDataFrame with polygon geometries
        area_threshold: Maximum area for elimination (in CRS units squared)
        max_iterations: Maximum merge iterations
        n_jobs: Number of parallel jobs (-1 for all cores)
        batch_size: Batch size for parallel processing
        progress: Show progress

    Returns:
        GeoDataFrame with small polygons eliminated
    """
    gdf = gdf.copy().reset_index(drop=True)

    for iteration in range(max_iterations):
        # Get current areas
        areas = gdf.geometry.area.values

        # Find small polygons
        small_mask = areas <= area_threshold
        n_small = small_mask.sum()

        if n_small == 0:
            if progress:
                print(f"  Iteration {iteration + 1}: No small polygons remaining")
            break

        if progress:
            print(f"  Iteration {iteration + 1}: {n_small} polygons <= {area_threshold} m²")

        # Build STRtree for fast spatial queries
        geometries = list(gdf.geometry)
        tree = STRtree(geometries)

        # Get small polygon indices
        small_indices = np.where(small_mask)[0].tolist()

        # Split into batches
        batches = [
            small_indices[i:i + batch_size]
            for i in range(0, len(small_indices), batch_size)
        ]

        # Parallel neighbor search
        if progress:
            desc = f"  Finding neighbors"
        else:
            desc = None

        results = Parallel(n_jobs=n_jobs, prefer="threads")(
            delayed(find_neighbor_batch)(
                batch, geometries, areas, area_threshold, tree
            )
            for batch in (tqdm(batches, desc=desc, leave=False) if progress else batches)
        )

        # Combine results
        merge_map = {}
        for result in results:
            merge_map.update(result)

        if not merge_map:
            if progress:
                print(f"  No more polygons can be merged")
            break

        # Apply merges
        gdf = apply_merges_fast(gdf, merge_map)

        if progress:
            print(f"  Merged {len(merge_map)} polygons, {len(gdf)} remaining")

    return gdf


def apply_merges_fast(
    gdf: gpd.GeoDataFrame,
    merge_map: dict[int, int],
) -> gpd.GeoDataFrame:
    """
    Apply merge operations efficiently.

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
        if target in indices_to_drop:
            continue

        # Collect geometries to merge
        geoms = [gdf.iloc[target].geometry]
        for s in sources:
            if s not in indices_to_drop:
                geoms.append(gdf.iloc[s].geometry)
                indices_to_drop.add(s)

        # Merge geometries
        merged = unary_union(geoms)

        # Handle MultiPolygon (keep largest part)
        if isinstance(merged, MultiPolygon):
            merged = max(merged.geoms, key=lambda x: x.area)

        gdf.iloc[target, gdf.columns.get_loc("geometry")] = merged

    # Drop merged polygons
    gdf = gdf.drop(list(indices_to_drop))
    gdf = gdf.reset_index(drop=True)

    # Recalculate area
    if "shape_area" in gdf.columns:
        gdf["shape_area"] = gdf.geometry.area

    return gdf


def tiered_eliminate_fast(
    gdf: gpd.GeoDataFrame,
    thresholds: Optional[list[float]] = None,
    n_jobs: int = -1,
    progress: bool = True,
) -> gpd.GeoDataFrame:
    """
    Apply fast elimination in tiers.

    Default thresholds: 100, 1000, 10000 square meters

    Args:
        gdf: GeoDataFrame with polygon geometries
        thresholds: List of area thresholds for each tier
        n_jobs: Number of parallel jobs
        progress: Show progress information

    Returns:
        GeoDataFrame with small polygons eliminated
    """
    if thresholds is None:
        thresholds = [100.0, 1000.0, 10000.0]

    for i, threshold in enumerate(thresholds):
        if progress:
            print(f"Elimination tier {i + 1}: threshold = {threshold} m²")

        gdf = eliminate_fast(
            gdf,
            area_threshold=threshold,
            max_iterations=10,
            n_jobs=n_jobs,
            progress=progress,
        )

        if progress:
            print(f"  After tier {i + 1}: {len(gdf)} polygons")

    return gdf
