"""0002_add_incidents_table

Add incidents table to persist verified AI/ML pipeline incident outputs
with PostGIS spatial indexing.

Revision ID: 0002_add_incidents_table
Revises: 0001_initial_schema
Create Date: 2026-08-30 00:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import geoalchemy2

# revision identifiers, used by Alembic.
revision: str = "0002_add_incidents_table"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("incident_id", sa.String(length=100), nullable=False),
        sa.Column("facility_id", sa.String(length=100), nullable=True),
        sa.Column("hotspot_id", sa.Integer(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("timestamp_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("satellite_source", sa.String(length=50), nullable=False),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(
                geometry_type="POINT",
                srid=4326,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                nullable=True,
            ),
            nullable=True,
        ),
        sa.Column("hazard_type", sa.String(length=50), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("severity_level", sa.String(length=10), nullable=False),
        sa.Column("temp_mir_k", sa.Float(), nullable=False),
        sa.Column("temp_tir_k", sa.Float(), nullable=False),
        sa.Column("frp_mw", sa.Float(), nullable=False),
        sa.Column("frp_spike_ratio", sa.Float(), nullable=False),
        sa.Column("historical_pass_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("osm_landuse", sa.String(length=100), nullable=True),
        sa.Column("is_glint", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["hotspot_id"], ["hotspots.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("incident_id"),
    )
    op.create_index(op.f("ix_incidents_incident_id"), "incidents", ["incident_id"], unique=True)
    op.create_index(op.f("ix_incidents_facility_id"), "incidents", ["facility_id"], unique=False)
    op.create_index(op.f("ix_incidents_hotspot_id"), "incidents", ["hotspot_id"], unique=False)
    op.create_index(op.f("ix_incidents_timestamp_utc"), "incidents", ["timestamp_utc"], unique=False)
    op.create_index(op.f("ix_incidents_hazard_type"), "incidents", ["hazard_type"], unique=False)
    op.create_index(op.f("ix_incidents_severity_level"), "incidents", ["severity_level"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_incidents_severity_level"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_hazard_type"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_timestamp_utc"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_hotspot_id"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_facility_id"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_incident_id"), table_name="incidents")
    op.drop_table("incidents")
