from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class BitBrowserWindowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    browser_id: str
    seq: Optional[int] = None
    name: Optional[str] = None
    remark: Optional[str] = None
    platform: Optional[str] = None
    group_id: Optional[str] = None
    proxy_method: Optional[int] = None
    proxy_type: Optional[str] = None
    host: Optional[str] = None
    port: Optional[str] = None
    last_ip: Optional[str] = None
    account_username: Optional[str] = None
    status: Optional[int] = None
    raw_snapshot: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class BitBrowserWindowListOut(BitBrowserWindowOut):
    """窗口列表（含是否已登记到系统、自建平台归类）。"""

    saved_to_system: bool = False
    catalog_platform_id: Optional[int] = None
    catalog_platform_name: Optional[str] = None
    catalog_note: Optional[str] = None
    #: 已登记时：最近一次同步是否仍在本机列表中（本页有行的恒为 True）
    catalog_in_local_cache: Optional[bool] = None


class BitBrowserSyncResult(BaseModel):
    """从本地 BitBrowser 服务同步后的统计。"""

    fetched: int = Field(..., description="从本地 API 拉到的窗口条数")
    upserted: int = Field(..., description="写入或更新到本库的条数")
    removed_stale: int = Field(0, description="本地已不存在、从本库删除的条数")
    last_sync_at: Optional[datetime] = Field(
        None, description="本次同步完成时间（写入用户记录，便于前端展示）"
    )


class BitBrowserSyncMetaOut(BaseModel):
    """当前用户 BitBrowser 缓存元信息（无需触发本地同步）。"""

    last_sync_at: Optional[datetime] = Field(None, description="最近一次成功从本机同步的时间")
    cached_rows: int = Field(0, description="当前库中缓存的窗口条数")


class BitBrowserSettingsOut(BaseModel):
    """当前用户保存的本机 BitBrowser 连接信息（不返回 API Token 明文）。"""

    local_url: Optional[str] = None
    has_api_key: bool = False


class BitBrowserSettingsUpdate(BaseModel):
    """更新本机连接；api_key 仅在请求体中包含该字段时才会写入或清除。"""

    local_url: str = Field(..., min_length=4, max_length=512, description="Local API 根地址，如 http://127.0.0.1:54345")
    api_key: Optional[str] = Field(
        default=None,
        max_length=512,
        description="不传该字段则保留原 Token；传空字符串则清除；传非空则更新",
    )


class BitBrowserOpenResponse(BaseModel):
    """``POST /browser/open`` 代理返回（data 字段以 BitBrowser 原始为准）。"""

    success: bool = True
    data: dict[str, Any] = Field(default_factory=dict)


# ----- 自建平台 -----


class BitBrowserPlatformOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    name: str
    code: Optional[str] = None
    remark: Optional[str] = None
    sort_order: int = 0
    created_at: datetime
    updated_at: datetime


class BitBrowserPlatformCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    code: Optional[str] = Field(None, max_length=64)
    remark: Optional[str] = None
    sort_order: int = 0


class BitBrowserPlatformUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    code: Optional[str] = Field(None, max_length=64)
    remark: Optional[str] = None
    sort_order: Optional[int] = None


# ----- 窗口登记到系统（唯一键：owner_id + browser_id）-----


class BitBrowserCatalogSave(BaseModel):
    """保存/更新登记；以 BitBrowser 窗口 id 关联缓存表中的行。"""

    platform_id: Optional[int] = Field(None, description="自建平台 id，可为空表示仅登记不归类")
    note: Optional[str] = Field(None, description="备注")


class BitBrowserCatalogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    browser_id: str
    platform_id: Optional[int] = None
    platform_name: Optional[str] = None
    note: Optional[str] = None
    cached_window_name: Optional[str] = None
    cached_env_platform: Optional[str] = None
    in_local_cache: bool = True
    created_at: datetime
    updated_at: datetime


class BitBrowserCatalogRowOut(BitBrowserCatalogOut):
    """系统登记列表：登记信息 + 当前缓存行快照（无缓存时仅登记与快照字段有值）。"""

    seq: Optional[int] = None
    name: Optional[str] = None
    platform: Optional[str] = None
    remark: Optional[str] = None
    proxy_type: Optional[str] = None
    host: Optional[str] = None
    port: Optional[str] = None
    last_ip: Optional[str] = None
    account_username: Optional[str] = None
    status: Optional[int] = None
    window_updated_at: Optional[datetime] = None
