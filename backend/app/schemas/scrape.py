from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.scrape import ScrapeTaskStatus, ScrapeTaskType


class ScrapeTaskCreate(BaseModel):
    name: Optional[str] = None
    task_type: ScrapeTaskType

    keywords: Optional[list[str]] = None
    hashtags: Optional[list[str]] = None
    address: Optional[str] = None
    start_urls: Optional[list[str]] = None
    max_items: int = Field(50, ge=1, le=1000)
    posts_per_page: int = Field(10, ge=1, le=200)
    page_limit: int = Field(50, ge=1, le=500)
    extra_input: Optional[dict[str, Any]] = None

    enable_ai_filter: bool = False
    llm_provider_id: Optional[int] = None
    prompt_template_id: Optional[int] = None


class ScrapeTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: Optional[str]
    task_type: ScrapeTaskType
    status: ScrapeTaskStatus
    keywords: Optional[list[str]]
    hashtags: Optional[list[str]]
    address: Optional[str]
    start_urls: Optional[list[str]]
    max_items: int
    posts_per_page: int
    page_limit: int
    extra_input: Optional[dict[str, Any]] = None
    enable_ai_filter: bool
    llm_provider_id: Optional[int]
    prompt_template_id: Optional[int]
    apify_run_id: Optional[str]
    apify_dataset_id: Optional[str]
    result_count: int
    filtered_count: int
    error: Optional[str]
    owner_id: int
    created_at: datetime
    updated_at: datetime
