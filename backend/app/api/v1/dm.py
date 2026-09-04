"""私信内容：分类、模板、图片上传。"""
from __future__ import annotations

import random
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx
from loguru import logger
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.deps import can_view, get_current_user, get_db, scope_query
from app.db.session import SessionLocal
from app.models.bitbrowser import BitBrowserWindow
from app.models.dm import DmCategory, DmContent, DmOutreachJob, DmOutreachLog
from app.models.influencer import Influencer
from app.models.influencer_scrape_task import InfluencerScrapeTask
from app.models.social_account import InfluencerSocialAccount, SocialPlatform
from app.models.user import User
from app.services.influencer_service import (
    build_ig_profile_url,
    match_influencer_id_by_url,
)
from app.schemas.dm import (
    DmCategoryCreate,
    DmCategoryOut,
    DmCategoryUpdate,
    DmContentCreate,
    DmContentOut,
    DmContentUpdate,
    DmImageItem,
    DmOutreachJobCreate,
    DmOutreachJobDetailOut,
    DmOutreachJobOut,
    DmOutreachLogOut,
    DmOutreachOut,
    DmOutreachStart,
    DmUploadOut,
)
from app.api.v1.influencer import _run_scrape_profile_bg
from app.services.fb_dm_automation import open_profile_and_message

router = APIRouter(prefix="/dm", tags=["dm"])

_JOB_CANCEL_POLL_SECONDS = 5

_ALLOWED_IMAGE_SUFFIX = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _dm_upload_root() -> Path:
    root = Path(settings.dm_upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _media_url(owner_id: int, filename: str) -> str:
    return f"/api/v1/dm/media/{owner_id}/{filename}"


def _get_category_or_404(db: Session, user: User, category_id: int) -> DmCategory:
    row = (
        scope_query(db.query(DmCategory), DmCategory, user)
        .filter(DmCategory.id == category_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="分类不存在")
    return row


def _get_content_or_404(db: Session, user: User, content_id: int) -> DmContent:
    row = (
        scope_query(db.query(DmContent), DmContent, user)
        .filter(DmContent.id == content_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="内容不存在")
    return row


def _content_to_out(row: DmContent) -> DmContentOut:
    cat_name = row.category.name if row.category else None
    images = row.images if isinstance(row.images, list) else []
    tags = row.tags if isinstance(row.tags, list) else []
    return DmContentOut(
        id=row.id,
        owner_id=row.owner_id,
        category_id=row.category_id,
        category_name=cat_name,
        title=row.title,
        summary=row.summary,
        content=row.content,
        images=images,
        tags=tags,
        is_active=bool(row.is_active),
        is_pinned=bool(row.is_pinned),
        sort_order=row.sort_order,
        remark=row.remark,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ----- 分类 -----


@router.get("/categories", response_model=list[DmCategoryOut])
def list_dm_categories(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    active_only: bool = Query(False, description="仅返回启用中的分类"),
):
    q = scope_query(db.query(DmCategory), DmCategory, user)
    if active_only:
        q = q.filter(DmCategory.is_active.is_(True))
    return q.order_by(DmCategory.sort_order.asc(), DmCategory.id.asc()).all()


@router.post("/categories", response_model=DmCategoryOut)
def create_dm_category(
    body: DmCategoryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = DmCategory(
        owner_id=user.id,
        name=body.name.strip(),
        code=(body.code or "").strip() or None,
        color=(body.color or "").strip() or None,
        remark=(body.remark or "").strip() or None,
        sort_order=body.sort_order,
        is_active=body.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/categories/{category_id}", response_model=DmCategoryOut)
def update_dm_category(
    category_id: int,
    body: DmCategoryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _get_category_or_404(db, user, category_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip()
    if "code" in data:
        data["code"] = (data["code"] or "").strip() or None
    if "color" in data:
        data["color"] = (data["color"] or "").strip() or None
    if "remark" in data:
        data["remark"] = (data["remark"] or "").strip() or None
    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/categories/{category_id}")
def delete_dm_category(
    category_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _get_category_or_404(db, user, category_id)
    db.delete(row)
    db.commit()
    return {"ok": True}


# ----- 内容 -----


@router.get("/contents", response_model=list[DmContentOut])
def list_dm_contents(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    category_id: int | None = Query(None, description="按分类筛选；不传为全部"),
    keyword: str | None = Query(None, description="标题/摘要/正文模糊搜索"),
    active_only: bool = Query(False),
    pinned_only: bool = Query(False),
):
    q = scope_query(db.query(DmContent), DmContent, user)
    if category_id is not None:
        if category_id == 0:
            q = q.filter(DmContent.category_id.is_(None))
        else:
            q = q.filter(DmContent.category_id == category_id)
    if active_only:
        q = q.filter(DmContent.is_active.is_(True))
    if pinned_only:
        q = q.filter(DmContent.is_pinned.is_(True))
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(
            (DmContent.title.like(like))
            | (DmContent.summary.like(like))
            | (DmContent.content.like(like))
        )
    rows = (
        q.options(joinedload(DmContent.category))
        .order_by(
            DmContent.is_pinned.desc(),
            DmContent.sort_order.asc(),
            DmContent.id.desc(),
        )
        .all()
    )
    return [_content_to_out(r) for r in rows]


@router.get("/contents/{content_id}", response_model=DmContentOut)
def get_dm_content(
    content_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _get_content_or_404(db, user, content_id)
    return _content_to_out(row)


@router.post("/contents", response_model=DmContentOut)
def create_dm_content(
    body: DmContentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if body.category_id is not None:
        _get_category_or_404(db, user, body.category_id)
    images = [img.model_dump() for img in body.images]
    tags = [t.strip() for t in body.tags if t and t.strip()]
    row = DmContent(
        owner_id=user.id,
        category_id=body.category_id,
        title=body.title.strip(),
        summary=(body.summary or "").strip() or None,
        content=body.content.strip(),
        images=images or None,
        tags=tags or None,
        is_active=body.is_active,
        is_pinned=body.is_pinned,
        sort_order=body.sort_order,
        remark=(body.remark or "").strip() or None,
    )
    db.add(row)
    db.commit()
    row = (
        db.query(DmContent)
        .options(joinedload(DmContent.category))
        .filter(DmContent.id == row.id)
        .one()
    )
    return _content_to_out(row)


@router.put("/contents/{content_id}", response_model=DmContentOut)
def update_dm_content(
    content_id: int,
    body: DmContentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _get_content_or_404(db, user, content_id)
    data = body.model_dump(exclude_unset=True)
    if "category_id" in data and data["category_id"] is not None:
        _get_category_or_404(db, user, data["category_id"])
    if "title" in data and data["title"] is not None:
        data["title"] = data["title"].strip()
    if "summary" in data:
        data["summary"] = (data["summary"] or "").strip() or None
    if "content" in data and data["content"] is not None:
        data["content"] = data["content"].strip()
    if "images" in data and data["images"] is not None:
        data["images"] = [
            x if isinstance(x, dict) else DmImageItem.model_validate(x).model_dump()
            for x in data["images"]
        ]
    if "tags" in data and data["tags"] is not None:
        data["tags"] = [t.strip() for t in data["tags"] if t and t.strip()] or None
    if "remark" in data:
        data["remark"] = (data["remark"] or "").strip() or None
    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    row = (
        db.query(DmContent)
        .options(joinedload(DmContent.category))
        .filter(DmContent.id == row.id)
        .one()
    )
    return _content_to_out(row)


@router.delete("/contents/{content_id}")
def delete_dm_content(
    content_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _get_content_or_404(db, user, content_id)
    db.delete(row)
    db.commit()
    return {"ok": True}


# ----- 私信建联自动化 -----


def _browser_name(db: Session, owner_id: int, browser_id: str) -> str | None:
    row = (
        db.query(BitBrowserWindow.name)
        .filter(
            BitBrowserWindow.owner_id == owner_id,
            BitBrowserWindow.browser_id == browser_id,
        )
        .first()
    )
    return row[0] if row and row[0] else None


def _record_outreach_log(
    db: Session,
    user: User,
    url: str,
    browser_id: str,
    content: DmContent,
    result: dict | None,
    platform: str = "facebook",
    *,
    error: str | None = None,
    influencer_id: int | None = None,
    job_id: int | None = None,
) -> DmOutreachLog:
    """记录一条私信发送日志（成功/失败都记），并按主页 URL 关联到已入库达人（同一 owner）。"""
    if influencer_id is None:
        influencer_id = match_influencer_id_by_url(db, user.id, url, platform)
    images = content.images if isinstance(content.images, list) else []
    result = result or {}
    text_sent = bool(result.get("text_sent"))
    images_sent = int(result.get("images_sent") or 0)
    ok = error is None and (text_sent or images_sent > 0)
    if not ok and error is None:
        error = "未能发出消息（未找到发消息按钮或输入框）"
    log = DmOutreachLog(
        owner_id=user.id,
        influencer_id=influencer_id,
        url=url,
        browser_id=browser_id or None,
        browser_name=_browser_name(db, user.id, browser_id) if browser_id else None,
        content_id=content.id,
        content_title=content.title,
        content_text=content.content,
        images_count=len(images),
        text_sent=text_sent,
        images_sent=images_sent,
        status="success" if ok else "failed",
        error=None if ok else (error or "")[:4000],
        job_id=job_id,
    )
    db.add(log)
    db.commit()
    return log


def _resolve_content_image_paths(content: DmContent) -> list[Path]:
    image_paths: list[Path] = []
    images = content.images if isinstance(content.images, list) else []
    upload_root = _dm_upload_root()
    media_prefix = "/api/v1/dm/media/"
    for img in images:
        if not isinstance(img, dict):
            continue
        rel = str(img.get("path") or "").strip()
        if not rel:
            # 兼容早期数据：path 缺失时从 media URL 反推相对路径
            u = str(img.get("url") or "").strip()
            if media_prefix in u:
                rel = u.split(media_prefix, 1)[1]
        if not rel:
            continue
        p = (upload_root / rel).resolve()
        if upload_root.resolve() not in p.parents:
            continue
        if p.is_file():
            image_paths.append(p)
    return image_paths


@router.post("/outreach/start", response_model=DmOutreachOut)
def start_dm_outreach(
    body: DmOutreachStart,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """在指定 BitBrowser 窗口中打开达人主页并点击「发消息」（私信建联第一步）。"""
    content = (
        scope_query(db.query(DmContent), DmContent, user)
        .filter(DmContent.id == body.content_id)
        .first()
    )
    if not content:
        raise HTTPException(status_code=404, detail="私信内容不存在")
    platform = (body.platform or "facebook").strip().lower()
    if platform not in ("facebook", "instagram"):
        platform = "facebook"
    # IG 允许输入用户名/带参数链接，统一成标准主页 URL 再打开与匹配
    target_url = (
        build_ig_profile_url(body.url) if platform == "instagram" else body.url.strip()
    )
    image_paths = _resolve_content_image_paths(content)
    browser_id = body.browser_id.strip()
    try:
        result = open_profile_and_message(
            browser_id,
            target_url,
            user,
            db,
            message_text=content.content,
            image_paths=image_paths,
            platform=platform,
        )
    except ValueError as e:
        _record_outreach_log(db, user, target_url, browser_id, content, None, platform, error=str(e))
        raise HTTPException(status_code=400, detail=str(e)) from e
    except httpx.HTTPError as e:
        msg = f"连接 BitBrowser/CDP 失败: {e}"
        _record_outreach_log(db, user, target_url, browser_id, content, None, platform, error=msg)
        raise HTTPException(status_code=502, detail=msg) from e
    except RuntimeError as e:
        _record_outreach_log(db, user, target_url, browser_id, content, None, platform, error=str(e))
        raise HTTPException(status_code=502, detail=str(e)) from e
    _record_outreach_log(db, user, target_url, browser_id, content, result, platform)
    scrape_task_id: int | None = None
    if result.get("text_sent") or result.get("images_sent"):
        # 私信发出后自动抓主页并入库；若来自暂存列表则复用同一行任务，避免重复
        task: InfluencerScrapeTask | None = None
        if body.source_task_id:
            st = db.get(InfluencerScrapeTask, body.source_task_id)
            if st and st.owner_id == user.id:
                st.platform = platform
                st.url = target_url
                st.status = "pending"
                st.error = None
                st.result = None
                st.started_at = None
                st.finished_at = None
                task = st
        if task is None:
            task = InfluencerScrapeTask(
                owner_id=user.id, platform=platform, url=target_url, status="pending"
            )
            db.add(task)
        db.commit()
        db.refresh(task)
        scrape_task_id = task.id
        threading.Thread(
            target=_run_scrape_profile_bg, args=(task.id, True), daemon=True
        ).start()
    return DmOutreachOut(
        ok=True,
        browser_id=body.browser_id.strip(),
        content_id=content.id,
        content_title=content.title,
        page_opened=bool(result.get("page_opened")),
        message_clicked=bool(result.get("message_clicked")),
        matched_text=(str(result["matched_text"]) if result.get("matched_text") else None),
        text_sent=bool(result.get("text_sent")),
        images_sent=int(result.get("images_sent") or 0),
        scrape_task_id=scrape_task_id,
        final_url=(str(result["final_url"]) if result.get("final_url") else None),
        open_hint=result.get("open_hint"),
    )


# ----- 批量私信任务（对已入库达人）-----


def _influencer_target_url(db: Session, inf: Influencer, platform: str) -> str | None:
    """取达人在指定平台的主页链接：优先关联账号，FB 兼容旧 fb_page_url。"""
    try:
        plat = SocialPlatform(platform)
    except ValueError:
        return None
    rows = (
        db.query(InfluencerSocialAccount.url, InfluencerSocialAccount.handle)
        .filter(
            InfluencerSocialAccount.influencer_id == inf.id,
            InfluencerSocialAccount.platform == plat,
        )
        .order_by(InfluencerSocialAccount.id.asc())
        .all()
    )
    for u, _h in rows:
        if u and u.strip():
            return u.strip()
    if platform == "instagram":
        for _u, h in rows:
            if h and h.strip():
                return h.strip()
    if platform == "facebook" and inf.fb_page_url:
        return inf.fb_page_url.strip()
    return None


def _job_out(db: Session, job: DmOutreachJob, with_logs: bool = False):
    owner = db.get(User, job.owner_id)
    data = DmOutreachJobOut.model_validate(job).model_dump()
    data["owner_name"] = owner.username if owner else None
    if not with_logs:
        return DmOutreachJobOut(**data)
    logs = (
        db.query(DmOutreachLog)
        .filter(DmOutreachLog.job_id == job.id)
        .order_by(DmOutreachLog.id.asc())
        .all()
    )
    out_logs = []
    for lg in logs:
        d = DmOutreachLogOut.model_validate(lg).model_dump()
        d["owner_name"] = owner.username if owner else None
        out_logs.append(DmOutreachLogOut(**d))
    return DmOutreachJobDetailOut(**data, logs=out_logs)


def _wait_unless_cancelled(db: Session, job_id: int, seconds: int) -> bool:
    """分段 sleep，期间任务被取消则提前返回 False。"""
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        time.sleep(min(remaining, _JOB_CANCEL_POLL_SECONDS))
        db.expire_all()
        job = db.get(DmOutreachJob, job_id)
        if not job or job.status == "cancelled":
            return False


def _run_dm_outreach_job_bg(job_id: int) -> None:
    """后台线程：逐个达人发送，每条成功/失败都写入 DmOutreachLog（job_id 关联）。"""
    db = SessionLocal()
    try:
        job = db.get(DmOutreachJob, job_id)
        if not job or job.status != "pending":
            return
        user = db.get(User, job.owner_id)
        content = db.get(DmContent, job.content_id) if job.content_id else None
        job.status = "running"
        job.started_at = datetime.utcnow()
        db.commit()
        if not user or not content:
            job.status = "done"
            job.error = "发送人或私信内容已不存在"
            job.finished_at = datetime.utcnow()
            db.commit()
            return
        image_paths = _resolve_content_image_paths(content)
        targets = job.targets if isinstance(job.targets, list) else []
        for idx, t in enumerate(targets):
            if idx > 0:
                # 每条之间随机等待，等待期间可被取消
                wait_s = random.randint(
                    min(job.interval_min, job.interval_max),
                    max(job.interval_min, job.interval_max),
                )
                job.current_url = None
                db.commit()
                if not _wait_unless_cancelled(db, job_id, wait_s):
                    break
            db.refresh(job)
            if job.status == "cancelled":
                break
            url = str(t.get("url") or "").strip()
            inf_id = t.get("influencer_id")
            job.current_url = url
            db.commit()
            result: dict | None = None
            error: str | None = None
            try:
                result = open_profile_and_message(
                    job.browser_id,
                    url,
                    user,
                    db,
                    message_text=content.content,
                    image_paths=image_paths,
                    platform=job.platform,
                )
            except httpx.HTTPError as e:
                error = f"连接 BitBrowser/CDP 失败: {e}"
            except Exception as e:  # noqa: BLE001
                error = str(e) or e.__class__.__name__
            db.rollback()
            log = _record_outreach_log(
                db,
                user,
                url,
                job.browser_id,
                content,
                result,
                job.platform,
                error=error,
                influencer_id=int(inf_id) if inf_id else None,
                job_id=job.id,
            )
            job = db.get(DmOutreachJob, job_id)
            if log.status == "success":
                job.sent += 1
            else:
                job.failed += 1
            db.commit()
        job = db.get(DmOutreachJob, job_id)
        if job.status != "cancelled":
            job.status = "done"
        job.current_url = None
        job.finished_at = datetime.utcnow()
        db.commit()
    except Exception as e:  # noqa: BLE001
        logger.exception("dm outreach job {} crashed: {}", job_id, e)
        db.rollback()
        job = db.get(DmOutreachJob, job_id)
        if job:
            job.status = "done"
            job.error = str(e)[:4000]
            job.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


@router.post("/outreach/jobs", response_model=DmOutreachJobOut)
def create_dm_outreach_job(
    body: DmOutreachJobCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """对已入库达人发起一次批量私信（可二次私信），后台逐个发送，每条结果记入达人私信记录。"""
    content = (
        scope_query(db.query(DmContent), DmContent, user)
        .filter(DmContent.id == body.content_id)
        .first()
    )
    if not content:
        raise HTTPException(status_code=404, detail="私信内容不存在")
    platform = (body.platform or "facebook").strip().lower()
    if platform not in ("facebook", "instagram"):
        raise HTTPException(status_code=400, detail="仅支持 facebook / instagram 私信")
    ids = list(dict.fromkeys(body.influencer_ids))
    infs = db.query(Influencer).filter(Influencer.id.in_(ids)).all()
    by_id = {i.id: i for i in infs}
    targets: list[dict] = []
    missing: list[str] = []
    for iid in ids:
        inf = by_id.get(iid)
        if not inf or not can_view(inf, user):
            raise HTTPException(status_code=404, detail=f"达人 #{iid} 不存在")
        url = _influencer_target_url(db, inf, platform)
        if platform == "instagram" and url:
            url = build_ig_profile_url(url)
        if not url:
            missing.append(inf.display_name or f"#{iid}")
            continue
        targets.append({"influencer_id": inf.id, "url": url, "display_name": inf.display_name})
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"以下达人没有 {platform} 主页链接，无法私信：{'、'.join(missing[:10])}",
        )
    browser_id = body.browser_id.strip()
    job = DmOutreachJob(
        owner_id=user.id,
        platform=platform,
        browser_id=browser_id,
        browser_name=_browser_name(db, user.id, browser_id),
        content_id=content.id,
        content_title=content.title,
        targets=targets,
        interval_min=min(body.interval_min, body.interval_max),
        interval_max=max(body.interval_min, body.interval_max),
        total=len(targets),
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    threading.Thread(target=_run_dm_outreach_job_bg, args=(job.id,), daemon=True).start()
    return _job_out(db, job)


@router.get("/outreach/jobs", response_model=list[DmOutreachJobOut])
def list_dm_outreach_jobs(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        scope_query(db.query(DmOutreachJob), DmOutreachJob, user)
        .order_by(DmOutreachJob.id.desc())
        .limit(limit)
        .all()
    )
    return [_job_out(db, j) for j in rows]


@router.get("/outreach/jobs/{job_id}", response_model=DmOutreachJobDetailOut)
def get_dm_outreach_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = db.get(DmOutreachJob, job_id)
    if not job or not can_view(job, user):
        raise HTTPException(status_code=404, detail="任务不存在")
    return _job_out(db, job, with_logs=True)


@router.post("/outreach/jobs/{job_id}/cancel", response_model=DmOutreachJobOut)
def cancel_dm_outreach_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """取消：当前正在发的一条会发完，后续不再发送。"""
    job = db.get(DmOutreachJob, job_id)
    if not job or job.owner_id != user.id:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status in ("pending", "running"):
        if job.status == "pending":
            job.finished_at = datetime.utcnow()
        job.status = "cancelled"
        db.commit()
        db.refresh(job)
    return _job_out(db, job)


# ----- 上传 -----


@router.post("/uploads", response_model=DmUploadOut)
async def upload_dm_image(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="未选择文件")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in _ALLOWED_IMAGE_SUFFIX:
        raise HTTPException(status_code=400, detail="仅支持 jpg/png/gif/webp/bmp 图片")
    raw = await file.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="图片不能超过 10MB")
    safe_name = f"{uuid.uuid4().hex}{suffix}"
    user_dir = _dm_upload_root() / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    dest = user_dir / safe_name
    dest.write_bytes(raw)
    rel = f"{user.id}/{safe_name}"
    return DmUploadOut(url=_media_url(user.id, safe_name), path=rel, name=file.filename)


@router.get("/media/{owner_id}/{filename}")
def get_dm_media(owner_id: int, filename: str):
    """返回已上传的私信图片（文件名为随机 uuid，供 <img> 标签直接加载）。"""
    name = Path(filename).name
    if name != filename or Path(name).suffix.lower() not in _ALLOWED_IMAGE_SUFFIX:
        raise HTTPException(status_code=404, detail="图片不存在")
    path = _dm_upload_root() / str(owner_id) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path)
