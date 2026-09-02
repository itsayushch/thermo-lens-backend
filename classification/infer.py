import json
import logging
from pathlib import Path
from typing import Any, Final
import numpy as np
import pandas as pd
import xgboost as xgb

LOGGER = logging.getLogger(__name__)

# Core Model Paths
CLASSIFICATION_DIR = Path(__file__).resolve().parent
MODEL_PATH = CLASSIFICATION_DIR / "industrial_hazard_xgboost_master.json"

FEATURE_COLS = [
    'fp_power', 'fp_t4', 'log_fp_power', 'thermal_contrast',
    'normal_frp_median', 'frp_std_dev', 'normal_t4_median', 't4_std_dev',
    'frp_to_median_ratio', 't4_delta_median', 'max_frp_recorded',
    'pixel_area', 'frp_density', 'confidence_num',
    'total_passes', 'monsoon_ratio', 'night_ratio',
    'sin_month', 'cos_month'
]

ML_CLASS_NAMES = [
    'Background Noise', 'Agricultural Burn', 'Wildfire',
    'Industrial/Flare', 'Mining/Kiln', 'Industrial Hazard'
]

# Map ML names to our API expected schemas
CLASS_MAP = {
    'Background Noise': 'unknown',
    'Agricultural Burn': 'agricultural_burn',
    'Wildfire': 'wildfire',
    'Industrial/Flare': 'industrial',
    'Mining/Kiln': 'industrial',
    'Industrial Hazard': 'abnormal_industrial'
}

DEFAULT_BASELINE_FRP: Final[float] = 35.0

def _load_model() -> Any | None:
    """Load the xgboost json model without making app startup fragile."""
    try:
        if not MODEL_PATH.exists():
            LOGGER.warning("ThermoLens xgboost artifact missing: %s", MODEL_PATH)
            return None
        booster = xgb.Booster()
        booster.load_model(str(MODEL_PATH))
        LOGGER.info("Successfully loaded XGBoost ML model from %s", MODEL_PATH)
        return booster
    except Exception:
        LOGGER.exception("Failed to load ThermoLens XGBoost from %s", MODEL_PATH)
        return None

MODEL: Final[Any | None] = _load_model()

def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))

def calculate_severity_score(
    frp: float,
    baseline_frp: float,
    distance_m: float,
    confidence_num: float,
    persistence_days: int,
) -> int:
    safe_baseline = max(float(baseline_frp), 1.0)
    spike_ratio = max(float(frp), 0.0) / safe_baseline

    frp_spike_component = _clamp(spike_ratio / 3.0, 0.0, 1.0) * 40.0
    proximity_component = _clamp(1.0 - (max(float(distance_m), 0.0) / 1000.0), 0.0, 1.0) * 30.0
    confidence_component = _clamp(float(confidence_num), 0.0, 100.0) / 100.0 * 20.0
    persistence_component = _clamp(float(persistence_days) / 5.0, 0.0, 1.0) * 10.0

    return int(round(frp_spike_component + proximity_component + confidence_component + persistence_component))

def _fallback_classification(hotspot: dict[str, Any]) -> tuple[str, float]:
    """Deterministic fallback if ML model is missing."""
    distance_m = hotspot.get("distance_to_facility_m", 10_000.0)
    frp = hotspot.get("frp", 0.0)
    brightness = hotspot.get("brightness", 0.0)

    if distance_m <= 500.0 and frp >= 25.0:
        return "industrial", 0.55
    if distance_m <= 1200.0 and 8.0 <= frp <= 70.0 and brightness >= 330.0:
        return "gas_flare", 0.50
    if frp >= 80.0 or brightness >= 360.0:
        return "wildfire", 0.55
    return "agricultural_burn", 0.50

def build_features(hotspot: dict[str, Any]) -> pd.DataFrame:
    baseline = hotspot.get("baseline", {})
    
    # 1. Start with defaults
    df_dict = {
        'normal_frp_median': 0.0, 'frp_std_dev': 1.0, 
        'normal_t4_median': 0.0, 't4_std_dev': 1.0,
        'max_frp_recorded': 0.0, 'total_passes': 0.0,
        'monsoon_ratio': 0.0, 'night_ratio': 0.0,
        'pixel_area': 1.0, 'confidence_num': 50.0,
        'fp_power': 0.0, 'fp_t4': 300.0
    }
    
    # 2. Override with live hotspot data
    df_dict['fp_power'] = hotspot.get("frp", 0.0)
    df_dict['fp_t4'] = hotspot.get("brightness", 300.0)
    df_dict['confidence_num'] = hotspot.get("confidence_num", 50.0)
    
    # 3. Override with historical baseline data
    for k in df_dict.keys():
        if k in baseline and pd.notnull(baseline[k]):
            df_dict[k] = baseline[k]
            
    df = pd.DataFrame([df_dict])
    
    # 4. Calculate Physics Features
    df['log_fp_power'] = np.log1p(df['fp_power'])
    df['thermal_contrast'] = df['fp_t4'] - df['normal_t4_median'] 
    df['t4_delta_median'] = df['fp_t4'] - df['normal_t4_median']
    df['frp_to_median_ratio'] = df['fp_power'] / (df['normal_frp_median'] + 1e-5)
    df['frp_density'] = df['fp_power'] / (df['pixel_area'] + 1e-5)
    
    # 5. Calculate Temporal Features
    acq_date = hotspot.get("acq_date")
    if acq_date:
        month = acq_date.month
    else:
        month = 1
    df['sin_month'] = np.sin(2 * np.pi * month / 12.0)
    df['cos_month'] = np.cos(2 * np.pi * month / 12.0)
    
    return df[FEATURE_COLS]

def predict_hotspot(hotspot: dict[str, Any]) -> dict[str, Any]:
    frp = hotspot.get("frp", 0.0)
    baseline_dict = hotspot.get("baseline", {})
    baseline_frp = max(baseline_dict.get("normal_frp_median", DEFAULT_BASELINE_FRP), 1.0)
    distance_m = hotspot.get("distance_to_facility_m", 10_000.0)
    confidence_num = hotspot.get("confidence_num", 0.0)
    persistence_days = hotspot.get("persistence_days", 1)
    brightness = hotspot.get("brightness", 0.0)

    severity_score = calculate_severity_score(
        frp=frp,
        baseline_frp=baseline_frp,
        distance_m=distance_m,
        confidence_num=confidence_num,
        persistence_days=persistence_days,
    )

    if MODEL is None:
        predicted_class, confidence_score = _fallback_classification(hotspot)
    else:
        features_df = build_features(hotspot)
        X = features_df.to_numpy(dtype=np.float32)
        dmatrix = xgb.DMatrix(X, feature_names=FEATURE_COLS)
        
        probs = MODEL.predict(dmatrix)[0]
        pred_idx = int(np.argmax(probs))
        
        raw_ml_class = ML_CLASS_NAMES[pred_idx]
        predicted_class = CLASS_MAP.get(raw_ml_class, 'unknown')
        confidence_score = float(probs[pred_idx])

    return {
        "predicted_class": predicted_class,
        "confidence_score": round(_clamp(confidence_score, 0.0, 1.0), 4),
        "severity_score": severity_score,
        "is_abnormal": predicted_class == "abnormal_industrial",
    }
