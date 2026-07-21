"""私信内容：分类、模板、图片上传。"""
from __future__ import annotations

import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.models.dm import DmCategory, DmContent
from app.models.user import User
from app.schemas.dm import (
    DmCategoryCreate,
    DmCategoryOut,
    DmCategoryUpdate,
    DmContentCreate,
    DmContentOut,
    DmContentUpdate,
    DmImageItem,
    DmOutreachOut,
    DmOutreachStart,
    DmUploadOut,
)
from app.services.fb_dm_automation import open_fb_profile_and_message

router = APIRouter(prefix="/dm", tags=["dm"])

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
        db.query(DmCategory)
        .filter(DmCategory.id == category_id, DmCategory.owner_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="分类不存在")
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
    q = db.query(DmCategory).filter(DmCategory.owner_id == user.id)
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
    q = db.query(DmContent).filter(DmContent.owner_id == user.id)
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
    row = (
        db.query(DmContent)
        .options(joinedload(DmContent.category))
        .filter(DmContent.id == content_id, DmContent.owner_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="内容不存在")
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
    row = (
        db.query(DmContent)
        .filter(DmContent.id == content_id, DmContent.owner_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="内容不存在")
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
    row = (
        db.query(DmContent)
        .filter(DmContent.id == content_id, DmContent.owner_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="内容不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ----- 私信建联自动化 -----


@router.post("/outreach/start", response_model=DmOutreachOut)
def start_dm_outreach(
    body: DmOutreachStart,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """在指定 BitBrowser 窗口中打开达人主页并点击「发消息」（私信建联第一步）。"""
    content = (
        db.query(DmContent)
        .filter(DmContent.id == body.content_id, DmContent.owner_id == user.id)
        .first()
    )
    if not content:
        raise HTTPException(status_code=404, detail="私信内容不存在")
    try:
        result = open_fb_profile_and_message(
            body.browser_id.strip(),
            body.url,
            user,
            db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"连接 BitBrowser/CDP 失败: {e}") from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return DmOutreachOut(
        ok=True,
        browser_id=body.browser_id.strip(),
        content_id=content.id,
        content_title=content.title,
        page_opened=bool(result.get("page_opened")),
        message_clicked=bool(result.get("message_clicked")),
        matched_text=(str(result["matched_text"]) if result.get("matched_text") else None),
        final_url=(str(result["final_url"]) if result.get("final_url") else None),
        open_hint=result.get("open_hint"),
    )


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
