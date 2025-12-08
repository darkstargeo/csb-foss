"""
Tiled processing for large-scale CSB generation.

Breaks state-level processing into manageable tiles to handle
memory constraints when processing full state extents.
"""

from pathlib import Path
from typing import Optional, Tuple
import json

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.windows import Window, from_bounds
from shapely.geometry import box
from shapely.ops import unary_union
from tqdm import tqdm

from ..config import CSBConfig
from ..raster.io import get_cdl_paths_for_years, read_multi_year_stack, get_raster_profile
from ..raster.combine import encode_year_sequence, calculate_crop_counts
from ..vector.vectorize import vectorize_raster, filter_by_crop_presence, enrich_from_lookup
from ..vector.eliminate_fast import tiered_eliminate_fast
from ..vector.simplify import simplify_polygons


def generate_state_tiles(
    state_bounds: Tuple[float, float, float, float],
    tile_size_m: float = 50000.0,
    overlap_m: float = 1000.0,
    crs: str = "EPSG:5070",
) -> list[dict]:
    """
    Generate tile specifications covering a state extent.

    Args:
        state_bounds: (minx, miny, maxx, maxy) in target CRS
        tile_size_m: Tile size in meters
        overlap_m: Overlap between tiles in meters
        crs: Coordinate reference system

    Returns:
        List of tile dictionaries with bounds and indices
    """
    minx, miny, maxx, maxy = state_bounds

    tiles = []
    tile_idx = 0

    step = tile_size_m - overlap_m

    y = miny
    row = 0
    while y < maxy:
        x = minx
        col = 0
        while x < maxx:
            tile = {
                "idx": tile_idx,
                "row": row,
                "col": col,
                "bounds": (
                    x,
                    y,
                    min(x + tile_size_m, maxx),
                    min(y + tile_size_m, maxy),
                ),
                "crs": crs,
            }
            tiles.append(tile)
            tile_idx += 1
            x += step
            col += 1
        y += step
        row += 1

    return tiles


def get_tennessee_bounds(crs: str = "EPSG:5070") -> Tuple[float, float, float, float]:
    """
    Get Tennessee state bounds in specified CRS.

    Returns:
        (minx, miny, maxx, maxy) tuple
    """
    from pyproj import Transformer

    # Tennessee WGS84 bounds (approximate)
    # lat: 34.98 to 36.68, lon: -90.31 to -81.65
    tn_wgs84 = (-90.31, 34.98, -81.65, 36.68)

    if crs != "EPSG:4326":
        transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        x1, y1 = transformer.transform(tn_wgs84[0], tn_wgs84[1])
        x2, y2 = transformer.transform(tn_wgs84[2], tn_wgs84[3])
        return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    return tn_wgs84


def process_tile(
    tile: dict,
    cdl_paths: dict[int, Path],
    output_dir: Path,
    config: CSBConfig,
    progress: bool = False,
) -> Optional[Path]:
    """
    Process a single tile through the CSB pipeline.

    Args:
        tile: Tile specification dictionary
        cdl_paths: Dictionary of year -> CDL path
        output_dir: Output directory for tile results
        config: CSB configuration
        progress: Show progress

    Returns:
        Path to output GeoPackage, or None if tile has no data
    """
    tile_idx = tile["idx"]
    bounds = tile["bounds"]

    # Get first CDL for reference
    first_path = cdl_paths[min(cdl_paths.keys())]

    with rasterio.open(first_path) as src:
        # Get window for this tile
        window = from_bounds(*bounds, transform=src.transform)

        # Round to integer pixels
        window = Window(
            col_off=int(window.col_off),
            row_off=int(window.row_off),
            width=int(window.width),
            height=int(window.height),
        )

        if window.width <= 0 or window.height <= 0:
            return None

        ref_transform = src.window_transform(window)
        ref_crs = src.crs

    if progress:
        print(f"  Tile {tile_idx}: {window.width}x{window.height} pixels")

    # Step 1: Read and combine CDL stack
    try:
        stack, years, _ = read_multi_year_stack(cdl_paths, window=window)
    except Exception as e:
        if progress:
            print(f"  Tile {tile_idx}: Error reading - {e}")
        return None

    # Check if tile has any data
    if stack.max() == 0:
        if progress:
            print(f"  Tile {tile_idx}: No data, skipping")
        return None

    # Encode sequences
    coded, lookup = encode_year_sequence(stack)
    counts = calculate_crop_counts(lookup, len(years))

    # Write temporary combined raster
    tile_dir = output_dir / f"tile_{tile_idx:04d}"
    tile_dir.mkdir(parents=True, exist_ok=True)

    combined_path = tile_dir / "combined.tif"
    lookup_path = tile_dir / "lookup.json"

    profile = {
        "driver": "GTiff",
        "dtype": rasterio.uint32,
        "width": coded.shape[1],
        "height": coded.shape[0],
        "count": 1,
        "crs": ref_crs,
        "transform": ref_transform,
        "compress": "lzw",
    }

    with rasterio.open(combined_path, "w", **profile) as dst:
        dst.write(coded, 1)

    # Save lookup
    json_lookup = {
        str(k): {
            "values": list(v),
            "years": years,
            "count0": counts[k][0],
            "count45": counts[k][1],
        }
        for k, v in lookup.items()
    }
    with open(lookup_path, "w") as f:
        json.dump(json_lookup, f)

    # Step 2: Vectorize
    gdf = vectorize_raster(combined_path, lookup_path=lookup_path, progress=False)

    if len(gdf) == 0:
        return None

    # Step 3: Filter
    gdf = filter_by_crop_presence(
        gdf,
        min_crop_years=config.params.min_crop_years,
        min_area_single_year=config.params.min_area_single_year,
    )

    if len(gdf) == 0:
        return None

    # Step 4: Eliminate (use fast parallel version)
    gdf = tiered_eliminate_fast(
        gdf,
        thresholds=[100.0, 1000.0, 5000.0],
        n_jobs=-1,
        progress=False,
    )

    # Step 5: Simplify
    gdf = simplify_polygons(
        gdf,
        tolerance=config.params.simplify_tolerance,
        progress=False,
    )

    # Save tile output
    output_path = tile_dir / "csb.gpkg"
    gdf.to_file(output_path, driver="GPKG")

    # Clean up temporary files
    combined_path.unlink()
    lookup_path.unlink()

    return output_path


def merge_tile_outputs(
    tile_outputs: list[Path],
    output_path: Path,
    overlap_buffer: float = 500.0,
    progress: bool = True,
) -> gpd.GeoDataFrame:
    """
    Merge tile outputs into a single GeoDataFrame.

    Handles overlapping polygons at tile boundaries by:
    1. Dissolving identical polygons
    2. Keeping the polygon with larger area for overlaps

    Args:
        tile_outputs: List of tile output GeoPackage paths
        output_path: Output path for merged result
        overlap_buffer: Buffer for overlap detection in CRS units
        progress: Show progress

    Returns:
        Merged GeoDataFrame
    """
    if progress:
        print(f"Merging {len(tile_outputs)} tile outputs...")

    # Load all tiles
    gdfs = []
    iterator = tqdm(tile_outputs, desc="Loading tiles") if progress else tile_outputs

    for tile_path in iterator:
        if tile_path is not None and tile_path.exists():
            gdf = gpd.read_file(tile_path)
            gdfs.append(gdf)

    if not gdfs:
        raise ValueError("No valid tile outputs to merge")

    # Concatenate all
    merged = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True))

    if progress:
        print(f"  Total polygons before dedup: {len(merged)}")

    # Remove exact duplicates (same gridcode and overlapping significantly)
    merged = merged.drop_duplicates(subset=["gridcode", "geometry"])

    # Handle overlapping polygons at tile boundaries
    # For now, use simple approach: dissolve by gridcode
    if progress:
        print("  Resolving tile boundary overlaps...")

    # Group by gridcode and dissolve touching polygons
    dissolved = merged.dissolve(by="gridcode", aggfunc="first").reset_index()

    # Re-calculate area
    dissolved["shape_area"] = dissolved.geometry.area

    if progress:
        print(f"  Total polygons after merge: {len(dissolved)}")

    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dissolved.to_file(output_path, driver="GPKG")

    if progress:
        print(f"  Saved to {output_path}")

    return dissolved


def create_csb_tiled(
    config: CSBConfig,
    state_bounds: Optional[Tuple[float, float, float, float]] = None,
    tile_size_m: float = 50000.0,
    overlap_m: float = 1000.0,
    max_tiles: Optional[int] = None,
    progress: bool = True,
) -> Path:
    """
    Create CSB using tiled processing for large extents.

    Args:
        config: CSB configuration
        state_bounds: State bounds (minx, miny, maxx, maxy) or None for Tennessee
        tile_size_m: Tile size in meters (default 50km)
        overlap_m: Overlap between tiles in meters
        max_tiles: Optional limit on number of tiles to process
        progress: Show progress

    Returns:
        Path to output GeoPackage
    """
    import pandas as pd

    config.ensure_directories()

    # Get state bounds
    if state_bounds is None:
        state_bounds = get_tennessee_bounds()

    if progress:
        print(f"State bounds: {state_bounds}")
        width_km = (state_bounds[2] - state_bounds[0]) / 1000
        height_km = (state_bounds[3] - state_bounds[1]) / 1000
        print(f"Extent: {width_km:.0f} x {height_km:.0f} km")

    # Generate tiles
    tiles = generate_state_tiles(state_bounds, tile_size_m, overlap_m)

    if max_tiles is not None:
        tiles = tiles[:max_tiles]

    if progress:
        print(f"Processing {len(tiles)} tiles...")

    # Get CDL paths
    cdl_paths = get_cdl_paths_for_years(
        config.data.cdl_30m,
        config.params.start_year,
        config.params.end_year,
    )

    if progress:
        print(f"CDL years: {list(cdl_paths.keys())}")

    # Process tiles
    output_dir = config.output.create_dir / "tiles"
    output_dir.mkdir(parents=True, exist_ok=True)

    tile_outputs = []

    iterator = tqdm(tiles, desc="Processing tiles") if progress else tiles

    for tile in iterator:
        try:
            output = process_tile(
                tile,
                cdl_paths,
                output_dir,
                config,
                progress=False,
            )
            tile_outputs.append(output)
        except Exception as e:
            if progress:
                print(f"  Tile {tile['idx']} failed: {e}")
            tile_outputs.append(None)

    # Count successful tiles
    successful = sum(1 for o in tile_outputs if o is not None)
    if progress:
        print(f"\nSuccessful tiles: {successful}/{len(tiles)}")

    # Merge tile outputs
    valid_outputs = [o for o in tile_outputs if o is not None]

    if not valid_outputs:
        raise ValueError("No tiles produced output")

    # Import pandas for merge
    global pd
    import pandas as pd

    output_path = config.output.create_dir / f"csb_{config.params.start_year}_{config.params.end_year}_tiled.gpkg"

    merged = merge_tile_outputs(valid_outputs, output_path, progress=progress)

    if progress:
        print(f"\nTiled processing complete!")
        print(f"  Total polygons: {len(merged)}")
        print(f"  Total area: {merged.shape_area.sum() / 1e6:.1f} km²")

    return output_path


# Make pandas available at module level
import pandas as pd
