"""
Database schema definitions for CSB-FOSS.

Defines the GeoParquet and DuckDB table schemas for CSB polygons.
"""

# CSB polygon schema for DuckDB/GeoParquet
CSB_SCHEMA = """
CREATE TABLE IF NOT EXISTS csb_polygons (
    -- Unique identifiers
    csb_id          VARCHAR(15),
    csb_years       VARCHAR(4),

    -- Geometry (stored as WKB in GeoParquet)
    geometry        GEOMETRY,

    -- Area and centroid
    csb_acres       DOUBLE,
    shape_area      DOUBLE,
    inside_x        DOUBLE,
    inside_y        DOUBLE,

    -- Crop sequence (populated during prep)
    cdl_2017        INTEGER,
    cdl_2018        INTEGER,
    cdl_2019        INTEGER,
    cdl_2020        INTEGER,
    cdl_2021        INTEGER,
    cdl_2022        INTEGER,
    cdl_2023        INTEGER,
    cdl_2024        INTEGER,

    -- Crop counts
    count0          SMALLINT,
    count45         SMALLINT,

    -- Administrative boundaries
    state_fips      VARCHAR(2),
    state_asd       VARCHAR(10),
    asd             VARCHAR(2),
    county          VARCHAR(21),
    county_fips     VARCHAR(3),

    -- Processing metadata
    tile_id         VARCHAR(20),
    gridcode        INTEGER
);
"""

# Column order for final output (matching existing CSB format)
CSB_OUTPUT_COLUMNS = [
    "csb_id",
    "csb_years",
    "csb_acres",
    "cdl_2017",
    "cdl_2018",
    "cdl_2019",
    "cdl_2020",
    "cdl_2021",
    "cdl_2022",
    "cdl_2023",
    "cdl_2024",
    "state_fips",
    "state_asd",
    "asd",
    "county",
    "county_fips",
    "shape_area",
    "inside_x",
    "inside_y",
    "geometry",
]


def create_csb_table(con, table_name: str = "csb_polygons") -> None:
    """
    Create CSB table in DuckDB connection.

    Args:
        con: DuckDB connection
        table_name: Name for the table
    """
    schema = CSB_SCHEMA.replace("csb_polygons", table_name)
    con.execute(schema)


def get_year_columns(start_year: int, end_year: int) -> list[str]:
    """
    Get list of CDL year column names.

    Args:
        start_year: First year
        end_year: Last year (inclusive)

    Returns:
        List of column names like ['cdl_2017', 'cdl_2018', ...]
    """
    return [f"cdl_{year}" for year in range(start_year, end_year + 1)]


# State FIPS codes for distribution
STATE_FIPS = {
    "AL": "01", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
    "CT": "09", "DE": "10", "FL": "12", "GA": "13", "ID": "16",
    "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26",
    "MN": "27", "MS": "28", "MO": "29", "MT": "30", "NE": "31",
    "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36",
    "NC": "37", "ND": "38", "OH": "39", "OK": "40", "OR": "41",
    "PA": "42", "RI": "44", "SC": "45", "SD": "46", "TN": "47",
    "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56",
}

FIPS_TO_STATE = {v: k for k, v in STATE_FIPS.items()}
