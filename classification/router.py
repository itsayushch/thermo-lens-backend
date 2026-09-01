"""FastAPI router for ThermoLens ML classification."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from classification.infer import predict_hotspot

PredictedClass = Literal[
    "abnormal_industrial",
    "industrial",
    "gas_flare",
    "wildfire",
    "agricultural_burn",
]


class EnrichedHotspotInput(BaseModel):
    brightness: float = Field(..., description="Brightness temperature in Kelvin")
    frp: float = Field(..., ge=0.0, description="Fire Radiative Power in MW")
    distance_to_facility_m: float = Field(..., ge=0.0, description="Distance to nearest OSM polygon in meters")
    persistence_days: int = Field(..., ge=0, description="Consecutive or recurrent hotspot days")
    confidence_num: float = Field(..., ge=0.0, le=100.0, description="NASA FIRMS confidence from 0 to 100")
    baseline_frp: float = Field(35.0, ge=0.0, description="Historical normal FRP for nearest facility")


class ClassifiedHotspotOutput(BaseModel):
    predicted_class: PredictedClass
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    severity_score: int = Field(..., ge=0, le=100)
    is_abnormal: bool


router = APIRouter(tags=["classification"])


@router.post("/classify", response_model=list[ClassifiedHotspotOutput])
def classify_hotspots(hotspots: list[EnrichedHotspotInput]) -> list[ClassifiedHotspotOutput]:
    return [ClassifiedHotspotOutput(**predict_hotspot(hotspot.model_dump())) for hotspot in hotspots]
