from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.influencer import InfluencerSource, InfluencerStatus
from app.models.social_account import SocialPlatform


class SocialAccountProfile(BaseModel):
    """账号维度的资料字段（链接 / 粉丝 / 点赞 / 评分 / Messenger …），建/改/出共用。"""

    handle: Optional[str] = Field(default=None, max_length=128)
    url: Optional[str] = Field(default=None, max_length=512)
    followers: Optional[int] = None
    #: 平台内页面/账号 ID（原 fb_page_id）
    page_id: Optional[str] = Field(default=None, max_length=128)
    #: 平台内作者 ID（原 fb_author_id）
    author_id: Optional[str] = Field(default=None, max_length=255)
    #: 账号名 / 页面名称（原 fb_page_title）
    title: Optional[str] = Field(default=None, max_length=255)
    avatar_url: Optional[str] = Field(default=None, max_length=512)
    categories: Optional[list[str]] = None
    likes: Optional[int] = None
    rating: Optional[float] = None
    rating_count: Optional[int] = None
    checkins_mentions: Optional[int] = None
    page_created_at: Optional[datetime] = None
    ad_library_id: Optional[str] = Field(default=None, max_length=128)
    ad_status: Optional[str] = Field(default=None, max_length=64)
    #: 该账号的 Messenger / 私信入口
    messenger: Optional[str] = Field(default=None, max_length=255)
    #: 该账号备注
    notes: Optional[str] = Field(default=None, max_length=512)
    extra: Optional[dict[str, Any]] = None


class SocialAccountBase(SocialAccountProfile):
    platform: SocialPlatform
    #: 关联「平台管理」里的平台 id，不传时按 platform 自动对齐
    platform_id: Optional[int] = None


class SocialAccountCreate(SocialAccountBase):
    pass


class SocialAccountUpdate(SocialAccountProfile):
    """编辑单个社交账号：平台 / 平台关联 / 账号 / 链接 / 粉丝 / 点赞 / 评分 / 备注 / Messenger 等全部字段。"""

    platform: Optional[SocialPlatform] = None
    platform_id: Optional[int] = None


class SocialAccountOut(SocialAccountBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    influencer_id: int
    #: 「平台管理」里的平台展示名（未关联时为 None）
    platform_name: Optional[str] = None
    last_scraped_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class InfluencerProfileFields(BaseModel):
    """存量 Excel 表头对应的「人 / 建联」维度可选字段（KOL 编号 / 公司 / 性别 / 负责人 / 日期…）。"""

    code: Optional[str] = Field(default=None, max_length=64, description="KOL 编号")
    company: Optional[str] = Field(default=None, max_length=255, description="KOL 公司名")
    gender: Optional[str] = Field(default=None, max_length=16)
    contact_owner: Optional[str] = Field(default=None, max_length=64, description="建联负责人")
    landing_owner: Optional[str] = Field(default=None, max_length=64, description="落地负责人")
    source_channel: Optional[str] = Field(default=None, max_length=128, description="来源渠道")
    contact_started_at: Optional[datetime] = Field(default=None, description="建联开始日期")
    planned_visit_at: Optional[datetime] = Field(default=None, description="计划首次来访时间")
    has_twitter: Optional[bool] = Field(default=None, description="是否推特")
    twitter_channel: Optional[str] = Field(default=None, max_length=128, description="推特渠道")
    group_name: Optional[str] = Field(default=None, max_length=255, description="群名称")


class InfluencerBase(InfluencerProfileFields):
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
    website: Optional[str] = None

    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    progress: Optional[str] = Field(default=None, max_length=255, description="建联进度")
    status: InfluencerStatus = InfluencerStatus.pre_contact
    platform_id: Optional[int] = None


class InfluencerCreate(InfluencerBase):
    #: 账号维度信息（主页链接 / 粉丝 / Messenger …）一律走这里落到关联账号表
    social_accounts: Optional[list[SocialAccountCreate]] = None


class InfluencerUpdate(InfluencerProfileFields):
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
    #: 关联的社交账号（列表内直接展示：平台 + 账号 + 粉丝）
    accounts: list[SocialAccountOut] = []
    #: 各关联账号粉丝数的最大值，列表展示 & 区间筛选口径
    followers: Optional[int] = None
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


class SocialAccountScrapeRequest(BaseModel):
    """列表「一键抓取」：选中该达人的某条关联账号（仅 Facebook / Instagram）后发起抓取，结果回写到该账号。"""

    social_account_id: int


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
    # 一键抓取时绑定的关联账号 id（结果回写到该账号）
    social_account_id: Optional[int] = None


class InfluencerScrapeTaskPageOut(BaseModel):
    items: list[InfluencerScrapeTaskOut]
    total: int


class InfluencerScrapeBatchRunRequest(BaseModel):
    """整批操作：按批次名（可选限定平台）把暂存/失败的任务一次性丢进抓取队列。"""

    batch: Optional[str] = Field(default=None, max_length=128)
    platform: Optional[str] = Field(default=None, max_length=32)
    include_failed: bool = True
    #: 抓完是否直接入库达人库；save_status 为入库后的建联状态（默认预建联）
    auto_save: bool = False
    save_status: Optional[str] = Field(default=None, max_length=32)


class ImportColumnPreview(BaseModel):
    """上传表格的一列：列名 + 前几行样例 + 是否像主页链接列。"""

    index: int
    name: str
    samples: list[str] = []
    looks_like_url: bool = False


class ImportFieldOut(BaseModel):
    key: str
    label: str
    required: bool = False


class ImportPreviewOut(BaseModel):
    """表格导入第一步：回显列名/样例，交由用户选择主页链接列。"""

    filename: str
    total_rows: int
    columns: list[ImportColumnPreview] = []
    #: 猜测的主页链接列下标（用户可改）
    suggested_url_column: Optional[int] = None
    #: 按表头名猜的字段 -> 列下标（键见 IMPORT_FIELDS，用户可改）
    suggested_columns: dict[str, int] = {}
    #: 可映射的字段清单（key + 中文名），前端据此渲染列映射
    fields: list[ImportFieldOut] = []


class ImportConflictOut(BaseModel):
    """导入时被「对照账号」占用而跳过的行。"""

    url: str
    owner: str


class ImportResultOut(BaseModel):
    """表格导入结果统计。"""

    total_rows: int
    created: int
    #: 链接匹配到已有达人并补了资料的行数
    updated: int = 0
    duplicated: int
    skipped: int
    scrape_tasks: int
    batch: Optional[str] = None
    #: 主页链接已在对照账号名下、按配置区别开而跳过的行数及明细
    cross_user_skipped: int = 0
    cross_user_conflicts: list[ImportConflictOut] = Field(default_factory=list)


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
