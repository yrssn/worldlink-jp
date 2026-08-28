from __future__ import annotations

import enum

from sqlalchemy import JSON, Enum, ForeignKey, Integer, String
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
    """达人在各平台的社交账号 1:N。"""

    __tablename__ = "influencer_social_accounts"

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

    platform_ref: Mapped["BitBrowserPlatform | None"] = relationship(  # noqa: F821
        "BitBrowserPlatform", lazy="joined"
    )

    @property
    def platform_name(self) -> str | None:
        """「平台管理」里的展示名，没关联时为 ``None``。"""
        return self.platform_ref.name if self.platform_ref else None
