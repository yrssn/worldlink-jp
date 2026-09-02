from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class SocialPlatform(str, enum.Enum):
    facebook = "facebook"
    instagram = "instagram"
    tiktok = "tiktok"
    youtube = "youtube"
    twitter = "twitter"
    wechat = "wechat"
    xiaohongshu = "xiaohongshu"
    line = "line"
    other = "other"


class InfluencerSocialAccount(Base, TimestampMixin):
    """达人在各平台的社交账号 1:N。

    账号维度的信息（链接 / 粉丝 / 点赞 / 评分 / Messenger …）都落在这里，
    主表 ``influencers`` 只留「人 / 建联」维度。
    """

    __tablename__ = "influencer_social_accounts"
    __table_args__ = (
        Index("ix_isa_page_id", "page_id"),
        Index("ix_isa_url", "url", mysql_length=191),
    )

    influencer_id: Mapped[int] = mapped_column(
        ForeignKey("influencers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[SocialPlatform] = mapped_column(Enum(SocialPlatform), nullable=False)
    #: 关联「平台管理」里的平台（平台归属在账号上：一个达人可有多个平台的账号）
    platform_id: Mapped[int | None] = mapped_column(
        ForeignKey("bitbrowser_platforms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    handle: Mapped[str | None] = mapped_column(String(128), nullable=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    followers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    #: 平台内的页面/账号 ID（FB pageId / IG id）
    page_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: 平台内作者 ID（FB 群组帖子作者 user.id，用于按作者去重）
    author_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: 账号/页面名称（表头「账号名」）
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    categories: Mapped[list | None] = mapped_column(JSON, nullable=True)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checkins_mentions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ad_library_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ad_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 该账号的 Messenger / 私信入口
    messenger: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: 该账号备注（如「另一个账号」）
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    platform_ref: Mapped["BitBrowserPlatform | None"] = relationship(  # noqa: F821
        "BitBrowserPlatform", lazy="joined"
    )

    @property
    def platform_name(self) -> str | None:
        """「平台管理」里的展示名，没关联时为 ``None``。"""
        return self.platform_ref.name if self.platform_ref else None
