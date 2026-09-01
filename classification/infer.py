"""Production inference wrapper for ThermoLens hotspot classification.

The public contract in this module intentionally uses plain dictionaries so it can
be imported by the FastAPI backend branch without coupling to database or
pipeline-internal schemas.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Final

import joblib
import pandas as pd

LOGGER = logging.getLogger(__name__)

BASE_DIR: Final[Path] = Path(__file__).resolve().parent
ARTIFACTS_DIR: Final[Path] = BASE_DIR / "artifacts"
MODEL_PATH: Final[Path] = ARTIFACTS_DIR / "thermolens_classifier.joblib"
BASELINES_PATH: Final[Path] = ARTIFACTS_DIR / "facility_baselines.json"

FEATURE_COLUMNS: Final[list[str]] = [
    "brightness",
    "frp",
    "distance_to_facility_m",
    "persistence_days",
    "confidence_num",
    "baseline_frp",
]

DEFAULT_BASELINE_FRP: Final[float] = 35.0
BASE_CLASSES: Final[set[str]] = {
    "gas_flare",
    "industrial",
    "wildfire",
    "agricultural_burn",
}


def _load_model() -> Any | None:
    """Load the scikit-learn model without making app startup fragile."""
    try:
        if not MODEL_PATH.exists():
            LOGGER.warning("ThermoLens classifier artifact missing: %s", MODEL_PATH)
            return None
        return joblib.load(MODEL_PATH)
    except Exception:
        LOGGER.exception("Failed to load ThermoLens classifier from %s", MODEL_PATH)
        return None


def _load_facility_baselines() -> dict[str, dict[str, float]]:
    """Load facility baselines with a small default fallback."""
    fallback = {"default_refinery": {"mean_frp": DEFAULT_BASELINE_FRP}}
    try:
        if not BASELINES_PATH.exists():
            LOGGER.warning("ThermoLens facility baselines missing: %s", BASELINES_PATH)
            return fallback
        with BASELINES_PATH.open("r", encoding="utf-8") as baselines_file:
            loaded = json.load(baselines_file)
        if not isinstance(loaded, dict):
            LOGGER.warning("Facility baselines file did not contain a dictionary")
            return fallback
        return loaded
    except Exception:
        LOGGER.exception("Failed to load ThermoLens baselines from %s", BASELINES_PATH)
        return fallback


MODEL: Final[Any | None] = _load_model()
FACILITY_BASELINES: Final[dict[str, dict[str, float]]] = _load_facility_baselines()


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def calculate_severity_score(
    frp: float,
    baseline_frp: float,
    distance_m: float,
    confidence_num: float,
    persistence_days: int,
) -> int:
    """Calculate a 0-100 incident severity score.

    Weighting:
    - 40% FRP spike against facility baseline
    - 30% proximity to industrial infrastructure
    - 20% satellite confidence
    - 10% repeated temporal persistence
    """
    safe_baseline = max(float(baseline_frp), 1.0)
    spike_ratio = max(float(frp), 0.0) / safe_baseline

    frp_spike_component = _clamp(spike_ratio / 3.0, 0.0, 1.0) * 40.0
    proximity_component = _clamp(1.0 - (max(float(distance_m), 0.0) / 1000.0), 0.0, 1.0) * 30.0
    confidence_component = _clamp(float(confidence_num), 0.0, 100.0) / 100.0 * 20.0
    persistence_component = _clamp(float(persistence_days) / 5.0, 0.0, 1.0) * 10.0

    return int(round(frp_spike_component + proximity_component + confidence_component + persistence_component))


def _feature_frame(hotspot: dict[str, Any]) -> pd.DataFrame:
    baseline_frp = _as_float(hotspot.get("baseline_frp"), DEFAULT_BASELINE_FRP)
    row = {
        "brightness": _as_float(hotspot.get("brightness"), 0.0),
        "frp": _as_float(hotspot.get("frp"), 0.0),
        "distance_to_facility_m": _as_float(hotspot.get("distance_to_facility_m"), 10_000.0),
        "persistence_days": _as_int(hotspot.get("persistence_days"), 1),
        "confidence_num": _as_float(hotspot.get("confidence_num"), 0.0),
        "baseline_frp": baseline_frp,
    }
    return pd.DataFrame([row], columns=FEATURE_COLUMNS)


def _fallback_classification(hotspot: dict[str, Any]) -> tuple[str, float]:
    """Small deterministic fallback for CI or first boot before artifacts exist."""
    distance_m = _as_float(hotspot.get("distance_to_facility_m"), 10_000.0)
    frp = _as_float(hotspot.get("frp"), 0.0)
    brightness = _as_float(hotspot.get("brightness"), 0.0)

    if distance_m <= 500.0 and frp >= 25.0:
        return "industrial", 0.55
    if distance_m <= 1200.0 and 8.0 <= frp <= 70.0 and brightness >= 330.0:
        return "gas_flare", 0.50
    if frp >= 80.0 or brightness >= 360.0:
        return "wildfire", 0.55
    return "agricultural_burn", 0.50


def predict_hotspot(hotspot: dict[str, Any]) -> dict[str, Any]:
    """Classify one enriched hotspot using the Thermal Fingerprinting Rule first."""
    frp = _as_float(hotspot.get("frp"), 0.0)
    baseline_frp = max(_as_float(hotspot.get("baseline_frp"), DEFAULT_BASELINE_FRP), 1.0)
    distance_m = _as_float(hotspot.get("distance_to_facility_m"), 10_000.0)
    confidence_num = _as_float(hotspot.get("confidence_num"), 0.0)
    persistence_days = _as_int(hotspot.get("persistence_days"), 1)

    severity_score = calculate_severity_score(
        frp=frp,
        baseline_frp=baseline_frp,
        distance_m=distance_m,
        confidence_num=confidence_num,
        persistence_days=persistence_days,
    )

    if distance_m <= 250.0 and frp >= (2.0 * baseline_frp):
        return {
            "predicted_class": "abnormal_industrial",
            "confidence_score": 1.0,
            "severity_score": severity_score,
            "is_abnormal": True,
        }

    if MODEL is None:
        predicted_class, confidence_score = _fallback_classification(hotspot)
    else:
        features = _feature_frame(hotspot)
        predicted_class = str(MODEL.predict(features)[0])
        probabilities = MODEL.predict_proba(features)[0]
        confidence_score = float(max(probabilities))

    if predicted_class not in BASE_CLASSES:
        LOGGER.warning("Unexpected model class '%s'; falling back to industrial", predicted_class)
        predicted_class = "industrial"
        confidence_score = min(confidence_score, 0.50)

    return {
        "predicted_class": predicted_class,
        "confidence_score": round(_clamp(confidence_score, 0.0, 1.0), 4),
        "severity_score": severity_score,
        "is_abnormal": False,
    }
