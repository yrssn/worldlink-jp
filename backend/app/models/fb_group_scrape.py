"""Facebook 群组维度抓取配置。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
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
