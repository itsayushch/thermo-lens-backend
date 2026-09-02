import logging
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

LOGGER = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PARQUET_PATH = DATA_DIR / "factory_roster_2yr.parquet"

_ball_tree = None
_facility_coords = None
_baseline_df = None

def _init_cache():
    global _ball_tree, _facility_coords, _baseline_df
    if _ball_tree is not None:
        return

    if not PARQUET_PATH.exists():
        LOGGER.warning(f"Facility roster not found at {PARQUET_PATH}")
        return

    LOGGER.info("Loading facility roster into Pandas memory cache...")
    try:
        df = pd.read_parquet(PARQUET_PATH)
        df = df.drop_duplicates(subset=['lat_grid', 'lon_grid'])
        
        # 1. Build Historical Baseline (for ML Inference)
        LOGGER.info(f"Building memory-optimized baseline index for {len(df)} points...")
        # Keep only the columns needed by the ML model to save RAM
        ml_cols = ['lat_grid', 'lon_grid', 'normal_frp_median', 'frp_std_dev', 
                   'normal_t4_median', 't4_std_dev', 'max_frp_recorded', 
                   'total_passes', 'monsoon_ratio', 'night_ratio']

        required_cols = set(ml_cols) | {'night_passes'}
        missing_cols = required_cols.difference(df.columns)
        if missing_cols:
            raise ValueError(
                f"Facility roster is missing required columns: {sorted(missing_cols)}"
            )

        # Derive facility coordinates before reducing the dataframe to ML columns.
        facility_df = df[
            (df['total_passes'] >= 15) | (df['night_passes'] >= 5)
        ]
        
        df = df[ml_cols].copy()
        
        # Downcast to float32 to drastically reduce RAM usage (so it fits in Render 512MB Free Tier)
        for col in ml_cols:
            if df[col].dtype == 'float64':
                df[col] = df[col].astype('float32')
        
        # Round the grid to 3 decimal places to avoid floating point hash issues
        df['lat_grid'] = df['lat_grid'].round(3)
        df['lon_grid'] = df['lon_grid'].round(3)
        
        # Store as a multi-index DataFrame instead of 4.9M Python dictionaries
        global _baseline_df
        _baseline_df = df.set_index(['lat_grid', 'lon_grid'])
        
        # 2. Build BallTree for True Factories (for Spatial Distance)
        LOGGER.info("Filtering true factories for BallTree...")
        _facility_coords = facility_df[['lat_grid', 'lon_grid']].values
        coords_rad = np.radians(_facility_coords)
        
        LOGGER.info(f"Building BallTree for {len(_facility_coords)} facility locations...")
        _ball_tree = BallTree(coords_rad, metric='haversine')
        LOGGER.info("Spatial cache initialization complete.")
    except Exception as e:
        LOGGER.error(f"Failed to initialize spatial cache: {e}", exc_info=True)

def get_nearest_facility_distances(hotspots: list[tuple[float, float]]) -> list[float | None]:
    """
    Given a list of (lat, lon) tuples, returns the distance to the nearest true facility in meters.
    """
    _init_cache()
    if _ball_tree is None or not hotspots:
        return [None] * len(hotspots)

    query_rad = np.radians(hotspots)
    distances_rad, _ = _ball_tree.query(query_rad, k=1)
    EARTH_RADIUS_M = 6371000.0
    distances_m = distances_rad.flatten() * EARTH_RADIUS_M
    return [round(d, 2) for d in distances_m]

def get_historical_baselines(hotspots: list[tuple[float, float]]) -> list[dict]:
    """
    Given a list of (lat, lon) tuples, returns the historical baseline dict for each point.
    """
    _init_cache()
    global _baseline_df
    if _baseline_df is None or _baseline_df.empty or not hotspots:
        return [{}] * len(hotspots)
        
    results = []
    for lat, lon in hotspots:
        # Snap live lat/lon to the nearest 0.005 degree grid
        lat_snap = round(round(lat / 0.005) * 0.005, 3)
        lon_snap = round(round(lon / 0.005) * 0.005, 3)
        
        try:
            # Pandas .loc returns a Series which we convert to dict
            row = _baseline_df.loc[(lat_snap, lon_snap)]
            # If multiple duplicates exist somehow, take the first
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            results.append(row.to_dict())
        except KeyError:
            results.append({})
        
    return results
