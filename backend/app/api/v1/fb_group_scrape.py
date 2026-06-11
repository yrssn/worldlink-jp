"""Facebook 群组维度抓取配置 CRUD（软删除）+ 后台拉取任务。"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
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
    FbGroupScheduleTask,
    FbGroupScheduleTaskStatus,
)
from app.models.influencer import Influencer, InfluencerSource, InfluencerStatus
from app.models.social_account import InfluencerSocialAccount, SocialPlatform
from app.models.user import User
from app.schemas.fb_group_scrape import (
    FbGroupBatchPullBody,
    FbGroupPostOut,
    FbGroupPostPage,
    FbGroupPreContactOut,
    FbGroupPullTaskCreate,
    FbGroupPullTaskOut,
    FbGroupScrapeCreate,
    FbGroupScrapeOut,
    FbGroupScrapeUpdate,
    FbGroupScheduleTaskCreate,
    FbGroupScheduleTaskOut,
    FbGroupScheduleTaskUpdate,
)
from app.services import apify_service, influencer_service
from app.services.fb_group_post_filter import (
    exclude_known_influencer_posts,
    should_filter_group_post_item,
)

router = APIRouter(prefix="/scraper/fb-group-scrapes", tags=["scraper-fb-group"])

# 单次拉取的默认/最大条数（不再支持"全部拉取"，防止 Apify 超时烧钱）。
DEFAULT_RESULTS_LIMIT = 20
MAX_RESULTS_LIMIT = 500


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


def _format_apify_since(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def _last_successful_pull_started_at(db: Session, config_id: int) -> datetime | None:
    task = (
        db.query(FbGroupPullTask)
        .filter(
            FbGroupPullTask.config_id == config_id,
            FbGroupPullTask.status == FbGroupPullTaskStatus.done,
            FbGroupPullTask.started_at.isnot(None),
        )
        .order_by(FbGroupPullTask.started_at.desc(), FbGroupPullTask.id.desc())
        .first()
    )
    if not task or not task.started_at:
        return None
    return task.started_at - timedelta(minutes=5)


def _build_pull_params(
    db: Session,
    config_id: int,
    *,
    results_limit: int | None,
    view_option: str,
    search_group_keyword: str | None,
    search_group_year: str | None,
    only_posts_newer_than: str | None,
) -> dict:
    since = (only_posts_newer_than or "").strip()
    auto_since = False
    if not since:
        last_started_at = _last_successful_pull_started_at(db, config_id)
        if last_started_at:
            since = _format_apify_since(last_started_at)
            auto_since = True
    params = {
        "results_limit": results_limit,
        "view_option": view_option,
        "search_group_keyword": search_group_keyword,
        "search_group_year": search_group_year,
        "only_posts_newer_than": since or None,
        "auto_only_posts_newer_than": auto_since,
    }
    return params


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

        # 始终限制抓取条数，禁止"全部拉取"（避免 Apify 超时烧钱）；
        # 兼容历史任务里 results_limit 为空/0 的情况，统一回退到 DEFAULT_RESULTS_LIMIT。
        results_limit = params.get("results_limit")
        try:
            results_limit = int(results_limit)
        except (TypeError, ValueError):
            results_limit = 0
        if results_limit <= 0:
            results_limit = DEFAULT_RESULTS_LIMIT
        results_limit = min(results_limit, MAX_RESULTS_LIMIT)

        try:
            result = apify_service.run_fb_groups(
                group_url,
                results_limit=results_limit,
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
        task.total_fetched = len(items)

        saved = 0
        duplicates = 0
        filtered = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            if should_filter_group_post_item(db, task.created_by_id, item):
                filtered += 1
                continue
            post = _item_to_post(item, task_id=task_id, config_id=task.config_id)
            if post is None:
                continue
            try:
                with db.begin_nested():   # SAVEPOINT：只回滚这一条，不影响其他帖子
                    db.add(post)
                saved += 1
            except IntegrityError:
                duplicates += 1  # 记录重复帖子

        task.result_count = saved
        task.duplicate_count = duplicates
        task.filtered_count = filtered
        task.status = FbGroupPullTaskStatus.done
        task.finished_at = datetime.utcnow()
        db.commit()
        logger.info(
            "[FbGroupPullTask#{}] done, saved {} posts, {} duplicates, {} filtered, {} total fetched",
            task_id, saved, duplicates, filtered, task.total_fetched
        )
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
        duplicate_count=task.duplicate_count,
        filtered_count=task.filtered_count,
        total_fetched=task.total_fetched,
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
    params = _build_pull_params(
        db,
        row.id,
        results_limit=opts.results_limit,
        view_option=opts.view_option,
        search_group_keyword=opts.search_group_keyword,
        search_group_year=opts.search_group_year,
        only_posts_newer_than=opts.only_posts_newer_than,
    )
    task = FbGroupPullTask(
        config_id=row.id,
        created_by_id=user.id,
        status=FbGroupPullTaskStatus.pending,
        params=params,
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


@router.post("/batch-pull", response_model=list[FbGroupPullTaskOut])
def batch_pull_fb_group_posts(
    body: FbGroupBatchPullBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """批量提交后台拉取任务（多个群组共享同一组参数）。"""
    if not body.config_ids:
        raise HTTPException(status_code=400, detail="config_ids 不能为空")

    configs = (
        db.query(FbGroupScrapeConfig)
        .options(joinedload(FbGroupScrapeConfig.creator))
        .filter(
            FbGroupScrapeConfig.id.in_(body.config_ids),
            FbGroupScrapeConfig.deleted_at.is_(None),
        )
        .all()
    )
    if not is_admin(user):
        configs = [c for c in configs if c.created_by_id == user.id]

    found_ids = {c.id for c in configs}
    missing = [i for i in body.config_ids if i not in found_ids]
    if missing:
        raise HTTPException(status_code=404, detail=f"以下配置不存在或已删除: {missing}")

    created_tasks: list[FbGroupPullTask] = []
    for config in configs:
        params = _build_pull_params(
            db,
            config.id,
            results_limit=body.results_limit,
            view_option=body.view_option,
            search_group_keyword=body.search_group_keyword,
            search_group_year=body.search_group_year,
            only_posts_newer_than=body.only_posts_newer_than,
        )
        task = FbGroupPullTask(
            config_id=config.id,
            created_by_id=user.id,
            status=FbGroupPullTaskStatus.pending,
            params=params,
        )
        db.add(task)
        db.flush()
        created_tasks.append(task)
    db.commit()

    result_tasks = (
        db.query(FbGroupPullTask)
        .options(
            joinedload(FbGroupPullTask.config),
            joinedload(FbGroupPullTask.creator),
        )
        .filter(FbGroupPullTask.id.in_([t.id for t in created_tasks]))
        .all()
    )

    for task in result_tasks:
        t = threading.Thread(target=_run_pull_task_bg, args=(task.id,), daemon=True)
        t.start()
    logger.info(
        "[FbGroupBatchPull] {} tasks started by user#{}", len(result_tasks), user.id
    )

    id_order = {t.id: i for i, t in enumerate(created_tasks)}
    result_tasks.sort(key=lambda t: id_order.get(t.id, 999))
    return [_to_task_out(t) for t in result_tasks]


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


@router.post("/tasks/{task_id}/fail", response_model=FbGroupPullTaskOut)
def fail_pull_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """手动将卡住的 pending/running 任务标记为失败。"""
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
        raise HTTPException(status_code=403, detail="无权操作")
    if task.status not in (FbGroupPullTaskStatus.pending, FbGroupPullTaskStatus.running):
        raise HTTPException(status_code=400, detail=f"任务当前状态为 {task.status}，无需标记失败")
    task.status = FbGroupPullTaskStatus.failed
    task.error = "手动标记为失败"
    task.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
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
    q = exclude_known_influencer_posts(q, db, task.created_by_id)
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


@router.post("/posts/{post_id}/pre-contact", response_model=FbGroupPreContactOut)
def pre_contact_from_group_post(
    post_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """把 Facebook 群组帖子作者加入建联达人，按 user 去重。"""
    post = db.get(FbGroupPost, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")
    task = db.get(FbGroupPullTask, post.task_id)
    if not task or (task.created_by_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=403, detail="无权操作")

    raw = post.raw_data or {}
    user_obj = raw.get("user") if isinstance(raw.get("user"), dict) else {}
    display_name = (post.user_name or user_obj.get("name") or "").strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="帖子缺少 user.name，无法预建联")

    platform = influencer_service.get_or_create_facebook_platform(db, user.id)
    profile_url = (
        user_obj.get("profileUrl")
        or user_obj.get("url")
        or user_obj.get("profile_url")
    )

    # 调用 Apify facebook-pages-scraper 抓取该用户主页的完整资料（关注数/邮箱/电话/分类等）。
    page_profile: dict | None = None
    scrape_error: str | None = None
    if profile_url:
        try:
            result = apify_service.run_fb_pages([profile_url], max_items=1, db=db)
            items = result.get("items") or []
            page_profile = next((it for it in items if isinstance(it, dict)), None)
        except Exception as e:  # noqa: BLE001
            scrape_error = str(e)
            logger.warning(
                "[FbGroupPreContact] facebook-pages-scraper 失败 url={} err={}",
                profile_url, e,
            )

    mapped = influencer_service.map_page_profile(page_profile) if page_profile else {}

    existing = influencer_service.find_duplicate_for_platform_user(
        db,
        owner_id=user.id,
        platform_id=platform.id,
        fb_page_id=mapped.get("fb_page_id") or post.user_id,
        fb_page_url=mapped.get("fb_page_url") or profile_url,
        email=mapped.get("email"),
        display_name=mapped.get("display_name") or display_name,
    )
    if existing:
        return FbGroupPreContactOut(influencer=existing, created=False)

    notes = f"来自 Facebook 群组帖子：{post.post_url or post.legacy_id}"
    if scrape_error:
        notes += f"\n（主页抓取失败，仅保存帖子作者信息：{scrape_error[:200]}）"

    # 以 facebook-pages-scraper 映射结果为主，缺失字段回退到群组帖子里的 user 信息。
    data = {k: v for k, v in mapped.items() if v is not None and k != "raw_profile"}
    data["display_name"] = mapped.get("display_name") or display_name
    data.setdefault("fb_page_id", post.user_id)
    data.setdefault("fb_page_url", profile_url)
    data.setdefault("fb_page_title", display_name)
    data.update(
        status=InfluencerStatus.pre_contact,
        source=InfluencerSource.scrape,
        platform_id=platform.id,
        owner_id=user.id,
        notes=notes,
        raw_profile={
            "source": "facebook_group_post",
            "group_title": post.group_title,
            "post_id": post.id,
            "post_url": post.post_url,
            "post_text": post.text,
            "user": user_obj,
            "page_profile": page_profile,
            "post": raw,
        },
    )
    influencer = Influencer(**data)
    db.add(influencer)
    db.flush()
    if influencer.fb_page_id or influencer.fb_page_url:
        db.add(
            InfluencerSocialAccount(
                influencer_id=influencer.id,
                platform=SocialPlatform.facebook,
                handle=influencer.fb_page_id,
                url=influencer.fb_page_url,
                followers=influencer.fb_followers,
            )
        )
    db.commit()
    db.refresh(influencer)
    return FbGroupPreContactOut(influencer=influencer, created=True)


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
    q = exclude_known_influencer_posts(q, db, row.created_by_id)
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


# ─── 定时拉取任务 ───────────────────────────────────────────────────

def _to_schedule_out(task: FbGroupScheduleTask) -> FbGroupScheduleTaskOut:
    return FbGroupScheduleTaskOut(
        id=task.id,
        config_id=task.config_id,
        config_title=task.config.title if task.config else None,
        created_by_id=task.created_by_id,
        created_by_username=task.creator.username if task.creator else None,
        status=task.status.value,
        schedule_type=task.schedule_type,
        schedule_config=task.schedule_config,
        pull_params=task.pull_params,
        last_run_at=task.last_run_at,
        next_run_at=task.next_run_at,
        last_task_id=task.last_task_id,
        consecutive_failures=task.consecutive_failures,
        max_consecutive_failures=task.max_consecutive_failures,
        remark=task.remark,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.post("/{record_id}/schedules", response_model=FbGroupScheduleTaskOut)
def create_schedule_task(
    record_id: int,
    body: FbGroupScheduleTaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """为某群组配置创建定时拉取任务。"""
    row = _get_or_404(db, user, record_id)
    if row.deleted_at is not None:
        raise HTTPException(status_code=400, detail="已删除的记录不可创建定时任务")

    task = FbGroupScheduleTask(
        config_id=row.id,
        created_by_id=user.id,
        status=FbGroupScheduleTaskStatus.active,
        schedule_type=body.schedule_type,
        schedule_config=body.schedule_config,
        pull_params=body.pull_params,
        max_consecutive_failures=body.max_consecutive_failures,
        remark=body.remark,
    )
    db.add(task)
    db.commit()
    task = (
        db.query(FbGroupScheduleTask)
        .options(
            joinedload(FbGroupScheduleTask.config),
            joinedload(FbGroupScheduleTask.creator),
        )
        .filter(FbGroupScheduleTask.id == task.id)
        .one()
    )

    # 注册到调度器
    from app.services.fb_group_scheduler import fb_group_scheduler
    fb_group_scheduler.add_schedule(task)

    logger.info("[FbGroupSchedule] Created schedule#{} for config#{}", task.id, record_id)
    return _to_schedule_out(task)


@router.get("/{record_id}/schedules", response_model=list[FbGroupScheduleTaskOut])
def list_schedule_tasks(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出某群组配置的所有定时任务。"""
    row = _get_or_404(db, user, record_id, include_deleted=True)
    q = (
        db.query(FbGroupScheduleTask)
        .options(
            joinedload(FbGroupScheduleTask.config),
            joinedload(FbGroupScheduleTask.creator),
        )
        .filter(FbGroupScheduleTask.config_id == row.id)
    )
    if not is_admin(user):
        q = q.filter(FbGroupScheduleTask.created_by_id == user.id)
    tasks = q.order_by(FbGroupScheduleTask.id.desc()).all()
    return [_to_schedule_out(t) for t in tasks]


@router.put("/schedules/{schedule_id}", response_model=FbGroupScheduleTaskOut)
def update_schedule_task(
    schedule_id: int,
    body: FbGroupScheduleTaskUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新定时任务。"""
    task = (
        db.query(FbGroupScheduleTask)
        .options(
            joinedload(FbGroupScheduleTask.config),
            joinedload(FbGroupScheduleTask.creator),
        )
        .filter(FbGroupScheduleTask.id == schedule_id)
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    if not is_admin(user) and task.created_by_id != user.id:
        raise HTTPException(status_code=403, detail="无权修改")

    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(task, k, v)
    db.commit()
    db.refresh(task)

    # 更新调度器
    from app.services.fb_group_scheduler import fb_group_scheduler
    fb_group_scheduler.update_schedule(task)

    logger.info("[FbGroupSchedule] Updated schedule#{}", schedule_id)
    return _to_schedule_out(task)


@router.delete("/schedules/{schedule_id}")
def delete_schedule_task(
    schedule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除定时任务。"""
    task = db.query(FbGroupScheduleTask).filter(FbGroupScheduleTask.id == schedule_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    if not is_admin(user) and task.created_by_id != user.id:
        raise HTTPException(status_code=403, detail="无权删除")

    db.delete(task)
    db.commit()

    # 从调度器移除
    from app.services.fb_group_scheduler import fb_group_scheduler
    fb_group_scheduler.remove_schedule(schedule_id)

    logger.info("[FbGroupSchedule] Deleted schedule#{}", schedule_id)
    return {"ok": True}


@router.post("/schedules/{schedule_id}/execute", response_model=FbGroupPullTaskOut)
def execute_schedule_now(
    schedule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """立即执行定时任务（创建一个拉取任务）。"""
    schedule = db.query(FbGroupScheduleTask).filter(FbGroupScheduleTask.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    if not is_admin(user) and schedule.created_by_id != user.id:
        raise HTTPException(status_code=403, detail="无权执行")

    raw_pull_params = dict(schedule.pull_params or {})
    pull_params = _build_pull_params(
        db,
        schedule.config_id,
        results_limit=raw_pull_params.get("results_limit"),
        view_option=raw_pull_params.get("view_option") or "CHRONOLOGICAL",
        search_group_keyword=raw_pull_params.get("search_group_keyword"),
        search_group_year=raw_pull_params.get("search_group_year"),
        only_posts_newer_than=raw_pull_params.get("only_posts_newer_than"),
    )

    # 创建拉取任务
    task = FbGroupPullTask(
        config_id=schedule.config_id,
        created_by_id=user.id,
        status=FbGroupPullTaskStatus.pending,
        params=pull_params,
    )
    db.add(task)
    db.flush()
    task_id = task.id

    schedule.last_run_at = datetime.utcnow()
    schedule.last_task_id = task_id
    db.commit()

    # 后台执行拉取
    import threading
    t = threading.Thread(target=_run_pull_task_bg, args=(task_id,), daemon=True)
    t.start()

    task = (
        db.query(FbGroupPullTask)
        .options(
            joinedload(FbGroupPullTask.config),
            joinedload(FbGroupPullTask.creator),
        )
        .filter(FbGroupPullTask.id == task_id)
        .one()
    )

    logger.info("[FbGroupSchedule] Manually executed schedule#{}, created task#{}", schedule_id, task_id)
    return _to_task_out(task)
