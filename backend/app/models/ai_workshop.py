"""AI 工坊：Agent 接入密钥与调用审计。

每个用户可自助创建 API Key 供外部智能体（Codex / Claude Code / 任意脚本）调用。
密钥明文只在创建时返回一次，库里只存 SHA-256 哈希；Agent 的每次调用都以
密钥属主用户身份执行，数据可见范围复用 RBAC 的 ``owner_filter``（见 ai_auth / ai_workshop 服务）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class AiApiKey(Base, TimestampMixin):
    """Agent 接入密钥（属主 = 创建它的系统用户）。"""

    __tablename__ = "ai_api_keys"

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: 用途/备注名，如「codex 寻客」
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    #: 明文前缀（如 ``skjw-ab12cd34``），列表展示用
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    #: SHA-256(明文) hex，唯一
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: 过期时间（UTC 存库），空 = 永不过期
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    owner = relationship("User", foreign_keys=[owner_id])

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= datetime.utcnow()


class AiApiCallLog(Base, TimestampMixin):
    """Agent 调用审计：每次 MCP 工具调用 / REST Agent 请求记一条。"""

    __tablename__ = "ai_api_call_logs"

    key_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_api_keys.id", ondelete="SET NULL"), nullable=True, index=True
    )
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: 工具名或 ``METHOD path``
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    #: ok / error
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 结果摘要：结果条数、影响到的 influencer_id、关键参数等
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
