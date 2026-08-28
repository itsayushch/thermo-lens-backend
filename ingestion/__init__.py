"""Ingestion Module - Satellite Thermal Anomaly Feeds.

Module Ownership: Ingestion Engineer
Responsibilities:
- Ingest active fire detections from NASA FIRMS API (VIIRS / MODIS)
- Parse raw satellite sensor feeds into RawHotspot Pydantic models
- Persist ingested raw observations into PostgreSQL
"""
