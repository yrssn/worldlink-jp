"""Add screenshot fields: influencers.homepage_screenshot / dm_outreach_logs.screenshot.

Revision ID: 018
Revises: 017
Create Date: 2026-09-29 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)

    if inspector.has_table("influencers"):
        cols = {c["name"] for c in inspector.get_columns("influencers")}
        if "homepage_screenshot" not in cols:
            op.add_column(
                "influencers",
                sa.Column("homepage_screenshot", sa.String(length=512), nullable=True),
            )

    if inspector.has_table("dm_outreach_logs"):
        cols = {c["name"] for c in inspector.get_columns("dm_outreach_logs")}
        if "screenshot" not in cols:
            op.add_column(
                "dm_outreach_logs",
                sa.Column("screenshot", sa.String(length=512), nullable=True),
            )


def downgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)

    if inspector.has_table("dm_outreach_logs"):
        cols = {c["name"] for c in inspector.get_columns("dm_outreach_logs")}
        if "screenshot" in cols:
            op.drop_column("dm_outreach_logs", "screenshot")

    if inspector.has_table("influencers"):
        cols = {c["name"] for c in inspector.get_columns("influencers")}
        if "homepage_screenshot" in cols:
            op.drop_column("influencers", "homepage_screenshot")
