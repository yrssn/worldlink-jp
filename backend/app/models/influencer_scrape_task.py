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
    # 批次名：批量导入链接时用于分组/筛选（如「7月FB第一批」），可空
    batch: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # status：staged(仅暂存未跑) / pending / running / done / failed / contacted(已私信)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", index=True
    )
    # 表格导入时先建好的达人：抓取完成后把资料补写回这条达人，而不是新建一条
    influencer_id: Mapped[int | None] = mapped_column(
        ForeignKey("influencers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 列表「一键抓取」时绑定的关联账号：抓取结果回写到这条账号，而不是按链接再去猜
    social_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("influencer_social_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])
