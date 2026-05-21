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
from app.models import bitbrowser as _bitbrowser_model  # noqa: F401
from app.models import social_account as _social_account_model  # noqa: F401
from app.models import dm as _dm_model  # noqa: F401
from app.models import fb_group_scrape as _fb_group_scrape_model  # noqa: F401
from app.models import apify_key as _apify_key_model  # noqa: F401
from app.models.user import User, UserRole


def create_all() -> None:
    """开发环境：根据模型直接建表。生产建议用 alembic 迁移。"""
    Base.metadata.create_all(bind=engine)
    _ensure_users_bitbrowser_columns()
    _ensure_bitbrowser_window_catalog_columns()
    _ensure_apify_keys_columns()
    env = (settings.app_env or "").strip().lower()
    if env in ("dev", "development", "local", ""):
        _dev_auto_alter()
    else:
        logger.info(
            "Skip _dev_auto_alter (APP_ENV={}); schema change请用 Alembic 或手动执行 SQL",
            settings.app_env,
        )


def _ensure_users_bitbrowser_columns() -> None:
    """为 users 表补齐 BitBrowser 相关列（MySQL ADD COLUMN，启动时尝试）。"""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    ucols = {c["name"] for c in insp.get_columns("users")}
    patches: list[str] = []
    if "bitbrowser_local_url" not in ucols:
        patches.append("ALTER TABLE users ADD COLUMN bitbrowser_local_url VARCHAR(512) NULL")
    if "bitbrowser_api_key" not in ucols:
        patches.append("ALTER TABLE users ADD COLUMN bitbrowser_api_key VARCHAR(512) NULL")
    if "bitbrowser_last_sync_at" not in ucols:
        patches.append("ALTER TABLE users ADD COLUMN bitbrowser_last_sync_at DATETIME NULL")
    for sql in patches:
        try:
            logger.info("[schema-patch] {}", sql)
            with engine.begin() as conn:
                conn.execute(text(sql))
        except Exception as e:  # noqa: BLE001
            logger.warning("[schema-patch] failed: {} -> {}", sql, e)


def _ensure_bitbrowser_window_catalog_columns() -> None:
    """为 bitbrowser_window_catalog 表补齐列（MySQL ADD COLUMN）。"""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "bitbrowser_window_catalog" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("bitbrowser_window_catalog")}
    patches: list[str] = []
    if "in_local_cache" not in cols:
        patches.append(
            "ALTER TABLE bitbrowser_window_catalog ADD COLUMN in_local_cache TINYINT(1) NOT NULL DEFAULT 1"
        )
    if "cached_env_platform" not in cols:
        patches.append(
            "ALTER TABLE bitbrowser_window_catalog ADD COLUMN cached_env_platform VARCHAR(512) NULL"
        )
    for sql in patches:
        try:
            logger.info("[schema-patch] {}", sql)
            with engine.begin() as conn:
                conn.execute(text(sql))
        except Exception as e:  # noqa: BLE001
            logger.warning("[schema-patch] failed: {} -> {}", sql, e)


def _ensure_apify_keys_columns() -> None:
    """为 apify_keys 表补齐 exhausted_at 列。"""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "apify_keys" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("apify_keys")}
    if "exhausted_at" not in cols:
        sql = "ALTER TABLE apify_keys ADD COLUMN exhausted_at DATETIME NULL"
        try:
            logger.info("[schema-patch] {}", sql)
            with engine.begin() as conn:
                conn.execute(text(sql))
        except Exception as e:  # noqa: BLE001
            logger.warning("[schema-patch] failed: {} -> {}", sql, e)


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
                if "MODIFY COLUMN task_type" in sql:
                    logger.info(
                        "[dev-auto-alter] MODIFY scrape_tasks.task_type ENUM "
                        "(fb_search, fb_pages, fb_posts_by_page, fb_posts_by_hashtag, fb_posts_by_search)"
                    )
                else:
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
