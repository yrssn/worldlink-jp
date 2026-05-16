from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, is_admin
from app.core.security import encrypt_secret
from app.models.llm import LlmProvider
from app.models.user import User
from app.schemas.common import Msg
from app.schemas.llm import (
    LlmProviderCreate,
    LlmProviderOut,
    LlmProviderUpdate,
    LlmTestRequest,
    LlmTestResponse,
)
from app.services import llm_service

router = APIRouter(prefix="/llm/providers", tags=["llm"])


def _to_out(p: LlmProvider) -> LlmProviderOut:
    data = LlmProviderOut.model_validate(p)
    data.has_api_key = bool(p.api_key)
    return data


@router.get("", response_model=list[LlmProviderOut])
def list_providers(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(LlmProvider)
    if not is_admin(user):
        q = q.filter(LlmProvider.owner_id == user.id)
    return [_to_out(p) for p in q.order_by(LlmProvider.id.desc()).all()]


@router.post("", response_model=LlmProviderOut, status_code=status.HTTP_201_CREATED)
def create_provider(
    payload: LlmProviderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    p = LlmProvider(
        **payload.model_dump(exclude={"api_key"}),
        api_key=encrypt_secret(payload.api_key),
        owner_id=user.id,
    )
    if p.is_default:
        db.query(LlmProvider).filter(
            LlmProvider.owner_id == user.id, LlmProvider.is_default.is_(True)
        ).update({"is_default": False})
    db.add(p)
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.put("/{pid}", response_model=LlmProviderOut)
def update_provider(
    pid: int,
    payload: LlmProviderUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    p = db.get(LlmProvider, pid)
    if not p or (p.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="provider not found")
    data = payload.model_dump(exclude_unset=True)
    if "api_key" in data:
        data["api_key"] = encrypt_secret(data["api_key"])
    if data.get("is_default"):
        db.query(LlmProvider).filter(
            LlmProvider.owner_id == p.owner_id,
            LlmProvider.is_default.is_(True),
            LlmProvider.id != p.id,
        ).update({"is_default": False})
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.delete("/{pid}", response_model=Msg)
def delete_provider(
    pid: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    p = db.get(LlmProvider, pid)
    if not p or (p.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="provider not found")
    db.delete(p)
    db.commit()
    return Msg()


@router.post("/{pid}/test", response_model=LlmTestResponse)
def test_provider(
    pid: int,
    payload: LlmTestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    p = db.get(LlmProvider, pid)
    if not p or (p.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="provider not found")
    ok, output, err = llm_service.test_provider(p, payload.prompt)
    return LlmTestResponse(ok=ok, output=output, error=err)
