"""初始化数据库：建表、内置默认管理员。"""
from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import SessionLocal, engine

# 导入所有模型以注册到 Base.metadata
from app.models import user as _user_model  # noqa: F401
from app.models import llm as _llm_model  # noqa: F401
from app.models import prompt as _prompt_model  # noqa: F401
from app.models import scrape as _scrape_model  # noqa: F401
from app.models import post as _post_model  # noqa: F401
from app.models import influencer as _influencer_model  # noqa: F401
from app.models import social_account as _social_account_model  # noqa: F401
from app.models.user import User, UserRole


def create_all() -> None:
    """开发环境：根据模型直接建表。生产建议用 alembic 迁移。"""
    Base.metadata.create_all(bind=engine)
    _dev_auto_alter()


def _dev_auto_alter() -> None:
    """开发期兜底：补齐 scrape_tasks 表上新增的列。
    仅 ADD COLUMN，不会破坏已有数据。生产环境请使用 Alembic。
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "scrape_tasks" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("scrape_tasks")}
    statements: list[str] = []
    if "hashtags" not in cols:
        statements.append("ALTER TABLE scrape_tasks ADD COLUMN hashtags JSON NULL")
    if "posts_per_page" not in cols:
        statements.append(
            "ALTER TABLE scrape_tasks ADD COLUMN posts_per_page INT NOT NULL DEFAULT 10"
        )
    if "page_limit" not in cols:
        statements.append(
            "ALTER TABLE scrape_tasks ADD COLUMN page_limit INT NOT NULL DEFAULT 50"
        )
    # 扩展 task_type ENUM（MySQL）：不论是否检测到，都尝试一次 MODIFY
    statements.append(
        "ALTER TABLE scrape_tasks MODIFY COLUMN task_type "
        "ENUM('fb_search','fb_pages','fb_posts_by_page','fb_posts_by_hashtag','fb_posts_by_search') "
        "NOT NULL"
    )

    with engine.begin() as conn:
        for sql in statements:
            try:
                logger.info("[dev-auto-alter] {}", sql)
                conn.execute(text(sql))
            except Exception as e:  # noqa: BLE001
                logger.warning("[dev-auto-alter] failed: {} -> {}", sql, e)


def ensure_default_admin(db: Session) -> None:
    exists = (
        db.query(User)
        .filter(User.username == settings.default_admin_username)
        .first()
    )
    if exists:
        return
    admin = User(
        username=settings.default_admin_username,
        password_hash=hash_password(settings.default_admin_password),
        role=UserRole.admin,
        is_active=True,
    )
    db.add(admin)
    db.commit()
    logger.info(
        "Created default admin user: {} (please change the password)",
        settings.default_admin_username,
    )


def init_db() -> None:
    create_all()
    with SessionLocal() as db:
        ensure_default_admin(db)
