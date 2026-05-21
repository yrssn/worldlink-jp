from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


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
