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
