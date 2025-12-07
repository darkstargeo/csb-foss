"""
Vectorization module for CSB-FOSS.

Converts raster data to polygon features using rasterio.features.shapes().
Replaces arcpy.RasterToPolygon_conversion().
"""

import json
from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import shapes
from shapely.geometry import shape
from shapely.ops import unary_union
from tqdm import tqdm


def vectorize_raster(
    raster_path: Path,
    output_path: Optional[Path] = None,
    lookup_path: Optional[Path] = None,
    mask_nodata: bool = True,
    simplify_tolerance: Optional[float] = None,
    min_area: Optional[float] = None,
    progress: bool = True,
) -> gpd.GeoDataFrame:
    """
    Convert a raster to polygon features.

    Replaces arcpy.RasterToPolygon_conversion().

    Args:
        raster_path: Path to input raster
        output_path: Optional path to save output (GeoPackage or Shapefile)
        lookup_path: Optional path to lookup table JSON for attribute enrichment
        mask_nodata: Exclude nodata pixels from vectorization
        simplify_tolerance: Optional simplification tolerance in CRS units
        min_area: Optional minimum polygon area filter (in CRS units squared)
        progress: Show progress information

    Returns:
        GeoDataFrame with vectorized polygons
    """
    if progress:
        print(f"Vectorizing {raster_path.name}...")

    with rasterio.open(raster_path) as src:
        data = src.read(1)
        transform = src.transform
        crs = src.crs
        nodata = src.nodata

        # Create mask for nodata
        if mask_nodata and nodata is not None:
            mask = data != nodata
        else:
            mask = None

        # Vectorize
        if progress:
            print("  Extracting shapes...")

        geometries = []
        values = []

        for geom, val in shapes(data, mask=mask, transform=transform):
            poly = shape(geom)

            # Optional simplification during extraction
            if simplify_tolerance is not None:
                poly = poly.simplify(simplify_tolerance, preserve_topology=True)

            # Optional area filter
            if min_area is not None and poly.area < min_area:
                continue

            geometries.append(poly)
            values.append(int(val))

    if progress:
        print(f"  Extracted {len(geometries)} polygons")

    # Create GeoDataFrame
    gdf = gpd.GeoDataFrame(
        {"gridcode": values},
        geometry=geometries,
        crs=crs,
    )

    # Add attributes from lookup table if provided
    if lookup_path is not None and lookup_path.exists():
        gdf = enrich_from_lookup(gdf, lookup_path)

    # Calculate area
    gdf["shape_area"] = gdf.geometry.area

    # Save if output path provided
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        driver = "GPKG" if output_path.suffix.lower() == ".gpkg" else "ESRI Shapefile"
        gdf.to_file(output_path, driver=driver)
        if progress:
            print(f"  Saved to {output_path}")

    return gdf


def enrich_from_lookup(
    gdf: gpd.GeoDataFrame,
    lookup_path: Path,
) -> gpd.GeoDataFrame:
    """
    Add year values and counts from lookup table.

    Args:
        gdf: GeoDataFrame with 'gridcode' column
        lookup_path: Path to lookup table JSON

    Returns:
        Enriched GeoDataFrame
    """
    with open(lookup_path) as f:
        lookup = json.load(f)

    # Get years from first entry
    first_entry = next(iter(lookup.values()))
    years = first_entry.get("years", [])

    # Add columns for each year
    for i, year in enumerate(years):
        col_name = f"cdl_{year}"
        gdf[col_name] = gdf["gridcode"].apply(
            lambda x: lookup.get(str(x), {}).get("values", [None] * len(years))[i]
        )

    # Add counts
    gdf["count0"] = gdf["gridcode"].apply(
        lambda x: lookup.get(str(x), {}).get("count0", 0)
    )
    gdf["count45"] = gdf["gridcode"].apply(
        lambda x: lookup.get(str(x), {}).get("count45", 0)
    )

    return gdf


def filter_by_crop_presence(
    gdf: gpd.GeoDataFrame,
    min_crop_years: int = 2,
    min_area_single_year: float = 10000.0,
) -> gpd.GeoDataFrame:
    """
    Filter polygons by crop presence criteria.

    Matches the CSB filtering logic:
    (COUNT0 - COUNT45 >= min_crop_years) OR
    (area >= min_area_single_year AND COUNT0 - COUNT45 >= 1)

    Args:
        gdf: GeoDataFrame with count0, count45, and geometry columns
        min_crop_years: Minimum net crop years for inclusion
        min_area_single_year: Minimum area for single-year crop polygons

    Returns:
        Filtered GeoDataFrame
    """
    gdf = gdf.copy()

    # Calculate net crop years
    net_crop_years = gdf["count0"] - gdf["count45"]

    # Apply filter
    mask = (net_crop_years >= min_crop_years) | (
        (gdf.geometry.area >= min_area_single_year) & (net_crop_years >= 1)
    )

    filtered = gdf[mask].copy()

    print(f"Filtered {len(gdf)} -> {len(filtered)} polygons")

    return filtered


def vectorize_windowed(
    raster_path: Path,
    output_path: Path,
    tile_size: int = 4096,
    overlap: int = 100,
    lookup_path: Optional[Path] = None,
    simplify_tolerance: Optional[float] = None,
    progress: bool = True,
) -> gpd.GeoDataFrame:
    """
    Vectorize a large raster using windowed processing.

    Memory-efficient version for large rasters that don't fit in memory.
    Handles merging of geometries at tile boundaries.

    Args:
        raster_path: Path to input raster
        output_path: Path to save output
        tile_size: Size of processing tiles in pixels
        overlap: Overlap between tiles to handle boundary effects
        lookup_path: Optional path to lookup table
        simplify_tolerance: Optional simplification tolerance
        progress: Show progress bar

    Returns:
        GeoDataFrame with vectorized polygons
    """
    from ..raster.io import generate_windows

    with rasterio.open(raster_path) as src:
        crs = src.crs
        nodata = src.nodata

    # Collect all geometries by gridcode
    all_geoms: dict[int, list] = {}

    windows = list(generate_windows(raster_path, tile_size=tile_size, overlap=overlap))
    iterator = tqdm(windows, desc="Vectorizing tiles") if progress else windows

    for window, (row_idx, col_idx) in iterator:
        with rasterio.open(raster_path) as src:
            data = src.read(1, window=window)
            transform = src.window_transform(window)

            mask = data != nodata if nodata is not None else None

            for geom, val in shapes(data, mask=mask, transform=transform):
                val = int(val)
                if val not in all_geoms:
                    all_geoms[val] = []
                all_geoms[val].append(shape(geom))

    # Merge geometries that touch at tile boundaries
    if progress:
        print("Merging geometries across tiles...")

    geometries = []
    values = []

    for val, geoms in tqdm(all_geoms.items(), desc="Merging") if progress else all_geoms.items():
        merged = unary_union(geoms)

        # Handle MultiPolygon results
        if merged.geom_type == "MultiPolygon":
            for poly in merged.geoms:
                if simplify_tolerance is not None:
                    poly = poly.simplify(simplify_tolerance, preserve_topology=True)
                geometries.append(poly)
                values.append(val)
        else:
            if simplify_tolerance is not None:
                merged = merged.simplify(simplify_tolerance, preserve_topology=True)
            geometries.append(merged)
            values.append(val)

    gdf = gpd.GeoDataFrame(
        {"gridcode": values},
        geometry=geometries,
        crs=crs,
    )

    # Enrich from lookup
    if lookup_path is not None and lookup_path.exists():
        gdf = enrich_from_lookup(gdf, lookup_path)

    # Calculate area
    gdf["shape_area"] = gdf.geometry.area

    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(output_path, driver="GPKG")

    if progress:
        print(f"Saved {len(gdf)} polygons to {output_path}")

    return gdf
