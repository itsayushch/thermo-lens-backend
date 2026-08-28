"""ThermoLens API - FastAPI backend service for industrial fire classification."""

from datetime import date
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from db.session import engine

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
