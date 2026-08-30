"""Pydantic v2 schemas defining core data contracts across modules.

Modules (ingestion, enrichment, classification, API) interact through these validated
schemas to ensure consistent data structures across the processing pipeline.
"""

from datetime import date, datetime
from typing import Any, Dict, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

# Supported fire and thermal classification categories
HotspotClass = Literal[
    "industrial",
    "gas_flare",
    "agricultural_burn",
    "mining",
    "wildfire",
    "unknown",
]


class RawHotspot(BaseModel):
    """Raw hotspot observation ingested from satellite sensor feeds (NASA FIRMS / VIIRS / MODIS)."""

    model_config = ConfigDict(from_attributes=True)

    lat: float = Field(
        ...,
        description="Latitude in decimal degrees (WGS84, EPSG:4326)",
        ge=-90.0,
        le=90.0,
        examples=[28.6139],
    )
    lon: float = Field(
        ...,
        description="Longitude in decimal degrees (WGS84, EPSG:4326)",
        ge=-180.0,
        le=180.0,
        examples=[77.2090],
    )
    brightness: float = Field(
        ...,
        description="Brightness temperature in Kelvin (channel 21/22 or I-4)",
        gt=0.0,
        examples=[345.5],
    )
    frp: float = Field(
        ...,
        description="Fire Radiative Power (MW)",
        ge=0.0,
        examples=[12.8],
    )
    acq_date: date = Field(
        ...,
        description="Acquisition date of the satellite observation",
        examples=["2026-08-28"],
    )
    acq_time: str = Field(
        ...,
        description="Acquisition time in UTC (HHMM string or ISO formatted)",
        examples=["1430"],
    )
    confidence: str = Field(
        ...,
        description="Detection confidence quality indicator (e.g., nominal, high, l, n, h, or percentage)",
        examples=["nominal"],
    )
    satellite: str = Field(
        ...,
        description="Source satellite platform and sensor instrument (e.g., VIIRS-NOAA20, MODIS-Terra)",
        examples=["VIIRS-NOAA20"],
    )


class EnrichedHotspot(RawHotspot):
    """Hotspot enriched with spatial context, nearest facility distance, and landcover classification."""

    nearest_facility_id: Optional[int] = Field(
        default=None,
        description="Database identifier of the closest known industrial facility",
        examples=[101],
    )
    distance_to_facility_m: Optional[float] = Field(
        default=None,
        description="Geodesic distance to the nearest industrial facility in meters",
        ge=0.0,
        examples=[450.2],
    )
    landcover_class: Optional[str] = Field(
        default=None,
        description="Copernicus/ESA land cover classification category code or label",
        examples=["Industrial / Commercial"],
    )
    persistence_days: int = Field(
        default=1,
        description="Number of consecutive or recurrent active thermal anomaly days within the spatial cluster",
        ge=1,
        examples=[3],
    )


class ClassifiedHotspot(EnrichedHotspot):
    """Enriched hotspot evaluated by the ThermoLens classification model."""

    predicted_class: HotspotClass = Field(
        ...,
        description="Predicted fire category: industrial, gas_flare, agricultural_burn, mining, wildfire, or unknown",
        examples=["industrial"],
    )
    confidence_score: float = Field(
        ...,
        description="Model confidence score between 0.0 and 1.0",
        ge=0.0,
        le=1.0,
        examples=[0.94],
    )


class Facility(BaseModel):
    """Known industrial facility footprint or coordinate location."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(
        ...,
        description="Unique database identifier for the facility",
        examples=[1],
    )
    name: str = Field(
        ...,
        description="Facility or plant name",
        examples=["Jamnagar Refinery"],
    )
    facility_type: str = Field(
        ...,
        description="Facility sector/type (e.g. oil_refinery, steel_plant, chemical, power_plant, cement)",
        examples=["oil_refinery"],
    )
    geometry: Union[str, Dict[str, Any]] = Field(
        ...,
        description="PostGIS geometry representation as WKT string (e.g., POINT(77.20 28.61)) or GeoJSON dictionary",
        examples=[{"type": "Point", "coordinates": [77.209, 28.6139]}],
    )


# Severity level classification for AI/ML pipeline incident outputs
SeverityLevel = Literal["RED", "AMBER", "GREEN"]


class IncidentMetrics(BaseModel):
    """Thermal and radiometry metrics produced by the AI/ML processing pipeline."""

    model_config = ConfigDict(from_attributes=True)

    temp_mir_k: float = Field(
        ...,
        description="Mid-Infrared brightness temperature in Kelvin (e.g., VIIRS I-4 / MODIS 21/22)",
        gt=0.0,
        examples=[365.2],
    )
    temp_tir_k: float = Field(
        ...,
        description="Thermal Infrared brightness temperature in Kelvin (e.g., VIIRS I-5 / MODIS 31)",
        gt=0.0,
        examples=[295.4],
    )
    frp_mw: float = Field(
        ...,
        description="Fire Radiative Power in Megawatts (MW)",
        ge=0.0,
        examples=[18.5],
    )
    frp_spike_ratio: float = Field(
        ...,
        description="Ratio of current FRP relative to historical baseline for the coordinate",
        ge=0.0,
        examples=[2.4],
    )


class IncidentValidation(BaseModel):
    """Contextual and geometric validation indicators for the detected event."""

    model_config = ConfigDict(from_attributes=True)

    historical_pass_count: int = Field(
        ...,
        description="Number of historical satellite passes recorded over this location",
        ge=0,
        examples=[14],
    )
    osm_landuse: Optional[str] = Field(
        default=None,
        description="OpenStreetMap / land use classification tag at the detection site",
        examples=["industrial"],
    )
    is_glint: bool = Field(
        ...,
        description="Flag indicating whether detection is likely solar glint or false positive",
        examples=[False],
    )


class PipelineIncident(BaseModel):
    """Standardized JSON contract representing an incident output from the AI/ML pipeline."""

    model_config = ConfigDict(from_attributes=True)

    incident_id: str = Field(
        ...,
        description="Unique identifier for the detected incident",
        examples=["INC-20260830-001"],
    )
    facility_id: Optional[str] = Field(
        default=None,
        description="Identifier of the matched industrial facility (e.g. 'FAC_22.30_70.80'), or None if unmatched",
        examples=["FAC_22.30_70.80"],
    )
    latitude: float = Field(
        ...,
        description="Latitude in decimal degrees (WGS84, EPSG:4326)",
        ge=-90.0,
        le=90.0,
        examples=[28.6139],
    )
    longitude: float = Field(
        ...,
        description="Longitude in decimal degrees (WGS84, EPSG:4326)",
        ge=-180.0,
        le=180.0,
        examples=[77.2090],
    )
    timestamp_utc: datetime = Field(
        ...,
        description="Observation timestamp in UTC (ISO 8601 format)",
        examples=["2026-08-30T14:30:00Z"],
    )
    satellite_source: str = Field(
        ...,
        description="Source satellite platform and sensor instrument (e.g., VIIRS-NOAA20, MODIS-Terra)",
        examples=["VIIRS-NOAA20"],
    )
    hazard_type: HotspotClass = Field(
        ...,
        description="Predicted hazard category from classification model (industrial, gas_flare, agricultural_burn, mining, wildfire, unknown)",
        examples=["gas_flare"],
    )
    confidence_score: float = Field(
        ...,
        description="Model confidence score between 0.0 and 1.0",
        ge=0.0,
        le=1.0,
        examples=[0.95],
    )
    metrics: IncidentMetrics = Field(
        ...,
        description="Thermal and radiative intensity measurements",
    )
    validation: IncidentValidation = Field(
        ...,
        description="Contextual and geometric validation checks",
    )
    severity_level: SeverityLevel = Field(
        ...,
        description="Operational alert severity classification level",
        examples=["RED"],
    )

