from __future__ import annotations

import enum

from sqlalchemy import JSON, Boolean, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class LlmProviderType(str, enum.Enum):
    openai = "openai"
    azure_openai = "azure_openai"
    deepseek = "deepseek"
    claude = "claude"
    ollama = "ollama"
    qwen = "qwen"
    custom = "custom"


class LlmProvider(Base, TimestampMixin):
    __tablename__ = "llm_providers"

    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[LlmProviderType] = mapped_column(
        Enum(LlmProviderType), nullable=False
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)  # 加密后存储
    temperature: Mapped[float] = mapped_column(Float, default=0.2, nullable=False)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extra_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
