from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class PromptTemplate(Base, TimestampMixin):
    """关键词 / 提示词模板。
    用于在抓取时根据用户书写的 system_prompt + keywords + filter_rules 让 LLM 对帖子打分过滤。
    """

    __tablename__ = "prompt_templates"

    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)  # ["美妆", "东京"...]
    filter_rules: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 例：{"min_followers": 5000, "min_likes": 100, "min_comments": 10, "region": "JP"}
    output_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
