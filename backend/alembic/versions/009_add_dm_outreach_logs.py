"""Add dm_outreach_logs (私信建联发送记录，按 owner 隔离).

Revision ID: 009
Revises: 008
Create Date: 2026-07-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None

_TABLE = "dm_outreach_logs"


def upgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)
    if inspector.has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("influencer_id", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(length=512), nullable=False),
        sa.Column("browser_id", sa.String(length=128), nullable=True),
        sa.Column("content_id", sa.Integer(), nullable=True),
        sa.Column("content_title", sa.String(length=200), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("images_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("images_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["influencer_id"], ["influencers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["content_id"], ["dm_contents.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_dm_outreach_logs_owner_id", _TABLE, ["owner_id"])
    op.create_index("ix_dm_outreach_logs_influencer_id", _TABLE, ["influencer_id"])
    op.create_index("ix_dm_outreach_logs_url", _TABLE, ["url"])
    op.create_index("ix_dm_outreach_logs_content_id", _TABLE, ["content_id"])


def downgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)
    if not inspector.has_table(_TABLE):
        return
    op.drop_table(_TABLE)
