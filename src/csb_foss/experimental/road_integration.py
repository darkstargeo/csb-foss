"""
Road integration module for CSB-FOSS experimental track.

Incorporates TIGER/Line road and rail data as hard boundary constraints
for field segmentation.
"""

from pathlib import Path
from typing import Optional, Union

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from shapely.geometry import LineString, MultiLineString


def load_tiger_roads(
    roads_path: Path,
    bounds: Optional[tuple[float, float, float, float]] = None,
    crs: Optional[str] = None,
    mtfcc_filter: Optional[list[str]] = None,
) -> gpd.GeoDataFrame:
    """
    Load TIGER/Line road data.

    Args:
        roads_path: Path to TIGER roads shapefile or GeoPackage
        bounds: Optional bounding box (minx, miny, maxx, maxy) to filter
        crs: Target CRS for reprojection
        mtfcc_filter: Optional list of MTFCC codes to include
                     (e.g., ['S1100', 'S1200'] for primary/secondary roads)

    Returns:
        GeoDataFrame of road lines
    """
    # Read with optional bbox filter
    if bounds is not None:
        gdf = gpd.read_file(roads_path, bbox=bounds)
    else:
        gdf = gpd.read_file(roads_path)

    # Filter by MTFCC if specified
    if mtfcc_filter is not None and "MTFCC" in gdf.columns:
        gdf = gdf[gdf["MTFCC"].isin(mtfcc_filter)]

    # Reproject if needed
    if crs is not None and gdf.crs != crs:
        gdf = gdf.to_crs(crs)

    return gdf


def load_tiger_rails(
    rails_path: Path,
    bounds: Optional[tuple[float, float, float, float]] = None,
    crs: Optional[str] = None,
) -> gpd.GeoDataFrame:
    """
    Load TIGER/Line railroad data.

    Args:
        rails_path: Path to TIGER rails shapefile or GeoPackage
        bounds: Optional bounding box to filter
        crs: Target CRS for reprojection

    Returns:
        GeoDataFrame of railroad lines
    """
    if bounds is not None:
        gdf = gpd.read_file(rails_path, bbox=bounds)
    else:
        gdf = gpd.read_file(rails_path)

    if crs is not None and gdf.crs != crs:
        gdf = gdf.to_crs(crs)

    return gdf


def buffer_infrastructure(
    gdf: gpd.GeoDataFrame,
    buffer_distance: float = 15.0,
) -> gpd.GeoDataFrame:
    """
    Buffer road/rail lines to account for width and registration error.

    Args:
        gdf: GeoDataFrame of line geometries
        buffer_distance: Buffer distance in CRS units (meters for projected)

    Returns:
        GeoDataFrame with buffered geometries
    """
    gdf = gdf.copy()
    gdf["geometry"] = gdf.geometry.buffer(buffer_distance)
    return gdf


def rasterize_roads(
    roads_gdf: gpd.GeoDataFrame,
    reference_raster: Path,
    buffer_distance: float = 15.0,
) -> np.ndarray:
    """
    Rasterize road data to match a reference raster.

    Args:
        roads_gdf: GeoDataFrame of road geometries
        reference_raster: Reference raster for transform and shape
        buffer_distance: Buffer distance for road lines

    Returns:
        Binary road mask array (1 = road, 0 = not road)
    """
    with rasterio.open(reference_raster) as src:
        transform = src.transform
        shape = (src.height, src.width)

    # Buffer roads
    if buffer_distance > 0:
        buffered = buffer_infrastructure(roads_gdf, buffer_distance)
        geometries = buffered.geometry.tolist()
    else:
        geometries = roads_gdf.geometry.tolist()

    # Rasterize
    mask = rasterize(
        geometries,
        out_shape=shape,
        transform=transform,
        fill=0,
        default_value=1,
        dtype=np.uint8,
    )

    return mask


def create_road_mask(
    roads_path: Optional[Path] = None,
    rails_path: Optional[Path] = None,
    reference_raster: Path = None,
    buffer_distance: float = 15.0,
    bounds: Optional[tuple[float, float, float, float]] = None,
) -> np.ndarray:
    """
    Create combined road/rail mask for segmentation constraints.

    Args:
        roads_path: Path to TIGER roads data
        rails_path: Path to TIGER rails data
        reference_raster: Reference raster for georeferencing
        buffer_distance: Buffer distance in meters
        bounds: Optional bounding box filter

    Returns:
        Binary mask array (1 = infrastructure, 0 = not)
    """
    with rasterio.open(reference_raster) as src:
        transform = src.transform
        shape = (src.height, src.width)
        crs = src.crs

        if bounds is None:
            bounds = src.bounds

    all_geometries = []

    # Load and buffer roads
    if roads_path is not None and roads_path.exists():
        roads = load_tiger_roads(roads_path, bounds=bounds, crs=crs)
        if len(roads) > 0:
            buffered_roads = buffer_infrastructure(roads, buffer_distance)
            all_geometries.extend(buffered_roads.geometry.tolist())

    # Load and buffer rails
    if rails_path is not None and rails_path.exists():
        rails = load_tiger_rails(rails_path, bounds=bounds, crs=crs)
        if len(rails) > 0:
            buffered_rails = buffer_infrastructure(rails, buffer_distance)
            all_geometries.extend(buffered_rails.geometry.tolist())

    if not all_geometries:
        # Return empty mask if no infrastructure
        return np.zeros(shape, dtype=np.uint8)

    # Rasterize combined geometries
    mask = rasterize(
        all_geometries,
        out_shape=shape,
        transform=transform,
        fill=0,
        default_value=1,
        dtype=np.uint8,
    )

    return mask


def save_road_mask(
    mask: np.ndarray,
    output_path: Path,
    reference_raster: Path,
) -> Path:
    """
    Save road mask as GeoTIFF.

    Args:
        mask: Binary road mask array
        output_path: Output path
        reference_raster: Reference raster for georeferencing

    Returns:
        Output path
    """
    with rasterio.open(reference_raster) as src:
        profile = src.profile.copy()

    profile.update(
        dtype=rasterio.uint8,
        count=1,
        compress="lzw",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(mask, 1)

    return output_path


def combine_edge_sources(
    temporal_edges: np.ndarray,
    road_mask: np.ndarray,
    edge_weight: float = 1.0,
    road_weight: float = 2.0,
) -> np.ndarray:
    """
    Combine temporal edges with road mask into unified edge map.

    Roads are given higher weight as hard boundaries.

    Args:
        temporal_edges: Edge confidence from temporal voting (0-1 or 0-n_years)
        road_mask: Binary road mask (0 or 1)
        edge_weight: Weight for temporal edges
        road_weight: Weight for road edges (should be higher)

    Returns:
        Combined edge map (float)
    """
    # Normalize temporal edges to 0-1 if needed
    if temporal_edges.max() > 1:
        temporal_edges = temporal_edges.astype(np.float32) / temporal_edges.max()

    # Combine with weights
    combined = temporal_edges * edge_weight + road_mask.astype(np.float32) * road_weight

    # Normalize to 0-1
    if combined.max() > 0:
        combined = combined / combined.max()

    return combined
