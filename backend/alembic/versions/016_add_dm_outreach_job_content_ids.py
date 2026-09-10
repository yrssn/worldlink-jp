"""Add dm_outreach_jobs.content_ids（私信内容多选，发送时随机挑一条）.

Revision ID: 016
Revises: 015
Create Date: 2026-09-10 08:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)
    if not inspector.has_table("dm_outreach_jobs"):
        return
    cols = {c["name"] for c in inspector.get_columns("dm_outreach_jobs")}
    if "content_ids" not in cols:
        op.add_column("dm_outreach_jobs", sa.Column("content_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("dm_outreach_jobs", "content_ids")
