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
    from sqlalchemy import inspect
    inspector = inspect(op.get_context().bind)
    columns = [col['name'] for col in inspector.get_columns('fb_group_pull_tasks')]
    
    if 'duplicate_count' not in columns:
        op.add_column(
            'fb_group_pull_tasks',
            sa.Column('duplicate_count', sa.Integer(), nullable=False, server_default='0')
        )
    
    if 'total_fetched' not in columns:
        op.add_column(
            'fb_group_pull_tasks',
            sa.Column('total_fetched', sa.Integer(), nullable=False, server_default='0')
        )


def downgrade() -> None:
    from sqlalchemy import inspect
    inspector = inspect(op.get_context().bind)
    columns = [col['name'] for col in inspector.get_columns('fb_group_pull_tasks')]
    
    if 'total_fetched' in columns:
        op.drop_column('fb_group_pull_tasks', 'total_fetched')
    
    if 'duplicate_count' in columns:
        op.drop_column('fb_group_pull_tasks', 'duplicate_count')
