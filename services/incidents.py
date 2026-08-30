"""Incident persistence service for AI/ML pipeline outputs."""

from datetime import datetime
import logging
from typing import List, Optional, Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Incident
from shared.schemas import (
    HotspotClass,
    IncidentMetrics,
    IncidentValidation,
    PipelineIncident,
    SeverityLevel,
)

logger = logging.getLogger(__name__)


def _build_wkt_point(lon: float, lat: float) -> str:
    """Format decimal coordinates into a WGS84 PostGIS EWKT Point."""
    return f"SRID=4326;POINT({lon} {lat})"


def incident_to_pipeline_schema(incident: Incident) -> PipelineIncident:
    """Convert an Incident ORM model instance to a validated PipelineIncident Pydantic schema."""
    return PipelineIncident(
        incident_id=incident.incident_id,
        facility_id=incident.facility_id,
        latitude=incident.latitude,
        longitude=incident.longitude,
        timestamp_utc=incident.timestamp_utc,
        satellite_source=incident.satellite_source,
        hazard_type=incident.hazard_type,  # type: ignore[arg-type]
        confidence_score=incident.confidence_score,
        metrics=IncidentMetrics(
            temp_mir_k=incident.temp_mir_k,
            temp_tir_k=incident.temp_tir_k,
            frp_mw=incident.frp_mw,
            frp_spike_ratio=incident.frp_spike_ratio,
        ),
        validation=IncidentValidation(
            historical_pass_count=incident.historical_pass_count,
            osm_landuse=incident.osm_landuse,
            is_glint=incident.is_glint,
        ),
        severity_level=incident.severity_level,  # type: ignore[arg-type]
    )


def save_incident(
    db: Session,
    payload: PipelineIncident,
    hotspot_id: Optional[int] = None,
) -> Incident:
    """Persist a single verified incident from the AI/ML pipeline into PostgreSQL.

    Args:
        db: SQLAlchemy database session.
        payload: Validated PipelineIncident Pydantic model.
        hotspot_id: Optional database foreign key to the originating hotspot row.

    Returns:
        The persisted Incident ORM instance.

    Raises:
        Exception: If commit fails (rolls back active transaction).
    """
    incident = Incident(
        incident_id=payload.incident_id,
        facility_id=payload.facility_id,
        hotspot_id=hotspot_id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        timestamp_utc=payload.timestamp_utc,
        satellite_source=payload.satellite_source,
        geometry=_build_wkt_point(payload.longitude, payload.latitude),
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

    try:
        db.add(incident)
        db.commit()
        db.refresh(incident)
        logger.info(
            "Persisted incident %s (severity=%s, hazard=%s)",
            incident.incident_id,
            incident.severity_level,
            incident.hazard_type,
        )
        return incident
    except Exception as exc:
        db.rollback()
        logger.error("Failed to save incident '%s': %s", payload.incident_id, exc)
        raise


def save_incidents_batch(
    db: Session,
    payloads: Sequence[PipelineIncident],
    hotspot_ids: Optional[Sequence[Optional[int]]] = None,
    default_hotspot_id: Optional[int] = None,
) -> List[Incident]:
    """Persist a batch of AI/ML pipeline incident outputs in a single transaction.

    Args:
        db: SQLAlchemy database session.
        payloads: Sequence of validated PipelineIncident objects.
        hotspot_ids: Optional sequence of corresponding hotspot IDs matching payloads length.
        default_hotspot_id: Optional default hotspot ID applied to all items if hotspot_ids is omitted.

    Returns:
        List of created Incident ORM instances.

    Raises:
        ValueError: If hotspot_ids length does not match payloads length.
        Exception: If commit fails (rolls back active transaction).
    """
    if not payloads:
        return []

    if hotspot_ids is not None and len(hotspot_ids) != len(payloads):
        raise ValueError(
            f"Length of hotspot_ids ({len(hotspot_ids)}) must match payloads ({len(payloads)})"
        )

    incidents = []
    for idx, p in enumerate(payloads):
        hid = hotspot_ids[idx] if hotspot_ids is not None else default_hotspot_id
        inc = Incident(
            incident_id=p.incident_id,
            facility_id=p.facility_id,
            hotspot_id=hid,
            latitude=p.latitude,
            longitude=p.longitude,
            timestamp_utc=p.timestamp_utc,
            satellite_source=p.satellite_source,
            geometry=_build_wkt_point(p.longitude, p.latitude),
            hazard_type=p.hazard_type,
            confidence_score=p.confidence_score,
            severity_level=p.severity_level,
            temp_mir_k=p.metrics.temp_mir_k,
            temp_tir_k=p.metrics.temp_tir_k,
            frp_mw=p.metrics.frp_mw,
            frp_spike_ratio=p.metrics.frp_spike_ratio,
            historical_pass_count=p.validation.historical_pass_count,
            osm_landuse=p.validation.osm_landuse,
            is_glint=p.validation.is_glint,
        )
        incidents.append(inc)

    try:
        db.add_all(incidents)
        db.commit()
        for inc in incidents:
            db.refresh(inc)
        logger.info("Batch persisted %d incidents", len(incidents))
        return incidents
    except Exception as exc:
        db.rollback()
        logger.error("Failed to batch persist %d incidents: %s", len(payloads), exc)
        raise


def get_incident_by_id(db: Session, incident_id: str) -> Optional[Incident]:
    """Retrieve an incident by its unique business identifier."""
    stmt = select(Incident).where(Incident.incident_id == incident_id)
    return db.execute(stmt).scalar_one_or_none()


def get_incidents(
    db: Session,
    severity_level: Optional[SeverityLevel] = None,
    hazard_type: Optional[HotspotClass] = None,
    facility_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    offset: int = 0,
    limit: int = 100,
) -> List[Incident]:
    """Query incidents with multi-attribute filtering and pagination."""
    stmt = select(Incident)

    if severity_level:
        stmt = stmt.where(Incident.severity_level == severity_level)
    if hazard_type:
        stmt = stmt.where(Incident.hazard_type == hazard_type)
    if facility_id:
        stmt = stmt.where(Incident.facility_id == facility_id)
    if start_time:
        stmt = stmt.where(Incident.timestamp_utc >= start_time)
    if end_time:
        stmt = stmt.where(Incident.timestamp_utc <= end_time)

    stmt = stmt.order_by(Incident.timestamp_utc.desc()).offset(offset).limit(limit)
    return list(db.execute(stmt).scalars().all())
