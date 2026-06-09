"""邮箱账号管理 CRUD 与 Apify Key 登记。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.security import decrypt_secret, encrypt_secret
from app.models.apify_key import ApifyKey
from app.models.email_account import EmailAccount
from app.models.user import User
from app.schemas.apify_key import ApifyKeyOut
from app.schemas.email_account import EmailAccountCreate, EmailAccountOut, EmailAccountUpdate

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
        apify_full_name=row.apify_full_name,
        apify_username=row.apify_username,
        apify_user_id=row.apify_user_id,
        apify_token=decrypt_secret(row.apify_token),
        apify_registered_at=row.apify_registered_at,
        last_verification_code=row.last_verification_code,
        last_verification_at=row.last_verification_at,
        note=row.note,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[EmailAccountOut])
def list_email_accounts(
    q: str | None = Query(None, description="按注册邮箱/验证邮箱/Apify 用户名搜索"),
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
            | EmailAccount.apify_username.like(like)
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
        apify_full_name=_clean_text(body.apify_full_name),
        apify_username=_clean_text(body.apify_username),
        apify_user_id=_clean_text(body.apify_user_id),
        apify_token=encrypt_secret(_clean_text(body.apify_token)),
        apify_registered_at=body.apify_registered_at,
        last_verification_code=_clean_text(body.last_verification_code),
        last_verification_at=body.last_verification_at,
        note=_clean_text(body.note),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


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
    if "apify_full_name" in data:
        row.apify_full_name = _clean_text(body.apify_full_name)
    if "apify_username" in data:
        row.apify_username = _clean_text(body.apify_username)
    if "apify_user_id" in data:
        row.apify_user_id = _clean_text(body.apify_user_id)
    if "apify_token" in data:
        row.apify_token = encrypt_secret(_clean_text(body.apify_token))
    if "apify_registered_at" in data:
        row.apify_registered_at = body.apify_registered_at
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


@router.post("/{account_id}/register-apify-key", response_model=ApifyKeyOut)
def register_apify_key(
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
    token = _clean_text(decrypt_secret(row.apify_token))
    if not token:
        raise HTTPException(status_code=400, detail="请先填写 Apify API Token")
    registered_at = row.apify_registered_at or datetime.utcnow()
    label = row.apify_username or row.email
    remark_parts = [f"邮箱管理: {row.email}", f"注册时间: {registered_at:%Y-%m-%d %H:%M:%S}"]
    if row.apify_user_id:
        remark_parts.append(f"Apify User ID: {row.apify_user_id}")
    apify_key = db.query(ApifyKey).filter(ApifyKey.token == token).first()
    if apify_key:
        apify_key.label = label
        apify_key.remark = "；".join(remark_parts)
        apify_key.email_account_id = row.id
    else:
        apify_key = ApifyKey(
            label=label,
            token=token,
            is_default=False,
            remark="；".join(remark_parts),
            email_account_id=row.id,
        )
        db.add(apify_key)
    row.apify_registered_at = registered_at
    row.status = "apify_registered"
    db.commit()
    db.refresh(apify_key)
    return apify_key
