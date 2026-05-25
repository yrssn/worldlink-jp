"""Facebook 群组维度抓取配置 CRUD（软删除）+ 后台拉取任务。"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_current_user, get_db, is_admin
from app.db.session import SessionLocal
from app.models.fb_group_scrape import (
    FbGroupPost,
    FbGroupPullTask,
    FbGroupPullTaskStatus,
    FbGroupScrapeConfig,
)
from app.models.user import User
from app.schemas.fb_group_scrape import (
    FbGroupPostOut,
    FbGroupPostPage,
    FbGroupPullTaskCreate,
    FbGroupPullTaskOut,
    FbGroupScrapeCreate,
    FbGroupScrapeOut,
    FbGroupScrapeUpdate,
)
from app.services import apify_service

router = APIRouter(prefix="/scraper/fb-group-scrapes", tags=["scraper-fb-group"])


# ─── 工具函数 ───────────────────────────────────────────────────

def _parse_post_time(raw: str | None) -> Optional[datetime]:
    if not raw:
        return None
    try:
        from datetime import timezone
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)
    except Exception:
        return None


def _item_to_post(item: dict, task_id: int, config_id: int) -> FbGroupPost | None:
    legacy_id = str(item.get("legacyId") or item.get("id") or "").strip()
    if not legacy_id:
        return None
    user_obj = item.get("user") or {}
    return FbGroupPost(
        task_id=task_id,
        config_id=config_id,
        legacy_id=legacy_id,
        post_url=item.get("url"),
        facebook_group_id=str(item.get("facebookId") or "").strip() or None,
        group_title=item.get("groupTitle"),
        user_id=str(user_obj.get("id") or "").strip() or None,
        user_name=user_obj.get("name"),
        text=item.get("text"),
        post_time=_parse_post_time(item.get("time")),
        likes_count=int(item.get("likesCount") or 0),
        comments_count=int(item.get("commentsCount") or 0),
        shares_count=int(item.get("sharesCount") or 0),
        has_attachments=bool(item.get("attachments")),
        has_shared_post=bool(item.get("sharedPost")),
        raw_data=item,
    )


def _run_pull_task_bg(task_id: int) -> None:
    """后台线程：执行 Apify 拉取并将结果写入数据库。"""
    db = SessionLocal()
    try:
        task: FbGroupPullTask | None = db.query(FbGroupPullTask).filter(
            FbGroupPullTask.id == task_id
        ).first()
        if not task:
            return

        task.status = FbGroupPullTaskStatus.running
        task.started_at = datetime.utcnow()
        db.commit()

        params = task.params or {}
        config: FbGroupScrapeConfig = db.query(FbGroupScrapeConfig).filter(
            FbGroupScrapeConfig.id == task.config_id
        ).first()
        if not config:
            task.status = FbGroupPullTaskStatus.failed
            task.error = "关联的群组配置不存在"
            task.finished_at = datetime.utcnow()
            db.commit()
            return

        try:
            group_url = _normalize_group_url(config.connection)
        except HTTPException as e:
            task.status = FbGroupPullTaskStatus.failed
            task.error = str(e.detail)[:2000]
            task.finished_at = datetime.utcnow()
            db.commit()
            return

        try:
            result = apify_service.run_fb_groups(
                group_url,
                results_limit=params.get("results_limit", 5),
                view_option=params.get("view_option", "CHRONOLOGICAL"),
                search_group_keyword=params.get("search_group_keyword"),
                search_group_year=params.get("search_group_year"),
                only_posts_newer_than=params.get("only_posts_newer_than"),
                timeout_secs=900,
                db=db,
            )
        except Exception as e:  # noqa: BLE001
            task.status = FbGroupPullTaskStatus.failed
            task.error = str(e)[:2000]
            task.finished_at = datetime.utcnow()
            db.commit()
            logger.error("[FbGroupPullTask#{}] failed: {}", task_id, e)
            return

        items = result.get("items") or []
        task.apify_run_id = result.get("run_id")
        task.apify_dataset_id = result.get("dataset_id")

        saved = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            post = _item_to_post(item, task_id=task_id, config_id=task.config_id)
            if post is None:
                continue
            try:
                db.add(post)
                db.flush()
                saved += 1
            except IntegrityError:
                db.rollback()

        task.result_count = saved
        task.status = FbGroupPullTaskStatus.done
        task.finished_at = datetime.utcnow()
        db.commit()
        logger.info("[FbGroupPullTask#{}] done, saved {} posts", task_id, saved)
    except Exception as e:  # noqa: BLE001
        logger.exception("[FbGroupPullTask#{}] unexpected error: {}", task_id, e)
        try:
            task = db.query(FbGroupPullTask).filter(FbGroupPullTask.id == task_id).first()
            if task:
                task.status = FbGroupPullTaskStatus.failed
                task.error = str(e)[:2000]
                task.finished_at = datetime.utcnow()
                db.commit()
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()


def _to_task_out(task: FbGroupPullTask) -> FbGroupPullTaskOut:
    return FbGroupPullTaskOut(
        id=task.id,
        config_id=task.config_id,
        config_title=task.config.title if task.config else None,
        created_by_id=task.created_by_id,
        created_by_username=task.creator.username if task.creator else None,
        status=task.status.value,
        params=task.params,
        apify_run_id=task.apify_run_id,
        apify_dataset_id=task.apify_dataset_id,
        result_count=task.result_count,
        error=task.error,
        started_at=task.started_at,
        finished_at=task.finished_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _active_query(db: Session, user: User, *, include_deleted: bool):
    q = db.query(FbGroupScrapeConfig).options(joinedload(FbGroupScrapeConfig.creator))
    if not is_admin(user):
        q = q.filter(FbGroupScrapeConfig.created_by_id == user.id)
    if not include_deleted:
        q = q.filter(FbGroupScrapeConfig.deleted_at.is_(None))
    return q


def _to_out(row: FbGroupScrapeConfig) -> FbGroupScrapeOut:
    username = row.creator.username if row.creator else None
    return FbGroupScrapeOut(
        id=row.id,
        created_by_id=row.created_by_id,
        created_by_username=username,
        connection=row.connection,
        title=row.title,
        remark=row.remark,
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
    )


# 列表展示时优先展示的字段（其余字段仍会在 field_keys / 原始 JSON 中出现）
_DISPLAY_FIELD_PRIORITY = (
    "url",
    "postUrl",
    "text",
    "message",
    "postText",
    "userName",
    "author",
    "authorName",
    "time",
    "timestamp",
    "date",
    "likes",
    "likesCount",
    "comments",
    "commentsCount",
    "shares",
    "sharesCount",
    "groupTitle",
    "groupUrl",
    "facebookId",
    "postId",
    "feedbackId",
)


def _collect_field_keys(items: list[dict]) -> list[str]:
    keys: set[str] = set()
    for it in items:
        if isinstance(it, dict):
            keys.update(it.keys())
    ordered = [k for k in _DISPLAY_FIELD_PRIORITY if k in keys]
    rest = sorted(k for k in keys if k not in ordered)
    return ordered + rest


def _normalize_group_url(connection: str) -> str:
    raw = (connection or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="连接为空，请填写 Facebook 群组 URL")
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if "facebook.com/groups/" in raw:
        return f"https://{raw.lstrip('/')}"
    raise HTTPException(
        status_code=400,
        detail="连接需为 Facebook 公开群组 URL，例如 https://www.facebook.com/groups/xxxxx",
    )


def _get_or_404(
    db: Session, user: User, record_id: int, *, include_deleted: bool = False
) -> FbGroupScrapeConfig:
    q = _active_query(db, user, include_deleted=include_deleted).filter(
        FbGroupScrapeConfig.id == record_id
    )
    row = q.first()
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")
    return row


@router.get("", response_model=list[FbGroupScrapeOut])
def list_fb_group_scrapes(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    keyword: str | None = Query(None, description="标题/连接/备注模糊搜索"),
    include_deleted: bool = Query(False, description="是否包含已软删除（仅管理员建议开启）"),
):
    q = _active_query(db, user, include_deleted=include_deleted and is_admin(user))
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(
            (FbGroupScrapeConfig.title.like(like))
            | (FbGroupScrapeConfig.connection.like(like))
            | (FbGroupScrapeConfig.remark.like(like))
        )
    rows = q.order_by(FbGroupScrapeConfig.id.desc()).all()
    return [_to_out(r) for r in rows]


@router.get("/{record_id}", response_model=FbGroupScrapeOut)
def get_fb_group_scrape(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _get_or_404(db, user, record_id)
    return _to_out(row)


@router.post("", response_model=FbGroupScrapeOut)
def create_fb_group_scrape(
    body: FbGroupScrapeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = FbGroupScrapeConfig(
        created_by_id=user.id,
        connection=body.connection.strip(),
        title=body.title.strip(),
        remark=(body.remark or "").strip() or None,
    )
    db.add(row)
    db.commit()
    row = (
        db.query(FbGroupScrapeConfig)
        .options(joinedload(FbGroupScrapeConfig.creator))
        .filter(FbGroupScrapeConfig.id == row.id)
        .one()
    )
    return _to_out(row)


@router.put("/{record_id}", response_model=FbGroupScrapeOut)
def update_fb_group_scrape(
    record_id: int,
    body: FbGroupScrapeUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _get_or_404(db, user, record_id)
    if row.deleted_at is not None:
        raise HTTPException(status_code=400, detail="已删除的记录不可编辑，请先恢复")
    data = body.model_dump(exclude_unset=True)
    if "connection" in data and data["connection"] is not None:
        data["connection"] = data["connection"].strip()
    if "title" in data and data["title"] is not None:
        data["title"] = data["title"].strip()
    if "remark" in data:
        data["remark"] = (data["remark"] or "").strip() or None
    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    row = (
        db.query(FbGroupScrapeConfig)
        .options(joinedload(FbGroupScrapeConfig.creator))
        .filter(FbGroupScrapeConfig.id == row.id)
        .one()
    )
    return _to_out(row)


@router.delete("/{record_id}")
def soft_delete_fb_group_scrape(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _get_or_404(db, user, record_id)
    if row.deleted_at is not None:
        return {"ok": True}
    row.deleted_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.post("/{record_id}/pull", response_model=FbGroupPullTaskOut)
def pull_fb_group_posts_async(
    record_id: int,
    body: FbGroupPullTaskCreate | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """提交后台拉取任务（立即返回任务 ID，Apify 在后台线程中执行）。"""
    row = _get_or_404(db, user, record_id)
    if row.deleted_at is not None:
        raise HTTPException(status_code=400, detail="已删除的记录不可拉取")
    opts = body or FbGroupPullTaskCreate()
    task = FbGroupPullTask(
        config_id=row.id,
        created_by_id=user.id,
        status=FbGroupPullTaskStatus.pending,
        params={
            "results_limit": opts.results_limit,
            "view_option": opts.view_option,
            "search_group_keyword": opts.search_group_keyword,
            "search_group_year": opts.search_group_year,
            "only_posts_newer_than": opts.only_posts_newer_than,
        },
    )
    db.add(task)
    db.commit()
    task = (
        db.query(FbGroupPullTask)
        .options(
            joinedload(FbGroupPullTask.config),
            joinedload(FbGroupPullTask.creator),
        )
        .filter(FbGroupPullTask.id == task.id)
        .one()
    )
    t = threading.Thread(target=_run_pull_task_bg, args=(task.id,), daemon=True)
    t.start()
    logger.info("[FbGroupPull] task#{} started in background for config#{}", task.id, row.id)
    return _to_task_out(task)


# ─── 任务查询 ───────────────────────────────────────────────────

@router.get("/{record_id}/tasks", response_model=list[FbGroupPullTaskOut])
def list_pull_tasks(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出某群组配置的所有拉取任务。"""
    row = _get_or_404(db, user, record_id, include_deleted=True)
    q = (
        db.query(FbGroupPullTask)
        .options(
            joinedload(FbGroupPullTask.config),
            joinedload(FbGroupPullTask.creator),
        )
        .filter(FbGroupPullTask.config_id == row.id)
    )
    if not is_admin(user):
        q = q.filter(FbGroupPullTask.created_by_id == user.id)
    tasks = q.order_by(FbGroupPullTask.id.desc()).all()
    return [_to_task_out(t) for t in tasks]


@router.get("/tasks/{task_id}", response_model=FbGroupPullTaskOut)
def get_pull_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取单个拉取任务详情。"""
    task = (
        db.query(FbGroupPullTask)
        .options(
            joinedload(FbGroupPullTask.config),
            joinedload(FbGroupPullTask.creator),
        )
        .filter(FbGroupPullTask.id == task_id)
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not is_admin(user) and task.created_by_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问")
    return _to_task_out(task)


# ─── 帖子查询 ───────────────────────────────────────────────────

@router.get("/tasks/{task_id}/posts", response_model=FbGroupPostPage)
def list_task_posts(
    task_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, description="文本/用户名关键词"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """分页查询某拉取任务的帖子。"""
    task = db.query(FbGroupPullTask).filter(FbGroupPullTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not is_admin(user) and task.created_by_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问")

    q = db.query(FbGroupPost).filter(FbGroupPost.task_id == task_id)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(
            (FbGroupPost.text.like(like)) | (FbGroupPost.user_name.like(like))
        )
    total = q.count()
    items = (
        q.order_by(FbGroupPost.post_time.desc(), FbGroupPost.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return FbGroupPostPage(
        total=total,
        page=page,
        page_size=page_size,
        items=[FbGroupPostOut.model_validate(p) for p in items],
    )


@router.get("/{record_id}/posts", response_model=FbGroupPostPage)
def list_config_posts(
    record_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """分页查询某群组配置的所有帖子（跨任务）。"""
    row = _get_or_404(db, user, record_id, include_deleted=True)
    q = db.query(FbGroupPost).filter(FbGroupPost.config_id == row.id)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(
            (FbGroupPost.text.like(like)) | (FbGroupPost.user_name.like(like))
        )
    total = q.count()
    items = (
        q.order_by(FbGroupPost.post_time.desc(), FbGroupPost.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return FbGroupPostPage(
        total=total,
        page=page,
        page_size=page_size,
        items=[FbGroupPostOut.model_validate(p) for p in items],
    )


@router.post("/{record_id}/restore", response_model=FbGroupScrapeOut)
def restore_fb_group_scrape(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """恢复软删除记录（管理员或创建人）。"""
    row = _get_or_404(db, user, record_id, include_deleted=True)
    if row.deleted_at is None:
        return _to_out(row)
    row.deleted_at = None
    db.commit()
    row = (
        db.query(FbGroupScrapeConfig)
        .options(joinedload(FbGroupScrapeConfig.creator))
        .filter(FbGroupScrapeConfig.id == row.id)
        .one()
    )
    return _to_out(row)
