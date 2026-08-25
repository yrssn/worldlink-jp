"""Add RBAC tables (menus / roles / role_menus / user_roles).

Revision ID: 010
Revises: 009
Create Date: 2026-08-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)

    if not inspector.has_table("menus"):
        op.create_table(
            "menus",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code", sa.String(length=128), nullable=False),
            sa.Column("title", sa.String(length=128), nullable=False),
            sa.Column("parent_id", sa.Integer(), nullable=True),
            sa.Column("path", sa.String(length=255), nullable=True),
            sa.Column("icon", sa.String(length=64), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "type",
                sa.Enum("catalog", "menu", "button", name="menutype"),
                nullable=False,
                server_default="menu",
            ),
            sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("api_prefixes", sa.JSON(), nullable=True),
            sa.Column(
                "api_enforce_mode",
                sa.Enum("all", "write", "off", name="apienforcemode"),
                nullable=False,
                server_default="all",
            ),
            sa.Column("remark", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["parent_id"], ["menus.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("code", name="uq_menus_code"),
        )
        op.create_index("ix_menus_code", "menus", ["code"])
        op.create_index("ix_menus_parent_id", "menus", ["parent_id"])

    if not inspector.has_table("roles"):
        op.create_table(
            "roles",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("remark", sa.String(length=255), nullable=True),
            sa.Column(
                "data_scope",
                sa.Enum("own", "all", name="datascope"),
                nullable=False,
                server_default="own",
            ),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("code", name="uq_roles_code"),
        )
        op.create_index("ix_roles_code", "roles", ["code"])

    if not inspector.has_table("role_menus"):
        op.create_table(
            "role_menus",
            sa.Column("role_id", sa.Integer(), primary_key=True),
            sa.Column("menu_id", sa.Integer(), primary_key=True),
            sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["menu_id"], ["menus.id"], ondelete="CASCADE"),
        )

    if not inspector.has_table("user_roles"):
        op.create_table(
            "user_roles",
            sa.Column("user_id", sa.Integer(), primary_key=True),
            sa.Column("role_id", sa.Integer(), primary_key=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        )


def downgrade() -> None:
    op.drop_table("user_roles")
    op.drop_table("role_menus")
    op.drop_table("roles")
    op.drop_table("menus")
