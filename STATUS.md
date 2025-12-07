# CSB-FOSS Project Status

**Last Updated**: 2025-12-07
**Project Phase**: Core Testing Complete
**Repository**: csb-foss (standalone from ArcGIS fork)

---

## Current State

### Test Results (2025-12-07)

| Test | Status | Notes |
|------|--------|-------|
| Module imports | PASS | All core modules import successfully |
| Data path access | PASS | CDL 30m (17 years), 10m (1 year), NAIP (6688 files) |
| Config loading | PASS | INI parsing and directory creation working |
| Raster combine | PASS | 8-year stack (2017-2024), 2858 unique signatures |
| Vectorization | PASS | 13,194 initial polygons from 5km test area |
| Elimination | PASS | Reduced to 393 polygons (tiered: 100/1000/10000 m²) |
| Simplification | PASS | 60m tolerance applied, topology preserved |

### Bug Fixes Applied

| Issue | Fix | File |
|-------|-----|------|
| `shapes()` dtype error | Cast uint32 to int32 before vectorization | `vector/vectorize.py` |
| numpy import order | Moved import to top of file | `vector/simplify.py` |

### Completed Components

| Component | Status | Notes |
|-----------|--------|-------|
| Project Structure | DONE | All directories and `__init__.py` files created |
| `pyproject.toml` | DONE | Dependencies defined, installed successfully |
| `config/csb_foss.ini` | DONE | Configured with user's data paths |
| `raster/io.py` | DONE | CDL reading, windowing, multi-year stacking |
| `raster/combine.py` | DONE | Replaces `arcpy.Combine_sa()` |
| `vector/vectorize.py` | DONE | Replaces `arcpy.RasterToPolygon_conversion()` |
| `vector/eliminate.py` | DONE | Replaces `arcpy.management.Eliminate()` |
| `vector/simplify.py` | DONE | Replaces `arcpy.SimplifyPolygon()` |
| `experimental/edge_voting.py` | DONE | Temporal edge detection |
| `experimental/road_integration.py` | DONE | TIGER road rasterization |
| `experimental/naip_segmentation.py` | DONE | NAIP NDVI edge detection |
| `experimental/watershed.py` | DONE | Watershed segmentation |
| `db/schema.py` | DONE | DuckDB/GeoParquet schema |
| `db/duckdb_ops.py` | DONE | Spatial join, export functions |
| `pipeline/create.py` | DONE | Stage 1 orchestration |
| `pipeline/prep.py` | DONE | Stage 2 orchestration |
| `pipeline/distribute.py` | DONE | Stage 3 orchestration |
| `notebooks/01_explore_cdl.ipynb` | DONE | Data exploration notebook |

### Pending Tasks

| Task | Priority | Notes |
|------|----------|-------|
| Run full Tennessee baseline | HIGH | Need more memory or tiled processing |
| Test experimental track | MEDIUM | Requires TIGER roads data |
| Add TIGER road paths to config | MEDIUM | User has data locally |
| Validate against existing CSB | MEDIUM | Need reference data |
| Performance profiling | LOW | After validation |

---

## Data Paths

```
CDL 30m:  S:\_STAGING\01_RASTER_CORPUS\annual_cdl
          17 years (2008-2024): 2008_30m_cdls.tif ... 2024_30m_cdls.tif
CDL 10m:  S:\_STAGING\01_RASTER_CORPUS\annual_cdl_10m
          1 year (2024): 2024_10m_cdls.tif
NAIP TN:  S:\_STAGING\01_RASTER_CORPUS\naip_cog\Tennessee_Statewide
          6688 COG files
TIGER:    (need path from user)
```

---

## Architecture Overview

### Two Processing Tracks

1. **Baseline Track** (ArcGIS-compatible)
   - Combine CDL -> Vectorize -> Filter -> Eliminate -> Simplify
   - 60m simplification tolerance
   - Matches existing CSB output format

2. **Experimental Track** (Improved boundaries)
   - Temporal edge voting + NAIP edges + Roads
   - Watershed segmentation
   - 10m simplification tolerance
   - Three sub-approaches to compare

### Pipeline Stages

```
Stage 1: CREATE    CDL rasters -> CSB polygons
Stage 2: PREP      Add admin boundaries + crop attributes
Stage 3: DISTRIBUTE  Export by state (GPKG, SHP, TIF)
```

---

## Test Output Files

```
output/test/
├── test_combined.tif      # Combined 8-year CDL signatures
├── test_lookup.json       # Signature lookup table
├── test_vectorized.gpkg   # Initial vectorized polygons (13,194)
└── test_csb_final.gpkg    # Final CSB polygons (393)
```

---

## Key Files

| File | Purpose |
|------|---------|
| `csb-foss/pyproject.toml` | Project dependencies |
| `csb-foss/config/csb_foss.ini` | Runtime configuration |
| `csb-foss/src/csb_foss/pipeline/create.py` | Main entry point |
| `csb-foss/notebooks/01_explore_cdl.ipynb` | Data exploration |

---

## Recent Changes

### 2025-12-07 (Session 2)
- Installed dependencies successfully
- Fixed uint32 dtype issue in vectorization
- Fixed numpy import in simplify.py
- Tested full baseline pipeline on 5km West TN area
- All core modules working correctly

### 2025-12-07 (Session 1)
- Initial project creation
- All core modules implemented
- Baseline and experimental tracks defined
- Configuration with user's data paths
- Exploration notebook created

---

## Next Session Tasks

1. [x] Install dependencies: `pip install -e ".[notebooks]"`
2. [x] Test raster combine functionality
3. [x] Test vectorization and elimination
4. [x] Run full baseline pipeline on test area
5. [ ] Test experimental segmentation track
6. [ ] Run on larger Tennessee area
7. [ ] Compare output with existing CSB (if available)

---

## Notes

- Polygon elimination is working well - reduced 13K to 393 polygons
- NAIP is COG format - efficient for windowed reading
- Tennessee state FIPS = 47
- Target year range: 2017-2024 (8 years)
- CDL CRS: EPSG:5070 (Albers Equal Area Conic)
- Test area: West TN near Jackson (-88.82, 35.61) - agricultural area
