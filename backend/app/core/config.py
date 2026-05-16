from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置，从 .env 文件读取。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ===== App =====
    app_name: str = "spider_jp_worldlink"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = True

    # ===== Security =====
    secret_key: str = "please-change-me"
    access_token_expire_minutes: int = 120
    refresh_token_expire_days: int = 7
    fernet_key: Optional[str] = None

    # ===== MySQL =====
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "root"
    mysql_db: str = "spider_jp_worldlink"
    mysql_charset: str = "utf8mb4"

    # ===== Redis =====
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None

    # ===== Apify =====
    apify_token: Optional[str] = None
    # 五种 actor 默认 ID（可在 .env 中覆盖）：
    apify_fb_search_actor: str = "apify/facebook-search-scraper"        # 关键词→Pages
    apify_fb_pages_actor: str = "apify/facebook-pages-scraper"          # URL→主页详情
    apify_fb_posts_actor: str = "apify/facebook-posts-scraper"          # PageURL→帖子
    apify_fb_hashtag_actor: str = "apify/facebook-hashtag-scraper"      # hashtag→帖子
    apify_fb_search_posts_actor: str = "scrapeforge/facebook-search-posts"  # 任意关键词→帖子(第三方)

    # ===== Default admin =====
    default_admin_username: str = "admin"
    default_admin_password: str = "admin123"

    @property
    def sqlalchemy_database_uri(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}"
            f"?charset={self.mysql_charset}"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
