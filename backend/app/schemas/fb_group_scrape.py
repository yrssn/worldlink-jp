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
    """调用 Apify facebook-groups-scraper 的可选参数（测试默认条数较小）。"""

    results_limit: int = Field(5, ge=1, le=500, description="帖子条数上限")
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
