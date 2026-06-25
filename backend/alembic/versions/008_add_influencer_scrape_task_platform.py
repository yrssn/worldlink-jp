"""Add platform column to influencer_scrape_tasks (facebook / instagram).

Revision ID: 008
Revises: 007
Create Date: 2026-06-25 02:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None

_TABLE = "influencer_scrape_tasks"


def upgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)
    if not inspector.has_table(_TABLE):
        # 该表由 create_all 管理，未建则跳过（建表时已含 platform 列）。
        return
    columns = [col["name"] for col in inspector.get_columns(_TABLE)]
    if "platform" not in columns:
        op.add_column(
            _TABLE,
            sa.Column(
                "platform",
                sa.String(length=32),
                nullable=False,
                server_default="facebook",
            ),
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)
    if not inspector.has_table(_TABLE):
        return
    columns = [col["name"] for col in inspector.get_columns(_TABLE)]
    if "platform" in columns:
        op.drop_column(_TABLE, "platform")
