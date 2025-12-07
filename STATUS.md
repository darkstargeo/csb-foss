# CSB-FOSS Project Status

**Last Updated**: 2025-12-07
**Project Phase**: Initial Implementation Complete
**Repository**: New standalone repo recommended (separate from ArcGIS fork)

---

## Current State

### Completed Components

| Component | Status | Notes |
|-----------|--------|-------|
| Project Structure | ✅ Complete | All directories and `__init__.py` files created |
| `pyproject.toml` | ✅ Complete | Dependencies defined, ready for `pip install -e .` |
| `config/csb_foss.ini` | ✅ Complete | Configured with user's data paths |
| `raster/io.py` | ✅ Complete | CDL reading, windowing, multi-year stacking |
| `raster/combine.py` | ✅ Complete | Replaces `arcpy.Combine_sa()` |
| `vector/vectorize.py` | ✅ Complete | Replaces `arcpy.RasterToPolygon_conversion()` |
| `vector/eliminate.py` | ✅ Complete | Replaces `arcpy.management.Eliminate()` |
| `vector/simplify.py` | ✅ Complete | Replaces `arcpy.SimplifyPolygon()` |
| `experimental/edge_voting.py` | ✅ Complete | Temporal edge detection |
| `experimental/road_integration.py` | ✅ Complete | TIGER road rasterization |
| `experimental/naip_segmentation.py` | ✅ Complete | NAIP NDVI edge detection |
| `experimental/watershed.py` | ✅ Complete | Watershed segmentation |
| `db/schema.py` | ✅ Complete | DuckDB/GeoParquet schema |
| `db/duckdb_ops.py` | ✅ Complete | Spatial join, export functions |
| `pipeline/create.py` | ✅ Complete | Stage 1 orchestration |
| `pipeline/prep.py` | ✅ Complete | Stage 2 orchestration |
| `pipeline/distribute.py` | ✅ Complete | Stage 3 orchestration |
| `notebooks/01_explore_cdl.ipynb` | ✅ Complete | Data exploration notebook |

### Pending Tasks

| Task | Priority | Notes |
|------|----------|-------|
| Install and test dependencies | HIGH | Run `pip install -e ".[notebooks]"` |
| Test baseline pipeline on Tennessee | HIGH | Small area first |
| Validate against existing CSB output | HIGH | Need reference data |
| Test experimental segmentation | MEDIUM | Compare 3 approaches |
| Add TIGER road paths to config | MEDIUM | User has data locally |
| Performance profiling | LOW | After validation |
| Scale to full Tennessee | LOW | After validation |

---

## Data Paths

```
CDL 30m:  S:\_STAGING\01_RASTER_CORPUS\annual_cdl
CDL 10m:  S:\_STAGING\01_RASTER_CORPUS\annual_cdl_10m
NAIP TN:  S:\_STAGING\01_RASTER_CORPUS\naip_cog\Tennessee_Statewide
TIGER:    (need path from user)
```

---

## Architecture Overview

### Two Processing Tracks

1. **Baseline Track** (ArcGIS-compatible)
   - Combine CDL → Vectorize → Eliminate → Simplify
   - 60m simplification tolerance
   - Matches existing CSB output format

2. **Experimental Track** (Improved boundaries)
   - Temporal edge voting + NAIP edges + Roads
   - Watershed segmentation
   - 10m simplification tolerance
   - Three sub-approaches to compare

### Pipeline Stages

```
Stage 1: CREATE    CDL rasters → CSB polygons
Stage 2: PREP      Add admin boundaries + crop attributes
Stage 3: DISTRIBUTE  Export by state (GPKG, SHP, TIF)
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

### 2025-12-07
- Initial project creation
- All core modules implemented
- Baseline and experimental tracks defined
- Configuration with user's data paths
- Exploration notebook created

---

## Next Session Tasks

1. [ ] Install dependencies: `pip install -e ".[notebooks]"`
2. [ ] Run exploration notebook to verify data access
3. [ ] Test `combine_cdl_rasters` on small Tennessee area
4. [ ] Test `vectorize_raster` and `eliminate_small_polygons`
5. [ ] Run full baseline pipeline on test area
6. [ ] Compare output with existing CSB (if available)

---

## Notes

- Polygon elimination is the most complex algorithm - may need tuning
- NAIP is COG format - efficient for windowed reading
- Tennessee state FIPS = 47
- Target year range: 2017-2024 (8 years)
