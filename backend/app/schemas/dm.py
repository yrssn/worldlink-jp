from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class DmImageItem(BaseModel):
    url: str = Field(..., description="可访问的图片 URL")
    path: Optional[str] = Field(None, description="服务端存储相对路径")
    name: Optional[str] = None
    sort: int = 0


class DmCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    name: str
    code: Optional[str] = None
    color: Optional[str] = None
    remark: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class DmCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    code: Optional[str] = Field(None, max_length=64)
    color: Optional[str] = Field(None, max_length=32)
    remark: Optional[str] = Field(None, max_length=500)
    sort_order: int = 0
    is_active: bool = True


class DmCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    code: Optional[str] = Field(None, max_length=64)
    color: Optional[str] = Field(None, max_length=32)
    remark: Optional[str] = Field(None, max_length=500)
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class DmContentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    title: str
    summary: Optional[str] = None
    content: str
    images: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    is_active: bool = True
    is_pinned: bool = False
    sort_order: int = 0
    remark: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class DmContentCreate(BaseModel):
    category_id: Optional[int] = None
    title: str = Field(..., min_length=1, max_length=200)
    summary: Optional[str] = Field(None, max_length=500)
    content: str = Field(..., min_length=1)
    images: list[DmImageItem] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    is_active: bool = True
    is_pinned: bool = False
    sort_order: int = 0
    remark: Optional[str] = Field(None, max_length=500)


class DmContentUpdate(BaseModel):
    category_id: Optional[int] = None
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    summary: Optional[str] = Field(None, max_length=500)
    content: Optional[str] = Field(None, min_length=1)
    images: Optional[list[DmImageItem]] = None
    tags: Optional[list[str]] = None
    is_active: Optional[bool] = None
    is_pinned: Optional[bool] = None
    sort_order: Optional[int] = None
    remark: Optional[str] = Field(None, max_length=500)


class DmUploadOut(BaseModel):
    url: str
    path: str
    name: str


class DmOutreachStart(BaseModel):
    url: str = Field(..., min_length=1, description="达人主页链接")
    browser_id: str = Field(..., min_length=1, description="BitBrowser 窗口 ID")
    content_id: int = Field(..., description="私信内容库内容 ID")
    platform: str = Field("facebook", description="平台：facebook / instagram")
    source_task_id: int | None = Field(
        None, description="来源暂存任务 ID（从暂存列表发起时传入，用于复用同一行并自动入库）"
    )


class DmOutreachOut(BaseModel):
    ok: bool
    browser_id: str
    content_id: int
    content_title: Optional[str] = None
    page_opened: bool = False
    message_clicked: bool = False
    matched_text: Optional[str] = None
    text_sent: bool = False
    images_sent: int = 0
    scrape_task_id: Optional[int] = None
    final_url: Optional[str] = None
    open_hint: Optional[Any] = None


class DmOutreachLogOut(BaseModel):
    """私信建联发送记录（达人详情页展示：发了哪条私信、什么时候）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    influencer_id: Optional[int] = None
    url: str
    browser_id: Optional[str] = None
    content_id: Optional[int] = None
    content_title: Optional[str] = None
    content_text: Optional[str] = None
    images_count: int = 0
    text_sent: bool = False
    images_sent: int = 0
    job_id: Optional[int] = None
    browser_name: Optional[str] = None
    status: str = "success"
    error: Optional[str] = None
    owner_id: Optional[int] = None
    owner_name: Optional[str] = Field(None, description="发送人用户名")
    created_at: datetime


class DmOutreachJobCreate(BaseModel):
    """从达人库对已入库达人发起一次批量私信任务。"""

    influencer_ids: list[int] = Field(..., min_length=1, description="达人 ID 列表")
    browser_id: str = Field(..., min_length=1, description="BitBrowser 窗口 ID")
    content_id: int = Field(..., description="私信内容库内容 ID")
    platform: str = Field("facebook", description="平台：facebook / instagram")
    interval_min: int = Field(60, ge=0, le=86400, description="每条之间最少等待秒数")
    interval_max: int = Field(180, ge=0, le=86400, description="每条之间最多等待秒数（区间内随机）")


class DmOutreachJobTarget(BaseModel):
    influencer_id: int
    url: str
    display_name: Optional[str] = None


class DmOutreachJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    owner_name: Optional[str] = None
    platform: str
    browser_id: str
    browser_name: Optional[str] = None
    content_id: Optional[int] = None
    content_title: Optional[str] = None
    targets: Optional[list[DmOutreachJobTarget]] = None
    interval_min: int = 0
    interval_max: int = 0
    total: int = 0
    sent: int = 0
    failed: int = 0
    status: str
    current_url: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime


class DmOutreachJobDetailOut(DmOutreachJobOut):
    logs: list[DmOutreachLogOut] = []
