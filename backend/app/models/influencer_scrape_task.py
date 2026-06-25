"""建联达人「自动抓取」后台任务。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.user import User


class InfluencerScrapeTask(Base, TimestampMixin):
    """记录手工新增达人时「自动抓取」主页资料的后台任务状态与结果。

    按主页 URL 跑 facebook-pages-scraper 抓资料，映射成可填充的达人字段，
    前端轮询 status，done 后用 result 自动填充表单。
    """

    __tablename__ = "influencer_scrape_tasks"

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 抓取平台：facebook / instagram（为以后更多平台预留）
    platform: Mapped[str] = mapped_column(
        String(32), nullable=False, default="facebook", server_default="facebook"
    )
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])
