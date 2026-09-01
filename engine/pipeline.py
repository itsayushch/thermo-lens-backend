import os
from pathlib import Path
import pandas as pd
import numpy as np
import netCDF4 as nc
from physics_pipeline import run_physics_pipeline
from inference import build_features, predict_hazards

def read_viirs_granule(file_path: str) -> pd.DataFrame:
    """Extracts raw fire pixels from a live VIIRS NetCDF/HDF5 granule."""
    file_path = str(file_path)
    ds = nc.Dataset(file_path, 'r')
    
    # Verify if active fire variables exist in this granule
    if 'FP_latitude' not in ds.variables or len(ds.variables['FP_latitude']) == 0:
        ds.close()
        return pd.DataFrame()

    lat = np.array(ds.variables['FP_latitude'][:], dtype=np.float32)
    lon = np.array(ds.variables['FP_longitude'][:], dtype=np.float32)
    t4 = np.array(ds.variables['FP_T4'][:], dtype=np.float32)
    power = np.array(ds.variables['FP_power'][:], dtype=np.float32)
    
    conf = np.array(ds.variables['FP_confidence'][:], dtype=np.float32) if 'FP_confidence' in ds.variables else np.full_like(lat, 50.0)
    mask = np.array(ds.variables['FP_fire_mask'][:], dtype=np.int32) if 'FP_fire_mask' in ds.variables else np.full_like(lat, 8, dtype=np.int32)
    
    ds.close()
    
    return pd.DataFrame({
        'latitude': lat,
        'longitude': lon,
        'fp_t4': t4,
        'fp_power': power,
        'fp_confidence': conf,
        'fire_mask_code': mask
    })

def process_granule(input_data, file_path: str, factory_roster_df: pd.DataFrame, booster):
    """
    THE FULL LIVE ENTRY POINT: raw .nc file -> physics layers -> baseline join -> ML -> JSON
    """
    file_path = str(file_path)
    
    # 1. Parse file path into a DataFrame if input is a path
    if isinstance(input_data, (str, Path)):
        df = read_viirs_granule(input_data)
    else:
        df = input_data.copy()

    if df.empty:
        print("No active thermal anomalies found in this granule.")
        return []

    # 2. Clean raw data through the 4 physics layers
    df = run_physics_pipeline(df, file_path)
    if df.empty:
        return []

    # 3. Map onto 500m grid to match your Parquet baseline
    df['lat_grid'] = ((df['latitude'] / 0.005).round() * 0.005).astype(np.float32)
    df['lon_grid'] = ((df['longitude'] / 0.005).round() * 0.005).astype(np.float32)
    
    # 4. Join with the 114MB Parquet baseline 
    df = pd.merge(df, factory_roster_df, on=['lat_grid', 'lon_grid'], how='left')
    
    # 5. Compute the exact 19 features
    model_input_df = build_features(df)
    
   # 6. Get final ML predictions
    results = predict_hazards(booster, model_input_df)
    
    # 7. Format the JSON exactly as promised to the backend
    # Merge the live coordinates and temperatures with the AI predictions
    output_df = df[['latitude', 'longitude', 'fp_t4', 'fp_power']].copy()
    output_df['hazard_type'] = [r['predicted_class'] for r in results]
    output_df['confidence_score'] = [r['confidence_score'] for r in results]
    
    # Generate the exact PostGIS primary key string (e.g., FAC_22.305_70.810)
    output_df['FAC_lat_lon'] = 'FAC_' + df['lat_grid'].apply(lambda x: f"{x:.3f}") + '_' + df['lon_grid'].apply(lambda x: f"{x:.3f}")
    
    # Reorder columns for a clean JSON output
    final_json_df = output_df[['FAC_lat_lon', 'latitude', 'longitude', 'fp_t4', 'fp_power', 'hazard_type', 'confidence_score']]
    
    return final_json_df.to_dict(orient='records')