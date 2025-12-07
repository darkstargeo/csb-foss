"""
DuckDB spatial operations for CSB-FOSS.

Provides efficient spatial joins, attribute calculations, and
data management using DuckDB with the spatial extension.
"""

from pathlib import Path
from typing import Optional

import duckdb


def create_csb_database(
    db_path: Optional[Path] = None,
    memory_limit: str = "8GB",
) -> duckdb.DuckDBPyConnection:
    """
    Create a DuckDB connection with spatial extension.

    Args:
        db_path: Path to database file (None for in-memory)
        memory_limit: Memory limit for DuckDB

    Returns:
        DuckDB connection
    """
    if db_path is not None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(db_path))
    else:
        con = duckdb.connect()

    # Configure
    con.execute(f"SET memory_limit = '{memory_limit}'")

    # Load spatial extension
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")

    return con


def load_geoparquet(
    con: duckdb.DuckDBPyConnection,
    parquet_path: Path,
    table_name: str = "csb_polygons",
) -> None:
    """
    Load GeoParquet file into DuckDB table.

    Args:
        con: DuckDB connection
        parquet_path: Path to GeoParquet file
        table_name: Name for the table
    """
    con.execute(f"""
        CREATE OR REPLACE TABLE {table_name} AS
        SELECT * FROM ST_Read('{parquet_path}')
    """)


def load_geopandas(
    con: duckdb.DuckDBPyConnection,
    gdf,
    table_name: str = "csb_polygons",
) -> None:
    """
    Load GeoDataFrame into DuckDB table.

    Args:
        con: DuckDB connection
        gdf: GeoDataFrame
        table_name: Name for the table
    """
    # Convert to WKB for geometry
    import geopandas as gpd

    df = gdf.copy()
    df["geometry"] = df.geometry.apply(lambda g: g.wkb)

    con.execute(f"""
        CREATE OR REPLACE TABLE {table_name} AS
        SELECT *, ST_GeomFromWKB(geometry) as geom
        FROM df
    """)


def spatial_join_largest_overlap(
    con: duckdb.DuckDBPyConnection,
    polygons_table: str,
    admin_table: str,
    output_table: str,
    join_fields: list[str],
) -> None:
    """
    Perform spatial join with LARGEST_OVERLAP match option.

    Assigns each polygon to the admin unit with greatest intersection area.

    Args:
        con: DuckDB connection
        polygons_table: Name of polygon table
        admin_table: Name of admin boundary table
        output_table: Name for output table
        join_fields: Fields to join from admin table
    """
    fields_select = ", ".join([f"a.{f}" for f in join_fields])

    con.execute(f"""
        CREATE OR REPLACE TABLE {output_table} AS
        WITH overlap_areas AS (
            SELECT
                p.*,
                {fields_select},
                ST_Area(ST_Intersection(p.geometry, a.geometry)) as overlap_area
            FROM {polygons_table} p
            JOIN {admin_table} a
                ON ST_Intersects(p.geometry, a.geometry)
        ),
        ranked_overlaps AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY gridcode
                    ORDER BY overlap_area DESC
                ) as rn
            FROM overlap_areas
        )
        SELECT * EXCLUDE (rn, overlap_area)
        FROM ranked_overlaps
        WHERE rn = 1
    """)


def calculate_csb_fields(
    con: duckdb.DuckDBPyConnection,
    table_name: str,
    start_year: int,
    end_year: int,
) -> None:
    """
    Calculate derived CSB fields.

    Args:
        con: DuckDB connection
        table_name: Table to update
        start_year: First year of analysis
        end_year: Last year of analysis
    """
    # Calculate acres (area in sq meters / 4046.86)
    con.execute(f"""
        ALTER TABLE {table_name}
        ADD COLUMN IF NOT EXISTS csb_acres DOUBLE
    """)

    con.execute(f"""
        UPDATE {table_name}
        SET csb_acres = ST_Area(geometry) / 4046.86
    """)

    # Calculate centroid coordinates
    con.execute(f"""
        ALTER TABLE {table_name}
        ADD COLUMN IF NOT EXISTS inside_x DOUBLE
    """)

    con.execute(f"""
        ALTER TABLE {table_name}
        ADD COLUMN IF NOT EXISTS inside_y DOUBLE
    """)

    con.execute(f"""
        UPDATE {table_name}
        SET
            inside_x = ST_X(ST_Centroid(geometry)),
            inside_y = ST_Y(ST_Centroid(geometry))
    """)

    # Set CSB years
    years_str = f"{start_year % 100:02d}{end_year % 100:02d}"
    con.execute(f"""
        ALTER TABLE {table_name}
        ADD COLUMN IF NOT EXISTS csb_years VARCHAR(4)
    """)

    con.execute(f"""
        UPDATE {table_name}
        SET csb_years = '{years_str}'
    """)


def generate_csb_id(
    con: duckdb.DuckDBPyConnection,
    table_name: str,
) -> None:
    """
    Generate unique CSBID for each polygon.

    CSBID format: STATEFIPS + CSBYEARS + 9-digit sequence number

    Args:
        con: DuckDB connection
        table_name: Table to update
    """
    con.execute(f"""
        ALTER TABLE {table_name}
        ADD COLUMN IF NOT EXISTS csb_id VARCHAR(15)
    """)

    con.execute(f"""
        UPDATE {table_name}
        SET csb_id = state_fips || csb_years || LPAD(CAST(rowid AS VARCHAR), 9, '0')
    """)


def export_by_state(
    con: duckdb.DuckDBPyConnection,
    table_name: str,
    output_dir: Path,
    state_fips: Optional[str] = None,
    format: str = "geoparquet",
) -> list[Path]:
    """
    Export data partitioned by state.

    Args:
        con: DuckDB connection
        table_name: Source table
        output_dir: Output directory
        state_fips: Optional single state to export (exports all if None)
        format: Output format ("geoparquet" or "geojson")

    Returns:
        List of output file paths
    """
    from .schema import FIPS_TO_STATE

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []

    if state_fips is not None:
        states = [(state_fips, FIPS_TO_STATE.get(state_fips, state_fips))]
    else:
        # Get all states in data
        result = con.execute(f"""
            SELECT DISTINCT state_fips FROM {table_name}
            WHERE state_fips IS NOT NULL
        """).fetchall()
        states = [(row[0], FIPS_TO_STATE.get(row[0], row[0])) for row in result]

    for fips, abbrev in states:
        if format == "geoparquet":
            output_path = output_dir / f"CSB{abbrev}.parquet"
            con.execute(f"""
                COPY (
                    SELECT * FROM {table_name}
                    WHERE state_fips = '{fips}'
                ) TO '{output_path}' (FORMAT PARQUET)
            """)
        else:
            output_path = output_dir / f"CSB{abbrev}.geojson"
            con.execute(f"""
                COPY (
                    SELECT * FROM {table_name}
                    WHERE state_fips = '{fips}'
                ) TO '{output_path}' (FORMAT JSON)
            """)

        outputs.append(output_path)

    return outputs


def merge_tables(
    con: duckdb.DuckDBPyConnection,
    input_tables: list[str],
    output_table: str,
) -> None:
    """
    Merge multiple tables into one.

    Args:
        con: DuckDB connection
        input_tables: List of table names to merge
        output_table: Output table name
    """
    union_query = " UNION ALL ".join([f"SELECT * FROM {t}" for t in input_tables])

    con.execute(f"""
        CREATE OR REPLACE TABLE {output_table} AS
        {union_query}
    """)


def get_table_stats(
    con: duckdb.DuckDBPyConnection,
    table_name: str,
) -> dict:
    """
    Get statistics for a table.

    Args:
        con: DuckDB connection
        table_name: Table name

    Returns:
        Dictionary of statistics
    """
    count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

    total_area = con.execute(f"""
        SELECT SUM(ST_Area(geometry)) FROM {table_name}
    """).fetchone()[0]

    states = con.execute(f"""
        SELECT DISTINCT state_fips FROM {table_name}
        WHERE state_fips IS NOT NULL
    """).fetchall()

    return {
        "polygon_count": count,
        "total_area_sqm": total_area,
        "total_area_acres": total_area / 4046.86 if total_area else 0,
        "states": [row[0] for row in states],
    }
