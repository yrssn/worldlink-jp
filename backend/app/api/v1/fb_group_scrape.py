"""Facebook 群组维度抓取配置 CRUD（软删除）。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_current_user, get_db, is_admin
from app.models.fb_group_scrape import FbGroupScrapeConfig
from app.models.user import User
from app.schemas.fb_group_scrape import (
    FbGroupPullBody,
    FbGroupPullOut,
    FbGroupScrapeCreate,
    FbGroupScrapeOut,
    FbGroupScrapeUpdate,
)
from app.services import apify_service

router = APIRouter(prefix="/scraper/fb-group-scrapes", tags=["scraper-fb-group"])


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


@router.post("/{record_id}/pull", response_model=FbGroupPullOut)
def pull_fb_group_posts(
    record_id: int,
    body: FbGroupPullBody | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """调用 Apify ``facebook-groups-scraper`` 拉取该群组帖子（测试用，结果暂不入库）。"""
    row = _get_or_404(db, user, record_id)
    if row.deleted_at is not None:
        raise HTTPException(status_code=400, detail="已删除的记录不可拉取")
    opts = body or FbGroupPullBody()
    group_url = _normalize_group_url(row.connection)
    try:
        result = apify_service.run_fb_groups(
            group_url,
            results_limit=opts.results_limit,
            view_option=opts.view_option,
            search_group_keyword=opts.search_group_keyword,
            search_group_year=opts.search_group_year,
            only_posts_newer_than=opts.only_posts_newer_than,
            timeout_secs=900,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    items = result.get("items") or []
    if not isinstance(items, list):
        items = []
    safe_items = [x for x in items if isinstance(x, dict)]

    input_used = {
        "startUrls": [{"url": group_url}],
        "resultsLimit": opts.results_limit,
        "viewOption": opts.view_option,
    }
    if opts.search_group_keyword:
        input_used["searchGroupKeyword"] = opts.search_group_keyword
    if opts.search_group_year:
        input_used["searchGroupYear"] = opts.search_group_year
    if opts.only_posts_newer_than:
        input_used["onlyPostsNewerThan"] = opts.only_posts_newer_than

    return FbGroupPullOut(
        config_id=row.id,
        group_url=group_url,
        apify_run_id=result.get("run_id"),
        apify_dataset_id=result.get("dataset_id"),
        input_used=input_used,
        count=len(safe_items),
        field_keys=_collect_field_keys(safe_items),
        items=safe_items,
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
