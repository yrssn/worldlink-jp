"""add email accounts

Revision ID: 003
Revises: 002
Create Date: 2026-06-09 06:20:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_accounts",
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("email_password", sa.String(length=1000), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("mail_login_url", sa.String(length=512), nullable=True),
        sa.Column("verification_email", sa.String(length=255), nullable=True),
        sa.Column("verification_password", sa.String(length=1000), nullable=True),
        sa.Column("verification_login_url", sa.String(length=512), nullable=True),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("browser_id", sa.String(length=64), nullable=True),
        sa.Column("last_verification_code", sa.String(length=32), nullable=True),
        sa.Column("last_verification_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "email", name="uq_email_accounts_owner_email"),
    )
    op.create_index(op.f("ix_email_accounts_owner_id"), "email_accounts", ["owner_id"], unique=False)
    op.create_index(op.f("ix_email_accounts_email"), "email_accounts", ["email"], unique=False)
    op.create_index(op.f("ix_email_accounts_provider"), "email_accounts", ["provider"], unique=False)
    op.create_index(
        op.f("ix_email_accounts_verification_email"),
        "email_accounts",
        ["verification_email"],
        unique=False,
    )
    op.create_index(op.f("ix_email_accounts_purpose"), "email_accounts", ["purpose"], unique=False)
    op.create_index(op.f("ix_email_accounts_status"), "email_accounts", ["status"], unique=False)
    op.create_index(op.f("ix_email_accounts_browser_id"), "email_accounts", ["browser_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_email_accounts_browser_id"), table_name="email_accounts")
    op.drop_index(op.f("ix_email_accounts_status"), table_name="email_accounts")
    op.drop_index(op.f("ix_email_accounts_purpose"), table_name="email_accounts")
    op.drop_index(op.f("ix_email_accounts_verification_email"), table_name="email_accounts")
    op.drop_index(op.f("ix_email_accounts_provider"), table_name="email_accounts")
    op.drop_index(op.f("ix_email_accounts_email"), table_name="email_accounts")
    op.drop_index(op.f("ix_email_accounts_owner_id"), table_name="email_accounts")
    op.drop_table("email_accounts")
