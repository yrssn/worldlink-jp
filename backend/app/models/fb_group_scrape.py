"""Facebook 群组维度抓取配置。"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
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
    result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="新增帖子数")
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="重复帖子数（去重后跳过）")
    filtered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="达人库已存在而过滤的帖子数")
    total_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="Apify 返回的总帖子数")
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

    # ─── 建联 / 分析 ───────────────────────────────────────────────
    # 预建联后关联到的达人（NULL 表示尚未建联）
    influencer_id: Mapped[int | None] = mapped_column(
        ForeignKey("influencers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="预建联生成/命中的达人 id",
    )
    # 预建联任务状态：pending / running / done / failed（NULL 表示从未触发）
    pre_contact_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="预建联状态 pending/running/done/failed"
    )
    pre_contact_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 多维度分析结果（可扩展，见 services/fb_group_analysis.py）
    analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="多维度分析结果")
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FbGroupScheduleTaskStatus(str, enum.Enum):
    """定时任务状态"""
    active = "active"
    paused = "paused"
    disabled = "disabled"


class FbGroupScheduleTask(Base, TimestampMixin):
    """Facebook 群组定时拉取任务配置。"""

    __tablename__ = "fb_group_schedule_tasks"

    config_id: Mapped[int] = mapped_column(
        ForeignKey("fb_group_scrape_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[FbGroupScheduleTaskStatus] = mapped_column(
        Enum(FbGroupScheduleTaskStatus),
        default=FbGroupScheduleTaskStatus.active,
        nullable=False,
        index=True,
    )
    # 调度方式：'cron' 或 'interval'
    schedule_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="cron 或 interval"
    )
    # Cron 表达式（如 '0 10 * * *' 表示每天 10 点）或 interval 配置（如 '{"hours": 24}'）
    schedule_config: Mapped[dict] = mapped_column(
        JSON, nullable=False, comment="调度配置（cron 表达式或 interval 参数）"
    )
    # 拉取参数（results_limit, view_option 等）
    pull_params: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="拉取参数"
    )
    # 最后一次执行时间
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 下次执行时间
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 最后一次执行的任务 ID（用于追踪）
    last_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("fb_group_pull_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 连续失败次数
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 最大连续失败次数（超过则自动禁用）
    max_consecutive_failures: Mapped[int] = mapped_column(
        Integer, default=5, nullable=False
    )
    # 备注
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True)

    config: Mapped[FbGroupScrapeConfig] = relationship(
        "FbGroupScrapeConfig", foreign_keys=[config_id]
    )
    creator: Mapped[User] = relationship("User", foreign_keys=[created_by_id])
    last_task: Mapped[FbGroupPullTask | None] = relationship(
        "FbGroupPullTask", foreign_keys=[last_task_id]
    )
