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
    country_id: Optional[int] = Field(default=None, description="关联「国家管理」里的国家 id")
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
    progress: Optional[str] = Field(default=None, max_length=255, description="建联进度")
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
    country_id: Optional[int] = None
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
    progress: Optional[str] = Field(default=None, max_length=255)
    status: Optional[InfluencerStatus] = None
    platform_id: Optional[int] = None


class InfluencerOut(InfluencerBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: InfluencerSource
    #: 关联的社交账号（列表鼠标悬浮展示用）
    accounts: list[SocialAccountOut] = []
    platform_name: Optional[str] = None
    platform_code: Optional[str] = None
    country_name: Optional[str] = None
    country_name_en: Optional[str] = None
    country_code: Optional[str] = None
    owner_id: int
    owner_name: Optional[str] = None
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


class InfluencerScrapeBatchCreate(BaseModel):
    """批量导入链接到暂存区：只保存不跑抓取，按 平台 + 批次名 分组。"""

    urls: list[str] = Field(..., description="链接/用户名列表（前端按行拆分后传入）")
    #: ``auto`` = 按链接正则逐条自动识别平台；识别不出时用 fallback_platform
    platform: str = Field(default="auto", max_length=32)
    fallback_platform: str = Field(default="facebook", max_length=32)
    batch: Optional[str] = Field(default=None, max_length=128, description="批次名，不传则自动生成")


class PlatformDetectRequest(BaseModel):
    """按链接正则预分类（导入前预览）。"""

    urls: list[str]


class PlatformDetectItem(BaseModel):
    """单条链接的识别结果。platform=None 表示没识别出来。"""

    url: str
    platform: Optional[str] = None
    platform_id: Optional[int] = None
    platform_name: Optional[str] = None
    scrapable: bool = False


class PlatformOption(BaseModel):
    """抓取任务里可选的平台，由「平台管理」的记录 + 平台代码对齐得到。"""

    #: 平台规范名（facebook / instagram / ...），抓取任务用它决定走哪个抓取器
    platform: str
    #: 「平台管理」里的展示名与 id（没在平台管理里维护时为内置名 / None）
    name: str
    platform_id: Optional[int] = None
    code: Optional[str] = None
    #: 是否支持自动抓资料（其余平台只能暂存）
    scrapable: bool = False


class InfluencerScrapeBatchOut(BaseModel):
    """批次分组汇总：平台 + 批次名 + 创建人 + 各状态计数。"""

    platform: str
    batch: Optional[str] = None
    #: 批次归属：谁建的就是谁的
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    total: int
    staged: int
    running: int = 0
    failed: int = 0
    done: int


class InfluencerScrapeTaskOut(BaseModel):
    """自动抓取任务状态，done 后 result 为可填充表单的达人字段。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str = "facebook"
    batch: Optional[str] = None
    url: str
    status: str
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    created_at: datetime
    finished_at: Optional[datetime] = None
    # 该任务抓到的主页是否已入库建联达人（命中则为达人 id，便于前端展示「已存入」）
    influencer_id: Optional[int] = None


class InfluencerScrapeBatchRunRequest(BaseModel):
    """整批操作：按批次名（可选限定平台）把暂存/失败的任务一次性丢进抓取队列。"""

    batch: Optional[str] = Field(default=None, max_length=128)
    platform: Optional[str] = Field(default=None, max_length=32)
    include_failed: bool = True
    #: 抓完是否直接入库达人库；save_status 为入库后的建联状态（默认预建联）
    auto_save: bool = False
    save_status: Optional[str] = Field(default=None, max_length=32)


class InfluencerScrapeBatchActionResult(BaseModel):
    """整批操作结果。"""

    affected: int
    skipped: int = 0


class InfluencerScrapeTaskUpdate(BaseModel):
    """在暂存列表内修改任务字段（目前支持改平台，纠正批量导入时选错的平台）。"""

    platform: Optional[str] = Field(default=None, max_length=32)


class InfluencerScrapeRunRequest(BaseModel):
    """发起抓取时的选项：抓完是否直接入库、入库后的建联状态。"""

    auto_save: bool = False
    save_status: Optional[str] = Field(default=None, max_length=32)


class InfluencerScrapeTaskSaveRequest(BaseModel):
    """把某个抓取任务的结果存入建联达人库时的可选备注。"""

    notes: Optional[str] = None


class AvatarCacheResult(BaseModel):
    """存量头像本地化结果：total 为本次处理条数，failed 的仍保留远端地址。"""

    total: int
    cached: int
    failed: int


class InfluencerScrapeSaveResult(BaseModel):
    """存入达人库的结果：created=False 表示库中已存在、已复用未重复创建。"""

    influencer: InfluencerOut
    created: bool


class InfluencerFromScrapeRequest(BaseModel):
    """从抓取"待审核博主"列表点击【建联】时使用。
    传入 post_id 或 author_url，其中任一即可定位。
    """

    post_id: Optional[int] = None
    author_url: Optional[str] = None
    page_profile: Optional[dict[str, Any]] = None  # 已抓到的 page profile（可选）
    source_post_ids: Optional[list[int]] = None    # 触发该 Page 的源帖子 ids（来自 page_profile._source_post_ids）
    notes: Optional[str] = None
