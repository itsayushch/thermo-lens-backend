"""Hotspot feed service for live or file-based NASA FIRMS data."""

from __future__ import annotations

import logging
import math
import os
from collections import defaultdict
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from shapely.geometry import Point, shape
from shapely.ops import unary_union
from shapely.prepared import PreparedGeometry, prep

from classification.infer import predict_hotspot
from ingestion.firms import parse_firms_csv, parse_firms_csv_text
from shared.schemas import RawHotspot

LOGGER = logging.getLogger(__name__)

DEFAULT_INDIA_BBOX = (68.0, 6.0, 98.0, 37.0)
DEFAULT_SOURCE = "VIIRS_SNPP_NRT"
DEFAULT_DAY_RANGE = 1
DEFAULT_LIMIT = 1000
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
INDIA_BOUNDARY_URL = "https://raw.githubusercontent.com/datameet/maps/master/Country/india-composite.geojson"


def parse_bbox(bbox: str | None) -> tuple[float, float, float, float]:
    if not bbox:
        return DEFAULT_INDIA_BBOX

    parts = [float(part.strip()) for part in bbox.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must contain four comma-separated numbers")

    min_lon, min_lat, max_lon, max_lat = parts
    if min_lon >= max_lon or min_lat >= max_lat:
        raise ValueError("bbox must be ordered as min_lon,min_lat,max_lon,max_lat")

    return min_lon, min_lat, max_lon, max_lat


def confidence_to_number(confidence: str | int | float) -> float:
    if isinstance(confidence, (int, float)):
        return max(0.0, min(100.0, float(confidence)))

    normalized = str(confidence).strip().lower()
    if normalized in {"h", "high"}:
        return 90.0
    if normalized in {"n", "nominal"}:
        return 60.0
    if normalized in {"l", "low"}:
        return 30.0

    try:
        return max(0.0, min(100.0, float(normalized)))
    except ValueError:
        return 60.0


def estimate_affected_radius_m(hotspot: RawHotspot) -> int:
    """Estimate a display footprint from FIRMS pixel scale and signal strength.

    FIRMS active-fire points are detections, not burn perimeters. This radius is a
    conservative map footprint/uncertainty estimate derived from sensor resolution,
    FRP, and detection confidence.
    """
    satellite = hotspot.satellite.lower()
    if "modis" in satellite:
        base_radius_m = 500.0
    else:
        base_radius_m = 190.0

    frp_factor = 1.0 + min(1.0, math.sqrt(max(hotspot.frp, 0.0) / 250.0)) * 0.55
    confidence = confidence_to_number(hotspot.confidence)
    confidence_factor = 1.0 + ((100.0 - confidence) / 100.0) * 0.20

    radius_m = base_radius_m * frp_factor * confidence_factor
    return round(max(150.0, min(1200.0, radius_m)))


def _in_bbox(hotspot: RawHotspot, bounds: tuple[float, float, float, float]) -> bool:
    min_lon, min_lat, max_lon, max_lat = bounds
    return min_lon <= hotspot.lon <= max_lon and min_lat <= hotspot.lat <= max_lat


@lru_cache(maxsize=1)
def _india_boundary() -> PreparedGeometry | None:
    try:
        response = httpx.get(INDIA_BOUNDARY_URL, timeout=30.0)
        response.raise_for_status()
        boundary = response.json()
        geometries = [
            shape(feature["geometry"])
            for feature in boundary.get("features", [])
            if feature.get("geometry")
        ]
        if not geometries:
            return None
        return prep(unary_union(geometries))
    except Exception:
        LOGGER.exception("Failed to load India boundary; falling back to India bounding box only")
        return None


def _in_india(hotspot: RawHotspot) -> bool:
    boundary = _india_boundary()
    if boundary is not None:
        point = Point(hotspot.lon, hotspot.lat)
        return boundary.contains(point) or boundary.covers(point)

    return _in_bbox(hotspot, DEFAULT_INDIA_BBOX)


def _date_allowed(hotspot: RawHotspot, start_date: date | None, end_date: date | None) -> bool:
    if start_date and hotspot.acq_date < start_date:
        return False
    if end_date and hotspot.acq_date > end_date:
        return False
    return True


def _local_csv_hotspots() -> list[RawHotspot]:
    hotspots: list[RawHotspot] = []
    for csv_path in sorted(DATA_DIR.glob("*.csv")):
        try:
            hotspots.extend(parse_firms_csv(csv_path))
        except Exception:
            LOGGER.exception("Failed to parse local FIRMS CSV: %s", csv_path)
    return hotspots


def _fetch_live_firms_hotspots(
    bounds: tuple[float, float, float, float],
    source: str,
    day_range: int,
    end_date: date | None,
) -> list[RawHotspot]:
    map_key = os.getenv("FIRMS_API_KEY", "").strip()
    if not map_key or map_key == "your_firms_api_key_here":
        return []

    area = ",".join(f"{value:g}" for value in bounds)
    if day_range <= 1 or end_date is None:
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/{source}/{area}/1"
        if end_date:
            url = f"{url}/{end_date.isoformat()}"
        response = httpx.get(url, timeout=30.0)
        response.raise_for_status()
        return parse_firms_csv_text(response.text)

    hotspots: list[RawHotspot] = []
    for offset in range(day_range):
        request_date = end_date - timedelta(days=day_range - offset - 1)
        url = (
            f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
            f"{map_key}/{source}/{area}/1/{request_date.isoformat()}"
        )
        response = httpx.get(url, timeout=30.0)
        response.raise_for_status()
        hotspots.extend(parse_firms_csv_text(response.text))

    deduped: dict[tuple[float, float, date, str, str], RawHotspot] = {}
    for hotspot in hotspots:
        key = (
            round(hotspot.lat, 5),
            round(hotspot.lon, 5),
            hotspot.acq_date,
            hotspot.acq_time,
            hotspot.satellite,
        )
        deduped[key] = hotspot

    return list(deduped.values())


def _hotspot_to_feature(hotspot: RawHotspot, index: int) -> dict[str, Any]:
    baseline_frp = 35.0
    affected_radius_m = estimate_affected_radius_m(hotspot)
    affected_area_km2 = math.pi * (affected_radius_m / 1000.0) ** 2
    classifier_input = {
        "brightness": hotspot.brightness,
        "frp": hotspot.frp,
        "distance_to_facility_m": 10_000.0,
        "persistence_days": 1,
        "confidence_num": confidence_to_number(hotspot.confidence),
        "baseline_frp": baseline_frp,
    }
    classification = predict_hotspot(classifier_input)

    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [hotspot.lon, hotspot.lat],
        },
        "properties": {
            "id": f"firms-{hotspot.acq_date.isoformat()}-{hotspot.acq_time}-{index}",
            "latitude": hotspot.lat,
            "longitude": hotspot.lon,
            "brightness": hotspot.brightness,
            "frp": hotspot.frp,
            "baseline_frp": baseline_frp,
            "acq_date": hotspot.acq_date.isoformat(),
            "acq_time": hotspot.acq_time,
            "confidence": hotspot.confidence,
            "satellite": hotspot.satellite,
            "distance_to_facility_m": None,
            "persistence_days": 1,
            "predicted_class": classification["predicted_class"],
            "confidence_score": round(float(classification["confidence_score"]) * 100.0),
            "severity_score": classification["severity_score"],
            "affected_radius_m": affected_radius_m,
            "affected_area_km2": round(affected_area_km2, 3),
        },
    }


def _limit_balanced_by_date(hotspots: list[RawHotspot], limit: int) -> list[RawHotspot]:
    if len(hotspots) <= limit:
        return hotspots

    grouped: dict[date, list[RawHotspot]] = defaultdict(list)
    for hotspot in sorted(hotspots, key=lambda item: (item.acq_date, item.acq_time), reverse=True):
        grouped[hotspot.acq_date].append(hotspot)

    selected: list[RawHotspot] = []
    grouped_dates = sorted(grouped.keys(), reverse=True)
    while len(selected) < limit and grouped_dates:
        next_dates: list[date] = []
        for hotspot_date in grouped_dates:
            group = grouped[hotspot_date]
            if group and len(selected) < limit:
                selected.append(group.pop(0))
            if group:
                next_dates.append(hotspot_date)
        grouped_dates = next_dates

    return selected


def get_hotspot_feature_collection(
    bbox: str | None,
    start_date: date | None,
    end_date: date | None,
    hotspot_class: str | None,
    source: str = DEFAULT_SOURCE,
    day_range: int = DEFAULT_DAY_RANGE,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    requested_bounds = parse_bbox(bbox)
    india_bounds = DEFAULT_INDIA_BBOX
    bounds = (
        max(requested_bounds[0], india_bounds[0]),
        max(requested_bounds[1], india_bounds[1]),
        min(requested_bounds[2], india_bounds[2]),
        min(requested_bounds[3], india_bounds[3]),
    )
    if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        return {
            "type": "FeatureCollection",
            "features": [],
            "metadata": {
                "source": "outside India",
                "count": 0,
                "country": "IND",
            },
        }
    safe_day_range = max(1, min(day_range, 10))
    safe_limit = max(1, min(limit, 5000))

    data_source = "NASA FIRMS live API"
    try:
        hotspots = _fetch_live_firms_hotspots(bounds, source, safe_day_range, end_date)
    except Exception:
        LOGGER.exception("Live FIRMS request failed; falling back to local CSV files")
        hotspots = []

    if not hotspots:
        data_source = "local FIRMS CSV"
        hotspots = _local_csv_hotspots()

    eligible_hotspots: list[RawHotspot] = []
    for hotspot in hotspots:
        if not _in_bbox(hotspot, bounds):
            continue
        if not _in_india(hotspot):
            continue
        if not _date_allowed(hotspot, start_date, end_date):
            continue
        eligible_hotspots.append(hotspot)

    features = []
    for index, hotspot in enumerate(_limit_balanced_by_date(eligible_hotspots, safe_limit)):
        feature = _hotspot_to_feature(hotspot, index)
        if hotspot_class and feature["properties"]["predicted_class"] != hotspot_class:
            continue

        features.append(feature)

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source": data_source,
            "count": len(features),
            "available_count": len(eligible_hotspots),
            "country": "IND",
        },
    }
