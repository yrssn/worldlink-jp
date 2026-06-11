"""Facebook 群组帖子分析（可扩展多维度）。

设计目标
========
抓帖子（拉取任务）完成后，对每条帖子跑一组「分析维度」，把结果写进
``FbGroupPost.analysis``（JSON）。后续会持续新增不同维度（关键词命中、
语言/地区识别、AI 评分等），所以这里用「注册表 + 统一接口」的方式，
新增维度只需实现一个 ``PostAnalyzer`` 并加入 ``ANALYZERS`` 即可，
不需要改动调用方。

analysis 结构示例::

    {
        "already_influencer": {
            "hit": true,        # 是否命中
            "filter": true,     # 是否应当在列表里被过滤掉
            "influencer_id": 12,
            "matched_by": "fb_page_id"
        },
        # ... 后续维度
    }

当前维度
========
- ``already_influencer``：帖子作者是否已经在「建联达人」里存在，
  存在则标记 ``filter=True``，前端默认隐藏，避免重复建联。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Protocol

from loguru import logger
from sqlalchemy.orm import Session

from app.models.fb_group_scrape import FbGroupPost
from app.services import influencer_service


# ─── 工具 ────────────────────────────────────────────────────────

def build_fb_profile_url(post: FbGroupPost) -> Optional[str]:
    """根据群组帖子里的作者信息推断其 Facebook 主页 URL。

    facebook-groups-scraper 的 ``user`` 对象通常只有 ``id`` / ``name``，
    据此拼出主页地址供 facebook-pages-scraper 抓取与去重比对。
    """
    raw = post.raw_data if isinstance(post.raw_data, dict) else {}
    user = raw.get("user") if isinstance(raw.get("user"), dict) else {}
    # 优先用原始数据里可能携带的主页字段
    for key in ("profileUrl", "url", "profile_url", "link"):
        val = user.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    uid = post.user_id or str(user.get("id") or "").strip()
    if uid:
        return f"https://www.facebook.com/{uid}"
    return None


# ─── 维度接口 ─────────────────────────────────────────────────────

class PostAnalyzer(Protocol):
    """单个分析维度。实现 ``dimension`` 与 ``analyze`` 即可。"""

    dimension: str

    def analyze(self, db: Session, owner_id: int, post: FbGroupPost) -> dict[str, Any]:
        ...


class AlreadyInfluencerAnalyzer:
    """维度：帖子作者是否已在「建联达人」中存在（已存在则过滤）。"""

    dimension = "already_influencer"

    def analyze(self, db: Session, owner_id: int, post: FbGroupPost) -> dict[str, Any]:
        # 已经预建联过（influencer_id 有值）直接视为命中
        if post.influencer_id:
            return {
                "hit": True,
                "filter": True,
                "influencer_id": post.influencer_id,
                "matched_by": "linked",
            }
        profile_url = build_fb_profile_url(post)
        existing = influencer_service.find_duplicate(
            db,
            owner_id=owner_id,
            fb_page_id=str(post.user_id) if post.user_id else None,
            fb_page_url=profile_url,
        )
        if existing:
            matched_by = "fb_page_id" if (
                post.user_id and existing.fb_page_id == str(post.user_id)
            ) else "fb_page_url"
            return {
                "hit": True,
                "filter": True,
                "influencer_id": existing.id,
                "matched_by": matched_by,
            }
        return {"hit": False, "filter": False}


# 注册表：新增维度时在此追加（顺序即执行顺序）。
ANALYZERS: list[PostAnalyzer] = [
    AlreadyInfluencerAnalyzer(),
]


# ─── 对外接口 ─────────────────────────────────────────────────────

def analyze_post(db: Session, owner_id: int, post: FbGroupPost) -> dict[str, Any]:
    """对单条帖子跑全部维度，返回 analysis dict（不落库）。"""
    result: dict[str, Any] = {}
    for analyzer in ANALYZERS:
        try:
            result[analyzer.dimension] = analyzer.analyze(db, owner_id, post)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[fb_group_analysis] dimension {} failed on post {}: {}",
                analyzer.dimension, post.id, e,
            )
            result[analyzer.dimension] = {"error": str(e)[:500]}
    return result


def analyze_posts(db: Session, owner_id: int, posts: list[FbGroupPost]) -> int:
    """对一批帖子跑分析并落库，返回被标记为「需过滤」的数量。

    若 ``already_influencer`` 维度命中已有达人，则把帖子的 ``influencer_id``
    指向该达人，便于列表用 SQL 直接过滤「已建联」帖子。
    """
    filtered = 0
    now = datetime.utcnow()
    for post in posts:
        post.analysis = analyze_post(db, owner_id, post)
        post.analyzed_at = now
        ai = post.analysis.get("already_influencer") or {}
        if (
            isinstance(ai, dict)
            and ai.get("hit")
            and ai.get("influencer_id")
            and not post.influencer_id
        ):
            post.influencer_id = ai["influencer_id"]
        if is_filtered(post.analysis):
            filtered += 1
    db.commit()
    return filtered


def is_filtered(analysis: Optional[dict[str, Any]]) -> bool:
    """任一维度标记 filter=True 即认为该帖子应被过滤。"""
    if not analysis:
        return False
    return any(
        isinstance(v, dict) and v.get("filter")
        for v in analysis.values()
    )
