"""Add FbGroupScheduleTask table for scheduled pulls.

Revision ID: 001
Revises: 
Create Date: 2026-05-30 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'fb_group_schedule_tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('config_id', sa.Integer(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.Enum('active', 'paused', 'disabled', name='fbgroupscheduletaskstatus'), nullable=False),
        sa.Column('schedule_type', sa.String(20), nullable=False),
        sa.Column('schedule_config', sa.JSON(), nullable=False),
        sa.Column('pull_params', sa.JSON(), nullable=True),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('next_run_at', sa.DateTime(), nullable=True),
        sa.Column('last_task_id', sa.Integer(), nullable=True),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_consecutive_failures', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('remark', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['config_id'], ['fb_group_scrape_configs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['last_task_id'], ['fb_group_pull_tasks.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_fb_group_schedule_tasks_config_id'), 'fb_group_schedule_tasks', ['config_id'], unique=False)
    op.create_index(op.f('ix_fb_group_schedule_tasks_created_by_id'), 'fb_group_schedule_tasks', ['created_by_id'], unique=False)
    op.create_index(op.f('ix_fb_group_schedule_tasks_status'), 'fb_group_schedule_tasks', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_fb_group_schedule_tasks_status'), table_name='fb_group_schedule_tasks')
    op.drop_index(op.f('ix_fb_group_schedule_tasks_created_by_id'), table_name='fb_group_schedule_tasks')
    op.drop_index(op.f('ix_fb_group_schedule_tasks_config_id'), table_name='fb_group_schedule_tasks')
    op.drop_table('fb_group_schedule_tasks')
