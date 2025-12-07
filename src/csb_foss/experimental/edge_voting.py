"""
Temporal edge voting module for CSB-FOSS experimental track.

Computes edge confidence by counting how many years each pixel
appears as an edge (where neighbor differs in crop type).
"""

from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from scipy.ndimage import generic_filter
from tqdm import tqdm


def compute_temporal_edge_votes(
    cdl_stack: np.ndarray,
    connectivity: int = 4,
    progress: bool = True,
) -> np.ndarray:
    """
    For each pixel, count years where it's an edge (neighbor differs).

    Args:
        cdl_stack: 3D array of shape (n_years, height, width) with CDL values
        connectivity: 4 (cardinal) or 8 (include diagonals)
        progress: Show progress information

    Returns:
        2D array of edge vote counts (0 to n_years)
    """
    n_years, h, w = cdl_stack.shape
    edge_votes = np.zeros((h, w), dtype=np.uint8)

    # Define neighbor offsets based on connectivity
    if connectivity == 4:
        offsets = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    else:  # 8-connectivity
        offsets = [
            (-1, -1), (-1, 0), (-1, 1),
            (0, -1),           (0, 1),
            (1, -1),  (1, 0),  (1, 1),
        ]

    iterator = range(n_years)
    if progress:
        iterator = tqdm(iterator, desc="Computing edge votes")

    for year_idx in iterator:
        year_data = cdl_stack[year_idx]

        # Find edges where any neighbor differs
        edges = np.zeros((h, w), dtype=bool)

        for dy, dx in offsets:
            # Shift array
            shifted = np.roll(np.roll(year_data, dy, axis=0), dx, axis=1)

            # Mark where values differ
            edges |= (year_data != shifted)

        # Handle boundary effects (edges at image boundary are always edges)
        if dy != 0 or dx != 0:
            if dy == -1:
                edges[0, :] = True
            elif dy == 1:
                edges[-1, :] = True
            if dx == -1:
                edges[:, 0] = True
            elif dx == 1:
                edges[:, -1] = True

        edge_votes += edges.astype(np.uint8)

    return edge_votes


def compute_edge_stability(
    cdl_stack: np.ndarray,
    progress: bool = True,
) -> np.ndarray:
    """
    Compute edge stability - how consistent edges are across years.

    Stability = edge_votes / n_years

    Args:
        cdl_stack: 3D array of shape (n_years, height, width)
        progress: Show progress

    Returns:
        2D array of stability values (0.0 to 1.0)
    """
    n_years = cdl_stack.shape[0]
    edge_votes = compute_temporal_edge_votes(cdl_stack, progress=progress)
    stability = edge_votes.astype(np.float32) / n_years
    return stability


def threshold_stable_edges(
    edge_votes: np.ndarray,
    n_years: int,
    min_votes: Optional[int] = None,
    min_fraction: float = 0.5,
) -> np.ndarray:
    """
    Create binary edge mask from edge votes.

    Args:
        edge_votes: 2D array of vote counts
        n_years: Total number of years
        min_votes: Minimum votes to be considered edge (overrides min_fraction)
        min_fraction: Minimum fraction of years (default 0.5 = 50%)

    Returns:
        Binary edge mask
    """
    if min_votes is None:
        min_votes = int(np.ceil(n_years * min_fraction))

    return (edge_votes >= min_votes).astype(np.uint8)


def compute_edge_gradient(
    cdl_stack: np.ndarray,
    progress: bool = True,
) -> np.ndarray:
    """
    Compute gradient magnitude based on crop type changes.

    For categorical data, this computes a pseudo-gradient based on
    the frequency of value changes in each direction.

    Args:
        cdl_stack: 3D array of CDL values
        progress: Show progress

    Returns:
        2D array of gradient magnitudes
    """
    n_years, h, w = cdl_stack.shape
    gradient = np.zeros((h, w), dtype=np.float32)

    iterator = range(n_years)
    if progress:
        iterator = tqdm(iterator, desc="Computing gradients")

    for year_idx in iterator:
        year_data = cdl_stack[year_idx].astype(np.float32)

        # Compute differences in x and y directions
        diff_y = np.abs(np.diff(year_data, axis=0))
        diff_x = np.abs(np.diff(year_data, axis=1))

        # Pad to original size
        diff_y = np.vstack([diff_y, np.zeros((1, w))])
        diff_x = np.hstack([diff_x, np.zeros((h, 1))])

        # Add to gradient (non-zero difference = edge)
        gradient += (diff_y > 0).astype(np.float32)
        gradient += (diff_x > 0).astype(np.float32)

    # Normalize
    gradient = gradient / (2 * n_years)

    return gradient


def save_edge_votes(
    edge_votes: np.ndarray,
    output_path: Path,
    reference_raster: Path,
) -> Path:
    """
    Save edge votes as a GeoTIFF using reference raster for georeferencing.

    Args:
        edge_votes: 2D array of edge votes
        output_path: Output path
        reference_raster: Reference raster for CRS and transform

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
        dst.write(edge_votes, 1)

    return output_path
