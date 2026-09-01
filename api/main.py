"""ThermoLens API - FastAPI backend service for industrial fire classification."""

from datetime import date, datetime
import logging
from typing import Any, Dict, List, Optional
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from classification.router import router as ml_router
from db.session import engine, get_db
from services.incidents import (
    get_incident_by_id,
    get_incidents as fetch_incidents,
    incident_to_pipeline_schema,
    save_incident,
)
from shared.schemas import (
    HotspotClass,
    PipelineIncident,
    SeverityLevel,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="ThermoLens API",
    description="Geospatial API backend for ThermoLens industrial fire classification and monitoring.",
    version="0.1.0",
)

# CORS Configuration - allow Next.js frontend on localhost:3000
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ml_router)


@app.get("/", tags=["Root"])
def root() -> Dict[str, str]:
    """Root metadata endpoint."""
    return {
        "title": "ThermoLens API",
        "version": "0.1.0",
        "docs_url": "/docs",
        "health_url": "/health",
    }


@app.get("/health", tags=["Health"])
def health_check() -> Dict[str, Any]:
    """Health check endpoint validating API status and PostgreSQL / PostGIS database connectivity.

    Returns HTTP 200 with status info if healthy, or raises HTTP 503 Service Unavailable
    with diagnostic instructions if PostgreSQL is unreachable.
    """
    db_status = "unknown"
    postgis_version = None

    try:
        with engine.connect() as connection:
            # Check basic DB connectivity
            connection.execute(text("SELECT 1"))
            db_status = "connected"

            # Check PostGIS extension availability
            try:
                result = connection.execute(text("SELECT PostGIS_Version()")).scalar()
                postgis_version = str(result)
            except Exception:
                postgis_version = "not installed or extension not enabled in this database"

        return {
            "status": "ok",
            "database": db_status,
            "postgis_version": postgis_version,
            "message": "ThermoLens backend is operational.",
        }

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "error",
                "database": "disconnected",
                "error": str(exc),
                "message": (
                    "Could not connect to PostgreSQL. Please verify that your local PostgreSQL "
                    "service is running, the PostGIS extension is enabled, and DATABASE_URL "
                    "in your .env file matches your local database credentials."
                ),
            },
        )


@app.get("/hotspots", tags=["Hotspots"])
def get_hotspots(
    bbox: Optional[str] = Query(
        default=None,
        description="Bounding box coordinates in format: min_lon,min_lat,max_lon,max_lat (WGS84)",
        examples=["77.0,28.0,77.5,28.5"],
    ),
    start_date: Optional[date] = Query(
        default=None,
        description="Filter observations on or after this acquisition date (YYYY-MM-DD)",
        examples=["2026-08-01"],
    ),
    end_date: Optional[date] = Query(
        default=None,
        description="Filter observations on or before this acquisition date (YYYY-MM-DD)",
        examples=["2026-08-28"],
    ),
    hotspot_class: Optional[str] = Query(
        default=None,
        alias="class",
        description="Filter by fire classification (industrial, gas_flare, agricultural_burn, mining, wildfire, unknown)",
        examples=["industrial"],
    ),
) -> Dict[str, Any]:
    """Query satellite hotspot detections filtered by bounding box, date range, and classification.

    Returns a GeoJSON FeatureCollection. (Stub implementation)
    """
    # Stub response returning an empty GeoJSON FeatureCollection
    return {
        "type": "FeatureCollection",
        "features": [],
    }


@app.get("/facilities", tags=["Facilities"])
def get_facilities(
    facility_type: Optional[str] = Query(
        default=None,
        description="Filter by facility type (e.g. oil_refinery, steel_plant, chemical, power_plant)",
        examples=["oil_refinery"],
    ),
    bbox: Optional[str] = Query(
        default=None,
        description="Bounding box coordinates in format: min_lon,min_lat,max_lon,max_lat (WGS84)",
        examples=["77.0,28.0,77.5,28.5"],
    ),
) -> Dict[str, Any]:
    """Query known industrial facilities filtered by facility type and bounding box.

    Returns a GeoJSON FeatureCollection. (Stub implementation)
    """
    # Stub response returning an empty GeoJSON FeatureCollection
    return {
        "type": "FeatureCollection",
        "features": [],
    }


@app.post(
    "/incidents",
    response_model=PipelineIncident,
    status_code=status.HTTP_201_CREATED,
    tags=["Incidents"],
    summary="Record verified AI/ML pipeline incident",
)
def create_incident(
    incident: PipelineIncident,
    hotspot_id: Optional[int] = Query(
        default=None,
        description="Optional foreign key linking to raw hotspot row",
    ),
    db: Session = Depends(get_db),
) -> PipelineIncident:
    """Ingest and persist a verified thermal anomaly incident emitted by the AI/ML pipeline."""
    try:
        saved_incident = save_incident(db, incident, hotspot_id=hotspot_id)
        return incident_to_pipeline_schema(saved_incident)
    except IntegrityError as exc:
        db.rollback()
        logger.warning(
            "Duplicate incident creation attempt for ID '%s': %s",
            incident.incident_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Incident with ID '{incident.incident_id}' already exists.",
        )
    except Exception as exc:
        db.rollback()
        logger.error(
            "Failed to persist incident '%s': %s",
            incident.incident_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist incident.",
        )


@app.get(
    "/incidents",
    response_model=List[PipelineIncident],
    status_code=status.HTTP_200_OK,
    tags=["Incidents"],
    summary="Query verified incidents",
)
def list_incidents(
    severity_level: Optional[SeverityLevel] = Query(
        default=None,
        description="Filter by operational severity (RED, AMBER, GREEN)",
    ),
    hazard_type: Optional[HotspotClass] = Query(
        default=None,
        description="Filter by fire hazard classification category",
    ),
    facility_id: Optional[str] = Query(
        default=None,
        description="Filter by facility identifier",
    ),
    start_time: Optional[datetime] = Query(
        default=None,
        description="Filter incidents on or after this timestamp (ISO 8601 UTC)",
    ),
    end_time: Optional[datetime] = Query(
        default=None,
        description="Filter incidents on or before this timestamp (ISO 8601 UTC)",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
        description="Maximum number of records to return",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Number of records to skip for pagination",
    ),
    db: Session = Depends(get_db),
) -> List[PipelineIncident]:
    """Retrieve verified incidents with multi-attribute filtering and pagination."""
    incidents = fetch_incidents(
        db=db,
        severity_level=severity_level,
        hazard_type=hazard_type,
        facility_id=facility_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )
    return [incident_to_pipeline_schema(inc) for inc in incidents]


@app.get(
    "/incidents/geojson",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    tags=["Incidents"],
    summary="Query verified incidents as GeoJSON FeatureCollection",
)
def get_incidents_geojson(
    severity_level: Optional[SeverityLevel] = Query(
        default=None,
        description="Filter by operational severity (RED, AMBER, GREEN)",
    ),
    hazard_type: Optional[HotspotClass] = Query(
        default=None,
        description="Filter by fire hazard classification category",
    ),
    facility_id: Optional[str] = Query(
        default=None,
        description="Filter by facility identifier",
    ),
    start_time: Optional[datetime] = Query(
        default=None,
        description="Filter incidents on or after this timestamp (ISO 8601 UTC)",
    ),
    end_time: Optional[datetime] = Query(
        default=None,
        description="Filter incidents on or before this timestamp (ISO 8601 UTC)",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
        description="Maximum number of records to return",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Number of records to skip for pagination",
    ),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve verified incidents formatted as a standard GeoJSON FeatureCollection."""
    incidents = fetch_incidents(
        db=db,
        severity_level=severity_level,
        hazard_type=hazard_type,
        facility_id=facility_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )

    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [inc.longitude, inc.latitude],
            },
            "properties": {
                "incident_id": inc.incident_id,
                "facility_id": inc.facility_id,
                "hazard_type": inc.hazard_type,
                "severity_level": inc.severity_level,
                "confidence_score": inc.confidence_score,
                "frp_mw": inc.frp_mw,
                "frp_spike_ratio": inc.frp_spike_ratio,
                "satellite_source": inc.satellite_source,
                "timestamp_utc": (
                    inc.timestamp_utc.isoformat()
                    if hasattr(inc.timestamp_utc, "isoformat")
                    else str(inc.timestamp_utc)
                ),
            },
        }
        for inc in incidents
    ]

    return {
        "type": "FeatureCollection",
        "features": features,
    }


@app.get(
    "/incidents/{incident_id}",
    response_model=PipelineIncident,
    status_code=status.HTTP_200_OK,
    tags=["Incidents"],
    summary="Retrieve single incident by ID",
)
def get_incident(
    incident_id: str,
    db: Session = Depends(get_db),
) -> PipelineIncident:
    """Retrieve incident details by unique business incident_id."""
    incident = get_incident_by_id(db, incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found.",
        )
    return incident_to_pipeline_schema(incident)


