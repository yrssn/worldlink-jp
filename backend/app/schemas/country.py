from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CountryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: Optional[int] = None
    name_zh: str
    name_en: Optional[str] = None
    code: Optional[str] = None
    remark: Optional[str] = None
    sort_order: int = 0
    label: str
    created_at: datetime
    updated_at: datetime


class CountryCreate(BaseModel):
    name_zh: str = Field(..., min_length=1, max_length=128, description="中文名，如 日本")
    name_en: Optional[str] = Field(None, max_length=128, description="英文名，如 Japan")
    code: Optional[str] = Field(None, max_length=16, description="国家代码，如 JP")
    remark: Optional[str] = None
    sort_order: int = 0


class CountryUpdate(BaseModel):
    name_zh: Optional[str] = Field(None, min_length=1, max_length=128)
    name_en: Optional[str] = Field(None, max_length=128)
    code: Optional[str] = Field(None, max_length=16)
    remark: Optional[str] = None
    sort_order: Optional[int] = None
