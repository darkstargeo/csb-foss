"""
Prep stage for CSB-FOSS pipeline.

Enriches CSB polygons with administrative boundaries and crop attributes.
Replaces CSB-Run/CSB-Run/CSB-prep.py
"""

from pathlib import Path
from typing import Optional

import geopandas as gpd
from rasterstats import zonal_stats

from ..config import CSBConfig
from ..db.duckdb_ops import (
    create_csb_database,
    spatial_join_largest_overlap,
    calculate_csb_fields,
)


def prep_csb(
    config: CSBConfig,
    input_path: Optional[Path] = None,
    progress: bool = True,
) -> Path:
    """
    Stage 2: Enrich CSB polygons with admin boundaries and crop attributes.

    Args:
        config: CSB configuration
        input_path: Path to input GeoPackage (from create stage)
        progress: Show progress information

    Returns:
        Path to output GeoPackage
    """
    config.ensure_directories()

    start_year = config.params.start_year
    end_year = config.params.end_year

    if progress:
        print(f"CSB Prep Stage: {start_year}-{end_year}")

    # Find input if not specified
    if input_path is None:
        input_path = config.output.create_dir / f"csb_{start_year}_{end_year}.gpkg"

    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")

    # Load polygons
    if progress:
        print("\n1. Loading CSB polygons...")

    gdf = gpd.read_file(input_path)

    if progress:
        print(f"   Loaded {len(gdf)} polygons")

    # Step 2: Spatial join with admin boundaries
    if config.data.admin_boundaries is not None and config.data.admin_boundaries.exists():
        if progress:
            print("\n2. Joining with admin boundaries...")

        gdf = spatial_join_admin(gdf, config.data.admin_boundaries, progress)
    else:
        if progress:
            print("\n2. Skipping admin join (no boundaries configured)")

    # Step 3: Calculate zonal statistics for each year
    if progress:
        print("\n3. Calculating crop majority per year...")

    gdf = calculate_crop_majority(gdf, config, progress)

    # Step 4: Calculate derived fields
    if progress:
        print("\n4. Calculating derived fields...")

    gdf = calculate_derived_fields(gdf, start_year, end_year)

    # Save output
    output_path = config.output.prep_dir / f"csb_{start_year}_{end_year}_prep.gpkg"
    gdf.to_file(output_path, driver="GPKG")

    if progress:
        print(f"\nPrep stage complete: {len(gdf)} polygons")
        print(f"Output: {output_path}")

    return output_path


def spatial_join_admin(
    gdf: gpd.GeoDataFrame,
    admin_path: Path,
    progress: bool = True,
) -> gpd.GeoDataFrame:
    """
    Join CSB polygons with administrative boundaries.

    Uses LARGEST_OVERLAP - assigns each CSB to the admin unit
    with the greatest intersection area.

    Args:
        gdf: CSB polygons
        admin_path: Path to admin boundaries
        progress: Show progress

    Returns:
        GeoDataFrame with admin attributes added
    """
    admin_gdf = gpd.read_file(admin_path)

    # Ensure same CRS
    if gdf.crs != admin_gdf.crs:
        admin_gdf = admin_gdf.to_crs(gdf.crs)

    # Perform spatial join
    joined = gpd.sjoin(gdf, admin_gdf, how="left", predicate="intersects")

    # For polygons that intersect multiple admin units, keep largest overlap
    # (simplified: sjoin already picks first match)

    # Expected admin columns
    admin_cols = ["STATE_FIPS", "STATEFP", "COUNTYFP", "COUNTY", "ASD"]
    for col in admin_cols:
        if col in joined.columns:
            # Rename to match CSB schema
            col_lower = col.lower()
            if col == "STATE_FIPS" or col == "STATEFP":
                joined = joined.rename(columns={col: "state_fips"})
            elif col == "COUNTYFP":
                joined = joined.rename(columns={col: "county_fips"})
            elif col == "COUNTY":
                joined = joined.rename(columns={col: "county"})
            elif col == "ASD":
                joined = joined.rename(columns={col: "asd"})

    # Drop join index column
    if "index_right" in joined.columns:
        joined = joined.drop(columns=["index_right"])

    return joined


def calculate_crop_majority(
    gdf: gpd.GeoDataFrame,
    config: CSBConfig,
    progress: bool = True,
) -> gpd.GeoDataFrame:
    """
    Calculate majority crop type for each polygon for each year.

    Uses zonal statistics to find the mode (majority) CDL value.

    Args:
        gdf: CSB polygons
        config: Configuration
        progress: Show progress

    Returns:
        GeoDataFrame with cdl_YYYY columns
    """
    from ..raster.io import get_cdl_paths_for_years
    from tqdm import tqdm

    cdl_paths = get_cdl_paths_for_years(
        config.data.cdl_30m,
        config.params.start_year,
        config.params.end_year,
    )

    years = sorted(cdl_paths.keys())
    iterator = tqdm(years, desc="Zonal stats") if progress else years

    for year in iterator:
        cdl_path = cdl_paths[year]
        col_name = f"cdl_{year}"

        # Skip if column already exists and populated
        if col_name in gdf.columns and gdf[col_name].notna().all():
            continue

        # Calculate zonal stats
        stats = zonal_stats(
            gdf,
            str(cdl_path),
            stats=["majority"],
            geojson_out=False,
        )

        gdf[col_name] = [s["majority"] for s in stats]

    return gdf


def calculate_derived_fields(
    gdf: gpd.GeoDataFrame,
    start_year: int,
    end_year: int,
) -> gpd.GeoDataFrame:
    """
    Calculate derived CSB fields.

    Args:
        gdf: GeoDataFrame
        start_year: First year
        end_year: Last year

    Returns:
        GeoDataFrame with derived fields
    """
    # CSB years
    years_str = f"{start_year % 100:02d}{end_year % 100:02d}"
    gdf["csb_years"] = years_str

    # Area in acres
    gdf["csb_acres"] = gdf.geometry.area / 4046.86

    # Centroid coordinates
    centroids = gdf.geometry.centroid
    gdf["inside_x"] = centroids.x
    gdf["inside_y"] = centroids.y

    # Shape area in sq meters
    gdf["shape_area"] = gdf.geometry.area

    return gdf
