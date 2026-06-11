"""Add pre-contact / analysis fields to FbGroupPost.

Revision ID: 006
Revises: 005
Create Date: 2026-06-11 09:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)
    columns = [col["name"] for col in inspector.get_columns("fb_group_posts")]

    if "influencer_id" not in columns:
        op.add_column(
            "fb_group_posts",
            sa.Column("influencer_id", sa.Integer(), nullable=True),
        )
        op.create_index(
            "ix_fb_group_posts_influencer_id",
            "fb_group_posts",
            ["influencer_id"],
        )
        op.create_foreign_key(
            "fk_fb_group_posts_influencer_id",
            "fb_group_posts",
            "influencers",
            ["influencer_id"],
            ["id"],
            ondelete="SET NULL",
        )

    if "pre_contact_status" not in columns:
        op.add_column(
            "fb_group_posts",
            sa.Column("pre_contact_status", sa.String(length=20), nullable=True),
        )

    if "pre_contact_error" not in columns:
        op.add_column(
            "fb_group_posts",
            sa.Column("pre_contact_error", sa.Text(), nullable=True),
        )

    if "analysis" not in columns:
        op.add_column(
            "fb_group_posts",
            sa.Column("analysis", sa.JSON(), nullable=True),
        )

    if "analyzed_at" not in columns:
        op.add_column(
            "fb_group_posts",
            sa.Column("analyzed_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_context().bind)
    columns = [col["name"] for col in inspector.get_columns("fb_group_posts")]

    if "analyzed_at" in columns:
        op.drop_column("fb_group_posts", "analyzed_at")
    if "analysis" in columns:
        op.drop_column("fb_group_posts", "analysis")
    if "pre_contact_error" in columns:
        op.drop_column("fb_group_posts", "pre_contact_error")
    if "pre_contact_status" in columns:
        op.drop_column("fb_group_posts", "pre_contact_status")
    if "influencer_id" in columns:
        op.drop_constraint(
            "fk_fb_group_posts_influencer_id", "fb_group_posts", type_="foreignkey"
        )
        op.drop_index("ix_fb_group_posts_influencer_id", table_name="fb_group_posts")
        op.drop_column("fb_group_posts", "influencer_id")
