"""Unit tests for the SQLAlchemy Incident ORM model and Schema-to-Model mapping."""

from datetime import datetime, timezone
from shared.schemas import IncidentMetrics, IncidentValidation, PipelineIncident
from db.models import Base, Incident


def test_incident_model_metadata():
    """Verify Incident ORM table structure, column mappings, and constraints."""
    table = Incident.__table__

    assert table.name == "incidents"
    assert "incident_id" in table.c
    assert table.c.incident_id.unique is True
    assert table.c.facility_id.nullable is True
    assert table.c.hotspot_id.nullable is True
    assert "geometry" in table.c
    assert "severity_level" in table.c
    assert "temp_mir_k" in table.c
    assert "temp_tir_k" in table.c
    assert "frp_spike_ratio" in table.c
    assert "historical_pass_count" in table.c
    assert "is_glint" in table.c


def test_schema_to_model_mapping():
    """Test mapping a validated PipelineIncident Pydantic schema to an Incident ORM instance."""
    now = datetime.now(timezone.utc)
    payload = PipelineIncident(
        incident_id="INC-20260830-001",
        facility_id="FAC_22.30_70.80",
        latitude=22.3039,
        longitude=70.8022,
        timestamp_utc=now,
        satellite_source="VIIRS-NOAA20",
        hazard_type="gas_flare",
        confidence_score=0.96,
        metrics=IncidentMetrics(
            temp_mir_k=365.2,
            temp_tir_k=295.4,
            frp_mw=18.5,
            frp_spike_ratio=2.4,
        ),
        validation=IncidentValidation(
            historical_pass_count=14,
            osm_landuse="industrial",
            is_glint=False,
        ),
        severity_level="RED",
    )

    incident_db = Incident(
        incident_id=payload.incident_id,
        facility_id=payload.facility_id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        timestamp_utc=payload.timestamp_utc,
        satellite_source=payload.satellite_source,
        geometry=f"SRID=4326;POINT({payload.longitude} {payload.latitude})",
        hazard_type=payload.hazard_type,
        confidence_score=payload.confidence_score,
        severity_level=payload.severity_level,
        temp_mir_k=payload.metrics.temp_mir_k,
        temp_tir_k=payload.metrics.temp_tir_k,
        frp_mw=payload.metrics.frp_mw,
        frp_spike_ratio=payload.metrics.frp_spike_ratio,
        historical_pass_count=payload.validation.historical_pass_count,
        osm_landuse=payload.validation.osm_landuse,
        is_glint=payload.validation.is_glint,
    )

    assert incident_db.incident_id == "INC-20260830-001"
    assert incident_db.facility_id == "FAC_22.30_70.80"
    assert incident_db.severity_level == "RED"
    assert incident_db.temp_mir_k == 365.2
    assert incident_db.frp_spike_ratio == 2.4
    assert incident_db.is_glint is False
    assert incident_db.geometry == "SRID=4326;POINT(70.8022 22.3039)"
