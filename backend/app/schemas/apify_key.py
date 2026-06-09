from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ApifyKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    token: str
    is_default: bool
    remark: Optional[str] = None
    exhausted_at: Optional[datetime] = None
    email_account_id: Optional[int] = None
    email_account_email: Optional[str] = None
    email_account_verification_email: Optional[str] = None
    apify_full_name: Optional[str] = None
    apify_username: Optional[str] = None
    apify_user_id: Optional[str] = None
    apify_registered_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ApifyKeyCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=200)
    token: str = Field(..., min_length=1, max_length=500)
    is_default: bool = False
    remark: Optional[str] = Field(None, max_length=500)
    email_account_id: Optional[int] = None
    apify_full_name: Optional[str] = Field(None, max_length=128)
    apify_username: Optional[str] = Field(None, max_length=128)
    apify_user_id: Optional[str] = Field(None, max_length=128)
    apify_registered_at: Optional[datetime] = None


class ApifyKeyUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=200)
    token: Optional[str] = Field(None, min_length=1, max_length=500)
    remark: Optional[str] = Field(None, max_length=500)
    email_account_id: Optional[int] = None
    apify_full_name: Optional[str] = Field(None, max_length=128)
    apify_username: Optional[str] = Field(None, max_length=128)
    apify_user_id: Optional[str] = Field(None, max_length=128)
    apify_registered_at: Optional[datetime] = None
