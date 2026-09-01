"""Unit tests for the NASA FIRMS CSV ingestion module."""

from datetime import date
from pathlib import Path
import pytest
from pydantic import ValidationError

from ingestion.firms import parse_firms_csv, parse_firms_csv_text
from shared.schemas import RawHotspot
from services.hotspots import estimate_affected_radius_m, get_hotspot_feature_collection


def test_parse_standard_firms_csv(tmp_path: Path):
    """Test parsing a standard FIRMS CSV file with standard column names."""
    csv_content = (
        "latitude,longitude,brightness,frp,acq_date,acq_time,confidence,satellite\n"
        "28.6139,77.2090,345.5,12.8,2026-08-28,1430,nominal,VIIRS-NOAA20\n"
        "19.0760,72.8777,360.2,45.1,2026-08-28,0345,high,VIIRS-SNPP\n"
    )
    csv_file = tmp_path / "firms_standard.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    hotspots = parse_firms_csv(csv_file)

    assert len(hotspots) == 2
    assert all(isinstance(h, RawHotspot) for h in hotspots)

    h1 = hotspots[0]
    assert h1.lat == 28.6139
    assert h1.lon == 77.2090
    assert h1.brightness == 345.5
    assert h1.frp == 12.8
    assert h1.acq_date == date(2026, 8, 28)
    assert h1.acq_time == "1430"
    assert h1.confidence == "nominal"
    assert h1.satellite == "VIIRS-NOAA20"

    h2 = hotspots[1]
    assert h2.lat == 19.0760
    assert h2.lon == 72.8777
    assert h2.brightness == 360.2
    assert h2.frp == 45.1
    assert h2.acq_date == date(2026, 8, 28)
    assert h2.acq_time == "0345"
    assert h2.confidence == "high"
    assert h2.satellite == "VIIRS-SNPP"


def test_parse_viirs_nasa_csv_format(tmp_path: Path):
    """Test parsing NASA VIIRS CSV export format (bright_ti4, single-letter satellite codes)."""
    csv_content = (
        "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
        "22.3039,70.8022,332.4,0.4,0.6,2026-08-28,345,N,VIIRS,n,2.0NRT,295.1,8.4,N\n"
        "21.1702,72.8311,351.0,0.5,0.6,2026-08-28,1430,1,VIIRS,h,2.0NRT,301.2,22.0,D\n"
    )
    csv_file = tmp_path / "viirs_nasa.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    hotspots = parse_firms_csv(csv_file)

    assert len(hotspots) == 2
    # Row 1 with satellite 'N' mapped to 'VIIRS-SNPP' and acq_time '345' zero-padded to '0345'
    assert hotspots[0].lat == 22.3039
    assert hotspots[0].lon == 70.8022
    assert hotspots[0].brightness == 332.4
    assert hotspots[0].frp == 8.4
    assert hotspots[0].acq_time == "0345"
    assert hotspots[0].satellite == "VIIRS-SNPP"
    assert hotspots[0].confidence == "n"

    # Row 2 with satellite '1' mapped to 'VIIRS-NOAA20'
    assert hotspots[1].lat == 21.1702
    assert hotspots[1].lon == 72.8311
    assert hotspots[1].brightness == 351.0
    assert hotspots[1].frp == 22.0
    assert hotspots[1].acq_time == "1430"
    assert hotspots[1].satellite == "VIIRS-NOAA20"
    assert hotspots[1].confidence == "h"


def test_parse_modis_nasa_csv_format(tmp_path: Path):
    """Test parsing NASA MODIS CSV export format (numeric confidence, satellite 'T' -> 'MODIS-Terra')."""
    csv_content = (
        "latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight\n"
        "23.0225,72.5714,318.6,1.0,1.0,2026-08-28,0530,T,MODIS,85,6.1NRT,290.0,15.2,D\n"
        "13.0827,80.2707,325.1,1.1,1.0,2026-08-28,0615,A,MODIS,92,6.1NRT,292.4,19.7,D\n"
    )
    csv_file = tmp_path / "modis_nasa.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    hotspots = parse_firms_csv(csv_file)

    assert len(hotspots) == 2
    assert hotspots[0].satellite == "MODIS-Terra"
    assert hotspots[0].confidence == "85"
    assert hotspots[1].satellite == "MODIS-Aqua"
    assert hotspots[1].confidence == "92"


def test_handle_invalid_and_missing_rows_cleanly(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    """Test that invalid/corrupted rows are logged and skipped without failing the entire batch."""
    csv_content = (
        "latitude,longitude,brightness,frp,acq_date,acq_time,confidence,satellite\n"
        "28.6139,77.2090,345.5,12.8,2026-08-28,1430,nominal,VIIRS-NOAA20\n"
        "invalid_lat,77.2090,345.5,12.8,2026-08-28,1430,nominal,VIIRS-NOAA20\n"  # Invalid lat (non-numeric)
        "120.5000,77.2090,345.5,12.8,2026-08-28,1430,nominal,VIIRS-NOAA20\n"  # Latitude out of bounds (> 90.0)
        "28.6139,77.2090,-10.0,12.8,2026-08-28,1430,nominal,VIIRS-NOAA20\n"  # Brightness <= 0
        "28.6139,77.2090,345.5,12.8,invalid-date,1430,nominal,VIIRS-NOAA20\n"  # Invalid date
        ",77.2090,345.5,12.8,2026-08-28,1430,nominal,VIIRS-NOAA20\n"  # Missing lat
        "19.0760,72.8777,360.2,45.1,2026-08-28,0345,high,VIIRS-SNPP\n"  # Valid row
        "\n"  # Empty line
    )
    csv_file = tmp_path / "mixed_firms.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    with caplog.at_level("WARNING"):
        hotspots = parse_firms_csv(csv_file, strict=False)

    # Only the 2 valid rows should be returned
    assert len(hotspots) == 2
    assert hotspots[0].lat == 28.6139
    assert hotspots[1].lat == 19.0760

    # Warnings should have been logged for the invalid rows
    assert "Failed to parse FIRMS CSV row" in caplog.text


def test_strict_mode_raises_on_invalid_row(tmp_path: Path):
    """Test that strict=True raises an exception when encountering an invalid row."""
    csv_content = (
        "latitude,longitude,brightness,frp,acq_date,acq_time,confidence,satellite\n"
        "28.6139,77.2090,345.5,12.8,2026-08-28,1430,nominal,VIIRS-NOAA20\n"
        "999.0,77.2090,345.5,12.8,2026-08-28,1430,nominal,VIIRS-NOAA20\n"
    )
    csv_file = tmp_path / "invalid_row.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    with pytest.raises(ValidationError):
        parse_firms_csv(csv_file, strict=True)


def test_missing_file_raises_not_found(tmp_path: Path):
    """Test that non-existent file raises FileNotFoundError."""
    non_existent = tmp_path / "does_not_exist.csv"
    with pytest.raises(FileNotFoundError):
        parse_firms_csv(non_existent)


def test_missing_coordinate_headers_raises_value_error(tmp_path: Path):
    """Test that CSV missing coordinate headers raises ValueError."""
    csv_content = "some_col,another_col,value\n1,2,3\n"
    csv_file = tmp_path / "no_coords.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    with pytest.raises(ValueError, match="missing required coordinate columns"):
        parse_firms_csv(csv_file)


def test_empty_file_returns_empty_list(tmp_path: Path):
    """Test that an empty CSV file returns an empty list without error."""
    csv_file = tmp_path / "empty.csv"
    csv_file.write_text("", encoding="utf-8")

    hotspots = parse_firms_csv(csv_file)
    assert hotspots == []


def test_satellite_default_fallback(tmp_path: Path):
    """Test using default_satellite parameter when satellite column is missing in CSV."""
    csv_content = (
        "lat,lon,brightness,frp,acq_date,acq_time,confidence\n"
        "28.6139,77.2090,345.5,12.8,2026-08-28,1430,nominal\n"
    )
    csv_file = tmp_path / "no_satellite_col.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    hotspots = parse_firms_csv(csv_file, default_satellite="VIIRS-NOAA20")
    assert len(hotspots) == 1
    assert hotspots[0].satellite == "VIIRS-NOAA20"


def test_parse_firms_csv_text_from_api_response():
    """Test parsing FIRMS CSV text without writing a temporary file."""
    csv_content = (
        "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
        "22.3039,70.8022,332.4,0.4,0.6,2026-08-28,345,N,VIIRS,n,2.0NRT,295.1,8.4,N\n"
    )

    hotspots = parse_firms_csv_text(csv_content)

    assert len(hotspots) == 1
    assert hotspots[0].lat == 22.3039
    assert hotspots[0].lon == 70.8022
    assert hotspots[0].brightness == 332.4
    assert hotspots[0].frp == 8.4
    assert hotspots[0].acq_time == "0345"
    assert hotspots[0].satellite == "VIIRS-SNPP"


def test_estimate_affected_radius_uses_sensor_scale():
    viirs = RawHotspot(
        lat=22.3039,
        lon=70.8022,
        brightness=332.4,
        frp=8.4,
        acq_date=date(2026, 8, 28),
        acq_time="0345",
        confidence="h",
        satellite="VIIRS-SNPP",
    )
    modis = RawHotspot(
        lat=22.3039,
        lon=70.8022,
        brightness=332.4,
        frp=8.4,
        acq_date=date(2026, 8, 28),
        acq_time="0345",
        confidence="85",
        satellite="MODIS-Terra",
    )

    assert 150 <= estimate_affected_radius_m(viirs) < estimate_affected_radius_m(modis)
    assert estimate_affected_radius_m(modis) <= 1200


def test_default_hotspot_source_aggregates_viirs_feeds(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("services.hotspots._fetch_live_firms_hotspots_cached", lambda *args: ())
    monkeypatch.setattr("services.hotspots._local_csv_hotspots", lambda: [])

    collection = get_hotspot_feature_collection(
        bbox=None,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 1),
        hotspot_class=None,
    )

    assert collection["metadata"]["firms_sources"] == [
        "VIIRS_SNPP_NRT",
        "VIIRS_NOAA20_NRT",
        "VIIRS_NOAA21_NRT",
    ]
