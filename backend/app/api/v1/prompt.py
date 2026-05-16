from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, is_admin
from app.models.prompt import PromptTemplate
from app.models.user import User
from app.schemas.common import Msg
from app.schemas.prompt import (
    PromptTemplateCreate,
    PromptTemplateOut,
    PromptTemplateUpdate,
)

router = APIRouter(prefix="/llm/prompts", tags=["prompt"])


@router.get("", response_model=list[PromptTemplateOut])
def list_prompts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(PromptTemplate)
    if not is_admin(user):
        q = q.filter(PromptTemplate.owner_id == user.id)
    return q.order_by(PromptTemplate.id.desc()).all()


@router.post("", response_model=PromptTemplateOut, status_code=status.HTTP_201_CREATED)
def create_prompt(
    payload: PromptTemplateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    p = PromptTemplate(**payload.model_dump(), owner_id=user.id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.put("/{pid}", response_model=PromptTemplateOut)
def update_prompt(
    pid: int,
    payload: PromptTemplateUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    p = db.get(PromptTemplate, pid)
    if not p or (p.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="prompt not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/{pid}", response_model=Msg)
def delete_prompt(
    pid: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    p = db.get(PromptTemplate, pid)
    if not p or (p.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="prompt not found")
    db.delete(p)
    db.commit()
    return Msg()
