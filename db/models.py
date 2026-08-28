"""SQLAlchemy 2.x ORM models with PostGIS spatial extension support via GeoAlchemy2.

Tables:
- facilities: Known industrial sites with Point or Polygon geometries.
- hotspots: Satellite-detected thermal anomalies enriched with spatial metrics.
- classified_hotspots: Final classification predictions with confidence scores.
"""

from datetime import date, datetime
from typing import Any, Optional
from geoalchemy2 import Geometry
from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models."""
    pass


class Facility(Base):
    """Represents an industrial facility or plant with geographic boundaries/coordinates."""

    __tablename__ = "facilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    facility_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    hotspots: Mapped[list["Hotspot"]] = relationship("Hotspot", back_populates="facility")

    def __repr__(self) -> str:
        return f"<Facility(id={self.id}, name='{self.name}', type='{self.facility_type}')>"


class Hotspot(Base):
    """Represents a thermal anomaly observation enriched with contextual data."""

    __tablename__ = "hotspots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    brightness: Mapped[float] = mapped_column(Float, nullable=False)
    frp: Mapped[float] = mapped_column(Float, nullable=False)
    acq_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    acq_time: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[str] = mapped_column(String(50), nullable=False)
    satellite: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Enrichment fields
    nearest_facility_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("facilities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    distance_to_facility_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    landcover_class: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    persistence_days: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
    )

    # PostGIS Point geometry (WGS84 EPSG:4326)
    geometry: Mapped[Optional[Any]] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    facility: Mapped[Optional["Facility"]] = relationship("Facility", back_populates="hotspots")
    classification: Mapped[Optional["ClassifiedHotspot"]] = relationship(
        "ClassifiedHotspot",
        back_populates="hotspot",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Hotspot(id={self.id}, lat={self.lat}, lon={self.lon}, acq_date={self.acq_date})>"


class ClassifiedHotspot(Base):
    """Represents the classification prediction for a given hotspot."""

    __tablename__ = "classified_hotspots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hotspot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("hotspots.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    predicted_class: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )  # industrial, gas_flare, agricultural_burn, mining, wildfire, unknown
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    hotspot: Mapped["Hotspot"] = relationship("Hotspot", back_populates="classification")

    def __repr__(self) -> str:
        return f"<ClassifiedHotspot(id={self.id}, hotspot_id={self.hotspot_id}, class='{self.predicted_class}', score={self.confidence_score:.2f})>"
