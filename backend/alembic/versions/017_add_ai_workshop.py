"""Add AI workshop tables: ai_api_keys / ai_api_call_logs.

Revision ID: 017
Revises: 016
Create Date: 2026-09-28 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)

    if not inspector.has_table("ai_api_keys"):
        op.create_table(
            "ai_api_keys",
            sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
            sa.Column("name", sa.String(length=64), nullable=False, server_default="default"),
            sa.Column("key_prefix", sa.String(length=16), nullable=False),
            sa.Column("key_hash", sa.String(length=64), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.Column("last_used_ip", sa.String(length=64), nullable=True),
            sa.Column("owner_id", sa.Integer(), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
            ),
            sa.Column(
                "updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
            ),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("key_hash", name="uq_ai_api_keys_key_hash"),
        )
        op.create_index("ix_ai_api_keys_owner_id", "ai_api_keys", ["owner_id"])
        op.create_index("ix_ai_api_keys_key_hash", "ai_api_keys", ["key_hash"])

    if not inspector.has_table("ai_api_call_logs"):
        op.create_table(
            "ai_api_call_logs",
            sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
            sa.Column("key_id", sa.Integer(), nullable=True),
            sa.Column("owner_id", sa.Integer(), nullable=False),
            sa.Column("action", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="ok"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("detail", sa.JSON(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
            ),
            sa.Column(
                "updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
            ),
            sa.ForeignKeyConstraint(["key_id"], ["ai_api_keys.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_ai_api_call_logs_key_id", "ai_api_call_logs", ["key_id"])
        op.create_index("ix_ai_api_call_logs_owner_id", "ai_api_call_logs", ["owner_id"])


def downgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)
    if inspector.has_table("ai_api_call_logs"):
        op.drop_table("ai_api_call_logs")
    if inspector.has_table("ai_api_keys"):
        op.drop_table("ai_api_keys")
