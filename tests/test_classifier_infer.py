"""Unit tests for lightweight ThermoLens inference rules."""

from classification.infer import calculate_severity_score, predict_hotspot


def test_thermal_fingerprinting_marks_abnormal_industrial():
    result = predict_hotspot(
        {
            "brightness": 370.0,
            "frp": 90.0,
            "distance_to_facility_m": 120.0,
            "persistence_days": 1,
            "confidence_num": 90.0,
            "baseline_frp": 35.0,
        }
    )

    assert result["predicted_class"] == "abnormal_industrial"
    assert result["is_abnormal"] is True
    assert result["confidence_score"] == 1.0


def test_remote_confident_hotspot_is_wildfire_not_agricultural_burn():
    result = predict_hotspot(
        {
            "brightness": 340.0,
            "frp": 8.0,
            "distance_to_facility_m": 10_000.0,
            "persistence_days": 1,
            "confidence_num": 60.0,
            "baseline_frp": 35.0,
        }
    )

    assert result["predicted_class"] == "agricultural_burn"
    assert result["is_abnormal"] is False
    assert result["confidence_score"] >= 0.62


def test_low_confidence_low_intensity_remote_hotspot_remains_agricultural_burn():
    result = predict_hotspot(
        {
            "brightness": 321.0,
            "frp": 4.0,
            "distance_to_facility_m": 10_000.0,
            "persistence_days": 1,
            "confidence_num": 30.0,
            "baseline_frp": 35.0,
        }
    )

    assert result["predicted_class"] == "unknown"


def test_severity_score_stays_bounded():
    assert calculate_severity_score(
        frp=1000.0,
        baseline_frp=1.0,
        distance_m=0.0,
        confidence_num=100.0,
        persistence_days=10,
    ) == 100
