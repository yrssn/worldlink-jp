"""Add countries dictionary table and influencers.country_id.

Revision ID: 012
Revises: 011
Create Date: 2026-08-25 04:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)
    if not inspector.has_table("countries"):
        op.create_table(
            "countries",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("owner_id", sa.Integer(), nullable=True),
            sa.Column("name_zh", sa.String(length=128), nullable=False),
            sa.Column("name_en", sa.String(length=128), nullable=True),
            sa.Column("code", sa.String(length=16), nullable=True),
            sa.Column("remark", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_countries_owner_id", "countries", ["owner_id"])
        op.create_index("ix_countries_name_zh", "countries", ["name_zh"])
        op.create_index("ix_countries_name_en", "countries", ["name_en"])
        op.create_index("ix_countries_code", "countries", ["code"])

    if inspector.has_table("influencers"):
        columns = [col["name"] for col in inspector.get_columns("influencers")]
        if "country_id" not in columns:
            op.add_column("influencers", sa.Column("country_id", sa.Integer(), nullable=True))
            op.create_index("ix_influencers_country_id", "influencers", ["country_id"])


def downgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)
    if inspector.has_table("influencers"):
        columns = [col["name"] for col in inspector.get_columns("influencers")]
        if "country_id" in columns:
            op.drop_index("ix_influencers_country_id", table_name="influencers")
            op.drop_column("influencers", "country_id")
    if inspector.has_table("countries"):
        op.drop_table("countries")
