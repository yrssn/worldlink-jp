"""Apify Key 动态配置 CRUD。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.apify_key import ApifyKey
from app.models.email_account import EmailAccount
from app.models.user import User
from app.schemas.apify_key import ApifyKeyCreate, ApifyKeyOut, ApifyKeyUpdate

router = APIRouter(prefix="/scraper/apify-keys", tags=["scraper-apify-keys"])


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _validate_email_account(
    email_account_id: int | None,
    db: Session,
    user: User,
) -> int | None:
    if email_account_id is None:
        return None
    row = (
        db.query(EmailAccount)
        .filter(EmailAccount.id == email_account_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=400, detail="关联邮箱账号不存在")
    return row.id


@router.get("", response_model=list[ApifyKeyOut])
def list_keys(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return db.query(ApifyKey).order_by(ApifyKey.id.asc()).all()


@router.post("", response_model=ApifyKeyOut)
def create_key(
    body: ApifyKeyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if body.is_default:
        db.query(ApifyKey).filter(ApifyKey.is_default.is_(True)).update({"is_default": False})
    row = ApifyKey(
        label=body.label.strip(),
        token=body.token.strip(),
        is_default=body.is_default,
        remark=_clean_text(body.remark),
        email_account_id=_validate_email_account(body.email_account_id, db, user),
        apify_full_name=_clean_text(body.apify_full_name),
        apify_username=_clean_text(body.apify_username),
        apify_user_id=_clean_text(body.apify_user_id),
        apify_registered_at=body.apify_registered_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/{key_id}", response_model=ApifyKeyOut)
def update_key(
    key_id: int,
    body: ApifyKeyUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.get(ApifyKey, key_id)
    if not row:
        raise HTTPException(status_code=404, detail="Key 不存在")
    data = body.model_dump(exclude_unset=True)
    if "label" in data and data["label"] is not None:
        data["label"] = data["label"].strip()
    if "token" in data and data["token"] is not None:
        data["token"] = data["token"].strip()
    if "remark" in data:
        data["remark"] = _clean_text(data["remark"])
    if "email_account_id" in data:
        data["email_account_id"] = _validate_email_account(data["email_account_id"], db, user)
    if "label" in data and data["label"] is not None:
        row.label = data["label"]
    if "token" in data and data["token"] is not None:
        row.token = data["token"]
    if "remark" in data:
        row.remark = data["remark"]
    if "email_account_id" in data:
        row.email_account_id = data["email_account_id"]
    if "apify_full_name" in data:
        row.apify_full_name = _clean_text(data["apify_full_name"])
    if "apify_username" in data:
        row.apify_username = _clean_text(data["apify_username"])
    if "apify_user_id" in data:
        row.apify_user_id = _clean_text(data["apify_user_id"])
    if "apify_registered_at" in data:
        row.apify_registered_at = data["apify_registered_at"]
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{key_id}")
def delete_key(
    key_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = db.get(ApifyKey, key_id)
    if not row:
        raise HTTPException(status_code=404, detail="Key 不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/{key_id}/set-default", response_model=ApifyKeyOut)
def set_default_key(
    key_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = db.get(ApifyKey, key_id)
    if not row:
        raise HTTPException(status_code=404, detail="Key 不存在")
    db.query(ApifyKey).filter(ApifyKey.is_default.is_(True)).update({"is_default": False})
    row.is_default = True
    db.commit()
    db.refresh(row)
    return row


@router.post("/{key_id}/mark-exhausted", response_model=ApifyKeyOut)
def mark_exhausted(
    key_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = db.get(ApifyKey, key_id)
    if not row:
        raise HTTPException(status_code=404, detail="Key 不存在")
    row.exhausted_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


@router.post("/{key_id}/unmark-exhausted", response_model=ApifyKeyOut)
def unmark_exhausted(
    key_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = db.get(ApifyKey, key_id)
    if not row:
        raise HTTPException(status_code=404, detail="Key 不存在")
    row.exhausted_at = None
    db.commit()
    db.refresh(row)
    return row
