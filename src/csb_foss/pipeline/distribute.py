"""
Distribute stage for CSB-FOSS pipeline.

Merges regional data into national dataset and exports by state.
Replaces CSB-Run/CSB-Run/CSB-distribute.py
"""

from pathlib import Path
from typing import Optional, List

import geopandas as gpd
import rasterio
from rasterio.features import rasterize

from ..config import CSBConfig
from ..db.schema import STATE_FIPS, FIPS_TO_STATE


def distribute_csb(
    config: CSBConfig,
    input_path: Optional[Path] = None,
    states: Optional[List[str]] = None,
    progress: bool = True,
) -> dict:
    """
    Stage 3: Merge to national and export by state.

    Args:
        config: CSB configuration
        input_path: Path to input GeoPackage (from prep stage)
        states: Optional list of state abbreviations to export (None = all)
        progress: Show progress information

    Returns:
        Dictionary of output paths by format
    """
    config.ensure_directories()

    start_year = config.params.start_year
    end_year = config.params.end_year

    if progress:
        print(f"CSB Distribute Stage: {start_year}-{end_year}")

    # Find input if not specified
    if input_path is None:
        input_path = config.output.prep_dir / f"csb_{start_year}_{end_year}_prep.gpkg"

    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")

    # Load polygons
    if progress:
        print("\n1. Loading CSB polygons...")

    gdf = gpd.read_file(input_path)

    if progress:
        print(f"   Loaded {len(gdf)} polygons")

    # Step 2: Generate CSB IDs
    if progress:
        print("\n2. Generating CSBID...")

    gdf = generate_csb_ids(gdf)

    # Step 3: Determine states to export
    if states is None:
        # Get unique states from data
        if "state_fips" in gdf.columns:
            unique_fips = gdf["state_fips"].dropna().unique()
            states = [FIPS_TO_STATE.get(f, f) for f in unique_fips]
        else:
            states = []

    if progress:
        print(f"\n3. Exporting {len(states)} states...")

    outputs = {
        "gpkg": [],
        "shp": [],
        "tif": [],
    }

    for state in states:
        if progress:
            print(f"   Processing {state}...")

        state_outputs = export_state(
            gdf,
            state,
            config.output.distribute_dir,
            start_year,
            end_year,
        )

        for fmt, path in state_outputs.items():
            if path is not None:
                outputs[fmt].append(path)

    if progress:
        print(f"\nDistribute stage complete")
        print(f"Outputs: {config.output.distribute_dir}")

    return outputs


def generate_csb_ids(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Generate unique CSBID for each polygon.

    CSBID format: STATEFIPS + CSBYEARS + 9-digit sequence number

    Args:
        gdf: GeoDataFrame with csb_years and state_fips columns

    Returns:
        GeoDataFrame with csb_id column
    """
    gdf = gdf.copy()

    # Ensure required columns exist
    if "state_fips" not in gdf.columns:
        gdf["state_fips"] = "00"  # Unknown state

    if "csb_years" not in gdf.columns:
        gdf["csb_years"] = "0000"

    # Generate IDs
    gdf["csb_id"] = gdf.apply(
        lambda row: f"{row['state_fips']}{row['csb_years']}{row.name:09d}",
        axis=1,
    )

    return gdf


def export_state(
    gdf: gpd.GeoDataFrame,
    state: str,
    output_dir: Path,
    start_year: int,
    end_year: int,
) -> dict:
    """
    Export data for a single state in multiple formats.

    Args:
        gdf: Full GeoDataFrame
        state: State abbreviation (e.g., "TN")
        output_dir: Base output directory
        start_year: First year
        end_year: Last year

    Returns:
        Dictionary of format to output path
    """
    outputs = {"gpkg": None, "shp": None, "tif": None}

    # Filter to state
    state_fips = STATE_FIPS.get(state.upper())
    if state_fips is None:
        return outputs

    if "state_fips" in gdf.columns:
        state_gdf = gdf[gdf["state_fips"] == state_fips].copy()
    else:
        state_gdf = gdf.copy()

    if len(state_gdf) == 0:
        return outputs

    years_str = f"{start_year % 100:02d}{end_year % 100:02d}"
    base_name = f"CSB{state.upper()}{years_str}"

    # Create state directories
    gpkg_dir = output_dir / "gpkg"
    shp_dir = output_dir / "shp"
    tif_dir = output_dir / "tif"

    for d in [gpkg_dir, shp_dir, tif_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # Export GeoPackage
    gpkg_path = gpkg_dir / f"{base_name}.gpkg"
    state_gdf.to_file(gpkg_path, driver="GPKG")
    outputs["gpkg"] = gpkg_path

    # Export Shapefile
    shp_path = shp_dir / f"{base_name}.shp"
    state_gdf.to_file(shp_path, driver="ESRI Shapefile")
    outputs["shp"] = shp_path

    # Export Raster (CSBID as value)
    tif_path = tif_dir / f"{base_name}.tif"
    export_state_raster(state_gdf, tif_path)
    outputs["tif"] = tif_path

    return outputs


def export_state_raster(
    gdf: gpd.GeoDataFrame,
    output_path: Path,
    resolution: float = 30.0,
) -> Path:
    """
    Export state polygons as raster with CSBID as pixel value.

    Args:
        gdf: GeoDataFrame with csb_id column
        output_path: Output path
        resolution: Pixel size in CRS units

    Returns:
        Output path
    """
    # Get bounds
    bounds = gdf.total_bounds
    minx, miny, maxx, maxy = bounds

    # Calculate dimensions
    width = int((maxx - minx) / resolution)
    height = int((maxy - miny) / resolution)

    # Create transform
    from rasterio.transform import from_bounds

    transform = from_bounds(minx, miny, maxx, maxy, width, height)

    # Create shapes for rasterization
    # Use row index as value (CSBID is string, can't use directly)
    shapes = [(geom, idx) for idx, geom in enumerate(gdf.geometry, start=1)]

    # Rasterize
    raster = rasterize(
        shapes,
        out_shape=(height, width),
        transform=transform,
        fill=0,
        dtype="int32",
    )

    # Write raster
    profile = {
        "driver": "GTiff",
        "dtype": "int32",
        "width": width,
        "height": height,
        "count": 1,
        "crs": gdf.crs,
        "transform": transform,
        "compress": "lzw",
    }

    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(raster, 1)

    return output_path
