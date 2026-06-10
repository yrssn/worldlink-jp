"""add apify signup tasks

Revision ID: 005
Revises: 004
Create Date: 2026-06-10 08:30:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "apify_signup_tasks",
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("email_account_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_node", sa.String(length=128), nullable=True),
        sa.Column("node_started_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("logs", sa.Text(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["email_account_id"], ["email_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_apify_signup_tasks_owner_id"), "apify_signup_tasks", ["owner_id"])
    op.create_index(
        op.f("ix_apify_signup_tasks_email_account_id"),
        "apify_signup_tasks",
        ["email_account_id"],
    )
    op.create_index(op.f("ix_apify_signup_tasks_action"), "apify_signup_tasks", ["action"])
    op.create_index(op.f("ix_apify_signup_tasks_status"), "apify_signup_tasks", ["status"])
    op.create_index(
        op.f("ix_apify_signup_tasks_current_node"),
        "apify_signup_tasks",
        ["current_node"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_apify_signup_tasks_current_node"), table_name="apify_signup_tasks")
    op.drop_index(op.f("ix_apify_signup_tasks_status"), table_name="apify_signup_tasks")
    op.drop_index(op.f("ix_apify_signup_tasks_action"), table_name="apify_signup_tasks")
    op.drop_index(op.f("ix_apify_signup_tasks_email_account_id"), table_name="apify_signup_tasks")
    op.drop_index(op.f("ix_apify_signup_tasks_owner_id"), table_name="apify_signup_tasks")
    op.drop_table("apify_signup_tasks")
