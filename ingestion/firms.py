"""NASA FIRMS Active Fire / Hotspot CSV Ingestion Module.

Parses active fire / thermal anomaly CSV data feeds from NASA FIRMS (VIIRS and MODIS),
validates data integrity against the RawHotspot Pydantic contract, and returns
clean, structured hotspot observations.
"""

from datetime import date, datetime
import csv
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union
from pydantic import ValidationError

from shared.schemas import RawHotspot

logger = logging.getLogger(__name__)

# Standard NASA FIRMS satellite code mappings
SATELLITE_CODE_MAP: Dict[str, str] = {
    "N": "VIIRS-SNPP",
    "SNPP": "VIIRS-SNPP",
    "1": "VIIRS-NOAA20",
    "J1": "VIIRS-NOAA20",
    "NOAA-20": "VIIRS-NOAA20",
    "NOAA20": "VIIRS-NOAA20",
    "2": "VIIRS-NOAA21",
    "J2": "VIIRS-NOAA21",
    "NOAA-21": "VIIRS-NOAA21",
    "NOAA21": "VIIRS-NOAA21",
    "T": "MODIS-Terra",
    "TERRA": "MODIS-Terra",
    "A": "MODIS-Aqua",
    "AQUA": "MODIS-Aqua",
}

# Column candidates for matching FIRMS CSV headers
COLUMN_ALIASES: Dict[str, List[str]] = {
    "lat": ["latitude", "lat"],
    "lon": ["longitude", "lon", "long"],
    "brightness": ["brightness", "bright_ti4", "bright_t31", "bright_ti5"],
    "frp": ["frp", "frp_mw"],
    "acq_date": ["acq_date", "acqdate", "date"],
    "acq_time": ["acq_time", "acqtime", "time"],
    "confidence": ["confidence", "conf"],
    "satellite": ["satellite", "satellite_name", "sat", "instrument"],
}


def _normalize_header_name(header: str) -> str:
    """Normalize a CSV header string to lowercase trimmed snake_case."""
    return header.strip().lower().replace(" ", "_")


def _find_column_key(normalized_row: Dict[str, Any], canonical_key: str) -> Optional[str]:
    """Find the first matching column name from aliases present in the normalized row."""
    aliases = COLUMN_ALIASES.get(canonical_key, [canonical_key])
    for alias in aliases:
        if alias in normalized_row:
            return alias
    return None


def _format_acq_time(raw_time: Any) -> str:
    """Format acquisition time into a 4-digit HHMM string or clean string.
    
    Handles inputs like '345', 345 -> '0345', '1430' -> '1430', '14:30' -> '1430'.
    """
    if raw_time is None:
        raise ValueError("acq_time cannot be null")
    
    time_str = str(raw_time).strip()
    if not time_str:
        raise ValueError("acq_time cannot be empty")

    # If format is HH:MM, remove the colon
    if ":" in time_str:
        time_str = time_str.replace(":", "")

    # If it is numeric and shorter than 4 digits (e.g., '345' -> '0345')
    if time_str.isdigit() and len(time_str) < 4:
        time_str = time_str.zfill(4)

    return time_str


def _normalize_satellite(raw_sat: Any, default_satellite: Optional[str] = None) -> str:
    """Resolve satellite codes (e.g. 'N', '1', 'T') to descriptive satellite names."""
    if raw_sat is not None:
        sat_str = str(raw_sat).strip()
        if sat_str:
            sat_upper = sat_str.upper()
            if sat_upper in SATELLITE_CODE_MAP:
                return SATELLITE_CODE_MAP[sat_upper]
            return sat_str
    
    if default_satellite:
        return default_satellite.strip()

    raise ValueError("satellite information is missing")


def _parse_row_to_raw_hotspot(
    row: Dict[str, str],
    row_number: int,
    default_satellite: Optional[str] = None,
) -> RawHotspot:
    """Map and validate a single CSV row dictionary into a RawHotspot model.
    
    Raises:
        ValueError: If mandatory columns are missing or values cannot be converted.
        ValidationError: If Pydantic schema validation fails.
    """
    # Create normalized lookup dictionary (stripped lowercase keys and values)
    norm_row = {_normalize_header_name(k): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k is not None}

    # Find latitude
    lat_key = _find_column_key(norm_row, "lat")
    if not lat_key or norm_row[lat_key] == "" or norm_row[lat_key] is None:
        raise ValueError(f"Missing latitude in row {row_number}")
    lat_val = float(norm_row[lat_key])

    # Find longitude
    lon_key = _find_column_key(norm_row, "lon")
    if not lon_key or norm_row[lon_key] == "" or norm_row[lon_key] is None:
        raise ValueError(f"Missing longitude in row {row_number}")
    lon_val = float(norm_row[lon_key])

    # Find brightness
    bright_key = _find_column_key(norm_row, "brightness")
    if not bright_key or norm_row[bright_key] == "" or norm_row[bright_key] is None:
        raise ValueError(f"Missing brightness temperature in row {row_number}")
    bright_val = float(norm_row[bright_key])

    # Find FRP (Fire Radiative Power)
    frp_key = _find_column_key(norm_row, "frp")
    if frp_key and norm_row[frp_key] not in ("", None):
        frp_val = float(norm_row[frp_key])
    else:
        # Default FRP to 0.0 if not present in CSV
        frp_val = 0.0

    # Find acq_date
    date_key = _find_column_key(norm_row, "acq_date")
    if not date_key or norm_row[date_key] == "" or norm_row[date_key] is None:
        raise ValueError(f"Missing acq_date in row {row_number}")
    raw_date_str = str(norm_row[date_key]).replace("/", "-")
    # Validate date parseable
    acq_date_val = date.fromisoformat(raw_date_str)

    # Find acq_time
    time_key = _find_column_key(norm_row, "acq_time")
    if not time_key or norm_row[time_key] == "" or norm_row[time_key] is None:
        raise ValueError(f"Missing acq_time in row {row_number}")
    acq_time_val = _format_acq_time(norm_row[time_key])

    # Find confidence
    conf_key = _find_column_key(norm_row, "confidence")
    if not conf_key or norm_row[conf_key] == "" or norm_row[conf_key] is None:
        # Fallback to nominal if confidence column missing
        confidence_val = "nominal"
    else:
        confidence_val = str(norm_row[conf_key])

    # Find satellite
    sat_key = _find_column_key(norm_row, "satellite")
    raw_sat = norm_row[sat_key] if sat_key else None
    satellite_val = _normalize_satellite(raw_sat, default_satellite=default_satellite)

    # Construct and validate through RawHotspot schema
    return RawHotspot(
        lat=lat_val,
        lon=lon_val,
        brightness=bright_val,
        frp=frp_val,
        acq_date=acq_date_val,
        acq_time=acq_time_val,
        confidence=confidence_val,
        satellite=satellite_val,
    )


def parse_firms_csv(
    file_path: Union[str, Path],
    default_satellite: Optional[str] = None,
    strict: bool = False,
) -> List[RawHotspot]:
    """Parse a NASA FIRMS CSV file and validate rows into RawHotspot Pydantic models.

    Supports standard NASA FIRMS VIIRS (SNPP, NOAA-20, NOAA-21) and MODIS (Terra, Aqua) CSV formats,
    as well as standardized FIRMS CSV exports.

    Args:
        file_path: Path to the FIRMS CSV file.
        default_satellite: Fallback satellite platform name (e.g., 'VIIRS-NOAA20') if
            the satellite column is missing or blank in the CSV.
        strict: If True, raises on the first invalid row encountered. If False (default),
            logs a warning for malformed rows and continues parsing valid observations.

    Returns:
        List of validated RawHotspot objects.

    Raises:
        FileNotFoundError: If the specified file_path does not exist.
        ValueError: If the file is empty or missing essential required columns.
        ValidationError: If strict=True and a row fails schema validation.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"FIRMS CSV file not found: {path.resolve()}")

    hotspots: List[RawHotspot] = []
    error_count = 0

    with open(path, mode="r", encoding="utf-8-sig", newline="") as csvfile:
        # Read header and check if empty
        reader = csv.DictReader(csvfile)
        if reader.fieldnames is None:
            logger.warning("FIRMS CSV file is empty: %s", path)
            return []

        # Validate that essential geographic coordinate columns exist in the header
        normalized_headers = {_normalize_header_name(h) for h in reader.fieldnames if h}
        has_lat = any(alias in normalized_headers for alias in COLUMN_ALIASES["lat"])
        has_lon = any(alias in normalized_headers for alias in COLUMN_ALIASES["lon"])

        if not has_lat or not has_lon:
            raise ValueError(
                f"FIRMS CSV file '{path.name}' is missing required coordinate columns (lat/latitude, lon/longitude). "
                f"Found headers: {reader.fieldnames}"
            )

        for row_idx, row in enumerate(reader, start=2):  # start=2 considering header is line 1
            # Skip empty rows (e.g. blank lines at the end of CSV)
            if not row or all(v is None or str(v).strip() == "" for v in row.values()):
                continue

            try:
                hotspot = _parse_row_to_raw_hotspot(
                    row=row,
                    row_number=row_idx,
                    default_satellite=default_satellite,
                )
                hotspots.append(hotspot)
            except (ValidationError, ValueError, TypeError, KeyError) as exc:
                error_count += 1
                error_msg = f"Failed to parse FIRMS CSV row {row_idx} in '{path.name}': {exc}"
                if strict:
                    logger.error(error_msg)
                    raise
                logger.warning(error_msg)

    if error_count > 0:
        logger.info(
            "Parsed %d valid hotspots from '%s' (%d invalid rows skipped).",
            len(hotspots),
            path.name,
            error_count,
        )
    else:
        logger.info("Successfully parsed %d hotspots from '%s'.", len(hotspots), path.name)

    return hotspots


def parse_firms_csv_rows(
    rows: Iterable[Dict[str, str]],
    default_satellite: Optional[str] = None,
    strict: bool = False,
) -> List[RawHotspot]:
    """Parse in-memory FIRMS CSV rows into validated RawHotspot models."""
    hotspots: List[RawHotspot] = []
    error_count = 0

    for row_idx, row in enumerate(rows, start=2):
        if not row or all(v is None or str(v).strip() == "" for v in row.values()):
            continue

        try:
            hotspot = _parse_row_to_raw_hotspot(
                row=row,
                row_number=row_idx,
                default_satellite=default_satellite,
            )
            hotspots.append(hotspot)
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            error_count += 1
            error_msg = f"Failed to parse FIRMS CSV row {row_idx}: {exc}"
            if strict:
                logger.error(error_msg)
                raise
            logger.warning(error_msg)

    if error_count > 0:
        logger.info(
            "Parsed %d valid in-memory FIRMS hotspots (%d invalid rows skipped).",
            len(hotspots),
            error_count,
        )

    return hotspots


def parse_firms_csv_text(
    csv_text: str,
    default_satellite: Optional[str] = None,
    strict: bool = False,
) -> List[RawHotspot]:
    """Parse FIRMS CSV text returned by the NASA API."""
    reader = csv.DictReader(csv_text.splitlines())
    if reader.fieldnames is None:
        return []

    normalized_headers = {_normalize_header_name(h) for h in reader.fieldnames if h}
    has_lat = any(alias in normalized_headers for alias in COLUMN_ALIASES["lat"])
    has_lon = any(alias in normalized_headers for alias in COLUMN_ALIASES["lon"])
    if not has_lat or not has_lon:
        raise ValueError(
            "FIRMS CSV text is missing required coordinate columns "
            f"(lat/latitude, lon/longitude). Found headers: {reader.fieldnames}"
        )

    return parse_firms_csv_rows(
        reader,
        default_satellite=default_satellite,
        strict=strict,
    )
