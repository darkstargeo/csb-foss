"""
Watershed segmentation module for CSB-FOSS experimental track.

Performs watershed segmentation on edge maps to delineate field boundaries.
"""

from typing import Optional, Tuple

import numpy as np
from scipy.ndimage import distance_transform_edt, label
from skimage.segmentation import watershed
from skimage.feature import peak_local_max


def watershed_segment(
    edge_map: np.ndarray,
    road_mask: Optional[np.ndarray] = None,
    min_distance: int = 10,
    min_segment_size: int = 100,
    compactness: float = 0.0,
) -> np.ndarray:
    """
    Perform watershed segmentation on an edge map.

    Args:
        edge_map: Edge confidence map (0-1 float or 0-255 uint8)
        road_mask: Optional binary road mask (roads are hard boundaries)
        min_distance: Minimum distance between segment markers (pixels)
        min_segment_size: Minimum segment size in pixels
        compactness: Compactness parameter for watershed (0 = no compactness)

    Returns:
        Integer label array where each segment has a unique value
    """
    # Normalize edge map to 0-1 if needed
    if edge_map.max() > 1:
        edge_map = edge_map.astype(np.float32) / edge_map.max()

    # Invert edge map: interior = high, edges = low
    # This makes distance transform work correctly
    interior = 1.0 - edge_map

    # Create mask for watershed (where to compute)
    # Include all non-edge areas
    mask = interior > 0.3

    # If road mask provided, exclude roads from segmentation
    if road_mask is not None:
        mask = mask & (road_mask == 0)

    # Distance transform from edges
    # Pixels far from edges get high values
    distance = distance_transform_edt(interior > 0.5)

    # Find local maxima as markers (field centers)
    local_max_coords = peak_local_max(
        distance,
        min_distance=min_distance,
        exclude_border=False,
        labels=mask.astype(int),
    )

    # Create marker image
    markers = np.zeros(edge_map.shape, dtype=np.int32)
    for i, (y, x) in enumerate(local_max_coords):
        markers[y, x] = i + 1

    # Expand markers using connected components
    # This helps with very small initial markers
    markers, n_markers = label(markers > 0)

    # Perform watershed
    # Use negative distance so watershed flows from edges toward centers
    labels = watershed(
        -distance,
        markers,
        mask=mask,
        compactness=compactness,
    )

    # Enforce road mask as boundaries (set to 0)
    if road_mask is not None:
        labels[road_mask > 0] = 0

    # Remove small segments
    if min_segment_size > 0:
        labels = remove_small_segments(labels, min_segment_size)

    return labels


def remove_small_segments(
    labels: np.ndarray,
    min_size: int,
) -> np.ndarray:
    """
    Remove segments smaller than min_size pixels.

    Small segments are merged into their largest neighbor.

    Args:
        labels: Integer label array
        min_size: Minimum segment size in pixels

    Returns:
        Label array with small segments removed
    """
    from scipy.ndimage import find_objects

    labels = labels.copy()
    unique_labels = np.unique(labels)
    unique_labels = unique_labels[unique_labels > 0]  # Exclude background

    for lbl in unique_labels:
        mask = labels == lbl
        size = mask.sum()

        if size < min_size:
            # Find neighboring labels
            from scipy.ndimage import binary_dilation

            dilated = binary_dilation(mask)
            neighbors = labels[dilated & ~mask]
            neighbors = neighbors[neighbors > 0]
            neighbors = neighbors[neighbors != lbl]

            if len(neighbors) > 0:
                # Merge to most common neighbor
                unique, counts = np.unique(neighbors, return_counts=True)
                target_label = unique[counts.argmax()]
                labels[mask] = target_label

    return labels


def segment_with_markers(
    edge_map: np.ndarray,
    markers: np.ndarray,
    road_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Watershed segmentation with user-provided markers.

    Args:
        edge_map: Edge confidence map
        markers: Integer marker array (0 = no marker, >0 = segment ID)
        road_mask: Optional road mask

    Returns:
        Label array
    """
    # Normalize edge map
    if edge_map.max() > 1:
        edge_map = edge_map.astype(np.float32) / edge_map.max()

    interior = 1.0 - edge_map
    distance = distance_transform_edt(interior > 0.5)

    mask = interior > 0.3
    if road_mask is not None:
        mask = mask & (road_mask == 0)

    labels = watershed(-distance, markers, mask=mask)

    if road_mask is not None:
        labels[road_mask > 0] = 0

    return labels


def refine_segment_boundaries(
    labels: np.ndarray,
    edge_map: np.ndarray,
    iterations: int = 2,
) -> np.ndarray:
    """
    Refine segment boundaries by re-running watershed with current labels as markers.

    This can help clean up noisy boundaries.

    Args:
        labels: Initial label array
        edge_map: Edge map
        iterations: Number of refinement iterations

    Returns:
        Refined label array
    """
    for _ in range(iterations):
        # Use centroid of each segment as marker
        markers = np.zeros_like(labels)

        from scipy.ndimage import center_of_mass

        unique_labels = np.unique(labels)
        unique_labels = unique_labels[unique_labels > 0]

        for lbl in unique_labels:
            mask = labels == lbl
            if mask.sum() > 0:
                cy, cx = center_of_mass(mask.astype(float))
                cy, cx = int(cy), int(cx)
                if 0 <= cy < labels.shape[0] and 0 <= cx < labels.shape[1]:
                    markers[cy, cx] = lbl

        # Re-run watershed
        labels = segment_with_markers(edge_map, markers)

    return labels


def labels_to_edges(labels: np.ndarray) -> np.ndarray:
    """
    Convert label array to binary edge array.

    Args:
        labels: Integer label array

    Returns:
        Binary edge array
    """
    from scipy.ndimage import sobel

    # Compute gradient magnitude
    gx = sobel(labels.astype(float), axis=0)
    gy = sobel(labels.astype(float), axis=1)
    gradient = np.sqrt(gx**2 + gy**2)

    # Threshold to get edges
    edges = (gradient > 0).astype(np.uint8)

    return edges


def compute_segment_statistics(
    labels: np.ndarray,
    values: Optional[np.ndarray] = None,
) -> dict:
    """
    Compute statistics for each segment.

    Args:
        labels: Integer label array
        values: Optional value array for computing per-segment stats

    Returns:
        Dictionary with segment statistics
    """
    unique_labels = np.unique(labels)
    unique_labels = unique_labels[unique_labels > 0]

    stats = {
        "n_segments": len(unique_labels),
        "sizes": {},
        "values": {} if values is not None else None,
    }

    for lbl in unique_labels:
        mask = labels == lbl
        stats["sizes"][int(lbl)] = int(mask.sum())

        if values is not None:
            segment_values = values[mask]
            stats["values"][int(lbl)] = {
                "mean": float(segment_values.mean()),
                "std": float(segment_values.std()),
                "min": float(segment_values.min()),
                "max": float(segment_values.max()),
            }

    return stats
