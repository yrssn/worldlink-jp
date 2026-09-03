"""FastAPI 依赖：数据库、当前用户、权限。"""
from __future__ import annotations

from typing import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import SessionLocal
from app.models.user import User
from app.services import rbac_service

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    db: Session = Depends(get_db),
    token: str | None = Depends(oauth2_scheme),
) -> User:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if not rbac_service.is_super_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin required"
        )
    return user


def is_admin(user: User) -> bool:
    """是否拥有「全部数据」可见范围（超级管理员或角色 data_scope=all）。

    历史代码用它来判断「能否看别人的数据」，语义与 RBAC 的数据范围一致，故沿用此名。
    """
    return rbac_service.has_full_data_scope(user)


def owner_filter(query, model, user: User, attr: str = "owner_id"):
    """按当前路由的数据范围过滤归属列（本人 / 指定用户 / 全部）。"""
    ids = rbac_service.visible_owner_ids(user)
    if ids is None:
        return query
    column = getattr(model, attr)
    if len(ids) == 1:
        return query.filter(column == user.id)
    return query.filter(column.in_(ids))


def can_view(obj, user: User, attr: str = "owner_id") -> bool:
    """单条记录在当前路由下是否可见。"""
    if obj is None:
        return False
    ids = rbac_service.visible_owner_ids(user)
    return ids is None or getattr(obj, attr) in ids


def scope_query(query, model, user: User):
    """按数据归属过滤查询：共享表 / 全量范围不过滤，其余按当前路由数据范围过滤。"""
    if rbac_service.is_shared_table(model.__tablename__):
        return query
    return owner_filter(query, model, user)


def can_access(obj, user: User) -> bool:
    """单条记录可见性判断（共享表所有人可见）。"""
    if obj is None:
        return False
    if rbac_service.is_shared_table(type(obj).__tablename__):
        return True
    return can_view(obj, user)
