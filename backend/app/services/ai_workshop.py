"""AI 工坊服务层：密钥生成 + Agent 工具实现。

所有工具函数都以「密钥属主用户」身份执行：
- 查询统一走 ``app.core.deps.owner_filter``，数据可见范围与 Web 端完全一致；
- 写入（upsert_influencer）只在属主自己名下查重/更新，新建记录 ``owner_id`` 记属主。
"""
from __future__ import annotations

import base64
import binascii
import secrets
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.ai_auth import hash_api_key
from app.core.config import settings
from app.core.deps import can_view, owner_filter
from app.models.ai_workshop import AiApiCallLog, AiApiKey
from app.models.bitbrowser import BitBrowserPlatform
from app.models.country import Country
from app.models.dm import DmOutreachLog
from app.models.influencer import Influencer, InfluencerSource, InfluencerStatus
from app.models.influencer_scrape_task import InfluencerScrapeTask
from app.models.social_account import InfluencerSocialAccount, SocialPlatform
from app.models.user import User
from app.services import influencer_import, influencer_service
from app.utils.platform_detect import SCRAPABLE_PLATFORMS

KEY_PREFIX = "skjw-"

#: Agent 可用的工具名（MCP tools/list 与 whoami 用）
AGENT_TOOLS: tuple[str, ...] = (
    "search_influencers",
    "get_influencer",
    "upsert_influencer",
    "stage_urls",
    "run_scrape_tasks",
    "get_scrape_task",
    "save_homepage_screenshot",
    "record_outreach",
    "list_platforms",
    "list_countries",
    "whoami",
)

_PLATFORM_ALIASES: dict[str, str] = {
    "fb": "facebook",
    "facebook": "facebook",
    "ig": "instagram",
    "instagram": "instagram",
    "tt": "tiktok",
    "tiktok": "tiktok",
    "yt": "youtube",
    "youtube": "youtube",
    "tw": "twitter",
    "x": "twitter",
    "twitter": "twitter",
    "wechat": "wechat",
    "wx": "wechat",
    "xiaohongshu": "xiaohongshu",
    "xhs": "xiaohongshu",
    "line": "line",
    "other": "other",
}


def generate_api_key() -> tuple[str, str, str]:
    """生成 ``(明文, 展示前缀, sha256 哈希)``；明文只在创建响应里出现一次。"""
    raw = KEY_PREFIX + secrets.token_hex(24)
    return raw, raw[:12], hash_api_key(raw)


def log_call(
    db: Session,
    *,
    key_id: Optional[int],
    owner_id: int,
    action: str,
    status: str = "ok",
    error: Optional[str] = None,
    detail: Optional[dict] = None,
) -> None:
    """记一条调用审计并独立提交（调用方保证此刻会话里没有未决的半途数据）。"""
    db.add(
        AiApiCallLog(
            key_id=key_id,
            owner_id=owner_id,
            action=action[:64],
            status=status,
            error=(error or None) and str(error)[:2000],
            detail=detail,
        )
    )
    db.commit()


# --------------------------------------------------------------------------- #
# 内部辅助
# --------------------------------------------------------------------------- #
def _resolve_platform(value: Optional[str]) -> Optional[SocialPlatform]:
    text = (value or "").strip().lower()
    if not text:
        return None
    canonical = _PLATFORM_ALIASES.get(text)
    if canonical is None:
        return None
    return SocialPlatform(canonical)


def _load_accounts(db: Session, influencer_ids: list[int]) -> dict[int, list[InfluencerSocialAccount]]:
    if not influencer_ids:
        return {}
    rows = (
        db.query(InfluencerSocialAccount)
        .filter(InfluencerSocialAccount.influencer_id.in_(influencer_ids))
        .order_by(InfluencerSocialAccount.id.asc())
        .all()
    )
    result: dict[int, list[InfluencerSocialAccount]] = {}
    for row in rows:
        result.setdefault(row.influencer_id, []).append(row)
    return result


def _pick_primary_account(
    accounts: list[InfluencerSocialAccount],
    prefer: Optional[SocialPlatform] = None,
) -> Optional[InfluencerSocialAccount]:
    if not accounts:
        return None
    if prefer is not None:
        for acc in accounts:
            if acc.platform == prefer:
                return acc
    for acc in accounts:
        if acc.url:
            return acc
    return accounts[0]


def _followers_of(accounts: list[InfluencerSocialAccount]) -> Optional[int]:
    values = [acc.followers for acc in accounts if acc.followers is not None]
    return max(values) if values else None


def _influencer_compact(
    accounts: list[InfluencerSocialAccount],
    inf: Influencer,
    prefer: Optional[SocialPlatform] = None,
) -> dict[str, Any]:
    primary = _pick_primary_account(accounts, prefer)
    return {
        "id": inf.id,
        "display_name": inf.display_name,
        "platform": primary.platform.value if primary else None,
        "platform_name": primary.platform_name if primary else None,
        "url": primary.url if primary else None,
        "handle": primary.handle if primary else None,
        "followers": _followers_of(accounts),
        "homepage_screenshot": inf.homepage_screenshot,
        "email": inf.email,
        "phone": inf.phone,
        "country": inf.country,
        "country_code": inf.country_code,
        "status": inf.status.value if inf.status else None,
        "progress": inf.progress,
        "company": inf.company,
        "tags": inf.tags,
        "notes": inf.notes,
        "owner_id": inf.owner_id,
        "created_at": inf.created_at.isoformat() if inf.created_at else None,
    }


def _influencer_detail(
    db: Session,
    inf: Influencer,
) -> dict[str, Any]:
    accounts = _load_accounts(db, [inf.id]).get(inf.id, [])
    data = _influencer_compact(accounts, inf)
    data.update(
        {
            "real_name": inf.real_name,
            "bio": inf.bio,
            "city": inf.city,
            "address": inf.address,
            "website": inf.website,
            "contact_owner": inf.contact_owner,
            "landing_owner": inf.landing_owner,
            "source_channel": inf.source_channel,
            "accounts": [
                {
                    "id": acc.id,
                    "platform": acc.platform.value if acc.platform else None,
                    "handle": acc.handle,
                    "url": acc.url,
                    "followers": acc.followers,
                    "page_id": acc.page_id,
                    "author_id": acc.author_id,
                    "title": acc.title,
                    "messenger": acc.messenger,
                }
                for acc in accounts
            ],
        }
    )
    return data


# --------------------------------------------------------------------------- #
# 工具：查询
# --------------------------------------------------------------------------- #
def search_influencers(
    db: Session,
    user: User,
    *,
    keyword: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """按属主数据范围搜索达人（软删除的不可见）。"""
    prefer = _resolve_platform(platform)
    if platform and prefer is None:
        raise ValueError(f"未知平台: {platform}（可选: {[p.value for p in SocialPlatform]}）")
    status_enum: Optional[InfluencerStatus] = None
    if status:
        try:
            status_enum = InfluencerStatus(status.strip().lower())
        except ValueError as e:
            raise ValueError(
                f"未知状态: {status}（可选: {[s.value for s in InfluencerStatus]}）"
            ) from e

    query = db.query(Influencer).filter(Influencer.deleted_at.is_(None))
    query = owner_filter(query, Influencer, user)

    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        account_ids = (
            db.query(InfluencerSocialAccount.influencer_id)
            .filter(
                or_(
                    InfluencerSocialAccount.url.ilike(like),
                    InfluencerSocialAccount.handle.ilike(like),
                    InfluencerSocialAccount.title.ilike(like),
                )
            )
            .subquery()
        )
        query = query.filter(
            or_(
                Influencer.display_name.ilike(like),
                Influencer.email.ilike(like),
                Influencer.code.ilike(like),
                Influencer.company.ilike(like),
                Influencer.id.in_(account_ids),
            )
        )
    if prefer is not None:
        acc_ids = (
            db.query(InfluencerSocialAccount.influencer_id)
            .filter(InfluencerSocialAccount.platform == prefer)
            .subquery()
        )
        query = query.filter(Influencer.id.in_(acc_ids))
    if status_enum is not None:
        query = query.filter(Influencer.status == status_enum)
    if followers_min is not None or followers_max is not None:
        # 粉丝数口径 = 该达人所有平台账号里最大粉丝数（与列表展示一致）
        fmax_sq = (
            db.query(
                InfluencerSocialAccount.influencer_id.label("iid"),
                func.max(InfluencerSocialAccount.followers).label("fmax"),
            )
            .group_by(InfluencerSocialAccount.influencer_id)
            .subquery()
        )
        query = query.outerjoin(fmax_sq, fmax_sq.c.iid == Influencer.id)
        if followers_min is not None:
            query = query.filter(fmax_sq.c.fmax >= int(followers_min))
        if followers_max is not None:
            query = query.filter(fmax_sq.c.fmax <= int(followers_max))
    if country:
        lookup = influencer_import.country_lookup(db)
        row = influencer_import.match_country(country, lookup)
        if row is not None:
            query = query.filter(Influencer.country_id == row.id)
        else:
            query = query.filter(Influencer.country.ilike(f"%{country.strip()}%"))

    page = max(1, int(page or 1))
    page_size = min(50, max(1, int(page_size or 20)))
    total = query.count()
    rows = (
        query.order_by(Influencer.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    accounts_by_id = _load_accounts(db, [r.id for r in rows])
    items = [_influencer_compact(accounts_by_id.get(r.id, []), r, prefer) for r in rows]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def get_influencer_detail(db: Session, user: User, influencer_id: int) -> dict[str, Any]:
    """按数据范围取单个达人详情；不可见/不存在返回 None。"""
    inf = db.get(Influencer, int(influencer_id))
    if inf is None or inf.deleted_at is not None or not can_view(inf, user):
        return None
    return _influencer_detail(db, inf)


# --------------------------------------------------------------------------- #
# 工具：写入（自动存数据）
# --------------------------------------------------------------------------- #
_PERSON_FIELDS = (
    "code",
    "company",
    "gender",
    "city",
    "address",
    "phone",
    "email",
    "contact_owner",
    "landing_owner",
    "source_channel",
    "progress",
    "notes",
    "bio",
)
_ACCOUNT_FIELDS = (
    "handle",
    "url",
    "followers",
    "page_id",
    "author_id",
    "title",
    "avatar_url",
    "messenger",
)


def _resolve_country_id(db: Session, payload: dict[str, Any]) -> Optional[int]:
    if payload.get("country_id") is not None:
        return int(payload["country_id"])
    text = (payload.get("country") or "").strip()
    if not text:
        return None
    lookup = influencer_import.country_lookup(db)
    row = influencer_import.match_country(text, lookup)
    return row.id if row else None


def upsert_influencer(db: Session, user: User, payload: dict[str, Any]) -> dict[str, Any]:
    """Agent 自动存达人：按属主名下去重（author_id/page_id/url/handle），
    命中则更新，未命中则新建。绝不触碰他人数据。
    """
    platform = _resolve_platform(payload.get("platform"))
    if payload.get("platform") and platform is None:
        raise ValueError(f"未知平台: {payload.get('platform')}")

    url = (payload.get("url") or "").strip() or None
    handle = (payload.get("handle") or "").strip() or None
    page_id = (payload.get("page_id") or "").strip() or None
    author_id = (payload.get("author_id") or "").strip() or None
    display_name = (payload.get("display_name") or "").strip() or None
    if not any([url, handle, page_id, author_id, display_name]):
        raise ValueError("至少提供 display_name / url / handle / page_id / author_id 之一")

    status_provided = bool(payload.get("status"))
    status_enum = InfluencerStatus.pre_contact
    if status_provided:
        try:
            status_enum = InfluencerStatus(str(payload["status"]).strip().lower())
        except ValueError as e:
            raise ValueError(
                f"未知状态: {payload.get('status')}（可选: {[s.value for s in InfluencerStatus]}）"
            ) from e

    # --- 属主名下查重：FB author_id/page_id/url 优先，再按平台 handle/url ---
    existing: Optional[Influencer] = None
    matched_by: Optional[str] = None
    if platform == SocialPlatform.facebook or platform is None:
        existing = influencer_service.find_duplicate(
            db, user.id, fb_author_id=author_id, fb_page_id=page_id, fb_page_url=url
        )
        if existing is not None:
            matched_by = "author_id" if author_id else ("page_id" if page_id else "url")
    if existing is None and platform is not None:
        existing = influencer_service.find_duplicate_social(
            db, user.id, platform, handle=handle, url=url
        )
        if existing is not None:
            matched_by = "handle" if handle else "url"

    country_id = _resolve_country_id(db, payload)
    tags = payload.get("tags")
    if tags is not None and not isinstance(tags, list):
        tags = None

    person_values: dict[str, Any] = {}
    for field in _PERSON_FIELDS:
        if payload.get(field) is not None and str(payload[field]).strip() != "":
            person_values[field] = str(payload[field]).strip()

    action = "updated"
    if existing is not None:
        inf = existing
        # 非空字段覆盖；标签有值时整体替换
        for field, value in person_values.items():
            setattr(inf, field, value)
        if display_name:
            inf.display_name = display_name
        if country_id is not None:
            inf.country_id = country_id
            country_row = db.get(Country, country_id)
            if country_row is not None:
                inf.country = country_row.code
        if status_provided:
            inf.status = status_enum
        if tags:
            inf.tags = tags
        if payload.get("homepage_screenshot"):
            _apply_homepage_screenshot(inf, payload["homepage_screenshot"])
    else:
        action = "created"
        name = display_name or handle or page_id or url or "Unknown"
        inf = Influencer(
            display_name=name,
            owner_id=user.id,
            source=InfluencerSource.manual,
            status=status_enum,
            country_id=country_id,
            tags=tags or None,
            **person_values,
        )
        if country_id is not None:
            country_row = db.get(Country, country_id)
            if country_row is not None:
                inf.country = country_row.code
        if payload.get("homepage_screenshot"):
            _apply_homepage_screenshot(inf, payload["homepage_screenshot"])
        db.add(inf)
        db.flush()

    # --- 账号维度：同平台已有账号则补全，否则新建 ---
    if platform is not None or url or handle:
        acc_platform = platform or SocialPlatform.other
        account: Optional[InfluencerSocialAccount] = None
        for acc in (
            db.query(InfluencerSocialAccount)
            .filter(
                InfluencerSocialAccount.influencer_id == inf.id,
                InfluencerSocialAccount.platform == acc_platform,
            )
            .order_by(InfluencerSocialAccount.id.asc())
            .all()
        ):
            if url and acc.url and influencer_service.normalize_fb_url(acc.url) == influencer_service.normalize_fb_url(url):
                account = acc
                break
            if handle and (acc.handle or "").strip().lower() == (handle or "").strip().lower():
                account = acc
                break
            if account is None:
                account = acc  # 兜底取同平台第一个
        if account is None:
            account = InfluencerSocialAccount(
                influencer_id=inf.id,
                platform=acc_platform,
                platform_id=influencer_service.resolve_platform_id(db, acc_platform),
            )
            db.add(account)
            db.flush()
        account.handle = handle or account.handle
        account.url = url or account.url
        account.page_id = page_id or account.page_id
        account.author_id = author_id or account.author_id
        for field in ("title", "avatar_url", "messenger"):
            if payload.get(field):
                setattr(account, field, str(payload[field]).strip()[:512])
        if payload.get("followers") is not None:
            account.followers = influencer_service._to_int(payload.get("followers"))  # noqa: SLF001
        if isinstance(payload.get("extra"), dict):
            account.extra = payload["extra"]

    db.commit()
    db.refresh(inf)
    return {
        "action": action,
        "matched_by": matched_by,
        "influencer_id": inf.id,
        "display_name": inf.display_name,
    }


# --------------------------------------------------------------------------- #
# 工具：字典 / 身份
# --------------------------------------------------------------------------- #
def list_platforms(db: Session) -> dict[str, Any]:
    """达人平台字典：系统登记的平台 + 社交平台枚举（Agent 传参用枚举值）。"""
    rows = db.query(BitBrowserPlatform).order_by(BitBrowserPlatform.id.asc()).all()
    return {
        "social_platforms": [p.value for p in SocialPlatform],
        "platforms": [
            {"id": row.id, "code": row.code, "name": row.name} for row in rows
        ],
    }


def list_countries(db: Session) -> list[dict[str, Any]]:
    rows = db.query(Country).order_by(Country.sort_order.asc(), Country.id.asc()).all()
    return [
        {"id": row.id, "code": row.code, "name_zh": row.name_zh, "name_en": row.name_en}
        for row in rows
    ]


def whoami(db: Session, user: User, key: AiApiKey) -> dict[str, Any]:
    """告知 Agent 自己的身份与数据范围。"""
    from app.services import rbac_service

    visible = rbac_service.visible_owner_ids(user)
    return {
        "username": user.username,
        "full_name": user.full_name,
        "key_name": key.name,
        "data_scope": "all" if visible is None else "own",
        "visible_owner_count": visible if visible is None else len(visible),
        "tools": list(AGENT_TOOLS),
    }


# --------------------------------------------------------------------------- #
# 工具：抓取暂存链路（复用建联达人页的自动抓取逻辑）
# --------------------------------------------------------------------------- #
def stage_urls(
    db: Session,
    user: User,
    urls: list[str],
    platform: Optional[str] = None,
    batch: Optional[str] = None,
) -> dict[str, Any]:
    """把一批主页链接塞进抓取暂存区（复用现有四层查重：本批/暂存任务/达人库/对照账号）。

    platform 留空则逐条按链接自动识别；返回 created（新任务）/skipped（跳过原因）。
    """
    from app.api.v1.influencer import _stage_urls

    clean = [str(u).strip() for u in (urls or []) if str(u).strip()]
    if not clean:
        raise ValueError("urls 不能为空（主页链接数组）")
    if len(clean) > 100:
        raise ValueError("单次最多暂存 100 条链接")
    result = _stage_urls(db, user, clean, platform, None, batch)
    return result.model_dump(mode="json")


def run_scrape_tasks(
    db: Session,
    user: User,
    task_ids: Optional[list[int]] = None,
    batch: Optional[str] = None,
    auto_save: bool = True,
    save_status: Optional[str] = None,
) -> dict[str, Any]:
    """触发暂存任务后台抓取（auto_save=True 抓完自动入库建联达人）。

    只操作属主自己的 staged 任务；不支持自动抓取的平台（如 TikTok）计入 skipped。
    抓取是后台异步执行，用 get_scrape_task 轮询进度。
    """
    import threading

    from app.api.v1.influencer import _parse_save_status, _run_scrape_profile_bg

    if not task_ids and not batch:
        raise ValueError("task_ids 和 batch 至少提供一个")
    query = db.query(InfluencerScrapeTask).filter(InfluencerScrapeTask.owner_id == user.id)
    if task_ids:
        query = query.filter(InfluencerScrapeTask.id.in_([int(t) for t in task_ids]))
    if batch:
        query = query.filter(InfluencerScrapeTask.batch == batch)
    tasks = query.filter(InfluencerScrapeTask.status == "staged").all()
    runnable = [t for t in tasks if (t.platform or "facebook") in SCRAPABLE_PLATFORMS]
    status = _parse_save_status(save_status)
    for t in runnable:
        t.status = "pending"
        t.error = None
        t.result = None
        t.started_at = None
        t.finished_at = None
    db.commit()
    for t in runnable:
        threading.Thread(
            target=_run_scrape_profile_bg,
            args=(t.id, auto_save, status.value if status else None),
            daemon=True,
        ).start()
    return {
        "affected": len(runnable),
        "skipped": len(tasks) - len(runnable),
        "task_ids": [t.id for t in runnable],
        "auto_save": auto_save,
        "hint": "抓取已在后台执行（约几十秒/条），用 get_scrape_task(task_id) 轮询",
    }


def get_scrape_task(db: Session, user: User, task_id: int) -> Optional[dict[str, Any]]:
    """查抓取任务状态/结果；done 且已入库时 influencer_id 即达人 ID。"""
    from app.api.v1.influencer import _scrape_task_out

    task = db.get(InfluencerScrapeTask, int(task_id))
    if task is None or not can_view(task, user):
        return None
    return _scrape_task_out(db, task).model_dump(mode="json")


# --------------------------------------------------------------------------- #
# 工具：截图与私信记录（agent 自动化闭环）
# --------------------------------------------------------------------------- #
#: 截图大小上限（解码后字节数）
_MEDIA_MAX_BYTES = 6 * 1024 * 1024


def _save_media_image(image_base64: str) -> str:
    """解码 base64 图片存进达人媒体目录，返回站点内可访问路径。"""
    raw = (image_base64 or "").strip()
    if not raw:
        raise ValueError("图片内容为空")
    if raw.startswith("data:"):
        _, _, raw = raw.partition(",")
        raw = raw.strip()
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError("image_base64 不是有效的 base64 图片") from e
    if len(data) < 64:
        raise ValueError("图片内容过小，疑似无效截图")
    if len(data) > _MEDIA_MAX_BYTES:
        raise ValueError("图片超过 6MB 限制")
    kind = "png"
    if data.startswith(b"\xff\xd8"):
        kind = "jpg"
    elif data.startswith(b"GIF8"):
        kind = "gif"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        kind = "webp"
    filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}.{kind}"
    directory = Path(settings.influencer_media_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_bytes(data)
    return f"/api/v1/influencers/media/{filename}"


def _find_influencer_by_url(db: Session, user: User, url: str) -> Optional[Influencer]:
    """在属主可见范围内按主页链接找达人（账号表精确/尾串匹配，兼容主表 fb_page_url）。"""
    text = (url or "").strip()
    if not text:
        return None
    base = owner_filter(
        db.query(Influencer).filter(Influencer.deleted_at.is_(None)), Influencer, user
    )
    acc_conds = [InfluencerSocialAccount.url == text]
    if len(text) > 20:
        acc_conds.append(InfluencerSocialAccount.url.ilike(f"%{text[-60:]}"))
    hit = (
        base.join(
            InfluencerSocialAccount, InfluencerSocialAccount.influencer_id == Influencer.id
        )
        .filter(or_(*acc_conds))
        .first()
    )
    if hit is not None:
        return hit
    return base.filter(Influencer.fb_page_url == text).first()


def _apply_homepage_screenshot(inf: Influencer, value: Any) -> None:
    """homepage_screenshot 字段兼容三种取值：base64/data-url → 落盘存路径；普通路径/URL → 直存。"""
    text = str(value or "").strip()
    if not text:
        return
    if text.startswith("data:") or len(text) > 512:
        inf.homepage_screenshot = _save_media_image(text)
    else:
        inf.homepage_screenshot = text[:512]


def save_homepage_screenshot(
    db: Session,
    user: User,
    image_base64: str,
    influencer_id: Optional[int] = None,
    url: Optional[str] = None,
) -> dict[str, Any]:
    """保存达人主页截图（influencer_id 或 url 定位达人，二选一）。"""
    if influencer_id is None and not (url or "").strip():
        raise ValueError("influencer_id 和 url 至少提供一个")
    inf: Optional[Influencer] = None
    if influencer_id is not None:
        inf = db.get(Influencer, int(influencer_id))
        if inf is None or inf.deleted_at is not None or not can_view(inf, user):
            raise ValueError(f"达人 {influencer_id} 不存在或无权查看")
    if inf is None:
        inf = _find_influencer_by_url(db, user, url or "")
    if inf is None:
        raise ValueError("未找到对应达人，请先用 upsert_influencer 存入")
    path = _save_media_image(image_base64)
    inf.homepage_screenshot = path
    db.commit()
    return {"influencer_id": inf.id, "homepage_screenshot": path}


def record_outreach(
    db: Session,
    user: User,
    url: str,
    content_text: Optional[str] = None,
    influencer_id: Optional[int] = None,
    screenshot_base64: Optional[str] = None,
    status: str = "success",
    error: Optional[str] = None,
    set_status: Optional[str] = None,
) -> dict[str, Any]:
    """记录一次 agent 自动私信（自包含快照：正文直接存，不依赖内容库模板；截图落盘）。

    url 定位达人（也可显式传 influencer_id）；找到达人时关联记录并按 set_status 更新建联状态。
    """
    link = (url or "").strip()
    if not link:
        raise ValueError("url（达人主页链接）必填")
    if status not in ("success", "failed"):
        raise ValueError("status 只能是 success / failed")

    inf: Optional[Influencer] = None
    if influencer_id is not None:
        inf = db.get(Influencer, int(influencer_id))
        if inf is None or inf.deleted_at is not None or not can_view(inf, user):
            raise ValueError(f"达人 {influencer_id} 不存在或无权查看")
    if inf is None:
        inf = _find_influencer_by_url(db, user, link)

    screenshot = _save_media_image(screenshot_base64) if screenshot_base64 else None
    log = DmOutreachLog(
        owner_id=user.id,
        influencer_id=inf.id if inf is not None else None,
        url=link[:512],
        content_text=(content_text or None) and str(content_text)[:5000],
        screenshot=screenshot,
        text_sent=bool(content_text),
        status=status,
        error=(error or None) and str(error)[:2000],
    )
    db.add(log)
    status_applied: Optional[str] = None
    if inf is not None and set_status:
        try:
            inf.status = InfluencerStatus(str(set_status).strip().lower())
        except ValueError as e:
            raise ValueError(
                f"未知状态: {set_status}（可选: {[s.value for s in InfluencerStatus]}）"
            ) from e
        status_applied = inf.status.value
    db.commit()
    return {
        "outreach_log_id": log.id,
        "influencer_id": inf.id if inf is not None else None,
        "matched_influencer": inf is not None,
        "screenshot": screenshot,
        "status": status,
        "influencer_status": status_applied,
    }
