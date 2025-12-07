"""
Raster combination module for CSB-FOSS.

Replaces ArcPy's Combine_sa function for creating unique
crop sequence signatures from multi-year CDL rasters.
"""

import json
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from rasterio.windows import Window
from tqdm import tqdm

from .io import read_multi_year_stack, generate_windows, get_raster_profile


def encode_year_sequence(stack: np.ndarray) -> tuple[np.ndarray, dict]:
    """
    Encode a multi-year CDL stack into unique signature codes.

    Uses polynomial encoding: code = sum(value_i * 256^i)
    This supports up to 8 years with CDL values 0-255.

    Args:
        stack: 3D array of shape (n_years, height, width) with CDL values

    Returns:
        Tuple of:
            - 2D array of signature codes (uint32 or uint64)
            - Lookup dict mapping codes to tuples of year values
    """
    n_years = stack.shape[0]

    # Use uint64 for encoding to handle 8+ years
    combined = np.zeros(stack.shape[1:], dtype=np.uint64)

    for i in range(n_years):
        combined += stack[i].astype(np.uint64) * (256 ** i)

    # Find unique values and create compact encoding
    unique_vals, inverse = np.unique(combined, return_inverse=True)
    coded = inverse.reshape(stack.shape[1:]).astype(np.uint32)

    # Build lookup table
    lookup = {}
    for code, val in enumerate(unique_vals):
        year_values = decode_sequence(int(val), n_years)
        lookup[code] = year_values

    return coded, lookup


def decode_sequence(value: int, n_years: int) -> tuple[int, ...]:
    """
    Decode a combined value back to individual year values.

    Args:
        value: Combined signature code
        n_years: Number of years encoded

    Returns:
        Tuple of CDL values for each year
    """
    result = []
    for _ in range(n_years):
        result.append(value % 256)
        value //= 256
    return tuple(result)


def calculate_crop_counts(lookup: dict, n_years: int) -> dict:
    """
    Calculate COUNT0 and COUNT45 for each signature.

    COUNT0: Number of years with any crop (CDL > 0)
    COUNT45: Number of years with barren land (CDL = 45, originally 131)

    Args:
        lookup: Signature lookup table
        n_years: Number of years

    Returns:
        Dict mapping signature code to (COUNT0, COUNT45)
    """
    counts = {}
    for code, values in lookup.items():
        count0 = sum(1 for v in values if v > 0)
        count45 = sum(1 for v in values if v == 45)
        counts[code] = (count0, count45)
    return counts


def combine_cdl_rasters(
    paths: dict[int, Path],
    output_path: Path,
    lookup_path: Optional[Path] = None,
    window: Optional[Window] = None,
    progress: bool = True,
) -> tuple[Path, dict]:
    """
    Combine multi-year CDL rasters into a single signature raster.

    This is the FOSS replacement for arcpy.gp.Combine_sa().

    Args:
        paths: Dictionary mapping year to CDL raster path
        output_path: Path for output signature raster
        lookup_path: Optional path to save lookup table as JSON
        window: Optional window for processing subset
        progress: Show progress bar

    Returns:
        Tuple of (output path, lookup dict)
    """
    years = sorted(paths.keys())
    n_years = len(years)

    # Get profile from first raster
    first_path = paths[years[0]]
    profile = get_raster_profile(first_path)

    if window is None:
        # Process entire raster in memory
        stack, _, metadata = read_multi_year_stack(paths, window=None)
        coded, lookup = encode_year_sequence(stack)

        # Update profile for output
        profile.update(
            dtype=rasterio.uint32,
            count=1,
            compress="lzw",
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(coded, 1)

    else:
        # Process single window
        stack, _, metadata = read_multi_year_stack(paths, window=window)
        coded, lookup = encode_year_sequence(stack)

        # Caller handles writing
        return coded, lookup

    # Save lookup table
    if lookup_path is not None:
        lookup_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert tuple keys to strings for JSON
        json_lookup = {
            str(k): {"values": list(v), "years": years}
            for k, v in lookup.items()
        }

        # Add counts
        counts = calculate_crop_counts(lookup, n_years)
        for k, (c0, c45) in counts.items():
            json_lookup[str(k)]["count0"] = c0
            json_lookup[str(k)]["count45"] = c45

        with open(lookup_path, "w") as f:
            json.dump(json_lookup, f, indent=2)

    return output_path, lookup


def combine_cdl_rasters_windowed(
    paths: dict[int, Path],
    output_path: Path,
    lookup_path: Path,
    tile_size: int = 4096,
    progress: bool = True,
) -> tuple[Path, dict]:
    """
    Combine multi-year CDL rasters using windowed processing.

    Memory-efficient version for large rasters.

    Args:
        paths: Dictionary mapping year to CDL raster path
        output_path: Path for output signature raster
        lookup_path: Path to save lookup table as JSON
        tile_size: Size of processing tiles in pixels
        progress: Show progress bar

    Returns:
        Tuple of (output path, lookup dict)
    """
    years = sorted(paths.keys())
    n_years = len(years)
    first_path = paths[years[0]]

    # Get profile
    profile = get_raster_profile(first_path)
    profile.update(
        dtype=rasterio.uint32,
        count=1,
        compress="lzw",
    )

    # Global lookup accumulator
    global_lookup = {}
    next_code = 0

    # Value to code mapping for consistent encoding across tiles
    value_to_code = {}

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(output_path, "w", **profile) as dst:
        windows = list(generate_windows(first_path, tile_size=tile_size))

        iterator = tqdm(windows, desc="Combining rasters") if progress else windows

        for window, (row_idx, col_idx) in iterator:
            # Read stack for this window
            stack, _, _ = read_multi_year_stack(paths, window=window)

            # Encode without compact remapping
            combined = np.zeros(stack.shape[1:], dtype=np.uint64)
            for i in range(n_years):
                combined += stack[i].astype(np.uint64) * (256 ** i)

            # Map to global codes
            coded = np.zeros_like(combined, dtype=np.uint32)

            for val in np.unique(combined):
                val = int(val)
                if val not in value_to_code:
                    value_to_code[val] = next_code
                    global_lookup[next_code] = decode_sequence(val, n_years)
                    next_code += 1

                mask = combined == val
                coded[mask] = value_to_code[val]

            # Write window
            dst.write(coded, 1, window=window)

    # Save lookup
    lookup_path.parent.mkdir(parents=True, exist_ok=True)

    counts = calculate_crop_counts(global_lookup, n_years)
    json_lookup = {
        str(k): {
            "values": list(v),
            "years": years,
            "count0": counts[k][0],
            "count45": counts[k][1],
        }
        for k, v in global_lookup.items()
    }

    with open(lookup_path, "w") as f:
        json.dump(json_lookup, f, indent=2)

    return output_path, global_lookup


def load_lookup_table(lookup_path: Path) -> dict:
    """
    Load a lookup table from JSON file.

    Args:
        lookup_path: Path to lookup JSON file

    Returns:
        Lookup dictionary with integer keys
    """
    with open(lookup_path) as f:
        json_lookup = json.load(f)

    # Convert string keys back to integers
    lookup = {
        int(k): tuple(v["values"])
        for k, v in json_lookup.items()
    }

    return lookup


def get_signature_stats(lookup_path: Path) -> dict:
    """
    Get statistics from a lookup table.

    Args:
        lookup_path: Path to lookup JSON file

    Returns:
        Dictionary with stats (n_signatures, years, count distributions)
    """
    with open(lookup_path) as f:
        json_lookup = json.load(f)

    n_signatures = len(json_lookup)
    years = json_lookup["0"]["years"] if json_lookup else []

    count0_dist = {}
    count45_dist = {}

    for entry in json_lookup.values():
        c0 = entry.get("count0", 0)
        c45 = entry.get("count45", 0)
        count0_dist[c0] = count0_dist.get(c0, 0) + 1
        count45_dist[c45] = count45_dist.get(c45, 0) + 1

    return {
        "n_signatures": n_signatures,
        "years": years,
        "count0_distribution": count0_dist,
        "count45_distribution": count45_dist,
    }
