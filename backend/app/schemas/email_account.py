from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class EmailAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    email: str
    email_password: Optional[str] = None
    provider: Optional[str] = None
    mail_login_url: Optional[str] = None
    verification_email: Optional[str] = None
    verification_password: Optional[str] = None
    verification_login_url: Optional[str] = None
    purpose: str
    status: str
    browser_id: Optional[str] = None
    apify_full_name: Optional[str] = None
    apify_username: Optional[str] = None
    apify_user_id: Optional[str] = None
    apify_token: Optional[str] = None
    apify_registered_at: Optional[datetime] = None
    last_verification_code: Optional[str] = None
    last_verification_at: Optional[datetime] = None
    note: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class EmailAccountCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    email_password: Optional[str] = Field(None, max_length=500)
    provider: Optional[str] = Field("zoho", max_length=64)
    mail_login_url: Optional[str] = Field(None, max_length=512)
    verification_email: Optional[str] = Field(None, max_length=255)
    verification_password: Optional[str] = Field(None, max_length=500)
    verification_login_url: Optional[str] = Field(None, max_length=512)
    purpose: str = Field("apify", min_length=1, max_length=64)
    status: str = Field("unused", min_length=1, max_length=64)
    browser_id: Optional[str] = Field(None, max_length=64)
    apify_full_name: Optional[str] = Field(None, max_length=128)
    apify_username: Optional[str] = Field(None, max_length=128)
    apify_user_id: Optional[str] = Field(None, max_length=128)
    apify_token: Optional[str] = Field(None, max_length=500)
    apify_registered_at: Optional[datetime] = None
    last_verification_code: Optional[str] = Field(None, max_length=32)
    last_verification_at: Optional[datetime] = None
    note: Optional[str] = None


class EmailAccountUpdate(BaseModel):
    email: Optional[str] = Field(None, min_length=3, max_length=255)
    email_password: Optional[str] = Field(None, max_length=500)
    provider: Optional[str] = Field(None, max_length=64)
    mail_login_url: Optional[str] = Field(None, max_length=512)
    verification_email: Optional[str] = Field(None, max_length=255)
    verification_password: Optional[str] = Field(None, max_length=500)
    verification_login_url: Optional[str] = Field(None, max_length=512)
    purpose: Optional[str] = Field(None, min_length=1, max_length=64)
    status: Optional[str] = Field(None, min_length=1, max_length=64)
    browser_id: Optional[str] = Field(None, max_length=64)
    apify_full_name: Optional[str] = Field(None, max_length=128)
    apify_username: Optional[str] = Field(None, max_length=128)
    apify_user_id: Optional[str] = Field(None, max_length=128)
    apify_token: Optional[str] = Field(None, max_length=500)
    apify_registered_at: Optional[datetime] = None
    last_verification_code: Optional[str] = Field(None, max_length=32)
    last_verification_at: Optional[datetime] = None
    note: Optional[str] = None
