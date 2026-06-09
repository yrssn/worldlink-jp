"""邮箱账号管理：注册邮箱、验证邮箱与浏览器环境。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class EmailAccount(Base, TimestampMixin):
    """用于账号注册自动化的邮箱资料。"""

    __tablename__ = "email_accounts"
    __table_args__ = (
        UniqueConstraint("owner_id", "email", name="uq_email_accounts_owner_email"),
    )

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email_password: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    mail_login_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    verification_email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    verification_password: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    verification_login_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    purpose: Mapped[str] = mapped_column(String(64), nullable=False, default="apify", index=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="unused", index=True)
    browser_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    last_verification_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_verification_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
