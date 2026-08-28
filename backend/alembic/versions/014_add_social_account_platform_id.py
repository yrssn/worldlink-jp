"""Add influencer_social_accounts.platform_id (平台关联到具体社交账号).

Revision ID: 014
Revises: 013
Create Date: 2026-08-28 06:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    bind = op.get_context().bind
    inspector = inspect(bind)
    if not inspector.has_table("influencer_social_accounts"):
        return
    cols = {c["name"] for c in inspector.get_columns("influencer_social_accounts")}
    if "platform_id" not in cols:
        op.add_column(
            "influencer_social_accounts",
            sa.Column("platform_id", sa.Integer(), nullable=True),
        )
        op.create_index(
            "ix_influencer_social_accounts_platform_id",
            "influencer_social_accounts",
            ["platform_id"],
        )
    _backfill(bind)


def _backfill(bind) -> None:
    """按账号的 platform 枚举回填「平台管理」里的平台 id，匹配不到的保持 NULL。"""
    from sqlalchemy import inspect

    from app.models.social_account import SocialPlatform
    from app.utils.platform_detect import match_platform_code

    if not inspect(bind).has_table("bitbrowser_platforms"):
        return
    rows = bind.execute(sa.text("SELECT id, name, code FROM bitbrowser_platforms")).fetchall()
    codes: dict[str, int] = {}
    for pid, name, _code in rows:
        key = (name or "").strip().lower()
        if key:
            codes.setdefault(key, pid)
    for pid, _name, code in rows:
        key = (code or "").strip().lower()
        if key:
            codes[key] = pid
    for platform in SocialPlatform:
        pid = match_platform_code(platform.value, codes)
        if pid is None:
            continue
        bind.execute(
            sa.text(
                "UPDATE influencer_social_accounts SET platform_id = :pid "
                "WHERE platform_id IS NULL AND platform = :platform"
            ),
            {"pid": pid, "platform": platform.value},
        )


def downgrade() -> None:
    op.drop_index(
        "ix_influencer_social_accounts_platform_id",
        table_name="influencer_social_accounts",
    )
    op.drop_column("influencer_social_accounts", "platform_id")
