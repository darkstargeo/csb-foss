# CSB-FOSS Project Status

**Last Updated**: 2025-12-08
**Project Phase**: Full Tennessee Processing In Progress
**Repository**: https://github.com/darkstargeo/csb-foss

---

## Current State

### Test Results (2025-12-07)

| Test | Status | Notes |
|------|--------|-------|
| Module imports | PASS | All core modules import successfully |
| Data path access | PASS | CDL 30m (17 years), 10m (1 year), NAIP (6688 files) |
| Config loading | PASS | INI parsing and directory creation working |
| TIGER road loading | PASS | GDB format supported, 593 roads in test area |
| Raster combine | PASS | 8-year stack, 64K unique signatures (25km area) |
| Vectorization | PASS | 392,827 initial polygons from 25km area |
| Elimination | PASS | Reduced to 13,240 polygons (tiered: 100/1000/10000 m²) |
| Simplification | PASS | 60m tolerance applied, topology preserved |
| Road mask creation | PASS | 15m buffer, 20% coverage in test area |
| Temporal edge voting | PASS | 8 years, edges detected correctly |
| Watershed segmentation | PASS | 44 segments from 5km test area |

### Pipeline Test Results

| Test | Area | Input | Output | Time |
|------|------|-------|--------|------|
| 5km baseline | West TN | 2,858 sigs | 393 polygons | ~30s |
| 25km baseline | West TN | 64,199 sigs | 13,240 polygons | ~10min |
| 5km experimental | West TN | Edge+Roads | 44 segments | ~5s |
| 5-tile tiled (20km) | SW TN | 5 tiles | 8,385 polygons | 3:38 |
| Full TN (546 tiles) | Full State | IN PROGRESS | ~34s/tile | ~5hrs |

### Bug Fixes Applied

| Issue | Fix | File |
|-------|-----|------|
| `shapes()` dtype error | Cast uint32 to int32 | `vector/vectorize.py` |
| numpy import order | Moved import to top | `vector/simplify.py` |
| GDB layer auto-detect | Added fiona layer detection | `experimental/road_integration.py` |

---

## Data Paths (Configured)

```
CDL 30m:  /path/to/annual_cdl
          17 years (2008-2024): 2008_30m_cdls.tif ... 2024_30m_cdls.tif
CDL 10m:  /path/to/annual_cdl_10m
          1 year (2024): 2024_10m_cdls.tif
NAIP:     /path/to/naip_cog
          COG format files
TIGER:    /path/to/tigerline_2024
          Roads and Rails geodatabases
```

---

## Architecture Overview

### Two Processing Tracks

1. **Baseline Track** (ArcGIS-compatible) - TESTED
   - Combine CDL -> Vectorize -> Filter -> Eliminate -> Simplify
   - 60m simplification tolerance
   - Matches existing CSB output format

2. **Experimental Track** (Improved boundaries) - TESTED
   - Temporal edge voting + Road mask + Watershed segmentation
   - 10m simplification tolerance
   - Road integration as hard boundaries

### Pipeline Stages

```
Stage 1: CREATE    CDL rasters -> CSB polygons
Stage 2: PREP      Add admin boundaries + crop attributes
Stage 3: DISTRIBUTE  Export by state (GPKG, SHP, TIF)
```

---

## Test Output Files

```
output/test/                     # 5km baseline test
├── test_combined.tif
├── test_lookup.json
├── test_vectorized.gpkg
└── test_csb_final.gpkg         # 393 polygons

output/tn_test/                  # 25km baseline test
├── tn_combined.tif
├── tn_lookup.json
└── tn_csb_25km.gpkg            # 13,240 polygons, 591.8 km²

output/experimental/             # 5km experimental test
├── reference.tif
├── road_mask.tif               # 20.2% road coverage
├── edge_votes.tif              # Temporal edges
├── combined_edges.tif          # Edge + road combined
├── segment_labels.tif          # Watershed labels
└── experimental_segments.gpkg  # 44 segments
```

---

## Completed Components

| Component | Status | Notes |
|-----------|--------|-------|
| Project Structure | DONE | All directories created |
| `pyproject.toml` | DONE | Dependencies installed |
| `config/csb_foss.ini` | DONE | All paths configured |
| `raster/io.py` | DONE | CDL reading, windowing |
| `raster/combine.py` | DONE | Replaces `arcpy.Combine_sa()` |
| `vector/vectorize.py` | DONE | Replaces `arcpy.RasterToPolygon_conversion()` |
| `vector/eliminate.py` | DONE | Replaces `arcpy.management.Eliminate()` |
| `vector/simplify.py` | DONE | Replaces `arcpy.SimplifyPolygon()` |
| `experimental/edge_voting.py` | DONE | Temporal edge detection |
| `experimental/road_integration.py` | DONE | TIGER GDB support |
| `experimental/naip_segmentation.py` | DONE | NAIP NDVI edges |
| `experimental/watershed.py` | DONE | Watershed segmentation |
| `db/schema.py` | DONE | DuckDB/GeoParquet schema |
| `db/duckdb_ops.py` | DONE | Spatial operations |
| `pipeline/create.py` | DONE | Stage 1 orchestration |
| `pipeline/prep.py` | DONE | Stage 2 orchestration |
| `pipeline/distribute.py` | DONE | Stage 3 orchestration |
| `pipeline/tiled_create.py` | DONE | Tiled state processing |
| `vector/eliminate_fast.py` | DONE | Parallel elimination with joblib |

---

## Official CSB Comparison (2017-2024)

| Metric | Official CSB | FOSS (5-tile test) | Notes |
|--------|-------------|-------------------|-------|
| TN polygons | 507,991 | 8,385 (partial) | Full TN in progress |
| TN area | 37,464 km² | 1,858 km² | 5 tiles only |
| Mean polygon | 73,748 m² | 221,569 m² | Different filtering |
| Median polygon | 27,151 m² | 13,500 m² | |
| CDL years | 2017-2024 | 2017-2024 | Same period |
| Unique crops | 62-76/year | TBD | |

---

## Pending Tasks

| Task | Priority | Notes |
|------|----------|-------|
| Complete full TN baseline | HIGH | 546 tiles, ~5 hours total |
| Compare FOSS vs official CSB | HIGH | Official CSB extracted |
| Refine crop filtering | MEDIUM | Match official CSB criteria |
| Performance optimization | LOW | eliminate_fast helps |

---

## Recent Changes

### 2025-12-08 (Session 3)
- Downloaded official CSB-2024 (3.4GB, 507K TN polygons)
- Created tiled_create.py for state-level processing
- Created eliminate_fast.py with parallel joblib processing
- Tested 5-tile processing: 8,385 polygons, 1,858 km²
- Started full Tennessee processing: 546 tiles, ~5 hours
- Initial FOSS vs official CSB comparison

### 2025-12-07 (Session 2 - continued)
- Added TIGER road geodatabase support
- Updated config with TIGER paths
- Tested 25km baseline pipeline (13,240 polygons)
- Tested experimental track with road integration
- Tested watershed segmentation (44 segments)
- All pipeline components working

### 2025-12-07 (Session 2 - start)
- Installed dependencies successfully
- Fixed uint32 dtype issue in vectorization
- Fixed numpy import in simplify.py
- Tested 5km baseline pipeline (393 polygons)

### 2025-12-07 (Session 1)
- Initial project creation
- All core modules implemented

---

## Next Steps

1. [ ] Run full Tennessee baseline (tiled processing)
2. [ ] Compare output with official CSB-2024
3. [ ] Test NAIP edge detection module
4. [ ] Run experimental track on larger area
5. [ ] Performance profiling and optimization
6. [ ] Documentation improvements

---

## Notes

- Polygon elimination is the bottleneck for large areas (O(n²) neighbor search)
- TIGER roads are in WGS84 (EPSG:4269), reprojected on-the-fly to EPSG:5070
- Watershed segmentation produces cleaner boundaries than raster vectorization
- Road mask covers 20% of test area - significant boundary constraint
- Tennessee state FIPS = 47
- CDL CRS: EPSG:5070 (Albers Equal Area Conic)
