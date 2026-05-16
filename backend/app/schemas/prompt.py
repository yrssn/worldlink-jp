from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class PromptTemplateBase(BaseModel):
    name: str
    description: Optional[str] = None
    system_prompt: str
    keywords: Optional[list[str]] = None
    filter_rules: Optional[dict[str, Any]] = None
    output_schema: Optional[dict[str, Any]] = None
    is_active: bool = True


class PromptTemplateCreate(PromptTemplateBase):
    pass


class PromptTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    keywords: Optional[list[str]] = None
    filter_rules: Optional[dict[str, Any]] = None
    output_schema: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None


class PromptTemplateOut(PromptTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    created_at: datetime
    updated_at: datetime
