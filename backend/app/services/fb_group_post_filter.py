"""Facebook 群组帖子过滤入口。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Query, Session

from app.models.fb_group_scrape import FbGroupPost
from app.models.influencer import Influencer


def normalize_influencer_name(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.strip().lower().split())


def extract_post_user_name(item: dict[str, Any]) -> str:
    user_obj = item.get("user") if isinstance(item.get("user"), dict) else {}
    return str(user_obj.get("name") or "").strip()


def influencer_name_exists(db: Session, owner_id: int, user_name: str | None) -> bool:
    normalized = normalize_influencer_name(user_name)
    if not normalized:
        return False
    return (
        db.query(Influencer.id)
        .filter(
            Influencer.owner_id == owner_id,
            func.lower(func.trim(Influencer.display_name)) == normalized,
        )
        .first()
        is not None
    )


def should_filter_group_post_item(db: Session, owner_id: int, item: dict[str, Any]) -> bool:
    return influencer_name_exists(db, owner_id, extract_post_user_name(item))


def exclude_known_influencer_posts(query: Query, db: Session, owner_id: int) -> Query:
    known_names = select(func.lower(func.trim(Influencer.display_name))).where(
        Influencer.owner_id == owner_id,
        Influencer.display_name.isnot(None),
    )
    post_name = func.lower(func.trim(FbGroupPost.user_name))
    return query.filter(
        or_(
            FbGroupPost.user_name.is_(None),
            ~post_name.in_(known_names),
        )
    )
