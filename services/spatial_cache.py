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
_baseline_dict = {}

def _init_cache():
    global _ball_tree, _facility_coords, _baseline_dict
    if _ball_tree is not None:
        return

    if not PARQUET_PATH.exists():
        LOGGER.warning(f"Facility roster not found at {PARQUET_PATH}")
        return

    LOGGER.info("Loading facility roster into Pandas memory cache...")
    try:
        df = pd.read_parquet(PARQUET_PATH)
        df = df.drop_duplicates(subset=['lat_grid', 'lon_grid'])
        
        # 1. Build Historical Baseline Dictionary (for ML Inference)
        LOGGER.info(f"Building O(1) baseline dictionary for {len(df)} points...")
        # Keep only the columns needed by the ML model to save RAM
        ml_cols = ['lat_grid', 'lon_grid', 'normal_frp_median', 'frp_std_dev', 
                   'normal_t4_median', 't4_std_dev', 'max_frp_recorded', 
                   'total_passes', 'monsoon_ratio', 'night_ratio']
        
        # Round the grid to 3 decimal places to avoid floating point hash issues
        df['lat_grid'] = df['lat_grid'].round(3)
        df['lon_grid'] = df['lon_grid'].round(3)
        
        records = df[ml_cols].to_dict('records')
        _baseline_dict = {(r['lat_grid'], r['lon_grid']): r for r in records}
        
        # 2. Build BallTree for True Factories (for Spatial Distance)
        LOGGER.info("Filtering true factories for BallTree...")
        df_filtered = df[(df['total_passes'] >= 15) | (df['night_passes'] >= 5)].copy()
        
        _facility_coords = df_filtered[['lat_grid', 'lon_grid']].values
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
    if not _baseline_dict or not hotspots:
        return [{}] * len(hotspots)
        
    results = []
    for lat, lon in hotspots:
        # Snap live lat/lon to the nearest 0.005 degree grid
        lat_snap = round(round(lat / 0.005) * 0.005, 3)
        lon_snap = round(round(lon / 0.005) * 0.005, 3)
        
        baseline = _baseline_dict.get((lat_snap, lon_snap), {})
        results.append(baseline)
        
    return results

