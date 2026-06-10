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
    purpose: str = Field("registration", min_length=1, max_length=64)
    status: str = Field("available", min_length=1, max_length=64)
    browser_id: Optional[str] = Field(None, max_length=64)
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
    last_verification_code: Optional[str] = Field(None, max_length=32)
    last_verification_at: Optional[datetime] = None
    note: Optional[str] = None


class ApifySignupStartOut(BaseModel):
    ok: bool = True
    browser_id: str
    signup_url: str
    first_url: str
    final_url: str
    logged_out: bool = False
    session_cleared: bool = False
    profile_cookies_cleared: bool = False
    profile_cookie_config_cleared: bool = False
    cleared_cookie_count: int = 0
    all_cookies_cleared: bool = False
    still_logged_in: bool = False
    ready: bool = False
    email_submitted: bool = False
    password_submitted: bool = False
    profile_submitted: bool = False
    captcha_required: bool = False
    email_verification_required: bool = False
    email_verified: bool = False
    email_already_taken: bool = False
    apify_login_attempted: bool = False
    apify_logged_in: bool = False
    apify_login_email_submitted: bool = False
    apify_login_password_submitted: bool = False
    apify_login_page_not_found: bool = False
    apify_login_url: Optional[str] = None
    apify_mail_inbox_ready: bool = False
    apify_mail_opened: bool = False
    apify_verification_link_clicked: bool = False
    apify_token_collected: bool = False
    apify_token_collection_attempted: bool = False
    apify_key_created: bool = False
    apify_key_id: Optional[int] = None
    apify_key_is_default: bool = False
    apify_full_name: Optional[str] = None
    apify_username: Optional[str] = None
    apify_user_id: Optional[str] = None
    apify_token: Optional[str] = None
    apify_registered_at: Optional[datetime] = None
    apify_mail_final_url: Optional[str] = None
    apify_mail_hint: Optional[str] = None
    apify_settings_final_url: Optional[str] = None
    open_hint: Optional[str] = None


class ApifySignupTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    email_account_id: int
    action: str
    status: str
    current_node: Optional[str] = None
    node_started_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    logs: Optional[str] = None
    result: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

class ZohoMailLoginOut(BaseModel):
    ok: bool = True
    browser_id: str
    mail_opened: bool = False
    mail_login_url: Optional[str] = None
    mail_final_url: Optional[str] = None
    mail_closed_tab_count: int = 0
    mail_email_submitted: bool = False
    mail_password_submitted: bool = False
    mail_verification_required: bool = False
    mail_refreshed: bool = False
    verification_mail_opened: bool = False
    verification_mail_login_url: Optional[str] = None
    verification_mail_final_url: Optional[str] = None
    verification_mail_login_submitted: bool = False
    verification_mail_inbox_ready: bool = False
    verification_mail_code_extracted: bool = False
    verification_code: Optional[str] = None
    mail_verification_code_submitted: bool = False
    mail_verification_refreshed: bool = False
    mail_verification_final_url: Optional[str] = None
    mail_verification_submit_hint: Optional[str] = None
    mail_open_hint: Optional[str] = None
    verification_mail_open_hint: Optional[str] = None


class VerificationMailLoginOut(BaseModel):
    ok: bool = True
    browser_id: str
    verification_mail_opened: bool = False
    verification_mail_login_url: Optional[str] = None
    verification_mail_final_url: Optional[str] = None
    verification_mail_login_submitted: bool = False
    verification_mail_inbox_ready: bool = False
    verification_mail_code_extracted: bool = False
    verification_code: Optional[str] = None
    verification_mail_open_hint: Optional[str] = None
