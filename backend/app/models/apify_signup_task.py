"""Apify 注册后台任务。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.email_account import EmailAccount
from app.models.user import User


class ApifySignupTask(Base, TimestampMixin):
    """记录 Apify 注册/继续流程的后台任务状态和节点日志。"""

    __tablename__ = "apify_signup_tasks"

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email_account_id: Mapped[int] = mapped_column(
        ForeignKey("email_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="start", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    current_node: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    node_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    logs: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])
    email_account: Mapped[EmailAccount] = relationship("EmailAccount", foreign_keys=[email_account_id])
