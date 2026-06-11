"""Add influencer platform and Facebook group filter counts.

Revision ID: 006
Revises: 005
Create Date: 2026-06-11 08:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)
    influencer_cols = {col['name'] for col in inspector.get_columns('influencers')}
    if 'platform_id' not in influencer_cols:
        op.add_column('influencers', sa.Column('platform_id', sa.Integer(), nullable=True))
        op.create_index(op.f('ix_influencers_platform_id'), 'influencers', ['platform_id'], unique=False)
        op.create_foreign_key(
            'fk_influencers_platform_id_bitbrowser_platforms',
            'influencers',
            'bitbrowser_platforms',
            ['platform_id'],
            ['id'],
            ondelete='SET NULL',
        )

    task_cols = {col['name'] for col in inspector.get_columns('fb_group_pull_tasks')}
    if 'filtered_count' not in task_cols:
        op.add_column(
            'fb_group_pull_tasks',
            sa.Column('filtered_count', sa.Integer(), nullable=False, server_default='0'),
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)
    task_cols = {col['name'] for col in inspector.get_columns('fb_group_pull_tasks')}
    if 'filtered_count' in task_cols:
        op.drop_column('fb_group_pull_tasks', 'filtered_count')

    influencer_cols = {col['name'] for col in inspector.get_columns('influencers')}
    if 'platform_id' in influencer_cols:
        op.drop_constraint('fk_influencers_platform_id_bitbrowser_platforms', 'influencers', type_='foreignkey')
        op.drop_index(op.f('ix_influencers_platform_id'), table_name='influencers')
        op.drop_column('influencers', 'platform_id')
