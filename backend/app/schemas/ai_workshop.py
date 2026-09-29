"""AI 工坊 schemas：密钥管理 / 调用记录 / Agent 请求。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ----- 密钥管理（Web 端） ----- #
class AiApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    expires_at: Optional[datetime] = None
    #: 超级管理员可指定属主，替其他用户生成密钥；普通用户忽略/校验为本人
    owner_id: Optional[int] = None


class AiApiKeyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    is_active: Optional[bool] = None
    expires_at: Optional[datetime] = None


class AiApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    name: str
    key_prefix: str
    is_active: bool
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    last_used_ip: Optional[str] = None
    created_at: datetime


class AiApiKeyCreatedOut(AiApiKeyOut):
    #: 完整明文密钥，仅创建时返回这一次
    key: str


# ----- 调用记录 ----- #
class AiApiCallLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key_id: Optional[int] = None
    key_name: Optional[str] = None
    action: str
    status: str
    error: Optional[str] = None
    detail: Optional[dict] = None
    created_at: datetime


class AiApiCallLogPageOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[AiApiCallLogOut]


# ----- Agent REST（API Key 认证） ----- #
class AgentSearchRequest(BaseModel):
    keyword: Optional[str] = None
    platform: Optional[str] = None
    country: Optional[str] = None
    status: Optional[str] = None
    followers_min: Optional[int] = Field(None, ge=0)
    followers_max: Optional[int] = Field(None, ge=0)
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=50)


class AgentInfluencerUpsertRequest(BaseModel):
    """字段全部可选；upsert 按 url/handle/page_id/author_id 去重。"""

    display_name: Optional[str] = None
    platform: Optional[str] = None
    url: Optional[str] = None
    handle: Optional[str] = None
    title: Optional[str] = None
    followers: Optional[int] = None
    page_id: Optional[str] = None
    author_id: Optional[str] = None
    avatar_url: Optional[str] = None
    messenger: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    bio: Optional[str] = None
    code: Optional[str] = None
    company: Optional[str] = None
    gender: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    contact_owner: Optional[str] = None
    landing_owner: Optional[str] = None
    source_channel: Optional[str] = None
    progress: Optional[str] = None
    country: Optional[str] = None
    country_id: Optional[int] = None
    status: Optional[str] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    extra: Optional[dict[str, Any]] = None


class AgentUpsertResultOut(BaseModel):
    action: str
    matched_by: Optional[str] = None
    influencer_id: int
    display_name: Optional[str] = None
