"""
Raster I/O utilities for CSB-FOSS.

Provides functions for reading CDL rasters with windowed access
for memory-efficient processing of large datasets.
"""

from pathlib import Path
from typing import Iterator, Optional

import numpy as np
import rasterio
from rasterio.windows import Window


def get_cdl_paths_for_years(
    base_path: Path,
    start_year: int,
    end_year: int,
    resolution: str = "30m",
) -> dict[int, Path]:
    """
    Find CDL raster paths for a range of years.

    Args:
        base_path: Base directory containing year subdirectories
        start_year: First year to include
        end_year: Last year to include (inclusive)
        resolution: "30m" or "10m"

    Returns:
        Dictionary mapping year to file path
    """
    paths = {}

    for year in range(start_year, end_year + 1):
        # Try common naming patterns
        patterns = [
            base_path / str(year) / f"{year}_{resolution}_cdls.tif",
            base_path / str(year) / f"{year}_30m_cdls.tif",
            base_path / str(year) / f"cdl_{year}.tif",
            base_path / str(year) / f"{year}_cdl.tif",
        ]

        for pattern in patterns:
            if pattern.exists():
                paths[year] = pattern
                break

        # Also check for direct files in base_path
        if year not in paths:
            direct_patterns = [
                base_path / f"{year}_{resolution}_cdls.tif",
                base_path / f"{year}_30m_cdls.tif",
                base_path / f"cdl_{year}.tif",
            ]
            for pattern in direct_patterns:
                if pattern.exists():
                    paths[year] = pattern
                    break

    return paths


def get_raster_profile(raster_path: Path) -> dict:
    """
    Get raster metadata/profile.

    Args:
        raster_path: Path to raster file

    Returns:
        Rasterio profile dictionary
    """
    with rasterio.open(raster_path) as src:
        return src.profile.copy()


def get_raster_bounds(raster_path: Path) -> tuple[float, float, float, float]:
    """
    Get raster bounding box.

    Args:
        raster_path: Path to raster file

    Returns:
        Tuple of (left, bottom, right, top)
    """
    with rasterio.open(raster_path) as src:
        return src.bounds


def read_cdl_window(
    raster_path: Path,
    window: Optional[Window] = None,
) -> tuple[np.ndarray, dict]:
    """
    Read CDL raster data, optionally for a specific window.

    Args:
        raster_path: Path to CDL raster
        window: Optional rasterio Window for subset reading

    Returns:
        Tuple of (data array, metadata dict with transform, crs, nodata)
    """
    with rasterio.open(raster_path) as src:
        if window is not None:
            data = src.read(1, window=window)
            transform = src.window_transform(window)
        else:
            data = src.read(1)
            transform = src.transform

        metadata = {
            "transform": transform,
            "crs": src.crs,
            "nodata": src.nodata,
            "width": data.shape[1],
            "height": data.shape[0],
        }

    return data, metadata


def generate_windows(
    raster_path: Path,
    tile_size: int = 4096,
    overlap: int = 0,
) -> Iterator[tuple[Window, tuple[int, int]]]:
    """
    Generate windows for tiled processing of a raster.

    Args:
        raster_path: Path to raster file
        tile_size: Size of tiles in pixels
        overlap: Overlap between tiles in pixels

    Yields:
        Tuples of (Window, (row_index, col_index))
    """
    with rasterio.open(raster_path) as src:
        height = src.height
        width = src.width

    step = tile_size - overlap
    row_idx = 0

    for row_off in range(0, height, step):
        col_idx = 0
        for col_off in range(0, width, step):
            win_height = min(tile_size, height - row_off)
            win_width = min(tile_size, width - col_off)

            window = Window(col_off, row_off, win_width, win_height)
            yield window, (row_idx, col_idx)

            col_idx += 1
        row_idx += 1


def read_multi_year_stack(
    paths: dict[int, Path],
    window: Optional[Window] = None,
) -> tuple[np.ndarray, list[int], dict]:
    """
    Read multiple years of CDL into a stacked array.

    Args:
        paths: Dictionary mapping year to raster path
        window: Optional window for subset reading

    Returns:
        Tuple of:
            - 3D array of shape (n_years, height, width)
            - List of years in order
            - Metadata dict
    """
    years = sorted(paths.keys())
    arrays = []
    metadata = None

    for year in years:
        data, meta = read_cdl_window(paths[year], window)
        arrays.append(data)
        if metadata is None:
            metadata = meta

    stack = np.stack(arrays, axis=0)
    return stack, years, metadata


def clip_raster_to_geometry(
    raster_path: Path,
    geometry,
    output_path: Path,
    all_touched: bool = True,
) -> Path:
    """
    Clip a raster to a geometry (e.g., state boundary).

    Args:
        raster_path: Input raster path
        geometry: Shapely geometry or GeoJSON-like dict
        output_path: Output path for clipped raster
        all_touched: Include all pixels touched by geometry

    Returns:
        Path to clipped raster
    """
    from rasterio.mask import mask

    with rasterio.open(raster_path) as src:
        out_image, out_transform = mask(
            src,
            [geometry],
            crop=True,
            all_touched=all_touched,
        )

        out_meta = src.meta.copy()
        out_meta.update({
            "driver": "GTiff",
            "height": out_image.shape[1],
            "width": out_image.shape[2],
            "transform": out_transform,
            "compress": "lzw",
        })

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(output_path, "w", **out_meta) as dst:
            dst.write(out_image)

    return output_path
