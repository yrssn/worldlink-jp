from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: Optional[int]
    platform: str
    post_id: Optional[str]
    url: Optional[str]
    text: Optional[str]
    published_at: Optional[datetime]
    likes: int
    comments_count: int
    shares: int
    reactions: Optional[dict[str, Any]]
    media: Optional[list[Any]]

    author_name: Optional[str]
    author_url: Optional[str]
    author_page_id: Optional[str]

    keywords_hit: Optional[list[str]]
    ai_passed: Optional[bool]
    ai_score: Optional[float]
    ai_reason: Optional[str]

    influencer_id: Optional[int]
    owner_id: int
    created_at: datetime
