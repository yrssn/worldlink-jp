from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.influencer import InfluencerSource, InfluencerStatus
from app.models.social_account import SocialPlatform


class SocialAccountBase(BaseModel):
    platform: SocialPlatform
    handle: Optional[str] = None
    url: Optional[str] = None
    followers: Optional[int] = None
    extra: Optional[dict[str, Any]] = None


class SocialAccountCreate(SocialAccountBase):
    pass


class SocialAccountOut(SocialAccountBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    influencer_id: int
    created_at: datetime


class InfluencerBase(BaseModel):
    display_name: str = Field(..., max_length=255)
    real_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None

    country: Optional[str] = "JP"
    region: Optional[str] = None
    city: Optional[str] = None
    language: Optional[str] = None
    address: Optional[str] = None

    email: Optional[str] = None
    phone: Optional[str] = None
    messenger: Optional[str] = None
    website: Optional[str] = None

    fb_page_id: Optional[str] = None
    fb_page_url: Optional[str] = None
    fb_page_title: Optional[str] = None
    fb_categories: Optional[list[str]] = None
    fb_followers: Optional[int] = None
    fb_likes: Optional[int] = None
    fb_rating: Optional[float] = None
    fb_rating_count: Optional[int] = None
    fb_checkins_mentions: Optional[int] = None
    fb_page_created_at: Optional[datetime] = None
    fb_ad_library_id: Optional[str] = None
    fb_ad_status: Optional[str] = None

    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    status: InfluencerStatus = InfluencerStatus.pre_contact
    platform_id: Optional[int] = None


class InfluencerCreate(InfluencerBase):
    social_accounts: Optional[list[SocialAccountCreate]] = None


class InfluencerUpdate(BaseModel):
    display_name: Optional[str] = None
    real_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    language: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    messenger: Optional[str] = None
    website: Optional[str] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    status: Optional[InfluencerStatus] = None
    platform_id: Optional[int] = None


class InfluencerOut(InfluencerBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: InfluencerSource
    platform_name: Optional[str] = None
    owner_id: int
    has_outreach: bool = False
    created_at: datetime
    updated_at: datetime


class InfluencerDetailOut(InfluencerOut):
    social_accounts: list[SocialAccountOut] = []
    source_post_ids: list[int] = []


class InfluencerScrapeTaskCreate(BaseModel):
    """发起「自动抓取」：传入主页 URL（FB 主页链接 / IG 用户名或主页链接）与平台。"""

    url: str = Field(..., max_length=512)
    # facebook（默认）/ instagram，为以后更多平台预留
    platform: str = Field(default="facebook", max_length=32)


class InfluencerScrapeTaskOut(BaseModel):
    """自动抓取任务状态，done 后 result 为可填充表单的达人字段。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str = "facebook"
    url: str
    status: str
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    created_at: datetime
    finished_at: Optional[datetime] = None
    # 该任务抓到的主页是否已入库建联达人（命中则为达人 id，便于前端展示「已存入」）
    influencer_id: Optional[int] = None


class InfluencerScrapeTaskSaveRequest(BaseModel):
    """把某个抓取任务的结果存入建联达人库时的可选备注。"""

    notes: Optional[str] = None


class InfluencerFromScrapeRequest(BaseModel):
    """从抓取"待审核博主"列表点击【建联】时使用。
    传入 post_id 或 author_url，其中任一即可定位。
    """

    post_id: Optional[int] = None
    author_url: Optional[str] = None
    page_profile: Optional[dict[str, Any]] = None  # 已抓到的 page profile（可选）
    source_post_ids: Optional[list[int]] = None    # 触发该 Page 的源帖子 ids（来自 page_profile._source_post_ids）
    notes: Optional[str] = None
