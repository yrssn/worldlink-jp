from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

FbGroupViewOption = Literal[
    "CHRONOLOGICAL",
    "RECENT_ACTIVITY",
    "TOP_POSTS",
    "CHRONOLOGICAL_LISTINGS",
]


class FbGroupScrapeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_by_id: int
    created_by_username: Optional[str] = None
    connection: str
    title: str
    remark: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


class FbGroupScrapeCreate(BaseModel):
    connection: str = Field(..., min_length=1, description="连接/群组 URL")
    title: str = Field(..., min_length=1, max_length=200)
    remark: Optional[str] = Field(None, max_length=500)


class FbGroupScrapeUpdate(BaseModel):
    connection: Optional[str] = Field(None, min_length=1)
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    remark: Optional[str] = Field(None, max_length=500)


class FbGroupPullBody(BaseModel):
    """调用 Apify facebook-groups-scraper 的可选参数。"""

    results_limit: int = Field(20, ge=1, le=500, description="帖子条数上限")
    view_option: FbGroupViewOption = Field(
        "CHRONOLOGICAL",
        description="排序：CHRONOLOGICAL / RECENT_ACTIVITY / TOP_POSTS / CHRONOLOGICAL_LISTINGS",
    )
    search_group_keyword: Optional[str] = Field(
        None, description="按字母搜索（未登录时效果有限）"
    )
    search_group_year: Optional[str] = Field(None, description="配合 search_group_keyword 的年份")
    only_posts_newer_than: Optional[str] = Field(
        None, description="仅抓取该日期之后，如 2024-01-01 或 7 days"
    )


class FbGroupPullOut(BaseModel):
    """拉取结果（暂不入库，直接返回给前端展示）。"""

    config_id: int
    group_url: str
    apify_run_id: Optional[str] = None
    apify_dataset_id: Optional[str] = None
    input_used: dict[str, Any] = Field(default_factory=dict)
    count: int = 0
    field_keys: list[str] = Field(default_factory=list, description="所有条目字段名并集")
    items: list[dict[str, Any]] = Field(default_factory=list)


# ─── 后台拉取任务 ───────────────────────────────────────────────

class FbGroupPullTaskOut(BaseModel):
    """后台拉取任务（返回给前端）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    config_id: int
    config_title: Optional[str] = None
    created_by_id: int
    created_by_username: Optional[str] = None
    status: str
    params: Optional[dict[str, Any]] = None
    apify_run_id: Optional[str] = None
    apify_dataset_id: Optional[str] = None
    result_count: int = 0
    duplicate_count: int = 0
    filtered_count: int = 0
    total_fetched: int = 0
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class FbGroupPullTaskCreate(BaseModel):
    """提交后台拉取任务的请求体（与 FbGroupPullBody 相同字段）。"""

    results_limit: int = Field(20, ge=1, le=500)
    view_option: FbGroupViewOption = Field("CHRONOLOGICAL")
    search_group_keyword: Optional[str] = None
    search_group_year: Optional[str] = None
    only_posts_newer_than: Optional[str] = None


class FbGroupBatchPullBody(BaseModel):
    """批量拉取请求体：多个 config_id + 共享拉取参数。"""

    config_ids: list[int] = Field(..., min_length=1, description="群组配置 ID 列表")
    results_limit: int = Field(20, ge=1, le=500)
    view_option: FbGroupViewOption = Field("CHRONOLOGICAL")
    search_group_keyword: Optional[str] = None
    search_group_year: Optional[str] = None
    only_posts_newer_than: Optional[str] = None


# ─── 帖子 ──────────────────────────────────────────────────────

class FbGroupPostOut(BaseModel):
    """群组帖子（结构化）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    config_id: int
    legacy_id: str
    post_url: Optional[str] = None
    facebook_group_id: Optional[str] = None
    group_title: Optional[str] = None
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    text: Optional[str] = None
    post_time: Optional[datetime] = None
    likes_count: int = 0
    comments_count: int = 0
    shares_count: int = 0
    has_attachments: bool = False
    has_shared_post: bool = False
    raw_data: Optional[dict[str, Any]] = None
    created_at: datetime

    # 建联 / 分析
    influencer_id: Optional[int] = None
    pre_contact_status: Optional[str] = None
    pre_contact_error: Optional[str] = None
    analysis: Optional[dict[str, Any]] = None
    analyzed_at: Optional[datetime] = None


class FbGroupPostPage(BaseModel):
    """帖子分页响应。"""

    total: int
    page: int
    page_size: int
    items: list[FbGroupPostOut]
    filtered_count: int = Field(
        0, description="命中分析过滤（已建联）的帖子数（当前过滤条件下）"
    )


class FbGroupPreContactOut(BaseModel):
    """预建联结果。"""

    post_id: int
    influencer_id: Optional[int] = None
    created: bool = False
    status: str
    message: str


# ─── 定时任务 ──────────────────────────────────────────────────────

class FbGroupScheduleTaskOut(BaseModel):
    """定时拉取任务（返回给前端）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    config_id: int
    config_title: Optional[str] = None
    created_by_id: int
    created_by_username: Optional[str] = None
    status: str
    schedule_type: str
    schedule_config: dict[str, Any]
    pull_params: Optional[dict[str, Any]] = None
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    last_task_id: Optional[int] = None
    consecutive_failures: int = 0
    max_consecutive_failures: int = 5
    remark: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class FbGroupScheduleTaskCreate(BaseModel):
    """创建定时任务请求体。"""

    schedule_type: Literal["cron", "interval"] = Field(
        ..., description="cron 或 interval"
    )
    schedule_config: dict[str, Any] = Field(
        ...,
        description='cron: {"cron": "0 10 * * *"} 或 interval: {"hours": 24}',
    )
    pull_params: Optional[dict[str, Any]] = Field(
        None,
        description="拉取参数（results_limit, view_option 等）",
    )
    max_consecutive_failures: int = Field(5, ge=1, le=100)
    remark: Optional[str] = Field(None, max_length=500)


class FbGroupScheduleTaskUpdate(BaseModel):
    """更新定时任务请求体。"""

    status: Optional[Literal["active", "paused", "disabled"]] = None
    schedule_type: Optional[Literal["cron", "interval"]] = None
    schedule_config: Optional[dict[str, Any]] = None
    pull_params: Optional[dict[str, Any]] = None
    max_consecutive_failures: Optional[int] = Field(None, ge=1, le=100)
    remark: Optional[str] = Field(None, max_length=500)
