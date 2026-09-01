"""Bootstrap and export the lightweight ThermoLens classifier.

This script intentionally uses synthetic data for MVP readiness. It gives the
backend a fast, interpretable baseline model while the real labeled corpus is
being assembled.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
MODEL_PATH = ARTIFACTS_DIR / "thermolens_classifier.joblib"
BASELINES_PATH = ARTIFACTS_DIR / "facility_baselines.json"

FEATURE_COLUMNS = [
    "brightness",
    "frp",
    "distance_to_facility_m",
    "persistence_days",
    "confidence_num",
    "baseline_frp",
]

RANDOM_SEED = 42
ROWS_PER_CLASS = 500


def _bounded_normal(
    rng: np.random.Generator,
    mean: float,
    std: float,
    lower: float,
    upper: float,
    size: int,
) -> np.ndarray:
    values = rng.normal(mean, std, size)
    return np.clip(values, lower, upper)


def generate_synthetic_hotspots(rows_per_class: int = ROWS_PER_CLASS) -> pd.DataFrame:
    """Generate 2000 synthetic rows across the four MVP base classes."""
    rng = np.random.default_rng(RANDOM_SEED)
    frames: list[pd.DataFrame] = []

    class_profiles = {
        "gas_flare": {
            "brightness": (345.0, 16.0, 315.0, 390.0),
            "frp": (32.0, 13.0, 8.0, 85.0),
            "distance": (650.0, 450.0, 50.0, 2200.0),
            "persistence": (6, 2, 2, 14),
            "confidence": (82.0, 11.0, 45.0, 100.0),
            "baseline": (30.0, 8.0, 12.0, 55.0),
        },
        "industrial": {
            "brightness": (335.0, 18.0, 305.0, 385.0),
            "frp": (42.0, 20.0, 8.0, 120.0),
            "distance": (260.0, 220.0, 0.0, 1000.0),
            "persistence": (3, 2, 1, 9),
            "confidence": (76.0, 14.0, 35.0, 100.0),
            "baseline": (35.0, 10.0, 15.0, 70.0),
        },
        "wildfire": {
            "brightness": (372.0, 24.0, 325.0, 450.0),
            "frp": (145.0, 70.0, 35.0, 450.0),
            "distance": (6200.0, 2600.0, 1200.0, 15000.0),
            "persistence": (4, 3, 1, 14),
            "confidence": (88.0, 10.0, 45.0, 100.0),
            "baseline": (22.0, 8.0, 5.0, 45.0),
        },
        "agricultural_burn": {
            "brightness": (322.0, 13.0, 295.0, 360.0),
            "frp": (18.0, 9.0, 2.0, 55.0),
            "distance": (3800.0, 2100.0, 700.0, 10000.0),
            "persistence": (1, 1, 1, 4),
            "confidence": (58.0, 17.0, 15.0, 95.0),
            "baseline": (18.0, 7.0, 5.0, 40.0),
        },
    }

    for class_name, profile in class_profiles.items():
        persistence_mean, persistence_std, persistence_min, persistence_max = profile["persistence"]
        frame = pd.DataFrame(
            {
                "brightness": _bounded_normal(rng, *profile["brightness"], size=rows_per_class),
                "frp": _bounded_normal(rng, *profile["frp"], size=rows_per_class),
                "distance_to_facility_m": _bounded_normal(rng, *profile["distance"], size=rows_per_class),
                "persistence_days": np.clip(
                    np.rint(rng.normal(persistence_mean, persistence_std, rows_per_class)),
                    persistence_min,
                    persistence_max,
                ).astype(int),
                "confidence_num": _bounded_normal(rng, *profile["confidence"], size=rows_per_class),
                "baseline_frp": _bounded_normal(rng, *profile["baseline"], size=rows_per_class),
                "predicted_class": class_name,
            }
        )
        frames.append(frame)

    data = pd.concat(frames, ignore_index=True)
    return data.sample(frac=1.0, random_state=RANDOM_SEED).reset_index(drop=True)


def train_and_export() -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    data = generate_synthetic_hotspots()
    x_train, x_test, y_train, y_test = train_test_split(
        data[FEATURE_COLUMNS],
        data["predicted_class"],
        test_size=0.20,
        random_state=RANDOM_SEED,
        stratify=data["predicted_class"],
    )

    model = RandomForestClassifier(
        n_estimators=100,
        max_depth=10,
        random_state=RANDOM_SEED,
    )
    model.fit(x_train, y_train)

    joblib.dump(model, MODEL_PATH)

    facility_baselines = {
        "default_refinery": {"mean_frp": 35.0},
        "default_power_plant": {"mean_frp": 28.0},
        "default_steel_plant": {"mean_frp": 42.0},
        "default_chemical_site": {"mean_frp": 30.0},
    }
    with BASELINES_PATH.open("w", encoding="utf-8") as baselines_file:
        json.dump(facility_baselines, baselines_file, indent=2, sort_keys=True)

    predictions = model.predict(x_test)
    print(f"Exported model to {MODEL_PATH}")
    print(f"Exported baselines to {BASELINES_PATH}")
    print(classification_report(y_test, predictions, digits=3))


if __name__ == "__main__":
    train_and_export()
