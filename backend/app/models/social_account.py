from __future__ import annotations

import enum

from sqlalchemy import JSON, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

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
    handle: Mapped[str | None] = mapped_column(String(128), nullable=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    followers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
