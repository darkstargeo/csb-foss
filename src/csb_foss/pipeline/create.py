"""
Create stage for CSB-FOSS pipeline.

Generates crop sequence boundary polygons from CDL rasters.
Replaces CSB-Run/CSB-Run/CSB-create.py
"""

from pathlib import Path
from typing import Optional

import geopandas as gpd

from ..config import CSBConfig
from ..raster.io import get_cdl_paths_for_years
from ..raster.combine import combine_cdl_rasters, combine_cdl_rasters_windowed
from ..vector.vectorize import vectorize_raster, filter_by_crop_presence
from ..vector.eliminate import tiered_eliminate
from ..vector.simplify import simplify_polygons


def create_csb(
    config: CSBConfig,
    track: str = "baseline",
    progress: bool = True,
) -> Path:
    """
    Stage 1: Generate CSB polygons from CDL rasters.

    Args:
        config: CSB configuration
        track: "baseline" (ArcGIS-compatible) or "experimental" (improved)
        progress: Show progress information

    Returns:
        Path to output GeoPackage
    """
    config.ensure_directories()

    start_year = config.params.start_year
    end_year = config.params.end_year

    if progress:
        print(f"CSB Create Stage: {start_year}-{end_year}, track={track}")

    # Step 1: Find CDL rasters
    if progress:
        print("\n1. Finding CDL rasters...")

    cdl_paths = get_cdl_paths_for_years(
        config.data.cdl_30m,
        start_year,
        end_year,
    )

    if not cdl_paths:
        raise FileNotFoundError(f"No CDL rasters found in {config.data.cdl_30m}")

    if progress:
        print(f"   Found {len(cdl_paths)} years: {list(cdl_paths.keys())}")

    # Step 2: Combine rasters
    if progress:
        print("\n2. Combining CDL rasters...")

    combined_path = config.output.create_dir / "combined.tif"
    lookup_path = config.output.create_dir / "lookup.json"

    combine_cdl_rasters_windowed(
        cdl_paths,
        combined_path,
        lookup_path,
        progress=progress,
    )

    # Step 3: Vectorize or run experimental segmentation
    if track == "baseline":
        output_gdf = run_baseline_track(
            combined_path,
            lookup_path,
            config,
            progress,
        )
    else:
        output_gdf = run_experimental_track(
            cdl_paths,
            combined_path,
            lookup_path,
            config,
            progress,
        )

    # Save output
    output_path = config.output.create_dir / f"csb_{start_year}_{end_year}.gpkg"
    output_gdf.to_file(output_path, driver="GPKG")

    if progress:
        print(f"\nCreate stage complete: {len(output_gdf)} polygons")
        print(f"Output: {output_path}")

    return output_path


def run_baseline_track(
    combined_path: Path,
    lookup_path: Path,
    config: CSBConfig,
    progress: bool = True,
) -> gpd.GeoDataFrame:
    """
    Run baseline (ArcGIS-compatible) processing track.

    Args:
        combined_path: Path to combined raster
        lookup_path: Path to lookup table
        config: Configuration
        progress: Show progress

    Returns:
        Processed GeoDataFrame
    """
    # Step 3a: Vectorize
    if progress:
        print("\n3. Vectorizing combined raster...")

    gdf = vectorize_raster(
        combined_path,
        lookup_path=lookup_path,
        progress=progress,
    )

    # Step 4: Filter by crop presence
    if progress:
        print("\n4. Filtering by crop presence...")

    gdf = filter_by_crop_presence(
        gdf,
        min_crop_years=config.params.min_crop_years,
        min_area_single_year=config.params.min_area_single_year,
    )

    # Step 5: Eliminate small polygons
    if progress:
        print("\n5. Eliminating small polygons...")

    gdf = tiered_eliminate(
        gdf,
        thresholds=config.params.eliminate_thresholds,
        progress=progress,
    )

    # Step 6: Simplify polygons
    if progress:
        print("\n6. Simplifying polygons...")

    gdf = simplify_polygons(
        gdf,
        tolerance=config.params.simplify_tolerance,
        progress=progress,
    )

    return gdf


def run_experimental_track(
    cdl_paths: dict[int, Path],
    combined_path: Path,
    lookup_path: Path,
    config: CSBConfig,
    progress: bool = True,
) -> gpd.GeoDataFrame:
    """
    Run experimental (improved) processing track.

    Uses temporal edge voting, NAIP imagery, and road integration
    for better boundary detection.

    Args:
        cdl_paths: Dictionary of year to CDL path
        combined_path: Path to combined raster
        lookup_path: Path to lookup table
        config: Configuration
        progress: Show progress

    Returns:
        Processed GeoDataFrame
    """
    from ..raster.io import read_multi_year_stack, get_raster_profile
    from ..experimental.edge_voting import compute_temporal_edge_votes, save_edge_votes
    from ..experimental.road_integration import create_road_mask, combine_edge_sources
    from ..experimental.watershed import watershed_segment
    from ..vector.vectorize import enrich_from_lookup
    from rasterio.features import shapes
    from shapely.geometry import shape
    import rasterio

    # Step 3: Load CDL stack
    if progress:
        print("\n3. Loading CDL stack for edge voting...")

    stack, years, metadata = read_multi_year_stack(cdl_paths)

    # Step 4: Compute temporal edge votes
    if progress:
        print("\n4. Computing temporal edge votes...")

    edge_votes = compute_temporal_edge_votes(stack, progress=progress)

    # Save edge votes
    edge_path = config.output.create_dir / "edge_votes.tif"
    save_edge_votes(edge_votes, edge_path, list(cdl_paths.values())[0])

    # Step 5: Create road mask (if available)
    if progress:
        print("\n5. Creating road mask...")

    if config.data.tiger_roads is not None:
        road_mask = create_road_mask(
            roads_path=config.data.tiger_roads,
            rails_path=config.data.tiger_rails,
            reference_raster=list(cdl_paths.values())[0],
            buffer_distance=config.params.road_buffer,
        )
    else:
        road_mask = None
        if progress:
            print("   No TIGER roads configured, skipping")

    # Step 6: Combine edge sources
    if progress:
        print("\n6. Combining edge sources...")

    if road_mask is not None:
        combined_edges = combine_edge_sources(edge_votes, road_mask)
    else:
        combined_edges = edge_votes.astype(float) / edge_votes.max()

    # Step 7: Watershed segmentation
    if progress:
        print("\n7. Running watershed segmentation...")

    labels = watershed_segment(
        combined_edges,
        road_mask=road_mask,
        min_distance=10,
    )

    # Step 8: Vectorize labels
    if progress:
        print("\n8. Vectorizing segments...")

    first_raster = list(cdl_paths.values())[0]
    with rasterio.open(first_raster) as src:
        transform = src.transform
        crs = src.crs

    geometries = []
    values = []

    for geom, val in shapes(labels.astype('int32'), transform=transform):
        if val == 0:  # Skip background
            continue
        geometries.append(shape(geom))
        values.append(int(val))

    gdf = gpd.GeoDataFrame(
        {"segment_id": values},
        geometry=geometries,
        crs=crs,
    )

    # Step 9: Assign CDL values to segments (majority vote)
    if progress:
        print("\n9. Assigning crop values to segments...")

    # For each segment, find the majority gridcode from combined raster
    # (simplified: use centroid sampling)
    with rasterio.open(combined_path) as src:
        combined_data = src.read(1)

    for idx in gdf.index:
        centroid = gdf.loc[idx, 'geometry'].centroid
        col, row = ~transform * (centroid.x, centroid.y)
        row, col = int(row), int(col)
        if 0 <= row < combined_data.shape[0] and 0 <= col < combined_data.shape[1]:
            gdf.loc[idx, 'gridcode'] = combined_data[row, col]

    # Enrich from lookup
    gdf = enrich_from_lookup(gdf, lookup_path)

    # Step 10: Simplify with reduced tolerance
    if progress:
        print("\n10. Simplifying polygons...")

    gdf = simplify_polygons(
        gdf,
        tolerance=config.params.simplify_tolerance_experimental,
        progress=progress,
    )

    return gdf
