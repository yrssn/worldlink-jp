"""Add progress column to influencers.

Revision ID: 011
Revises: 010
Create Date: 2026-08-25 03:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None

_TABLE = "influencers"
_COLUMNS = ("progress",)


def upgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)
    if not inspector.has_table(_TABLE):
        # 该表由 create_all 管理，未建则跳过（建表时已含该列）。
        return
    columns = [col["name"] for col in inspector.get_columns(_TABLE)]
    for name in _COLUMNS:
        if name not in columns:
            op.add_column(_TABLE, sa.Column(name, sa.String(length=255), nullable=True))


def downgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)
    if not inspector.has_table(_TABLE):
        return
    columns = [col["name"] for col in inspector.get_columns(_TABLE)]
    for name in _COLUMNS:
        if name in columns:
            op.drop_column(_TABLE, name)
