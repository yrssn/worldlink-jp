"""Facebook 群组维度抓取配置。"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.user import User


class FbGroupScrapeConfig(Base, TimestampMixin):
    """群组维度抓取记录（支持软删除）。"""

    __tablename__ = "fb_group_scrape_configs"

    created_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection: Mapped[str] = mapped_column(
        Text, nullable=False, comment="连接/群组 URL 或标识"
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    creator: Mapped[User] = relationship("User", foreign_keys=[created_by_id])


class FbGroupPullTaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class FbGroupPullTask(Base, TimestampMixin):
    """Facebook 群组帖子后台拉取任务。"""

    __tablename__ = "fb_group_pull_tasks"

    config_id: Mapped[int] = mapped_column(
        ForeignKey("fb_group_scrape_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[FbGroupPullTaskStatus] = mapped_column(
        Enum(FbGroupPullTaskStatus),
        default=FbGroupPullTaskStatus.pending,
        nullable=False,
        index=True,
    )
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="拉取参数")
    apify_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    apify_dataset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    config: Mapped[FbGroupScrapeConfig] = relationship(
        "FbGroupScrapeConfig", foreign_keys=[config_id]
    )
    creator: Mapped[User] = relationship("User", foreign_keys=[created_by_id])


class FbGroupPost(Base, TimestampMixin):
    """从 Facebook 群组抓取的帖子（结构化存储）。"""

    __tablename__ = "fb_group_posts"
    __table_args__ = (
        UniqueConstraint("config_id", "legacy_id", name="uq_fb_group_posts_config_legacy"),
    )

    task_id: Mapped[int] = mapped_column(
        ForeignKey("fb_group_pull_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    config_id: Mapped[int] = mapped_column(
        ForeignKey("fb_group_scrape_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    legacy_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="FB 帖子 legacyId")
    post_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    facebook_group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    group_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    likes_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comments_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shares_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    has_attachments: Mapped[bool] = mapped_column(default=False, nullable=False)
    has_shared_post: Mapped[bool] = mapped_column(default=False, nullable=False)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="原始 JSON")
