from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.llm import LlmProviderType


class LlmProviderBase(BaseModel):
    name: str = Field(..., max_length=64)
    provider: LlmProviderType
    model: str
    base_url: Optional[str] = None
    temperature: float = 0.2
    max_tokens: Optional[int] = None
    extra_params: Optional[dict[str, Any]] = None
    is_default: bool = False
    enabled: bool = True


class LlmProviderCreate(LlmProviderBase):
    api_key: Optional[str] = None


class LlmProviderUpdate(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    extra_params: Optional[dict[str, Any]] = None
    is_default: Optional[bool] = None
    enabled: Optional[bool] = None


class LlmProviderOut(LlmProviderBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    has_api_key: bool = False
    created_at: datetime
    updated_at: datetime


class LlmTestRequest(BaseModel):
    prompt: str = "你好，用一句话介绍你自己。"


class LlmTestResponse(BaseModel):
    ok: bool
    output: Optional[str] = None
    error: Optional[str] = None
