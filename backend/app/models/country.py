from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Country(Base, TimestampMixin):
    """国家字典：达人的国家分类，中英文各存一份，代码用于对齐外部数据。"""

    __tablename__ = "countries"

    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: 中文名，如「日本」
    name_zh: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    #: 英文名，如「Japan」
    name_en: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    #: 国家代码（ISO 3166-1 alpha-2 习惯写法，如 JP），抓取结果按它对齐
    code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    @property
    def label(self) -> str:
        """列表里展示用的「中文 / English」。"""
        return f"{self.name_zh} / {self.name_en}" if self.name_en else self.name_zh
