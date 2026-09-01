import xgboost as xgb
import numpy as np
import pandas as pd

MODEL_PATH = "engine/classification/industrial_hazard_xgboost_master.json"

# EXACT 19-feature order
FEATURE_COLS = [
    'fp_power', 'fp_t4', 'log_fp_power', 'thermal_contrast',
    'normal_frp_median', 'frp_std_dev', 'normal_t4_median', 't4_std_dev',
    'frp_to_median_ratio', 't4_delta_median', 'max_frp_recorded',
    'pixel_area', 'frp_density', 'confidence_num',
    'total_passes', 'monsoon_ratio', 'night_ratio',
    'sin_month', 'cos_month'
]

CLASS_NAMES = [
    'Background Noise', 'Agricultural Burn', 'Wildfire',
    'Industrial/Flare', 'Mining/Kiln', 'Industrial Hazard'
]

def load_model(path=MODEL_PATH):
    booster = xgb.Booster()
    booster.load_model(path)
    return booster

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Computes derived physics and temporal features with safe defaults."""
    # Ensure all required baseline/sensor columns exist
    defaults = {
        'normal_frp_median': 0.0, 'frp_std_dev': 1.0, 
        'normal_t4_median': 0.0, 't4_std_dev': 1.0,
        'max_frp_recorded': 0.0, 'total_passes': 0.0,
        'monsoon_ratio': 0.0, 'night_ratio': 0.0,
        'pixel_area': 1.0, 'confidence_num': 50.0,
        'fp_power': 0.0, 'fp_t4': 300.0
    }
    
    for col, default_val in defaults.items():
        if col not in df.columns:
            df[col] = default_val
        else:
            df[col] = df[col].fillna(default_val)
    
    # Physics features
    df['log_fp_power'] = np.log1p(df['fp_power'])
    df['thermal_contrast'] = df['fp_t4'] - df['normal_t4_median'] 
    df['t4_delta_median'] = df['fp_t4'] - df['normal_t4_median']
    df['frp_to_median_ratio'] = df['fp_power'] / (df['normal_frp_median'] + 1e-5)
    df['frp_density'] = df['fp_power'] / (df['pixel_area'] + 1e-5)
    
    # Temporal features
    month = pd.to_datetime(df['acq_date']).dt.month
    df['sin_month'] = np.sin(2 * np.pi * month / 12.0)
    df['cos_month'] = np.cos(2 * np.pi * month / 12.0)
    
    return df[FEATURE_COLS]

def predict_hazards(booster, features_df: pd.DataFrame):
    X = features_df[FEATURE_COLS].to_numpy(dtype=np.float32)
    dmatrix = xgb.DMatrix(X, feature_names=FEATURE_COLS)
    
    probs = booster.predict(dmatrix)
    pred_idx = np.argmax(probs, axis=1)

    results = []
    for i in range(len(pred_idx)):
        results.append({
            "predicted_class": CLASS_NAMES[pred_idx[i]],
            "confidence_score": float(probs[i][pred_idx[i]] * 100)
        })
    return results