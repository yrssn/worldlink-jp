"""建联模块业务逻辑：查重、从抓取入库。

字段映射对齐 apify/facebook-pages-scraper（与 facebook-search-scraper 输出一致）的真实字段：
  facebookUrl / pageUrl / pageId / pageName / title / facebookId
  intro / about_me.text / websites[] / website / email / phone / address / messenger
  likes / followers / followings
  rating(字符串) / ratingOverall(int) / ratingCount(int)
  categories[] / creation_date(字符串) / ad_status(字符串)
  profilePictureUrl / coverPhotoUrl / profilePhoto
  pageAdLibrary.id / pageAdLibrary.is_business_page_active
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.bitbrowser import BitBrowserPlatform
from app.models.influencer import Influencer, InfluencerSource
from app.models.post import Post
from app.models.social_account import InfluencerSocialAccount, SocialPlatform
from app.services.fb_group_post_filter import normalize_influencer_name


def find_duplicate(
    db: Session,
    owner_id: int,
    fb_page_id: Optional[str] = None,
    fb_page_url: Optional[str] = None,
    email: Optional[str] = None,
) -> Optional[Influencer]:
    """根据 fb_page_id / fb_page_url / email 查重。"""
    q = db.query(Influencer).filter(Influencer.owner_id == owner_id)
    conds = []
    if fb_page_id:
        conds.append(Influencer.fb_page_id == fb_page_id)
    if fb_page_url:
        conds.append(Influencer.fb_page_url == fb_page_url)
    if email:
        conds.append(Influencer.email == email)
    if not conds:
        return None
    return q.filter(or_(*conds)).first()


def find_duplicate_for_platform_user(
    db: Session,
    owner_id: int,
    *,
    platform_id: int | None,
    fb_page_id: Optional[str] = None,
    fb_page_url: Optional[str] = None,
    email: Optional[str] = None,
    display_name: Optional[str] = None,
) -> Optional[Influencer]:
    existing = find_duplicate(
        db,
        owner_id,
        fb_page_id=fb_page_id,
        fb_page_url=fb_page_url,
        email=email,
    )
    if existing:
        return existing
    normalized_name = normalize_influencer_name(display_name)
    if not normalized_name:
        return None
    return (
        db.query(Influencer)
        .filter(
            Influencer.owner_id == owner_id,
            func.lower(func.trim(Influencer.display_name)) == normalized_name,
        )
        .first()
    )


def get_or_create_facebook_platform(db: Session, owner_id: int) -> BitBrowserPlatform:
    row = (
        db.query(BitBrowserPlatform)
        .filter(BitBrowserPlatform.owner_id == owner_id)
        .filter(
            (func.lower(BitBrowserPlatform.code).in_(("facebook", "fb")))
            | (func.lower(BitBrowserPlatform.name) == "facebook")
        )
        .order_by(BitBrowserPlatform.id.asc())
        .first()
    )
    if row:
        return row
    row = BitBrowserPlatform(
        owner_id=owner_id,
        name="Facebook",
        code="facebook",
        remark="自动用于 Facebook 群组帖子预建联",
        sort_order=0,
    )
    db.add(row)
    db.flush()
    return row


def _to_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        if isinstance(v, str):
            v = v.replace(",", "").strip()
        return int(float(v))
    except Exception:
        return None


def _to_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        if isinstance(v, str):
            # 形如 "94% recommend (839 Reviews)"，抽数字
            m = "".join(ch for ch in v.split("%")[0] if ch.isdigit() or ch == ".")
            return float(m) if m else None
        return float(v)
    except Exception:
        return None


def _parse_fb_creation_date(v: Any) -> Optional[datetime]:
    """facebook-pages-scraper 的 creation_date 形如 "October 7, 2012"。"""
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    s = str(v).strip()
    for fmt in (
        "%B %d, %Y",
        "%b %d, %Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _first(v: Any) -> Optional[str]:
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _map_page_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """把 apify facebook-pages-scraper / facebook-search-scraper 的字段映射到 Influencer 字段。"""
    about_me = profile.get("about_me") if isinstance(profile.get("about_me"), dict) else {}
    page_ad_library = profile.get("pageAdLibrary") if isinstance(profile.get("pageAdLibrary"), dict) else {}

    display_name = (
        profile.get("title")
        or profile.get("pageName")
        or profile.get("name")
        or "Unknown"
    )

    bio = (
        profile.get("intro")
        or about_me.get("text")
        or profile.get("description")
    )

    return {
        "display_name": display_name,
        "fb_page_id": str(profile.get("pageId") or profile.get("facebookId") or "") or None,
        "fb_page_url": profile.get("pageUrl") or profile.get("facebookUrl") or profile.get("url"),
        "fb_page_title": profile.get("title") or profile.get("pageName"),
        "bio": bio,
        "address": profile.get("address"),
        "phone": profile.get("phone"),
        "email": profile.get("email"),
        "website": profile.get("website") or _first(profile.get("websites")),
        "messenger": profile.get("messenger") or profile.get("messengerLink"),
        "fb_categories": profile.get("categories"),
        "fb_followers": _to_int(profile.get("followers") or profile.get("followersCount")),
        "fb_likes": _to_int(profile.get("likes") or profile.get("likesCount")),
        "fb_rating": _to_float(profile.get("ratingOverall") or profile.get("rating")),
        "fb_rating_count": _to_int(profile.get("ratingCount")),
        "fb_checkins_mentions": _to_int(profile.get("checkInsAndMentions") or profile.get("checkins")),
        "fb_page_created_at": _parse_fb_creation_date(profile.get("creation_date") or profile.get("pageCreatedAt")),
        "fb_ad_library_id": (page_ad_library.get("id") if page_ad_library else None) or profile.get("adLibraryId"),
        "fb_ad_status": profile.get("ad_status") or profile.get("adStatus"),
        "avatar_url": profile.get("profilePictureUrl") or profile.get("profilePhoto") or profile.get("profileImage"),
        "cover_url": profile.get("coverPhotoUrl") or profile.get("coverImage"),
        "raw_profile": profile,
    }


def create_from_scrape(
    db: Session,
    owner_id: int,
    post: Optional[Post],
    page_profile: Optional[dict[str, Any]] = None,
    notes: Optional[str] = None,
    source_post_ids: Optional[list[int]] = None,
) -> Influencer:
    """从抓取的【待审核博主】点击【建联】入库。
    - 优先用 page_profile（Pages Scraper / Search Scraper 抓回来的）做映射；
    - 若没有 profile，则尝试用 post.author_* 兜底；
    - 入库前去重，存在则把 post 关联过去，并返回已有记录。
    """
    profile_data: dict[str, Any] = {}
    if page_profile:
        profile_data.update(_map_page_profile(page_profile))

    if post:
        profile_data.setdefault("display_name", post.author_name or "Unknown")
        profile_data.setdefault("fb_page_url", post.author_url)
        profile_data.setdefault("fb_page_id", post.author_page_id)

    profile_data.setdefault("display_name", "Unknown")
    profile_data["source"] = InfluencerSource.scrape
    profile_data["owner_id"] = owner_id
    if not profile_data.get("platform_id"):
        profile_data["platform_id"] = get_or_create_facebook_platform(db, owner_id).id
    if notes:
        profile_data["notes"] = notes

    existing = find_duplicate_for_platform_user(
        db,
        owner_id=owner_id,
        platform_id=profile_data.get("platform_id"),
        fb_page_id=profile_data.get("fb_page_id"),
        fb_page_url=profile_data.get("fb_page_url"),
        email=profile_data.get("email"),
        display_name=profile_data.get("display_name"),
    )
    if existing:
        # 把当前 post + page_profile 上挂的所有源帖子统一关联过去
        _attach_posts(db, existing.id, post, source_post_ids)
        return existing

    inf = Influencer(**profile_data)
    db.add(inf)
    db.flush()

    if inf.fb_page_url or inf.fb_page_id:
        db.add(
            InfluencerSocialAccount(
                influencer_id=inf.id,
                platform=SocialPlatform.facebook,
                handle=inf.fb_page_id,
                url=inf.fb_page_url,
                followers=inf.fb_followers,
            )
        )

    _attach_posts(db, inf.id, post, source_post_ids)
    db.refresh(inf)
    return inf


def _attach_posts(
    db: Session,
    influencer_id: int,
    post: Optional[Post],
    source_post_ids: Optional[list[int]],
) -> None:
    """把指定帖子关联到达人。"""
    ids: set[int] = set()
    if post:
        ids.add(post.id)
    if source_post_ids:
        ids.update(int(x) for x in source_post_ids if x)
    if not ids:
        db.commit()
        return
    db.query(Post).filter(Post.id.in_(ids)).update(
        {Post.influencer_id: influencer_id}, synchronize_session=False
    )
    db.commit()
