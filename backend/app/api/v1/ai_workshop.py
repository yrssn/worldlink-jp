"""AI 工坊：Agent 密钥管理 + 调用记录（Web 端，JWT + 菜单权限）。

密钥属主默认是创建人本人；超级管理员可以带 ``owner_id`` 代任意用户
创建/查看/启停/删除密钥（给其他设备/员工发放密钥时不用登录对方账号）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.ai_workshop import AiApiKey, AiApiCallLog
from app.models.user import User
from app.schemas.ai_workshop import (
    AiApiCallLogOut,
    AiApiCallLogPageOut,
    AiApiKeyCreate,
    AiApiKeyCreatedOut,
    AiApiKeyOut,
    AiApiKeyUpdate,
)
from app.services import ai_workshop, rbac_service

router = APIRouter(prefix="/ai", tags=["ai-workshop"])


def _key_or_404(db: Session, user: User, key_id: int) -> AiApiKey:
    """自己的密钥直接操作；超级管理员可操作任意人的密钥。"""
    row = db.get(AiApiKey, key_id)
    if row is None:
        raise HTTPException(status_code=404, detail="密钥不存在")
    if row.owner_id != user.id and not rbac_service.is_super_admin(user):
        raise HTTPException(status_code=404, detail="密钥不存在")
    return row


def _target_owner_or_403(db: Session, user: User, owner_id: int | None) -> int:
    """解析密钥属主：默认自己；仅超级管理员可指定他人。"""
    if owner_id is None or owner_id == user.id:
        return user.id
    if not rbac_service.is_super_admin(user):
        raise HTTPException(status_code=403, detail="只有超级管理员可以替他人管理密钥")
    target = db.get(User, int(owner_id))
    if target is None:
        raise HTTPException(status_code=400, detail="目标用户不存在")
    return target.id


@router.get("/keys", response_model=list[AiApiKeyOut])
def list_keys(
    owner_id: int | None = Query(None, description="超级管理员可传，查看指定用户的密钥"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if owner_id is not None and owner_id != user.id:
        if not rbac_service.is_super_admin(user):
            raise HTTPException(status_code=403, detail="只有超级管理员可以查看他人的密钥")
        return (
            db.query(AiApiKey)
            .filter(AiApiKey.owner_id == int(owner_id))
            .order_by(AiApiKey.id.desc())
            .all()
        )
    return (
        db.query(AiApiKey)
        .filter(AiApiKey.owner_id == user.id)
        .order_by(AiApiKey.id.desc())
        .all()
    )


@router.post("/keys", response_model=AiApiKeyCreatedOut, status_code=201)
def create_key(
    body: AiApiKeyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    owner_id = _target_owner_or_403(db, user, body.owner_id)
    raw, prefix, key_hash = ai_workshop.generate_api_key()
    row = AiApiKey(
        owner_id=owner_id,
        name=body.name.strip()[:64],
        key_prefix=prefix,
        key_hash=key_hash,
        expires_at=body.expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    out = AiApiKeyOut.model_validate(row)
    return AiApiKeyCreatedOut(**out.model_dump(), key=raw)


@router.put("/keys/{key_id}", response_model=AiApiKeyOut)
def update_key(
    key_id: int,
    body: AiApiKeyUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _key_or_404(db, user, key_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        row.name = str(data["name"]).strip()[:64]
    if "is_active" in data and data["is_active"] is not None:
        row.is_active = bool(data["is_active"])
    if "expires_at" in data:
        row.expires_at = data["expires_at"]
    db.commit()
    db.refresh(row)
    return row


@router.delete("/keys/{key_id}")
def delete_key(
    key_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _key_or_404(db, user, key_id)
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/logs", response_model=AiApiCallLogPageOut)
def list_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    key_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(AiApiCallLog).filter(AiApiCallLog.owner_id == user.id)
    if key_id is not None:
        query = query.filter(AiApiCallLog.key_id == key_id)
    total = query.count()
    rows = (
        query.order_by(AiApiCallLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    key_ids = {row.key_id for row in rows if row.key_id}
    key_names: dict[int, str] = {}
    if key_ids:
        for row in db.query(AiApiKey).filter(AiApiKey.id.in_(key_ids)).all():
            key_names[row.id] = row.name
    items = [
        AiApiCallLogOut(
            id=row.id,
            key_id=row.key_id,
            key_name=key_names.get(row.key_id) if row.key_id else None,
            action=row.action,
            status=row.status,
            error=row.error,
            detail=row.detail,
            created_at=row.created_at,
        )
        for row in rows
    ]
    return AiApiCallLogPageOut(total=total, page=page, page_size=page_size, items=items)
