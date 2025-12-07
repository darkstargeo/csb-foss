"""
NAIP-based segmentation module for CSB-FOSS experimental track.

Uses high-resolution NAIP imagery (60cm-1m, 4-band RGBIR) for
precise field boundary detection via NDVI edge detection.
"""

from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import rasterio
from rasterio.windows import Window
from scipy.ndimage import distance_transform_edt
from skimage.feature import canny
from skimage.filters import sobel
from tqdm import tqdm


def compute_naip_ndvi(
    naip_path: Path,
    window: Optional[Window] = None,
    red_band: int = 1,
    nir_band: int = 4,
) -> Tuple[np.ndarray, dict]:
    """
    Calculate NDVI from NAIP imagery.

    NDVI = (NIR - Red) / (NIR + Red)

    Args:
        naip_path: Path to NAIP COG/GeoTIFF
        window: Optional window for subset reading
        red_band: Band index for red (default 1, 1-indexed)
        nir_band: Band index for NIR (default 4, 1-indexed)

    Returns:
        Tuple of (NDVI array, metadata dict)
    """
    with rasterio.open(naip_path) as src:
        if window is not None:
            red = src.read(red_band, window=window).astype(np.float32)
            nir = src.read(nir_band, window=window).astype(np.float32)
            transform = src.window_transform(window)
        else:
            red = src.read(red_band).astype(np.float32)
            nir = src.read(nir_band).astype(np.float32)
            transform = src.transform

        metadata = {
            "transform": transform,
            "crs": src.crs,
            "width": red.shape[1],
            "height": red.shape[0],
        }

    # Compute NDVI with division safety
    denominator = nir + red
    ndvi = np.where(
        denominator > 0,
        (nir - red) / denominator,
        0.0,
    )

    # Clip to valid range
    ndvi = np.clip(ndvi, -1.0, 1.0)

    return ndvi, metadata


def detect_naip_edges(
    ndvi: np.ndarray,
    method: str = "canny",
    sigma: float = 2.0,
    low_threshold: float = 0.1,
    high_threshold: float = 0.3,
) -> np.ndarray:
    """
    Detect edges in NDVI image.

    Args:
        ndvi: NDVI array
        method: "canny" or "sobel"
        sigma: Gaussian smoothing sigma for Canny
        low_threshold: Low threshold for Canny hysteresis
        high_threshold: High threshold for Canny hysteresis

    Returns:
        Binary edge map or gradient magnitude
    """
    if method == "canny":
        # Normalize NDVI to 0-1 for Canny
        ndvi_norm = (ndvi + 1) / 2
        edges = canny(
            ndvi_norm,
            sigma=sigma,
            low_threshold=low_threshold,
            high_threshold=high_threshold,
        )
        return edges.astype(np.uint8)

    elif method == "sobel":
        # Sobel returns gradient magnitude
        edges = sobel(ndvi)
        # Normalize to 0-1
        if edges.max() > 0:
            edges = edges / edges.max()
        return edges.astype(np.float32)

    else:
        raise ValueError(f"Unknown method: {method}")


def resample_to_cdl_resolution(
    naip_edges: np.ndarray,
    naip_transform,
    cdl_transform,
    cdl_shape: Tuple[int, int],
    method: str = "max",
) -> np.ndarray:
    """
    Resample high-resolution NAIP edges to CDL resolution.

    Args:
        naip_edges: High-resolution edge map
        naip_transform: NAIP affine transform
        cdl_transform: CDL affine transform
        cdl_shape: Target (height, width)
        method: Aggregation method ("max", "mean", "any")

    Returns:
        Resampled edge map at CDL resolution
    """
    from rasterio.warp import reproject, Resampling

    # Choose resampling method
    if method == "max":
        resampling = Resampling.max
    elif method == "mean":
        resampling = Resampling.average
    else:  # "any" - use max for binary
        resampling = Resampling.max

    # Output array
    resampled = np.zeros(cdl_shape, dtype=naip_edges.dtype)

    # Reproject
    reproject(
        source=naip_edges,
        destination=resampled,
        src_transform=naip_transform,
        dst_transform=cdl_transform,
        src_crs="EPSG:5070",  # Albers
        dst_crs="EPSG:5070",
        resampling=resampling,
    )

    return resampled


def segment_with_naip(
    naip_path: Path,
    road_mask: np.ndarray,
    reference_transform,
    reference_shape: Tuple[int, int],
    edge_method: str = "canny",
    edge_sigma: float = 2.0,
    progress: bool = True,
) -> np.ndarray:
    """
    Segment fields using NAIP imagery.

    1. Compute NDVI from NAIP
    2. Edge detection on NDVI
    3. Combine with road mask
    4. Watershed segmentation

    Args:
        naip_path: Path to NAIP COG
        road_mask: Binary road mask at target resolution
        reference_transform: Target affine transform
        reference_shape: Target (height, width)
        edge_method: Edge detection method
        edge_sigma: Smoothing for edge detection
        progress: Show progress

    Returns:
        Segmented label array
    """
    from .watershed import watershed_segment

    if progress:
        print("Computing NDVI from NAIP...")

    ndvi, naip_meta = compute_naip_ndvi(naip_path)

    if progress:
        print("Detecting edges in NDVI...")

    edges = detect_naip_edges(ndvi, method=edge_method, sigma=edge_sigma)

    if progress:
        print("Resampling to target resolution...")

    # Resample edges to CDL resolution
    edges_resampled = resample_to_cdl_resolution(
        edges,
        naip_meta["transform"],
        reference_transform,
        reference_shape,
        method="max",
    )

    # Combine with road mask
    combined_edges = np.maximum(
        edges_resampled.astype(np.float32),
        road_mask.astype(np.float32),
    )

    if progress:
        print("Running watershed segmentation...")

    # Watershed
    labels = watershed_segment(combined_edges, road_mask)

    return labels


def refine_cdl_boundaries(
    cdl_boundaries: np.ndarray,
    naip_edges: np.ndarray,
    snap_distance: float = 30.0,
    cdl_transform=None,
    naip_transform=None,
) -> np.ndarray:
    """
    Refine coarse CDL boundaries using high-resolution NAIP edges.

    For each CDL boundary pixel, find the nearest NAIP edge within
    snap_distance and move the boundary to that edge.

    Args:
        cdl_boundaries: Binary CDL boundary mask
        naip_edges: High-resolution NAIP edge map
        snap_distance: Maximum snap distance in CRS units
        cdl_transform: CDL affine transform
        naip_transform: NAIP affine transform

    Returns:
        Refined boundary mask at CDL resolution
    """
    # If NAIP edges are at higher resolution, resample first
    if naip_edges.shape != cdl_boundaries.shape:
        naip_edges = resample_to_cdl_resolution(
            naip_edges,
            naip_transform,
            cdl_transform,
            cdl_boundaries.shape,
            method="max",
        )

    # Distance transform from NAIP edges
    naip_distance = distance_transform_edt(~naip_edges.astype(bool))

    # Convert snap_distance from CRS units to pixels
    if cdl_transform is not None:
        pixel_size = abs(cdl_transform[0])  # Assume square pixels
        snap_pixels = snap_distance / pixel_size
    else:
        snap_pixels = snap_distance / 30.0  # Assume 30m pixels

    # Find CDL boundary pixels that are within snap distance of NAIP edge
    can_snap = (cdl_boundaries > 0) & (naip_distance <= snap_pixels)

    # Create refined boundaries
    # Keep NAIP edges where CDL boundaries can snap, otherwise keep CDL
    refined = cdl_boundaries.copy()
    refined[can_snap] = 0  # Remove snappable CDL boundaries

    # Add NAIP edges that are near CDL boundaries
    cdl_distance = distance_transform_edt(~cdl_boundaries.astype(bool))
    naip_near_cdl = (naip_edges > 0) & (cdl_distance <= snap_pixels)
    refined = np.maximum(refined, naip_near_cdl.astype(refined.dtype))

    return refined


def process_naip_tiles(
    naip_dir: Path,
    output_dir: Path,
    reference_raster: Path,
    tile_pattern: str = "*.tif",
    progress: bool = True,
) -> list[Path]:
    """
    Process multiple NAIP tiles to extract edges.

    Args:
        naip_dir: Directory containing NAIP COGs
        output_dir: Output directory for edge maps
        reference_raster: Reference raster for georeferencing
        tile_pattern: Glob pattern for NAIP tiles
        progress: Show progress

    Returns:
        List of output edge map paths
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []

    tiles = list(naip_dir.glob(tile_pattern))

    if progress:
        tiles = tqdm(tiles, desc="Processing NAIP tiles")

    for tile_path in tiles:
        output_path = output_dir / f"{tile_path.stem}_edges.tif"

        # Compute NDVI and edges
        ndvi, meta = compute_naip_ndvi(tile_path)
        edges = detect_naip_edges(ndvi)

        # Save edges
        with rasterio.open(tile_path) as src:
            profile = src.profile.copy()

        profile.update(
            dtype=rasterio.uint8,
            count=1,
            compress="lzw",
        )

        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(edges, 1)

        outputs.append(output_path)

    return outputs
