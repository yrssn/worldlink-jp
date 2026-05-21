"""Apify API Key 动态配置（支持多个，最多一个默认）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ApifyKey(Base, TimestampMixin):
    """Apify Token 管理：可配置多个，is_default=True 的那个被 apify_service 使用。"""

    __tablename__ = "apify_keys"

    label: Mapped[str] = mapped_column(String(200), nullable=False, comment="显示名称")
    token: Mapped[str] = mapped_column(String(500), nullable=False, comment="Apify API Token")
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True, comment="是否为默认使用的 Key"
    )
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="备注")
    exhausted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="本月用完标记时间"
    )
