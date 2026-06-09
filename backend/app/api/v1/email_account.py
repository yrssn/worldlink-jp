"""邮箱账号管理 CRUD。"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.security import decrypt_secret, encrypt_secret
from app.models.apify_key import ApifyKey
from app.models.email_account import EmailAccount
from app.models.user import User
from app.schemas.email_account import (
    ApifySignupStartOut,
    EmailAccountCreate,
    EmailAccountOut,
    EmailAccountUpdate,
)
from app.services.apify_signup_automation import start_apify_signup

router = APIRouter(prefix="/email/accounts", tags=["email-accounts"])


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _clean_required(value: str) -> str:
    return value.strip()


def _clean_email(value: str | None) -> str | None:
    text = _clean_text(value)
    return text.lower() if text else None


def _to_out(row: EmailAccount) -> EmailAccountOut:
    return EmailAccountOut(
        id=row.id,
        owner_id=row.owner_id,
        email=row.email,
        email_password=decrypt_secret(row.email_password),
        provider=row.provider,
        mail_login_url=row.mail_login_url,
        verification_email=row.verification_email,
        verification_password=decrypt_secret(row.verification_password),
        verification_login_url=row.verification_login_url,
        purpose=row.purpose,
        status=row.status,
        browser_id=row.browser_id,
        last_verification_code=row.last_verification_code,
        last_verification_at=row.last_verification_at,
        note=row.note,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[EmailAccountOut])
def list_email_accounts(
    q: str | None = Query(None, description="按注册邮箱/验证邮箱搜索"),
    purpose: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(EmailAccount).filter(EmailAccount.owner_id == user.id)
    keyword = _clean_text(q)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            EmailAccount.email.like(like)
            | EmailAccount.verification_email.like(like)
        )
    purpose_clean = _clean_text(purpose)
    if purpose_clean:
        query = query.filter(EmailAccount.purpose == purpose_clean)
    status_clean = _clean_text(status)
    if status_clean:
        query = query.filter(EmailAccount.status == status_clean)
    rows = query.order_by(EmailAccount.created_at.desc(), EmailAccount.id.desc()).all()
    return [_to_out(row) for row in rows]


@router.post("", response_model=EmailAccountOut)
def create_email_account(
    body: EmailAccountCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    email = _clean_email(body.email)
    if not email:
        raise HTTPException(status_code=400, detail="请填写注册邮箱")
    exists = (
        db.query(EmailAccount)
        .filter(EmailAccount.owner_id == user.id, EmailAccount.email == email)
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="该邮箱已存在")
    row = EmailAccount(
        owner_id=user.id,
        email=email,
        email_password=encrypt_secret(_clean_text(body.email_password)),
        provider=_clean_text(body.provider),
        mail_login_url=_clean_text(body.mail_login_url),
        verification_email=_clean_email(body.verification_email),
        verification_password=encrypt_secret(_clean_text(body.verification_password)),
        verification_login_url=_clean_text(body.verification_login_url),
        purpose=_clean_required(body.purpose),
        status=_clean_required(body.status),
        browser_id=_clean_text(body.browser_id),
        last_verification_code=_clean_text(body.last_verification_code),
        last_verification_at=body.last_verification_at,
        note=_clean_text(body.note),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.post("/{account_id}/apify-signup/start", response_model=ApifySignupStartOut)
def start_email_apify_signup(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = (
        db.query(EmailAccount)
        .filter(EmailAccount.id == account_id, EmailAccount.owner_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="邮箱账号不存在")
    if not row.browser_id:
        raise HTTPException(status_code=400, detail="请先为该邮箱选择指纹浏览器")
    linked = db.query(ApifyKey).filter(ApifyKey.email_account_id == row.id).first()
    if linked:
        raise HTTPException(status_code=400, detail="该邮箱已关联 Apify Key，无需重复注册")
    try:
        return start_apify_signup(row.browser_id, user, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"连接 BitBrowser/CDP 失败: {e}") from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.put("/{account_id}", response_model=EmailAccountOut)
def update_email_account(
    account_id: int,
    body: EmailAccountUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = (
        db.query(EmailAccount)
        .filter(EmailAccount.id == account_id, EmailAccount.owner_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="邮箱账号不存在")
    data = body.model_dump(exclude_unset=True)
    if "email" in data:
        email = _clean_email(body.email)
        if not email:
            raise HTTPException(status_code=400, detail="请填写注册邮箱")
        duplicate = (
            db.query(EmailAccount)
            .filter(
                EmailAccount.owner_id == user.id,
                EmailAccount.email == email,
                EmailAccount.id != row.id,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=400, detail="该邮箱已存在")
        row.email = email
    if "email_password" in data:
        row.email_password = encrypt_secret(_clean_text(body.email_password))
    if "provider" in data:
        row.provider = _clean_text(body.provider)
    if "mail_login_url" in data:
        row.mail_login_url = _clean_text(body.mail_login_url)
    if "verification_email" in data:
        row.verification_email = _clean_email(body.verification_email)
    if "verification_password" in data:
        row.verification_password = encrypt_secret(_clean_text(body.verification_password))
    if "verification_login_url" in data:
        row.verification_login_url = _clean_text(body.verification_login_url)
    if "purpose" in data and body.purpose is not None:
        row.purpose = _clean_required(body.purpose)
    if "status" in data and body.status is not None:
        row.status = _clean_required(body.status)
    if "browser_id" in data:
        row.browser_id = _clean_text(body.browser_id)
    if "last_verification_code" in data:
        row.last_verification_code = _clean_text(body.last_verification_code)
    if "last_verification_at" in data:
        row.last_verification_at = body.last_verification_at
    if "note" in data:
        row.note = _clean_text(body.note)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.delete("/{account_id}")
def delete_email_account(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = (
        db.query(EmailAccount)
        .filter(EmailAccount.id == account_id, EmailAccount.owner_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="邮箱账号不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}
