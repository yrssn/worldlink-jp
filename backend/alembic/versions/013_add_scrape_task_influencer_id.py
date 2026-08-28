"""Add influencer_scrape_tasks.influencer_id (表格导入的达人回填目标).

Revision ID: 013
Revises: 012
Create Date: 2026-08-28 06:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)
    if not inspector.has_table("influencer_scrape_tasks"):
        return
    cols = {c["name"] for c in inspector.get_columns("influencer_scrape_tasks")}
    if "influencer_id" in cols:
        return
    op.add_column(
        "influencer_scrape_tasks",
        sa.Column("influencer_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_influencer_scrape_tasks_influencer_id",
        "influencer_scrape_tasks",
        ["influencer_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_influencer_scrape_tasks_influencer_id",
        table_name="influencer_scrape_tasks",
    )
    op.drop_column("influencer_scrape_tasks", "influencer_id")
