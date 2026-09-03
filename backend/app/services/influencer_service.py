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
from app.services import avatar_cache


def normalize_fb_url(u: Optional[str]) -> str:
    """规范化主页链接用于匹配：去空白、去 http(s):// 与 www.、去 query/fragment、去尾部斜杠、转小写。

    与回填 SQL（backend/sql/2026_social_account_fields.sql）里的归一化规则保持一致。
    """
    s = (u or "").strip()
    if not s:
        return ""
    s = s.split("?", 1)[0].split("#", 1)[0].strip()
    low = s.lower()
    for prefix in ("https://", "http://"):
        if low.startswith(prefix):
            low = low[len(prefix):]
            break
    if low.startswith("www."):
        low = low[4:]
    return low.rstrip("/")


def handle_from_url(url: Optional[str], fallback: Optional[str] = None) -> Optional[str]:
    """从主页链接末段解析账号 handle；``profile.php?id=`` 这类链接末段无意义，退化用 fallback（如 page_id）。"""
    norm = normalize_fb_url(url)
    if not norm or "/" not in norm or norm.endswith("profile.php"):
        return fallback or None
    seg = norm.rsplit("/", 1)[-1]
    return seg or fallback or None


def build_ig_profile_url(value: Optional[str]) -> str:
    """把 IG 用户名 / 主页链接归一化为标准主页 URL（打开浏览器 & 匹配用）。

    ``nasa`` / ``@nasa`` / ``https://instagram.com/nasa?hl=en`` →
    ``https://www.instagram.com/nasa/``；无法识别时原样返回。
    """
    from app.services.apify_service import normalize_ig_username

    name = normalize_ig_username(value or "")
    if not name:
        return (value or "").strip()
    return f"https://www.instagram.com/{name}/"


def _influencer_profile_urls(db: Session, influencer: "Influencer") -> set[str]:
    """收集该达人可用于私信匹配的所有主页 URL（各关联账号 + 兼容旧 FB 主字段）的规整值。"""
    urls: set[str] = set()
    if influencer.fb_page_url:
        n = normalize_fb_url(influencer.fb_page_url)
        if n:
            urls.add(n)
    if influencer.id is not None:
        rows = (
            db.query(InfluencerSocialAccount.url)
            .filter(InfluencerSocialAccount.influencer_id == influencer.id)
            .all()
        )
        for (u,) in rows:
            n = normalize_fb_url(u)
            if n:
                urls.add(n)
    return urls


def match_influencer_id_by_url(
    db: Session, owner_id: int, url: Optional[str], platform: str = "facebook"
) -> Optional[int]:
    """按主页 URL 在同一 owner 下匹配已入库达人的 id（比对各平台关联账号的链接，FB 额外兼容旧 fb_page_url）。"""
    target = normalize_fb_url(url)
    if not target:
        return None
    plat = (platform or "").strip().lower()
    q = (
        db.query(InfluencerSocialAccount.influencer_id, InfluencerSocialAccount.url)
        .join(Influencer, Influencer.id == InfluencerSocialAccount.influencer_id)
        .filter(
            Influencer.owner_id == owner_id,
            Influencer.deleted_at.is_(None),
            InfluencerSocialAccount.url.isnot(None),
        )
    )
    if plat in SocialPlatform.__members__:
        q = q.filter(InfluencerSocialAccount.platform == SocialPlatform(plat))
    for inf_id, u in q.all():
        if normalize_fb_url(u) == target:
            return inf_id
    if plat == "instagram":
        return None
    candidates = (
        db.query(Influencer)
        .filter(
            Influencer.owner_id == owner_id,
            Influencer.deleted_at.is_(None),
            Influencer.fb_page_url.isnot(None),
        )
        .all()
    )
    for c in candidates:
        if normalize_fb_url(c.fb_page_url) == target:
            return c.id
    return None


def link_outreach_logs_for_influencer(db: Session, influencer: "Influencer") -> int:
    """把该达人主页 URL 对应、尚未关联的私信记录回填 influencer_id（同一 owner）。

    返回回填条数。达人可能在私信发送之后才入库，故此处补上关联。
    同时匹配 FB 主页链接与各社交账号（含 Instagram）链接。
    """
    from app.models.dm import DmOutreachLog

    targets = _influencer_profile_urls(db, influencer)
    if not targets:
        return 0
    logs = (
        db.query(DmOutreachLog)
        .filter(
            DmOutreachLog.owner_id == influencer.owner_id,
            DmOutreachLog.influencer_id.is_(None),
        )
        .all()
    )
    linked = 0
    for log in logs:
        if normalize_fb_url(log.url) in targets:
            log.influencer_id = influencer.id
            linked += 1
    if linked:
        db.commit()
    return linked


def find_duplicate(
    db: Session,
    owner_id: int,
    fb_author_id: Optional[str] = None,
    fb_page_id: Optional[str] = None,
    fb_page_url: Optional[str] = None,
    email: Optional[str] = None,
) -> Optional[Influencer]:
    """根据作者 id（群组帖子作者 user.id）/ 页面 id / 主页链接 / email 查重。

    账号维度（author_id / page_id / url）先比 Facebook 关联账号（链接按归一化比对），
    再兼容旧的主表 fb_* 字段。已软删除（``deleted_at`` 有值）的达人不参与查重。
    """
    alive = (Influencer.owner_id == owner_id, Influencer.deleted_at.is_(None))
    acc_conds = []
    if fb_author_id:
        acc_conds.append(InfluencerSocialAccount.author_id == fb_author_id)
    if fb_page_id:
        acc_conds.append(InfluencerSocialAccount.page_id == fb_page_id)
    if acc_conds:
        hit = (
            db.query(Influencer)
            .join(InfluencerSocialAccount, InfluencerSocialAccount.influencer_id == Influencer.id)
            .filter(*alive, InfluencerSocialAccount.platform == SocialPlatform.facebook, or_(*acc_conds))
            .first()
        )
        if hit:
            return hit
    target = normalize_fb_url(fb_page_url)
    if target:
        rows = (
            db.query(Influencer, InfluencerSocialAccount.url)
            .join(InfluencerSocialAccount, InfluencerSocialAccount.influencer_id == Influencer.id)
            .filter(
                *alive,
                InfluencerSocialAccount.platform == SocialPlatform.facebook,
                InfluencerSocialAccount.url.isnot(None),
            )
            .all()
        )
        for inf, u in rows:
            if normalize_fb_url(u) == target:
                return inf

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
    return db.query(Influencer).filter(*alive, or_(*conds)).first()


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
        # 优先高清头像，避免列表里显示模糊小图
        "avatar_url": profile.get("profilePictureUrlHD")
        or profile.get("profilePhotoHD")
        or profile.get("profilePictureUrl")
        or profile.get("profilePhoto")
        or profile.get("profileImage"),
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


def _map_fb_profile_scraper(profile: dict[str, Any]) -> dict[str, Any]:
    """把 facebook-profile-scraper（apivault_labs 等社区 actor）的输出映射成表单字段。

    兼容多家 actor 的字段命名：
      fullName/name/username, bio/biography/intro, category/categories,
      followerCount/followers, likeCount/likes,
      primaryEmail/emails[], primaryPhone/phones[], primaryWebsite/websites[]/website,
      profileUrl/inputUrl/url, fbid/facebookId/pageId, avatarUrl/profilePictureUrl。
    """
    name = profile.get("fullName") or profile.get("name") or profile.get("username")

    categories = profile.get("categories")
    if not categories:
        cat = profile.get("category")
        if isinstance(cat, str) and cat:
            categories = [cat]
        elif isinstance(cat, list):
            categories = cat

    emails = profile.get("emails") if isinstance(profile.get("emails"), list) else None
    phones = profile.get("phones") if isinstance(profile.get("phones"), list) else None
    websites = profile.get("websites") if isinstance(profile.get("websites"), list) else None

    mapped = {
        "display_name": name,
        "fb_page_title": name,
        "fb_page_id": str(
            profile.get("fbid") or profile.get("facebookId") or profile.get("pageId") or ""
        )
        or None,
        "fb_page_url": profile.get("profileUrl")
        or profile.get("inputUrl")
        or profile.get("url"),
        "bio": profile.get("bio") or profile.get("biography") or profile.get("intro"),
        "address": profile.get("address"),
        "email": profile.get("primaryEmail") or _first(emails) or profile.get("email"),
        "phone": profile.get("primaryPhone") or _first(phones) or profile.get("phone"),
        "website": profile.get("primaryWebsite") or _first(websites) or profile.get("website"),
        "fb_categories": categories,
        "fb_followers": _to_int(
            profile.get("followerCount")
            or profile.get("followers")
            or profile.get("followersCount")
        ),
        "fb_likes": _to_int(profile.get("likeCount") or profile.get("likes")),
        "avatar_url": profile.get("avatarUrlHD")
        or profile.get("profilePictureUrlHD")
        or profile.get("avatarUrl")
        or profile.get("profilePictureUrl"),
        "cover_url": profile.get("coverUrl") or profile.get("coverPhotoUrl"),
    }
    return {k: v for k, v in mapped.items() if v not in (None, "")}


def fb_profile_to_form(profile: dict[str, Any]) -> dict[str, Any]:
    """facebook-profile-scraper 的一条主页资料 → 可填充表单字段。"""
    return _map_fb_profile_scraper(profile)


def fb_form_is_sparse(form: dict[str, Any]) -> bool:
    """判断 pages-scraper 抓到的表单是否过于稀疏（多半是 Profile 类账号）。

    既没拿到有效昵称（非空且非 "Unknown"）、又没拿到粉丝数时，视为稀疏。
    """
    name = str(form.get("display_name") or "").strip()
    has_name = bool(name) and name.lower() != "unknown"
    has_followers = bool(form.get("fb_followers"))
    return not (has_name or has_followers)


def merge_fb_forms(
    primary: dict[str, Any], fallback: dict[str, Any]
) -> dict[str, Any]:
    """以 primary（pages-scraper）为主，用 fallback（profile-scraper）补齐缺失字段。

    primary 的非空字段优先；display_name 若为空或 "Unknown" 则用 fallback 的。
    """
    merged: dict[str, Any] = dict(fallback)
    for k, v in primary.items():
        if v not in (None, ""):
            merged[k] = v
    pn = str(primary.get("display_name") or "").strip()
    if (not pn or pn.lower() == "unknown") and fallback.get("display_name"):
        merged["display_name"] = fallback["display_name"]
    return merged


#: 抓取表单中落到主表的「人 / 建联」维度字段
_FORM_INFLUENCER_FIELDS = (
    "display_name", "real_name", "bio", "avatar_url", "cover_url",
    "country", "region", "city", "language", "address",
    "email", "phone", "website",
    "tags", "notes",
)

#: 抓取表单（FB）中的账号维度字段 → influencer_social_accounts 列
_FORM_FB_ACCOUNT_FIELDS: dict[str, str] = {
    "fb_page_id": "page_id",
    "fb_author_id": "author_id",
    "fb_page_url": "url",
    "fb_page_title": "title",
    "fb_categories": "categories",
    "fb_followers": "followers",
    "fb_likes": "likes",
    "fb_rating": "rating",
    "fb_rating_count": "rating_count",
    "fb_checkins_mentions": "checkins_mentions",
    "fb_page_created_at": "page_created_at",
    "fb_ad_library_id": "ad_library_id",
    "fb_ad_status": "ad_status",
    "messenger": "messenger",
    "avatar_url": "avatar_url",
}


def fb_account_fields_from_form(form: dict[str, Any]) -> dict[str, Any]:
    """从 FB 抓取表单（fb_* 键）抽出账号维度字段，键名为账号表列名。"""
    fields: dict[str, Any] = {}
    for src, dst in _FORM_FB_ACCOUNT_FIELDS.items():
        v = form.get(src)
        if v in (None, "", []):
            continue
        fields[dst] = v
    created = fields.get("page_created_at")
    if isinstance(created, str):
        try:
            fields["page_created_at"] = datetime.fromisoformat(created)
        except ValueError:
            fields.pop("page_created_at", None)
    if fields.get("url") or fields.get("page_id"):
        fields.setdefault("handle", handle_from_url(fields.get("url"), fields.get("page_id")))
    return fields


def ig_account_fields_from_form(form: dict[str, Any]) -> dict[str, Any]:
    """从 IG 抓取表单（ig_username / ig_url / followers）抽出账号维度字段。"""
    raw = form.get("_ig_profile") if isinstance(form.get("_ig_profile"), dict) else {}
    fields: dict[str, Any] = {
        "handle": form.get("ig_username"),
        "url": form.get("ig_url"),
        "followers": _to_int(form.get("followers")),
        "title": form.get("real_name") or form.get("display_name"),
        "avatar_url": form.get("avatar_url"),
        "page_id": str(raw.get("id") or "") or None,
    }
    return {k: v for k, v in fields.items() if v not in (None, "", [])}


def account_fields_from_form(form: dict[str, Any]) -> tuple[SocialPlatform, dict[str, Any]]:
    """按表单里的 platform 把抓取结果换成 (平台, 账号字段)。"""
    if str(form.get("platform") or "").lower() == "instagram":
        return SocialPlatform.instagram, ig_account_fields_from_form(form)
    return SocialPlatform.facebook, fb_account_fields_from_form(form)


#: 抓取回来的这些指标以最新结果为准（覆盖旧值），其余字段只补空
_ACCOUNT_METRIC_FIELDS = frozenset(
    {"followers", "likes", "rating", "rating_count", "checkins_mentions", "ad_status"}
)


def apply_account_fields(
    acc: InfluencerSocialAccount,
    fields: dict[str, Any],
    *,
    overwrite: bool = False,
    keep_existing_url: bool = False,
    scraped: bool = False,
) -> InfluencerSocialAccount:
    """把账号维度字段写到账号行上。

    - ``overwrite=True``：非空值全部覆盖；否则指标类字段覆盖、其余只补空；
    - ``keep_existing_url=True``：已有链接时不换链接（同一账号的不同写法）；
    - ``scraped=True``：顺带记下 last_scraped_at。
    """
    for key, value in fields.items():
        if value in (None, "", []):
            continue
        if key in ("id", "influencer_id", "platform", "platform_id", "notes"):
            continue
        if key == "url" and keep_existing_url and acc.url:
            continue
        current = getattr(acc, key, None)
        if overwrite or key in _ACCOUNT_METRIC_FIELDS or current in (None, "", []):
            setattr(acc, key, value)
    if scraped:
        acc.last_scraped_at = datetime.utcnow()
    return acc


def _new_account(
    db: Session,
    influencer_id: int,
    platform: SocialPlatform,
    fields: dict[str, Any],
    platform_id: Optional[int] = None,
) -> InfluencerSocialAccount:
    acc = InfluencerSocialAccount(
        influencer_id=influencer_id,
        platform=platform,
        platform_id=platform_id or resolve_platform_id(db, platform),
    )
    apply_account_fields(acc, fields, overwrite=True)
    db.add(acc)
    return acc


def _sync_person_from_account(inf: Influencer, fields: dict[str, Any]) -> None:
    """账号资料里可以补到「人」上的部分：没名字时用账号名，没头像时用账号头像。"""
    name = str(inf.display_name or "").strip()
    if (not name or name.lower() == "unknown") and fields.get("title"):
        inf.display_name = str(fields["title"])[:255]
    if not inf.avatar_url and fields.get("avatar_url"):
        inf.avatar_url = fields["avatar_url"]


def create_influencer_from_form(
    db: Session,
    owner_id: int,
    form: dict[str, Any],
    notes: Optional[str] = None,
) -> tuple[Influencer, bool]:
    """把「自动抓取任务」的可填充表单结果入库为建联达人。

    - 主表只取「人」维度白名单字段；fb_* 等账号维度字段落到 Facebook 关联账号；
    - 按 page_id / 主页链接 / email 去重，命中则复用已有，不重复创建；
    返回 (influencer, created)。
    """
    form = avatar_cache.localize_form_avatar(dict(form))
    data: dict[str, Any] = {
        k: form.get(k) for k in _FORM_INFLUENCER_FIELDS if form.get(k) not in (None, "")
    }
    account = fb_account_fields_from_form(form)

    data.setdefault("display_name", "Unknown")
    data["owner_id"] = owner_id
    data["source"] = InfluencerSource.scrape
    if notes:
        data["notes"] = notes

    existing = find_duplicate(
        db,
        owner_id=owner_id,
        fb_page_id=account.get("page_id"),
        fb_page_url=account.get("url"),
        email=data.get("email"),
    )
    if existing:
        link_outreach_logs_for_influencer(db, existing)
        return existing, False

    inf = Influencer(**data)
    db.add(inf)
    db.flush()
    if account.get("url") or account.get("page_id"):
        _new_account(db, inf.id, SocialPlatform.facebook, account)
    db.commit()
    db.refresh(inf)
    link_outreach_logs_for_influencer(db, inf)
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
    """按某社交平台的 handle / url（归一化比对）查重。

    已软删除的达人不参与查重。
    """
    handle_key = (handle or "").strip().lower()
    target = normalize_fb_url(url)
    if not handle_key and not target:
        return None
    rows = (
        db.query(Influencer, InfluencerSocialAccount.handle, InfluencerSocialAccount.url)
        .join(InfluencerSocialAccount, InfluencerSocialAccount.influencer_id == Influencer.id)
        .filter(
            Influencer.owner_id == owner_id,
            Influencer.deleted_at.is_(None),
            InfluencerSocialAccount.platform == platform,
        )
        .all()
    )
    for inf, h, u in rows:
        if handle_key and (h or "").strip().lower() == handle_key:
            return inf
        if target and normalize_fb_url(u) == target:
            return inf
    return None


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

    inf = Influencer(**avatar_cache.localize_form_avatar(profile_data))
    db.add(inf)
    db.flush()

    if handle or url:
        _new_account(
            db,
            inf.id,
            SocialPlatform.instagram,
            {
                "handle": handle,
                "url": url,
                "followers": followers,
                "title": profile.get("fullName") or handle,
                "avatar_url": inf.avatar_url,
                "page_id": str(profile.get("id") or "") or None,
            },
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
    link_outreach_logs_for_influencer(db, inf)
    return inf, created


def platform_id_by_code(db: Session) -> dict[str, int]:
    """「平台管理」里的 ``{平台代码/名称小写: id}``，用于把账号平台对齐到平台字典。

    以「代码」为主（用户可自行改代码决定对齐到哪条平台），代码没填时退化用平台名称。
    """
    from app.models.bitbrowser import BitBrowserPlatform

    rows = db.query(BitBrowserPlatform.id, BitBrowserPlatform.name, BitBrowserPlatform.code).all()
    mapping: dict[str, int] = {}
    for pid, name, _code in rows:
        key = (name or "").strip().lower()
        if key:
            mapping.setdefault(key, pid)
    for pid, _name, code in rows:
        key = (code or "").strip().lower()
        if key:
            mapping[key] = pid
    return mapping


def resolve_platform_id(db: Session, platform: SocialPlatform | str | None) -> Optional[int]:
    """按平台规范名（facebook / instagram / ...）找「平台管理」里的平台 id。"""
    from app.utils.platform_detect import match_platform_code

    name = platform.value if isinstance(platform, SocialPlatform) else (platform or "")
    if not name:
        return None
    return match_platform_code(name, platform_id_by_code(db))


def _match_account(
    rows: list[InfluencerSocialAccount],
    handle: Optional[str],
    url: Optional[str],
    page_id: Optional[str] = None,
) -> Optional[InfluencerSocialAccount]:
    """在同一达人同平台的账号里，按 page_id / 归一化 URL / handle（忽略大小写）找已有记录。"""
    target = normalize_fb_url(url)
    handle_key = (handle or "").strip().lower()
    for r in rows:
        if page_id and r.page_id and r.page_id == page_id:
            return r
    for r in rows:
        if target and normalize_fb_url(r.url) == target:
            return r
    for r in rows:
        if handle_key and (r.handle or "").strip().lower() == handle_key:
            return r
    return None


def upsert_social_account(
    db: Session,
    influencer_id: int,
    platform: SocialPlatform,
    handle: Optional[str] = None,
    url: Optional[str] = None,
    followers: Optional[int] = None,
    keep_existing_url: bool = False,
    platform_id: Optional[int] = None,
    fields: Optional[dict[str, Any]] = None,
    account_id: Optional[int] = None,
    scraped: bool = False,
) -> Optional[InfluencerSocialAccount]:
    """写入/更新达人在某平台的账号。

    匹配顺序：``account_id`` 指定的账号（一键抓取）→ 同达人同平台里
    page_id / 归一化 URL / handle 命中的账号 → 该平台仅有一条账号且未传链接时复用它 → 新建。

    ``fields`` 为账号维度全量字段（title / likes / rating / messenger …）；
    ``keep_existing_url=True`` 时不覆盖已有主页链接（导入同一账号的不同写法时保留原链接）。
    """
    data: dict[str, Any] = dict(fields or {})
    if handle:
        data.setdefault("handle", handle)
    if url:
        data.setdefault("url", url)
    if followers is not None:
        data["followers"] = followers
    if not (data.get("handle") or data.get("url") or data.get("page_id") or account_id):
        return None

    acc: Optional[InfluencerSocialAccount] = None
    if account_id:
        acc = db.get(InfluencerSocialAccount, account_id)
        if acc is not None and acc.influencer_id != influencer_id:
            acc = None
    if acc is None:
        rows = (
            db.query(InfluencerSocialAccount)
            .filter(
                InfluencerSocialAccount.influencer_id == influencer_id,
                InfluencerSocialAccount.platform == platform,
            )
            .order_by(InfluencerSocialAccount.id.asc())
            .all()
        )
        acc = _match_account(rows, data.get("handle"), data.get("url"), data.get("page_id"))
        if acc is None and len(rows) == 1 and not (rows[0].url and data.get("url")):
            acc = rows[0]
    if acc is None:
        acc = InfluencerSocialAccount(influencer_id=influencer_id, platform=platform)
        db.add(acc)
    if acc.platform_id is None:
        acc.platform_id = platform_id or resolve_platform_id(db, platform)
    if not data.get("handle") and not acc.handle:
        data["handle"] = handle_from_url(data.get("url"), data.get("page_id"))
    apply_account_fields(acc, data, keep_existing_url=keep_existing_url, scraped=scraped)
    return acc


def enrich_influencer_from_form(
    db: Session,
    inf: Influencer,
    form: dict[str, Any],
    social_account_id: Optional[int] = None,
) -> Influencer:
    """把抓取结果补写到已存在的达人上。

    - 主表「人」维度字段只填空；
    - 账号维度（链接 / 粉丝 / 点赞 / 评分 / Messenger …）写到对应关联账号，
      ``social_account_id`` 指定时（列表一键抓取）直接回写到这条账号，指标类以最新抓取为准。

    表格导入时先按主页链接建好达人，抓取完成后回填资料，避免重复建档。
    """
    form = avatar_cache.localize_form_avatar(dict(form))
    for field in _FORM_INFLUENCER_FIELDS:
        value = form.get(field)
        if value in (None, ""):
            continue
        if field == "display_name" and str(value).strip().lower() == "unknown":
            continue
        if getattr(inf, field, None) in (None, "", []):
            setattr(inf, field, value)
    if isinstance(form.get("_ig_profile"), dict):
        inf.raw_profile = form["_ig_profile"]

    platform, account = account_fields_from_form(form)
    if account or social_account_id:
        acc = upsert_social_account(
            db,
            inf.id,
            platform,
            fields=account,
            account_id=social_account_id,
            keep_existing_url=True,
            scraped=True,
        )
        if acc is not None:
            _sync_person_from_account(inf, account)
    db.commit()
    db.refresh(inf)
    return inf


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

    mapped: dict[str, Any] = {}
    if page_profile:
        mapped.update(_map_page_profile(page_profile))

    if post:
        mapped.setdefault("display_name", post.author_name or "Unknown")
        mapped.setdefault("fb_page_url", post.author_url)
        mapped.setdefault("fb_page_id", post.author_page_id)

    profile_data, account = _split_person_and_account(mapped)
    profile_data.setdefault("display_name", "Unknown")
    profile_data["source"] = InfluencerSource.scrape
    profile_data["owner_id"] = owner_id
    if notes:
        profile_data["notes"] = notes

    existing = find_duplicate(
        db,
        owner_id=owner_id,
        fb_page_id=account.get("page_id"),
        fb_page_url=account.get("url"),
        email=profile_data.get("email"),
    )
    if existing:
        # 把当前 post + page_profile 上挂的所有源帖子统一关联过去
        _attach_posts(db, existing.id, post, source_post_ids)
        return existing

    inf = Influencer(**profile_data)
    db.add(inf)
    db.flush()

    if account.get("url") or account.get("page_id"):
        _new_account(db, inf.id, SocialPlatform.facebook, account)

    _attach_posts(db, inf.id, post, source_post_ids)
    db.refresh(inf)
    return inf


def _split_person_and_account(mapped: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """把 ``_map_page_profile`` 的结果拆成 (主表字段, Facebook 账号字段)。"""
    mapped = avatar_cache.localize_form_avatar(dict(mapped))
    person = {
        k: v
        for k, v in mapped.items()
        if k in _FORM_INFLUENCER_FIELDS or k == "raw_profile"
    }
    person = {k: v for k, v in person.items() if v not in (None, "")}
    return person, fb_account_fields_from_form(mapped)


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
    mapped: dict[str, Any] = {}
    if page_profile:
        mapped.update(_map_page_profile(page_profile))

    # 帖子兜底：群组帖子里的作者就是个人主页，用其作为最低限度的资料
    mapped.setdefault("display_name", post.user_name or "Unknown")
    if profile_url:
        mapped.setdefault("fb_page_url", profile_url)
    if post.user_id:
        mapped.setdefault("fb_page_id", str(post.user_id))
        # 记录帖子作者 user.id，后续按作者去重 / 命中已建联
        mapped["fb_author_id"] = str(post.user_id)

    profile_data, account = _split_person_and_account(mapped)
    profile_data.setdefault("display_name", "Unknown")
    profile_data["source"] = InfluencerSource.scrape
    profile_data["owner_id"] = owner_id
    if notes:
        profile_data["notes"] = notes

    existing = find_duplicate(
        db,
        owner_id=owner_id,
        fb_author_id=str(post.user_id) if post.user_id else None,
        fb_page_id=account.get("page_id"),
        fb_page_url=account.get("url"),
        email=profile_data.get("email"),
    )
    if existing:
        post.influencer_id = existing.id
        db.commit()
        return existing, False

    inf = Influencer(**profile_data)
    db.add(inf)
    db.flush()

    if account.get("url") or account.get("page_id"):
        _new_account(db, inf.id, SocialPlatform.facebook, account)

    post.influencer_id = inf.id
    db.commit()
    db.refresh(inf)
    return inf, True


def cross_user_url_index(db: Session, user) -> dict[str, str]:
    """用户配置了「对照账号」时，返回这些账号名下所有主页链接（归一化）→ 对照账号用户名。

    覆盖：关联账号 url、旧主表 fb_page_url、以及抓取任务里留下的原始分享链接。
    没配置对照账号时返回空 dict，导入 / 批量导入行为不变。
    """
    from app.models.influencer_scrape_task import InfluencerScrapeTask
    from app.models.user import User

    ids = {int(x) for x in (user.dedupe_against_user_ids or []) if str(x).isdigit()}
    ids.discard(user.id)
    if not ids:
        return {}
    names = {
        uid: (name or f"#{uid}")
        for uid, name in db.query(User.id, User.username).filter(User.id.in_(ids)).all()
    }
    index: dict[str, str] = {}

    def put(url: Optional[str], owner_id: int) -> None:
        key = normalize_fb_url(url)
        if key and key not in index:
            index[key] = names.get(owner_id, f"#{owner_id}")

    rows = (
        db.query(InfluencerSocialAccount.url, Influencer.owner_id)
        .join(Influencer, Influencer.id == InfluencerSocialAccount.influencer_id)
        .filter(Influencer.owner_id.in_(ids), InfluencerSocialAccount.url.isnot(None))
        .all()
    )
    for url, owner_id in rows:
        put(url, owner_id)
    for url, owner_id in (
        db.query(Influencer.fb_page_url, Influencer.owner_id)
        .filter(Influencer.owner_id.in_(ids), Influencer.fb_page_url.isnot(None))
        .all()
    ):
        put(url, owner_id)
    for url, owner_id in (
        db.query(InfluencerScrapeTask.url, InfluencerScrapeTask.owner_id)
        .filter(InfluencerScrapeTask.owner_id.in_(ids))
        .all()
    ):
        put(url, owner_id)
    return index
