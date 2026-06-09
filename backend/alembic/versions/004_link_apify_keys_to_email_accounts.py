"""link apify keys to email accounts

Revision ID: 004
Revises: 003
Create Date: 2026-06-09 06:35:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("apify_keys", sa.Column("email_account_id", sa.Integer(), nullable=True))
    op.add_column("apify_keys", sa.Column("apify_full_name", sa.String(length=128), nullable=True))
    op.add_column("apify_keys", sa.Column("apify_username", sa.String(length=128), nullable=True))
    op.add_column("apify_keys", sa.Column("apify_user_id", sa.String(length=128), nullable=True))
    op.add_column("apify_keys", sa.Column("apify_registered_at", sa.DateTime(), nullable=True))
    op.create_index(
        op.f("ix_apify_keys_email_account_id"),
        "apify_keys",
        ["email_account_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_apify_keys_email_account_id_email_accounts",
        "apify_keys",
        "email_accounts",
        ["email_account_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_apify_keys_email_account_id_email_accounts",
        "apify_keys",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_apify_keys_email_account_id"), table_name="apify_keys")
    op.drop_column("apify_keys", "apify_registered_at")
    op.drop_column("apify_keys", "apify_user_id")
    op.drop_column("apify_keys", "apify_username")
    op.drop_column("apify_keys", "apify_full_name")
    op.drop_column("apify_keys", "email_account_id")
