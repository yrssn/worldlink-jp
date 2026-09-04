"""Add dm_outreach_jobs (批量私信任务) and job/status columns on dm_outreach_logs.

Revision ID: 015
Revises: 014
Create Date: 2026-09-04 08:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    bind = op.get_context().bind
    inspector = inspect(bind)
    if not inspector.has_table("dm_outreach_jobs"):
        op.create_table(
            "dm_outreach_jobs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("platform", sa.String(32), nullable=False, server_default="facebook"),
            sa.Column("browser_id", sa.String(128), nullable=False),
            sa.Column("browser_name", sa.String(512), nullable=True),
            sa.Column("content_id", sa.Integer(), sa.ForeignKey("dm_contents.id", ondelete="SET NULL"), nullable=True),
            sa.Column("content_title", sa.String(200), nullable=True),
            sa.Column("targets", sa.JSON(), nullable=True),
            sa.Column("interval_min", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("interval_max", sa.Integer(), nullable=False, server_default="180"),
            sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sent", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("current_url", sa.String(512), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_dm_outreach_jobs_owner_id", "dm_outreach_jobs", ["owner_id"])
        op.create_index("ix_dm_outreach_jobs_status", "dm_outreach_jobs", ["status"])

    if inspector.has_table("dm_outreach_logs"):
        cols = {c["name"] for c in inspector.get_columns("dm_outreach_logs")}
        if "job_id" not in cols:
            op.add_column("dm_outreach_logs", sa.Column("job_id", sa.Integer(), nullable=True))
            op.create_index("ix_dm_outreach_logs_job_id", "dm_outreach_logs", ["job_id"])
        if "browser_name" not in cols:
            op.add_column("dm_outreach_logs", sa.Column("browser_name", sa.String(512), nullable=True))
        if "status" not in cols:
            op.add_column(
                "dm_outreach_logs",
                sa.Column("status", sa.String(16), nullable=False, server_default="success"),
            )
        if "error" not in cols:
            op.add_column("dm_outreach_logs", sa.Column("error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("dm_outreach_logs", "error")
    op.drop_column("dm_outreach_logs", "status")
    op.drop_column("dm_outreach_logs", "browser_name")
    op.drop_index("ix_dm_outreach_logs_job_id", table_name="dm_outreach_logs")
    op.drop_column("dm_outreach_logs", "job_id")
    op.drop_table("dm_outreach_jobs")
