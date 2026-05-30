"""Add deduplication tracking fields to FbGroupPullTask.

Revision ID: 002
Revises: 001
Create Date: 2026-05-30 15:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'fb_group_pull_tasks',
        sa.Column('duplicate_count', sa.Integer(), nullable=False, server_default='0')
    )
    op.add_column(
        'fb_group_pull_tasks',
        sa.Column('total_fetched', sa.Integer(), nullable=False, server_default='0')
    )


def downgrade() -> None:
    op.drop_column('fb_group_pull_tasks', 'total_fetched')
    op.drop_column('fb_group_pull_tasks', 'duplicate_count')
