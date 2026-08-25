from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class InfluencerStatus(str, enum.Enum):
    pre_contact = "pre_contact"     # 预建联（默认）
    contacting = "contacting"       # 建联中
    signed = "signed"               # 建联成功
    dropped = "dropped"             # 已放弃


class InfluencerSource(str, enum.Enum):
    scrape = "scrape"               # 来自抓取
    manual = "manual"               # 手工新增


class Influencer(Base, TimestampMixin):
    """建联模块 - 达人。"""

    __tablename__ = "influencers"

    # 基础信息
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    real_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)

    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # 地区 / 语言
    #: 兼容字段：国家代码/名称的自由文本，新数据由 ``country_id`` 关联的国家代码同步写入
    country: Mapped[str | None] = mapped_column(String(64), nullable=True, default="JP")
    country_id: Mapped[int | None] = mapped_column(
        ForeignKey("countries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    city: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 联系方式
    email: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    messenger: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Facebook Page 专属字段（参考 facebook-pages-scraper 输出）
    # 来源群组帖子作者的 FB user.id（用于按作者去重 / 命中已建联）
    fb_author_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    fb_page_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    fb_page_url: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    fb_page_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fb_categories: Mapped[list | None] = mapped_column(JSON, nullable=True)
    fb_followers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fb_likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fb_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    fb_rating_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fb_checkins_mentions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fb_page_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fb_ad_library_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fb_ad_status: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 标签 & 备注
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 建联进展（列表里可直接编辑的自由文本）
    progress: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 状态 & 来源
    status: Mapped[InfluencerStatus] = mapped_column(
        Enum(InfluencerStatus), default=InfluencerStatus.pre_contact, nullable=False
    )
    source: Mapped[InfluencerSource] = mapped_column(
        Enum(InfluencerSource), default=InfluencerSource.manual, nullable=False
    )
    platform_id: Mapped[int | None] = mapped_column(
        ForeignKey("bitbrowser_platforms.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # 原始资料备份（来自 Pages Scraper 的完整 JSON）
    raw_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # 软删除：删除达人时只置时间戳，列表不再展示；关联帖子据此显示「已删除」
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    platform = relationship("BitBrowserPlatform")
    country_ref = relationship("Country")
    owner = relationship("User", foreign_keys=[owner_id])

    # 非持久化：由接口按需标注「是否已私信过」，默认 False 便于 from_attributes 序列化
    has_outreach: bool = False

    @property
    def platform_name(self) -> str | None:
        return self.platform.name if self.platform else None

    @property
    def platform_code(self) -> str | None:
        return self.platform.code if self.platform else None

    @property
    def country_name(self) -> str | None:
        return self.country_ref.name_zh if self.country_ref else None

    @property
    def country_name_en(self) -> str | None:
        return self.country_ref.name_en if self.country_ref else None

    @property
    def country_code(self) -> str | None:
        if self.country_ref:
            return self.country_ref.code
        return (self.country or None)

    @property
    def owner_name(self) -> str | None:
        return self.owner.username if self.owner else None
