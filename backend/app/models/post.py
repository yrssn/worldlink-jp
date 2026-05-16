from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Post(Base, TimestampMixin):
    """抓取到的 Facebook 帖子。"""

    __tablename__ = "posts"

    # 来源任务
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # 平台标识
    platform: Mapped[str] = mapped_column(String(32), default="facebook", nullable=False)
    post_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    url: Mapped[str | None] = mapped_column(String(512), index=True, nullable=True)

    # 内容
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    likes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comments_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shares: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reactions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    media: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # 作者
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_url: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    author_page_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    # 命中关键词
    keywords_hit: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # AI 过滤
    ai_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ai_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 原始数据备份
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 建联后回写：达人 id
    influencer_id: Mapped[int | None] = mapped_column(
        ForeignKey("influencers.id", ondelete="SET NULL"), nullable=True, index=True
    )

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
