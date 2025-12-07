# CSB-FOSS: Open Source Crop Sequence Boundaries

A FOSS (Free and Open Source Software) reimplementation of the USDA NASS Crop Sequence Boundaries generation pipeline, originally built on ArcGIS/ArcPy.

## Overview

Crop Sequence Boundaries (CSB) are field-level polygons that represent consistent crop rotation patterns across multiple years of the Cropland Data Layer (CDL). This project provides:

1. **Baseline Track**: A compatible replacement for the ArcGIS-based workflow
2. **Experimental Track**: Improved boundary generation using modern segmentation techniques

## Features

- 🗺️ **FOSS Stack**: Uses GDAL, Rasterio, GeoPandas, Shapely, DuckDB
- 🔄 **Multi-year Analysis**: Combines 8 years of CDL (2017-2024)
- 🛣️ **Road Integration**: TIGER/Line roads as boundary constraints
- 🛰️ **NAIP Support**: High-resolution (60cm) NDVI edge detection
- 📊 **DuckDB Spatial**: Efficient vector analytics and exports
- ⚡ **Parallel Processing**: Tile-based multiprocessing for large datasets

## Installation

```bash
# Clone the repository
cd csb-foss

# Install in development mode
pip install -e .

# With notebook support
pip install -e ".[notebooks]"

# With development tools
pip install -e ".[dev]"
```

## Quick Start

### 1. Configure Data Paths

Edit `config/csb_foss.ini` with your data locations:

```ini
[data]
cdl_30m = S:\_STAGING\01_RASTER_CORPUS\annual_cdl
cdl_10m = S:\_STAGING\01_RASTER_CORPUS\annual_cdl_10m
naip = S:\_STAGING\01_RASTER_CORPUS\naip_cog\Tennessee_Statewide
tiger_roads = /path/to/tiger/roads
```

### 2. Run the Pipeline

```python
from pathlib import Path
from csb_foss.config import load_config
from csb_foss.pipeline import create_csb, prep_csb, distribute_csb

# Load configuration
config = load_config(Path("config/csb_foss.ini"))

# Stage 1: Create boundaries
create_output = create_csb(config, track="baseline")

# Stage 2: Enrich with attributes
prep_output = prep_csb(config, input_path=create_output)

# Stage 3: Export by state
distribute_csb(config, input_path=prep_output, states=["TN"])
```

### 3. Use Individual Modules

```python
from csb_foss.raster import combine_cdl_rasters, get_cdl_paths_for_years
from csb_foss.vector import vectorize_raster, eliminate_small_polygons, simplify_polygons

# Find CDL rasters
paths = get_cdl_paths_for_years(Path("cdl_dir"), 2017, 2024)

# Combine multi-year rasters
combine_cdl_rasters(paths, output_path, lookup_path)

# Vectorize
gdf = vectorize_raster(combined_raster, lookup_path=lookup_path)

# Process polygons
gdf = eliminate_small_polygons(gdf, area_threshold=10000)
gdf = simplify_polygons(gdf, tolerance=60.0)
```

## Architecture

### Pipeline Stages

```
┌─────────────────────────────────────────────────────────────────┐
│                         STAGE 1: CREATE                          │
│  CDL Rasters (8 years) → Combine → Vectorize → Eliminate → Simplify  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                          STAGE 2: PREP                           │
│  CSB Polygons → Spatial Join (ASD/County) → Zonal Stats (Crop)  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       STAGE 3: DISTRIBUTE                        │
│  Enriched CSB → Generate CSBID → Export by State (GPKG/SHP/TIF) │
└─────────────────────────────────────────────────────────────────┘
```

### Module Structure

```
csb-foss/
├── src/csb_foss/
│   ├── config.py              # Configuration management
│   ├── raster/
│   │   ├── io.py              # Raster I/O utilities
│   │   ├── combine.py         # Multi-year CDL combination
│   │   └── zonal_stats.py     # Zonal statistics
│   ├── vector/
│   │   ├── vectorize.py       # Raster to polygon conversion
│   │   ├── eliminate.py       # Small polygon elimination
│   │   ├── simplify.py        # Polygon simplification
│   │   └── spatial_join.py    # Admin boundary joins
│   ├── experimental/
│   │   ├── edge_voting.py     # Temporal edge detection
│   │   ├── road_integration.py # TIGER road constraints
│   │   ├── naip_segmentation.py # NAIP-based segmentation
│   │   └── watershed.py       # Watershed segmentation
│   ├── db/
│   │   ├── schema.py          # Database schemas
│   │   └── duckdb_ops.py      # DuckDB spatial operations
│   └── pipeline/
│       ├── create.py          # Stage 1
│       ├── prep.py            # Stage 2
│       └── distribute.py      # Stage 3
├── config/
│   └── csb_foss.ini           # Default configuration
├── notebooks/
│   ├── 01_explore_cdl.ipynb   # Data exploration
│   ├── 02_baseline_pipeline.ipynb
│   └── 03_experimental_segmentation.ipynb
└── tests/
```

## Processing Tracks

### Baseline Track (ArcGIS-Compatible)

Replicates the existing CSB workflow:

1. **Combine**: Stack 8 years of CDL into unique signatures
2. **Vectorize**: Convert raster to polygons with `rasterio.features.shapes()`
3. **Filter**: Remove non-cropland polygons (COUNT0 - COUNT45 >= 2)
4. **Eliminate**: Merge small polygons (<1 ha) to longest-boundary neighbor
5. **Simplify**: Douglas-Peucker at 60m tolerance

### Experimental Track (Improved)

Three approaches for better boundary detection:

#### Approach 1: CDL-Only Watershed
- Temporal edge voting across 8 years
- TIGER roads as hard boundaries
- Watershed segmentation

#### Approach 2: NAIP-Primary
- Compute NDVI from 60cm NAIP imagery
- Canny edge detection on NDVI gradients
- Watershed segmentation
- Label segments with CDL majority

#### Approach 3: Hybrid Refinement
- Generate CDL boundaries (baseline)
- Detect NAIP edges
- Snap CDL boundaries to nearest NAIP edge

## Key Algorithms

### Raster Combination

Combines multi-year CDL into unique signature codes:

```python
# Polynomial encoding: code = Σ(value_i × 256^i)
combined = Σ(cdl_year[i] × 256^i) for i in range(n_years)
```

### Polygon Elimination

Merges small polygons to neighbor with longest shared boundary:

```python
for polygon in small_polygons:
    neighbors = find_touching_neighbors(polygon)
    best = max(neighbors, key=shared_boundary_length)
    merge(polygon, best)
```

### Temporal Edge Voting

Counts years where each pixel is an edge:

```python
for year in years:
    edges = (cdl[year] != neighbor(cdl[year]))
    edge_votes += edges
# Stable edges have high vote counts
```

## Configuration Reference

```ini
[data]
cdl_30m = /path/to/annual_cdl           # 30m CDL directory
cdl_10m = /path/to/annual_cdl_10m       # 10m CDL (2024)
naip = /path/to/naip_cog                # NAIP imagery
tiger_roads = /path/to/tiger/roads      # TIGER roads
tiger_rails = /path/to/tiger/rails      # TIGER railroads
admin_boundaries = /path/to/admin       # ASD/County boundaries

[params]
start_year = 2017                       # First year
end_year = 2024                         # Last year
simplify_tolerance = 60.0               # Baseline: 60m
min_crop_years = 2                      # COUNT0 - COUNT45 threshold
cpu_fraction = 0.97                     # CPU utilization
road_buffer = 15.0                      # Road buffer (meters)

[output]
base_dir = ./output                     # Output directory

[processing]
track = baseline                        # 'baseline' or 'experimental'
state_filter = TN                       # State to process
```

## Output Formats

| Format | Extension | Description |
|--------|-----------|-------------|
| GeoPackage | `.gpkg` | Primary vector format |
| Shapefile | `.shp` | Legacy compatibility |
| GeoTIFF | `.tif` | Rasterized CSBID |
| GeoParquet | `.parquet` | Efficient columnar storage |

## Output Schema

| Field | Type | Description |
|-------|------|-------------|
| `csb_id` | VARCHAR(15) | Unique ID: STATEFIPS + YEARS + SEQ |
| `csb_years` | VARCHAR(4) | Year range (e.g., "1724") |
| `csb_acres` | DOUBLE | Area in acres |
| `cdl_YYYY` | INTEGER | Majority crop code per year |
| `count0` | SMALLINT | Years with cropland |
| `count45` | SMALLINT | Years with barren |
| `state_fips` | VARCHAR(2) | State FIPS code |
| `county_fips` | VARCHAR(3) | County FIPS code |
| `geometry` | GEOMETRY | Polygon boundary |

## Dependencies

### Core
- numpy, scipy
- rasterio, GDAL
- geopandas, shapely, fiona
- pyarrow (GeoParquet)
- duckdb (spatial extension)

### Segmentation
- scikit-image
- rasterstats

### Processing
- dask, dask-geopandas
- joblib, tqdm

## Comparison with ArcGIS Version

| Operation | ArcGIS (ArcPy) | CSB-FOSS |
|-----------|----------------|----------|
| Raster combine | `arcpy.gp.Combine_sa()` | NumPy polynomial encoding |
| Vectorize | `arcpy.RasterToPolygon_conversion()` | `rasterio.features.shapes()` |
| Eliminate | `arcpy.management.Eliminate()` | Custom longest-boundary merge |
| Simplify | `arcpy.SimplifyPolygon()` BEND_SIMPLIFY | Shapely Douglas-Peucker |
| Spatial join | `arcpy.SpatialJoin()` | DuckDB `ST_Intersects` |
| Zonal stats | `arcpy.ZonalStatisticsAsTable()` | rasterstats |

## References

- [USDA NASS CSB](https://www.nass.usda.gov/Research_and_Science/Crop-Sequence-Boundaries/)
- [CSB Metadata](https://www.nass.usda.gov/Research_and_Science/Crop-Sequence-Boundaries/metadata_Crop-Sequence-Boundaries-2024.htm)
- [Original CSB GitHub](https://github.com/USDA-REE-NASS/crop-sequence-boundaries)

## License

MIT License - See LICENSE file for details.

## Contributing

Contributions welcome! Please see CONTRIBUTING.md for guidelines.
