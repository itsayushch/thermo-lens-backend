""""0001_initial_schema

Initial migration creating facilities, hotspots, and classified_hotspots tables
with PostGIS geometry columns and spatial indexing.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-28 00:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import geoalchemy2

# revision identifiers, used by Alembic.revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade() -> None:
    # Ensure postgis extension is active
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

    # 1. Create facilities table
    op.create_table(
        "facilities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("facility_type", sa.String(length=100), nullable=False),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(
                geometry_type="GEOMETRY",
                srid=4326,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_facilities_name"), "facilities", ["name"], unique=False)
    op.create_index(op.f("ix_facilities_facility_type"), "facilities", ["facility_type"], unique=False)


    # 2. Create hotspots table
    op.create_table(
        "hotspots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("brightness", sa.Float(), nullable=False),
        sa.Column("frp", sa.Float(), nullable=False),
        sa.Column("acq_date", sa.Date(), nullable=False),
        sa.Column("acq_time", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.String(length=50), nullable=False),
        sa.Column("satellite", sa.String(length=50), nullable=False),
        sa.Column("nearest_facility_id", sa.Integer(), nullable=True),
        sa.Column("distance_to_facility_m", sa.Float(), nullable=True),
        sa.Column("landcover_class", sa.String(length=100), nullable=True),
        sa.Column("persistence_days", sa.Integer(), server_default="1", nullable=False),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["nearest_facility_id"], ["facilities.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_hotspots_acq_date"), "hotspots", ["acq_date"], unique=False)
    op.create_index(op.f("ix_hotspots_satellite"), "hotspots", ["satellite"], unique=False)
    op.create_index(op.f("ix_hotspots_nearest_facility_id"), "hotspots", ["nearest_facility_id"], unique=False)


    # 3. Create classified_hotspots table
    op.create_table(
        "classified_hotspots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hotspot_id", sa.Integer(), nullable=False),
        sa.Column("predicted_class", sa.String(length=50), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["hotspot_id"], ["hotspots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hotspot_id"),
    )
    op.create_index(op.f("ix_classified_hotspots_predicted_class"), "classified_hotspots", ["predicted_class"], unique=False)
    op.create_index(op.f("ix_classified_hotspots_hotspot_id"), "classified_hotspots", ["hotspot_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_classified_hotspots_hotspot_id"), table_name="classified_hotspots")
    op.drop_index(op.f("ix_classified_hotspots_predicted_class"), table_name="classified_hotspots")
    op.drop_table("classified_hotspots")

    op.drop_index(op.f("ix_hotspots_nearest_facility_id"), table_name="hotspots")
    op.drop_index(op.f("ix_hotspots_satellite"), table_name="hotspots")
    op.drop_index(op.f("ix_hotspots_acq_date"), table_name="hotspots")
    op.drop_table("hotspots")

    op.drop_index(op.f("ix_facilities_facility_type"), table_name="facilities")
    op.drop_index(op.f("ix_facilities_name"), table_name="facilities")
    op.drop_table("facilities")
