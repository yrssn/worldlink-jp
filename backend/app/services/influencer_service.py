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

import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.fb_group_scrape import FbGroupPost
from app.models.influencer import Influencer, InfluencerSource
from app.models.post import Post
from app.models.social_account import InfluencerSocialAccount, SocialPlatform


def find_duplicate(
    db: Session,
    owner_id: int,
    fb_author_id: Optional[str] = None,
    fb_page_id: Optional[str] = None,
    fb_page_url: Optional[str] = None,
    email: Optional[str] = None,
) -> Optional[Influencer]:
    """根据 fb_author_id（群组帖子作者 user.id）/ fb_page_id / fb_page_url / email 查重。

    已软删除（``deleted_at`` 有值）的达人不参与查重，便于删除后重新建联。
    """
    q = db.query(Influencer).filter(
        Influencer.owner_id == owner_id,
        Influencer.deleted_at.is_(None),
    )
    conds = []
    if fb_author_id:
        conds.append(Influencer.fb_author_id == fb_author_id)
    if fb_page_id:
        conds.append(Influencer.fb_page_id == fb_page_id)
    if fb_page_url:
        conds.append(Influencer.fb_page_url == fb_page_url)
    if email:
        conds.append(Influencer.email == email)
    if not conds:
        return None
    return q.filter(or_(*conds)).first()


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


_FB_GROUP_USER_RE = re.compile(r"/groups/\d+/user/(\d+)", re.IGNORECASE)
_FB_USER_PATH_RE = re.compile(r"/user/(\d+)", re.IGNORECASE)


def normalize_fb_profile_url(url: str | None) -> str:
    """把各种 Facebook 个人主页链接规整成 facebook-pages-scraper 能识别的标准格式。

    facebook-pages-scraper 只认主页/Page 链接，不认群组上下文链接
    （如 /groups/{群组ID}/user/{用户ID}）。这里统一抽取出数字用户 ID，
    转成 https://www.facebook.com/profile.php?id={uid}。无法识别时原样返回。
    """
    raw = (url or "").strip()
    if not raw:
        return raw
    if "://" not in raw:
        raw = "https://" + raw

    try:
        parts = urlsplit(raw)
    except ValueError:
        return (url or "").strip()

    host = (parts.netloc or "").lower()
    if "facebook.com" not in host:
        return (url or "").strip()

    path = parts.path or ""

    # 群组内成员入口：/groups/{gid}/user/{uid}
    m = _FB_GROUP_USER_RE.search(path) or _FB_USER_PATH_RE.search(path)
    if m:
        return f"https://www.facebook.com/profile.php?id={m.group(1)}"

    # 已是 profile.php?id=数字：只保留 id 参数，去掉群组/会话等多余参数
    if path.rstrip("/").endswith("/profile.php"):
        qs = parse_qs(parts.query)
        uid = (qs.get("id") or [None])[0]
        if uid and uid.isdigit():
            return f"https://www.facebook.com/profile.php?id={uid}"

    return (url or "").strip()


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


def page_profile_to_form(profile: dict[str, Any]) -> dict[str, Any]:
    """把 facebook-pages-scraper 抓回来的主页资料映射成「可填充表单」的达人字段。

    返回 JSON 友好（datetime → isoformat）、且只含表单需要的字段；去掉体积较大的 raw_profile。
    """
    mapped = _map_page_profile(profile)
    mapped.pop("raw_profile", None)
    created = mapped.get("fb_page_created_at")
    if isinstance(created, datetime):
        mapped["fb_page_created_at"] = created.isoformat()
    # 丢弃空值，避免覆盖用户已填内容
    return {k: v for k, v in mapped.items() if v not in (None, "")}


_FORM_INFLUENCER_FIELDS = (
    "display_name", "real_name", "bio", "avatar_url", "cover_url",
    "country", "region", "city", "language", "address",
    "email", "phone", "messenger", "website",
    "fb_page_id", "fb_page_url", "fb_page_title", "fb_categories",
    "fb_followers", "fb_likes", "fb_rating", "fb_rating_count",
    "fb_checkins_mentions", "fb_ad_library_id", "fb_ad_status",
    "tags", "notes",
)


def create_influencer_from_form(
    db: Session,
    owner_id: int,
    form: dict[str, Any],
    notes: Optional[str] = None,
) -> tuple[Influencer, bool]:
    """把「自动抓取任务」的可填充表单结果入库为建联达人。

    - 只取白名单字段，避免脏字段；fb_page_created_at(ISO 字符串)单独解析；
    - 按 fb_page_id / fb_page_url / email 去重，命中则复用已有，不重复创建；
    返回 (influencer, created)。
    """
    data: dict[str, Any] = {
        k: form.get(k) for k in _FORM_INFLUENCER_FIELDS if form.get(k) not in (None, "")
    }
    created_raw = form.get("fb_page_created_at")
    if isinstance(created_raw, str) and created_raw:
        try:
            data["fb_page_created_at"] = datetime.fromisoformat(created_raw)
        except ValueError:
            pass

    data.setdefault("display_name", "Unknown")
    data["owner_id"] = owner_id
    data["source"] = InfluencerSource.scrape
    if notes:
        data["notes"] = notes

    existing = find_duplicate(
        db,
        owner_id=owner_id,
        fb_page_id=data.get("fb_page_id"),
        fb_page_url=data.get("fb_page_url"),
        email=data.get("email"),
    )
    if existing:
        return existing, False

    inf = Influencer(**data)
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
    db.commit()
    db.refresh(inf)
    return inf, True


def _looks_like_instagram(profile: dict[str, Any]) -> bool:
    """判断一条 page_profile 是否来自 instagram-profile-scraper。

    Facebook Pages/Search Scraper 输出含 pageUrl / facebookUrl / pageName；
    Instagram Profile Scraper 输出以 username + followersCount 为特征。
    """
    if not isinstance(profile, dict):
        return False
    if any(profile.get(k) for k in ("pageUrl", "facebookUrl", "pageName", "pageId")):
        return False
    for key in ("inputUrl", "url"):
        v = profile.get(key)
        if isinstance(v, str) and "instagram.com" in v.lower():
            return True
    if profile.get("username") and (
        "followersCount" in profile
        or "profilePicUrl" in profile
        or "igtvVideoCount" in profile
        or "isBusinessAccount" in profile
    ):
        return True
    return False


def _ig_handle_url(profile: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    username = profile.get("username")
    handle = str(username).strip() if username else None
    url = profile.get("url") or profile.get("inputUrl")
    if not url and handle:
        url = f"https://www.instagram.com/{handle}"
    return handle, url


def _map_ig_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """把 apify/instagram-profile-scraper 的字段映射到 Influencer 通用字段。

    IG 没有 Facebook Page 概念，故只填写跨平台通用字段，
    IG 身份（用户名 / 主页 URL / 粉丝数）单独记到 InfluencerSocialAccount。
    """
    about = profile.get("about") if isinstance(profile.get("about"), dict) else {}
    display_name = profile.get("fullName") or profile.get("username") or "Unknown"
    return {
        "display_name": display_name,
        "real_name": profile.get("fullName"),
        "bio": profile.get("biography"),
        "avatar_url": profile.get("profilePicUrlHD") or profile.get("profilePicUrl"),
        "website": profile.get("externalUrl") or _first(profile.get("externalUrls")),
        "country": about.get("country") if about else None,
        "raw_profile": profile,
    }


def find_duplicate_social(
    db: Session,
    owner_id: int,
    platform: SocialPlatform,
    handle: Optional[str] = None,
    url: Optional[str] = None,
) -> Optional[Influencer]:
    """按某社交平台的 handle / url 查重（用于 Instagram 等非 FB 平台）。

    已软删除的达人不参与查重。
    """
    conds = []
    if handle:
        conds.append(InfluencerSocialAccount.handle == handle)
    if url:
        conds.append(InfluencerSocialAccount.url == url)
    if not conds:
        return None
    return (
        db.query(Influencer)
        .join(InfluencerSocialAccount, InfluencerSocialAccount.influencer_id == Influencer.id)
        .filter(
            Influencer.owner_id == owner_id,
            Influencer.deleted_at.is_(None),
            InfluencerSocialAccount.platform == platform,
            or_(*conds),
        )
        .first()
    )


def _create_from_ig_profile(
    db: Session,
    owner_id: int,
    profile: dict[str, Any],
    post: Optional[Post],
    notes: Optional[str],
    source_post_ids: Optional[list[int]],
) -> Influencer:
    """从 Instagram 主页资料【建联】入库，按 IG 用户名 / 主页 URL 去重。"""
    handle, url = _ig_handle_url(profile)
    followers = _to_int(profile.get("followersCount"))

    existing = find_duplicate_social(
        db, owner_id, SocialPlatform.instagram, handle=handle, url=url
    )
    if existing:
        _attach_posts(db, existing.id, post, source_post_ids)
        return existing

    profile_data = _map_ig_profile(profile)
    profile_data.setdefault("display_name", "Unknown")
    profile_data["source"] = InfluencerSource.scrape
    profile_data["owner_id"] = owner_id
    if notes:
        profile_data["notes"] = notes

    inf = Influencer(**profile_data)
    db.add(inf)
    db.flush()

    if handle or url:
        db.add(
            InfluencerSocialAccount(
                influencer_id=inf.id,
                platform=SocialPlatform.instagram,
                handle=handle,
                url=url,
                followers=followers,
            )
        )

    _attach_posts(db, inf.id, post, source_post_ids)
    db.refresh(inf)
    return inf


_IG_PROFILE_KEEP = (
    "id", "username", "url", "inputUrl", "fullName", "biography",
    "followersCount", "followsCount", "postsCount",
    "profilePicUrl", "profilePicUrlHD", "externalUrl", "externalUrls",
    "about", "isBusinessAccount", "verified",
)


def ig_profile_to_form(profile: dict[str, Any]) -> dict[str, Any]:
    """把 instagram-profile-scraper 的一条主页资料映射成「可填充表单」+ 存库所需信息。

    顶层放展示用字段（display_name / bio / followers / website / ig_username / ig_url），
    并在 _ig_profile 内保留精简后的原始资料，供存库时按 IG 用户名/主页 URL 去重。
    """
    handle, url = _ig_handle_url(profile)
    mapped = _map_ig_profile(profile)
    raw = {k: profile.get(k) for k in _IG_PROFILE_KEEP if profile.get(k) is not None}
    form = {
        "platform": "instagram",
        "display_name": mapped.get("display_name"),
        "real_name": mapped.get("real_name"),
        "bio": mapped.get("bio"),
        "avatar_url": mapped.get("avatar_url"),
        "website": mapped.get("website"),
        "country": mapped.get("country"),
        "ig_username": handle,
        "ig_url": url,
        "followers": _to_int(profile.get("followersCount")),
        "_ig_profile": raw,
    }
    return {k: v for k, v in form.items() if v not in (None, "")}


def create_influencer_from_ig_form(
    db: Session,
    owner_id: int,
    form: dict[str, Any],
    notes: Optional[str] = None,
) -> tuple[Influencer, bool]:
    """把 IG「自动抓取任务」结果入库为建联达人（按 IG 用户名/主页 URL 去重）。

    返回 (influencer, created)。
    """
    raw = form.get("_ig_profile")
    profile: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    # 兜底：原始资料缺失时用顶层字段补齐识别所需信息
    if not profile.get("username") and form.get("ig_username"):
        profile["username"] = form.get("ig_username")
    if not profile.get("url") and form.get("ig_url"):
        profile["url"] = form.get("ig_url")

    handle, url = _ig_handle_url(profile)
    existing = find_duplicate_social(
        db, owner_id, SocialPlatform.instagram, handle=handle, url=url
    )
    created = existing is None
    inf = _create_from_ig_profile(
        db, owner_id, profile, post=None, notes=notes, source_post_ids=None
    )
    db.commit()
    db.refresh(inf)
    return inf, created


def create_from_scrape(
    db: Session,
    owner_id: int,
    post: Optional[Post],
    page_profile: Optional[dict[str, Any]] = None,
    notes: Optional[str] = None,
    source_post_ids: Optional[list[int]] = None,
) -> Influencer:
    """从抓取的【待审核博主】点击【建联】入库。
    - 优先用 page_profile（Pages Scraper / Search Scraper / IG Profile Scraper 抓回来的）做映射；
    - 若没有 profile，则尝试用 post.author_* 兜底；
    - 入库前去重，存在则把 post 关联过去，并返回已有记录。
    """
    if page_profile and _looks_like_instagram(page_profile):
        return _create_from_ig_profile(
            db, owner_id, page_profile, post, notes, source_post_ids
        )

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
    if notes:
        profile_data["notes"] = notes

    existing = find_duplicate(
        db,
        owner_id=owner_id,
        fb_page_id=profile_data.get("fb_page_id"),
        fb_page_url=profile_data.get("fb_page_url"),
        email=profile_data.get("email"),
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


def create_from_group_post(
    db: Session,
    owner_id: int,
    post: FbGroupPost,
    page_profile: Optional[dict[str, Any]] = None,
    profile_url: Optional[str] = None,
    notes: Optional[str] = None,
) -> tuple[Influencer, bool]:
    """从 Facebook 群组帖子的【预建联】入库。

    - 优先用 page_profile（facebook-pages-scraper 抓回来的完整资料）映射字段；
    - profile 缺失字段用帖子里的 user_name / user_id / 主页 URL 兜底；
    - 入库前按 fb_page_id / fb_page_url / email 去重，命中则直接复用已有达人；
    - 把该帖子的 influencer_id 关联过去。

    返回 (influencer, created)，created 为 True 表示新建，False 表示命中已有。
    """
    profile_data: dict[str, Any] = {}
    if page_profile:
        profile_data.update(_map_page_profile(page_profile))

    # 帖子兜底：群组帖子里的作者就是个人主页，用其作为最低限度的资料
    profile_data.setdefault("display_name", post.user_name or "Unknown")
    if profile_url:
        profile_data.setdefault("fb_page_url", profile_url)
    if post.user_id:
        profile_data.setdefault("fb_page_id", str(post.user_id))
        # 记录帖子作者 user.id，后续按作者去重 / 命中已建联
        profile_data["fb_author_id"] = str(post.user_id)
    profile_data.setdefault("display_name", "Unknown")

    profile_data["source"] = InfluencerSource.scrape
    profile_data["owner_id"] = owner_id
    if notes:
        profile_data["notes"] = notes

    existing = find_duplicate(
        db,
        owner_id=owner_id,
        fb_author_id=str(post.user_id) if post.user_id else None,
        fb_page_id=profile_data.get("fb_page_id"),
        fb_page_url=profile_data.get("fb_page_url"),
        email=profile_data.get("email"),
    )
    if existing:
        post.influencer_id = existing.id
        db.commit()
        return existing, False

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

    post.influencer_id = inf.id
    db.commit()
    db.refresh(inf)
    return inf, True
