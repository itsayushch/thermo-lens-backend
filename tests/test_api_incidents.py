"""API integration and unit tests for /incidents endpoints."""

from datetime import datetime, timezone, timedelta
import pytest
import shapely.wkt
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.ext.compiler import compiles
from geoalchemy2 import Geometry
import geoalchemy2.admin.dialects.sqlite as sqlite_admin

from api.main import app
from db.models import Base
from db.session import get_db


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

    for table in Base.metadata.tables.values():
        for idx in list(table.indexes):
            if any(col.name == "geometry" for col in idx.columns):
                table.indexes.remove(idx)


from sqlalchemy.pool import StaticPool


@pytest.fixture
def client() -> TestClient:
    """Create a FastAPI TestClient with an isolated in-memory SQLite database."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

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

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)



def _sample_incident_payload(
    incident_id: str = "INC-API-001",
    facility_id: str = "FAC_22.30_70.80",
    hazard_type: str = "gas_flare",
    severity_level: str = "RED",
    timestamp_utc: str = "2026-08-30T14:30:00Z",
) -> dict:
    """Generate a dictionary payload matching PipelineIncident schema."""
    return {
        "incident_id": incident_id,
        "facility_id": facility_id,
        "latitude": 22.3039,
        "longitude": 70.8022,
        "timestamp_utc": timestamp_utc,
        "satellite_source": "VIIRS-NOAA20",
        "hazard_type": hazard_type,
        "confidence_score": 0.95,
        "metrics": {
            "temp_mir_k": 365.2,
            "temp_tir_k": 295.4,
            "frp_mw": 18.5,
            "frp_spike_ratio": 2.4,
        },
        "validation": {
            "historical_pass_count": 14,
            "osm_landuse": "industrial",
            "is_glint": False,
        },
        "severity_level": severity_level,
    }


def test_create_incident_success(client: TestClient):
    """POST /incidents: Should return 201 Created and return the created PipelineIncident."""
    payload = _sample_incident_payload("INC-CREATE-001")
    response = client.post("/incidents", json=payload)

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["incident_id"] == "INC-CREATE-001"
    assert data["facility_id"] == "FAC_22.30_70.80"
    assert data["severity_level"] == "RED"
    assert data["hazard_type"] == "gas_flare"
    assert data["metrics"]["temp_mir_k"] == 365.2


def test_create_incident_duplicate_returns_409(client: TestClient):
    """POST /incidents: Submitting an existing incident_id should return 409 Conflict."""
    payload = _sample_incident_payload("INC-DUP-001")
    res1 = client.post("/incidents", json=payload)
    assert res1.status_code == status.HTTP_201_CREATED

    res2 = client.post("/incidents", json=payload)
    assert res2.status_code == status.HTTP_409_CONFLICT
    assert "already exists" in res2.json()["detail"]


def test_create_incident_validation_error_returns_422(client: TestClient):
    """POST /incidents: Invalid schema inputs should return 422 Unprocessable Entity."""
    # Test invalid latitude (> 90.0)
    payload_invalid_lat = _sample_incident_payload("INC-ERR-001")
    payload_invalid_lat["latitude"] = 120.0
    res_lat = client.post("/incidents", json=payload_invalid_lat)
    assert res_lat.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Test invalid severity_level (not RED, AMBER, GREEN)
    payload_invalid_sev = _sample_incident_payload("INC-ERR-002")
    payload_invalid_sev["severity_level"] = "BLUE"
    res_sev = client.post("/incidents", json=payload_invalid_sev)
    assert res_sev.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Test negative temperature in metrics
    payload_invalid_temp = _sample_incident_payload("INC-ERR-003")
    payload_invalid_temp["metrics"]["temp_mir_k"] = -5.0
    res_temp = client.post("/incidents", json=payload_invalid_temp)
    assert res_temp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_get_incident_by_id_success_and_404(client: TestClient):
    """GET /incidents/{incident_id}: Returns 200 when found, 404 when not found."""
    # Query non-existent incident
    res_404 = client.get("/incidents/NON_EXISTENT_INCIDENT")
    assert res_404.status_code == status.HTTP_404_NOT_FOUND

    # Create and query
    payload = _sample_incident_payload("INC-LOOKUP-001", facility_id="FAC_TEST_99")
    client.post("/incidents", json=payload)

    res_200 = client.get("/incidents/INC-LOOKUP-001")
    assert res_200.status_code == status.HTTP_200_OK
    data = res_200.json()
    assert data["incident_id"] == "INC-LOOKUP-001"
    assert data["facility_id"] == "FAC_TEST_99"


def test_list_incidents_filtering_and_pagination(client: TestClient):
    """GET /incidents: Validates filtering and pagination parameters."""
    t0 = "2026-08-30T10:00:00Z"
    t1 = "2026-08-30T11:00:00Z"
    t2 = "2026-08-30T12:00:00Z"

    # Seed test records
    client.post("/incidents", json=_sample_incident_payload("INC-L1", facility_id="FAC_X", hazard_type="industrial", severity_level="RED", timestamp_utc=t0))
    client.post("/incidents", json=_sample_incident_payload("INC-L2", facility_id="FAC_X", hazard_type="gas_flare", severity_level="RED", timestamp_utc=t1))
    client.post("/incidents", json=_sample_incident_payload("INC-L3", facility_id="FAC_Y", hazard_type="wildfire", severity_level="AMBER", timestamp_utc=t2))

    # Filter by severity
    res_red = client.get("/incidents?severity_level=RED")
    assert res_red.status_code == status.HTTP_200_OK
    assert len(res_red.json()) == 2

    # Filter by hazard_type
    res_wildfire = client.get("/incidents?hazard_type=wildfire")
    assert res_wildfire.status_code == status.HTTP_200_OK
    assert len(res_wildfire.json()) == 1
    assert res_wildfire.json()[0]["incident_id"] == "INC-L3"

    # Filter by facility_id
    res_fac_x = client.get("/incidents?facility_id=FAC_X")
    assert res_fac_x.status_code == status.HTTP_200_OK
    assert len(res_fac_x.json()) == 2

    # Pagination: limit & offset
    res_paged = client.get("/incidents?limit=2&offset=1")
    assert res_paged.status_code == status.HTTP_200_OK
    assert len(res_paged.json()) == 2
