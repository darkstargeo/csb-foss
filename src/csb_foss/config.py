"""
Configuration management for CSB-FOSS.

Handles loading configuration from INI files and environment variables.
"""

import os
from configparser import ConfigParser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DataPaths:
    """Paths to input data sources."""

    cdl_30m: Path  # CDL 30m annual rasters
    cdl_10m: Optional[Path] = None  # CDL 10m (2024+)
    naip: Optional[Path] = None  # NAIP COG imagery
    tiger_roads: Optional[Path] = None  # TIGER/Line roads
    tiger_rails: Optional[Path] = None  # TIGER/Line railroads
    admin_boundaries: Optional[Path] = None  # ASD/County boundaries


@dataclass
class ProcessingParams:
    """Processing parameters."""

    # Year range
    start_year: int = 2017
    end_year: int = 2024

    # Polygon elimination thresholds (square meters)
    eliminate_thresholds: list[float] = field(
        default_factory=lambda: [100.0, 1000.0, 10000.0, 10000.0]
    )

    # Simplification tolerance (meters)
    simplify_tolerance: float = 60.0  # Baseline track
    simplify_tolerance_experimental: float = 10.0  # Experimental track

    # Crop filtering
    min_crop_years: int = 2  # COUNT0 - COUNT45 >= this
    min_area_single_year: float = 10000.0  # 1 hectare in sq meters

    # Road integration
    road_buffer: float = 15.0  # meters

    # Performance
    cpu_fraction: float = 0.97  # Fraction of CPUs to use
    tile_size: int = 100000  # Tile size in meters for large datasets
    tile_overlap: int = 1000  # Overlap between tiles


@dataclass
class OutputPaths:
    """Paths for output data."""

    base_dir: Path
    create_dir: Optional[Path] = None
    prep_dir: Optional[Path] = None
    distribute_dir: Optional[Path] = None
    logs_dir: Optional[Path] = None

    def __post_init__(self):
        """Set default subdirectories if not specified."""
        if self.create_dir is None:
            self.create_dir = self.base_dir / "create"
        if self.prep_dir is None:
            self.prep_dir = self.base_dir / "prep"
        if self.distribute_dir is None:
            self.distribute_dir = self.base_dir / "distribute"
        if self.logs_dir is None:
            self.logs_dir = self.base_dir / "logs"


@dataclass
class CSBConfig:
    """Complete CSB-FOSS configuration."""

    data: DataPaths
    params: ProcessingParams
    output: OutputPaths
    track: str = "baseline"  # 'baseline' or 'experimental'

    @classmethod
    def from_ini(cls, ini_path: Path) -> "CSBConfig":
        """Load configuration from INI file."""
        parser = ConfigParser()
        parser.read(ini_path)

        # Data paths
        data = DataPaths(
            cdl_30m=Path(parser.get("data", "cdl_30m")),
            cdl_10m=Path(parser.get("data", "cdl_10m", fallback="")) or None,
            naip=Path(parser.get("data", "naip", fallback="")) or None,
            tiger_roads=Path(parser.get("data", "tiger_roads", fallback="")) or None,
            tiger_rails=Path(parser.get("data", "tiger_rails", fallback="")) or None,
            admin_boundaries=Path(parser.get("data", "admin_boundaries", fallback="")) or None,
        )

        # Processing params
        params = ProcessingParams(
            start_year=parser.getint("params", "start_year", fallback=2017),
            end_year=parser.getint("params", "end_year", fallback=2024),
            simplify_tolerance=parser.getfloat("params", "simplify_tolerance", fallback=60.0),
            min_crop_years=parser.getint("params", "min_crop_years", fallback=2),
            cpu_fraction=parser.getfloat("params", "cpu_fraction", fallback=0.97),
        )

        # Output paths
        output = OutputPaths(
            base_dir=Path(parser.get("output", "base_dir")),
        )

        # Track selection
        track = parser.get("processing", "track", fallback="baseline")

        return cls(data=data, params=params, output=output, track=track)

    def ensure_directories(self):
        """Create output directories if they don't exist."""
        self.output.base_dir.mkdir(parents=True, exist_ok=True)
        self.output.create_dir.mkdir(parents=True, exist_ok=True)
        self.output.prep_dir.mkdir(parents=True, exist_ok=True)
        self.output.distribute_dir.mkdir(parents=True, exist_ok=True)
        self.output.logs_dir.mkdir(parents=True, exist_ok=True)


def load_config(config_path: Optional[Path] = None) -> CSBConfig:
    """
    Load configuration from file or environment.

    Args:
        config_path: Path to INI config file. If None, looks for:
            1. CSB_CONFIG environment variable
            2. ./config/csb_foss.ini
            3. ~/.csb_foss/config.ini

    Returns:
        CSBConfig instance
    """
    if config_path is None:
        # Check environment variable
        env_path = os.environ.get("CSB_CONFIG")
        if env_path:
            config_path = Path(env_path)
        # Check local config
        elif Path("config/csb_foss.ini").exists():
            config_path = Path("config/csb_foss.ini")
        # Check user config
        elif Path.home().joinpath(".csb_foss/config.ini").exists():
            config_path = Path.home() / ".csb_foss" / "config.ini"
        else:
            raise FileNotFoundError(
                "No configuration file found. Provide path or set CSB_CONFIG env var."
            )

    return CSBConfig.from_ini(config_path)
