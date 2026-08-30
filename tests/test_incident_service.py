"""Unit tests for the Incident persistence service (services/incidents.py)."""

from datetime import datetime, timezone, timedelta
import pytest
import shapely.wkt
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.ext.compiler import compiles
from geoalchemy2 import Geometry
import geoalchemy2.admin.dialects.sqlite as sqlite_admin

from db.models import Base, Incident
from shared.schemas import (
    IncidentMetrics,
    IncidentValidation,
    PipelineIncident,
)
from services.incidents import (
    get_incident_by_id,
    get_incidents,
    incident_to_pipeline_schema,
    save_incident,
    save_incidents_batch,
)


@pytest.fixture(scope="session", autouse=True)
def configure_sqlite_spatial():
    """Configure SQLite to support GeoAlchemy2 Geometry types without SpatiaLite in unit tests."""
    sqlite_admin.after_create = lambda *args, **kw: None
    sqlite_admin.before_create = lambda *args, **kw: None
    sqlite_admin.create_spatial_index = lambda *args, **kw: None
    sqlite_admin.after_drop = lambda *args, **kw: None
    sqlite_admin.before_drop = lambda *args, **kw: None

    @compiles(Geometry, "sqlite")
    def compile_geom_sqlite(type_, compiler, **kw):
        return "TEXT"

    # Remove spatial index from table metadata if targeting SQLite
    for table in Base.metadata.tables.values():
        for idx in list(table.indexes):
            if any(col.name == "geometry" for col in idx.columns):
                table.indexes.remove(idx)


@pytest.fixture
def db_session() -> Session:
    """Create an isolated in-memory SQLite database session for unit tests."""
    engine = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(engine, "connect")
    def setup_spatial_functions(dbapi_connection, connection_record):
        def to_wkb(val):
            if val is None:
                return None
            try:
                clean = val.split(";", 1)[-1] if ";" in val else val
                return shapely.wkt.loads(clean).wkb_hex
            except Exception:
                return shapely.wkt.loads("POINT(0 0)").wkb_hex

        dbapi_connection.create_function("GeomFromEWKT", 1, to_wkb)
        dbapi_connection.create_function("ST_GeomFromEWKT", 1, to_wkb)
        dbapi_connection.create_function("AsEWKB", 1, lambda x: x)
        dbapi_connection.create_function("ST_AsEWKB", 1, lambda x: x)

    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _create_sample_payload(
    incident_id: str = "INC-001",
    facility_id: str = "FAC_22.30_70.80",
    hazard_type: str = "gas_flare",
    severity_level: str = "RED",
    timestamp: datetime = None,
) -> PipelineIncident:
    """Helper to construct a valid PipelineIncident test payload."""
    if timestamp is None:
        timestamp = datetime(2026, 8, 30, 14, 30, 0, tzinfo=timezone.utc)

    return PipelineIncident(
        incident_id=incident_id,
        facility_id=facility_id,
        latitude=22.3039,
        longitude=70.8022,
        timestamp_utc=timestamp,
        satellite_source="VIIRS-NOAA20",
        hazard_type=hazard_type,
        confidence_score=0.95,
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
        severity_level=severity_level,
    )


def test_save_and_retrieve_incident(db_session: Session):
    """Test persisting a single incident and retrieving it by incident_id."""
    payload = _create_sample_payload("INC-101", facility_id="FAC_JAMNAGAR_01")
    incident = save_incident(db_session, payload, hotspot_id=42)

    assert incident.id is not None
    assert incident.incident_id == "INC-101"
    assert incident.facility_id == "FAC_JAMNAGAR_01"
    assert incident.hotspot_id == 42
    assert incident.severity_level == "RED"
    assert incident.hazard_type == "gas_flare"

    # Retrieve from DB
    retrieved = get_incident_by_id(db_session, "INC-101")
    assert retrieved is not None
    assert retrieved.incident_id == "INC-101"
    assert retrieved.temp_mir_k == 365.2
    assert retrieved.frp_mw == 18.5


def test_save_incident_rollback_on_duplicate(db_session: Session):
    """Test that save_incident triggers db.rollback() when uniqueness constraint is violated."""
    payload1 = _create_sample_payload("INC-DUP")
    save_incident(db_session, payload1)

    payload2 = _create_sample_payload("INC-DUP")
    with pytest.raises(Exception):
        save_incident(db_session, payload2)

    # Session should still be usable after rollback
    payload3 = _create_sample_payload("INC-OTHER")
    inc3 = save_incident(db_session, payload3)
    assert inc3.incident_id == "INC-OTHER"


def test_save_incidents_batch_success(db_session: Session):
    """Test batch persistence with hotspot_ids mapping."""
    payloads = [
        _create_sample_payload("INC-B1", facility_id="FAC_1", severity_level="RED"),
        _create_sample_payload("INC-B2", facility_id="FAC_2", severity_level="AMBER"),
        _create_sample_payload("INC-B3", facility_id=None, severity_level="GREEN"),
    ]
    hotspot_ids = [10, 20, None]

    results = save_incidents_batch(db_session, payloads, hotspot_ids=hotspot_ids)

    assert len(results) == 3
    assert results[0].incident_id == "INC-B1"
    assert results[0].hotspot_id == 10
    assert results[1].incident_id == "INC-B2"
    assert results[1].hotspot_id == 20
    assert results[2].incident_id == "INC-B3"
    assert results[2].hotspot_id is None


def test_save_incidents_batch_empty_and_default_hotspot(db_session: Session):
    """Test batch persistence with empty sequence and default_hotspot_id."""
    assert save_incidents_batch(db_session, []) == []

    payloads = [_create_sample_payload("INC-DEF1"), _create_sample_payload("INC-DEF2")]
    results = save_incidents_batch(db_session, payloads, default_hotspot_id=99)
    assert len(results) == 2
    assert results[0].hotspot_id == 99
    assert results[1].hotspot_id == 99


def test_save_incidents_batch_length_mismatch(db_session: Session):
    """Test that mismatched hotspot_ids length raises ValueError."""
    payloads = [_create_sample_payload("INC-M1"), _create_sample_payload("INC-M2")]
    with pytest.raises(ValueError, match="Length of hotspot_ids"):
        save_incidents_batch(db_session, payloads, hotspot_ids=[1])


def test_save_incidents_batch_rollback_on_failure(db_session: Session):
    """Test that a failure in batch persistence rolls back all records in the batch."""
    # First save an existing record
    save_incident(db_session, _create_sample_payload("INC-CONFLICT"))

    # Attempt to batch insert where one record causes a duplicate key violation
    batch = [
        _create_sample_payload("INC-NEW1"),
        _create_sample_payload("INC-CONFLICT"),  # Duplicate!
    ]

    with pytest.raises(Exception):
        save_incidents_batch(db_session, batch)

    # INC-NEW1 should not have been committed due to rollback
    assert get_incident_by_id(db_session, "INC-NEW1") is None


def test_get_incidents_filtering_and_pagination(db_session: Session):
    """Test querying incidents with filters and pagination."""
    t0 = datetime(2026, 8, 30, 10, 0, 0, tzinfo=timezone.utc)
    incidents_data = [
        _create_sample_payload("INC-F1", facility_id="FAC_A", hazard_type="industrial", severity_level="RED", timestamp=t0),
        _create_sample_payload("INC-F2", facility_id="FAC_A", hazard_type="gas_flare", severity_level="RED", timestamp=t0 + timedelta(hours=1)),
        _create_sample_payload("INC-F3", facility_id="FAC_B", hazard_type="wildfire", severity_level="AMBER", timestamp=t0 + timedelta(hours=2)),
        _create_sample_payload("INC-F4", facility_id="FAC_B", hazard_type="agricultural_burn", severity_level="GREEN", timestamp=t0 + timedelta(hours=3)),
    ]
    save_incidents_batch(db_session, incidents_data)

    # Filter by severity
    red_incidents = get_incidents(db_session, severity_level="RED")
    assert len(red_incidents) == 2

    # Filter by hazard_type
    wildfire_incidents = get_incidents(db_session, hazard_type="wildfire")
    assert len(wildfire_incidents) == 1
    assert wildfire_incidents[0].incident_id == "INC-F3"

    # Filter by facility_id
    fac_a_incidents = get_incidents(db_session, facility_id="FAC_A")
    assert len(fac_a_incidents) == 2

    # Filter by time range
    time_filtered = get_incidents(
        db_session,
        start_time=t0 + timedelta(hours=1),
        end_time=t0 + timedelta(hours=2, minutes=30),
    )
    assert len(time_filtered) == 2

    # Pagination: limit & offset
    paginated = get_incidents(db_session, limit=2, offset=1)
    assert len(paginated) == 2


def test_incident_to_pipeline_schema_reconstitution(db_session: Session):
    """Test bidirectional mapping from ORM back to PipelineIncident Pydantic schema."""
    payload = _create_sample_payload(
        incident_id="INC-RECON",
        facility_id="FAC_RECON_99",
        hazard_type="mining",
        severity_level="AMBER",
    )
    incident_orm = save_incident(db_session, payload)

    reconstituted = incident_to_pipeline_schema(incident_orm)

    assert isinstance(reconstituted, PipelineIncident)
    assert reconstituted.incident_id == payload.incident_id
    assert reconstituted.facility_id == payload.facility_id
    assert reconstituted.latitude == payload.latitude
    assert reconstituted.longitude == payload.longitude
    assert reconstituted.hazard_type == payload.hazard_type
    assert reconstituted.severity_level == payload.severity_level
    assert reconstituted.metrics.temp_mir_k == payload.metrics.temp_mir_k
    assert reconstituted.metrics.frp_spike_ratio == payload.metrics.frp_spike_ratio
    assert reconstituted.validation.historical_pass_count == payload.validation.historical_pass_count
    assert reconstituted.validation.is_glint == payload.validation.is_glint
