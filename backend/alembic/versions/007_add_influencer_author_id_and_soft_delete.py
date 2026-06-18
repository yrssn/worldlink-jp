"""Add fb_author_id + deleted_at (soft delete) to influencers.

Revision ID: 007
Revises: 006
Create Date: 2026-06-18 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)
    columns = [col["name"] for col in inspector.get_columns("influencers")]

    if "fb_author_id" not in columns:
        op.add_column(
            "influencers",
            sa.Column("fb_author_id", sa.String(length=255), nullable=True),
        )
        op.create_index(
            "ix_influencers_fb_author_id", "influencers", ["fb_author_id"]
        )

    if "deleted_at" not in columns:
        op.add_column(
            "influencers",
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "ix_influencers_deleted_at", "influencers", ["deleted_at"]
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)
    columns = [col["name"] for col in inspector.get_columns("influencers")]

    if "deleted_at" in columns:
        op.drop_index("ix_influencers_deleted_at", table_name="influencers")
        op.drop_column("influencers", "deleted_at")

    if "fb_author_id" in columns:
        op.drop_index("ix_influencers_fb_author_id", table_name="influencers")
        op.drop_column("influencers", "fb_author_id")
