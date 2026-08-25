"""路由级权限校验：按请求路径反查所需菜单，校验当前用户是否拥有该菜单。

只挂在 ``api_router`` 上一处即可，无需给每个接口单独加依赖；
菜单与 API 前缀的对应关系存在 ``menus.api_prefixes``，在「路由列表」页面可直接维护。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from starlette.requests import HTTPConnection

from app.core.deps import get_db
from app.core.security import decode_token
from app.models.rbac import ApiEnforceMode, Menu
from app.models.user import User
from app.services import rbac_service

#: 不做菜单校验的路径前缀（登录/刷新/我的菜单等基础接口）
EXEMPT_PREFIXES: tuple[str, ...] = (
    "/api/v1/auth",
    "/api/v1/system/profile",
    "/api/v1/dm/media",
)

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

MENU_CACHE_TTL_SEC = 30.0


@dataclass
class _MenuRule:
    code: str
    title: str
    prefixes: list[str]
    write_only: bool


_rules_cache: list[_MenuRule] | None = None
_rules_cached_at: float = 0.0


def invalidate_menu_cache() -> None:
    """菜单/角色发生变更时调用，下一次请求重新加载规则。"""
    global _rules_cache
    _rules_cache = None


def _load_rules(db: Session) -> list[_MenuRule]:
    global _rules_cache, _rules_cached_at
    now = time.monotonic()
    if _rules_cache is not None and now - _rules_cached_at < MENU_CACHE_TTL_SEC:
        return _rules_cache
    rules: list[_MenuRule] = []
    for menu in db.query(Menu).filter(Menu.is_active.is_(True)).all():
        if menu.api_enforce_mode == ApiEnforceMode.off or not menu.api_prefixes:
            continue
        prefixes = [p for p in menu.api_prefixes if p]
        if not prefixes:
            continue
        rules.append(
            _MenuRule(
                code=menu.code,
                title=menu.title,
                prefixes=prefixes,
                write_only=menu.api_enforce_mode == ApiEnforceMode.write,
            )
        )
    _rules_cache = rules
    _rules_cached_at = now
    return rules


def _matched_rules(db: Session, path: str, method: str) -> list[_MenuRule]:
    """找出「声明了该路径前缀」且需要在后端校验的菜单规则。"""
    matched: list[_MenuRule] = []
    for rule in _load_rules(db):
        if rule.write_only and method not in WRITE_METHODS:
            continue
        for prefix in rule.prefixes:
            if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
                matched.append(rule)
                break
    return matched


def _bearer_token(conn: HTTPConnection) -> str | None:
    auth = conn.headers.get("authorization") or ""
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def enforce_route_permission(
    conn: HTTPConnection,
    db: Session = Depends(get_db),
) -> None:
    """校验当前用户对本次请求路径是否有菜单权限。

    未带 token 时直接放过，交由各接口自己的 ``get_current_user`` 返回 401；
    WebSocket 连接（比特浏览器中继）自带 token 鉴权，不走菜单校验。
    """
    if conn.scope.get("type") != "http":
        return
    path = conn.url.path
    if any(path.startswith(p) for p in EXEMPT_PREFIXES):
        return
    token = _bearer_token(conn)
    if not token:
        return
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return
    user_id = payload.get("sub")
    if user_id is None:
        return
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.is_active:
        return
    if rbac_service.is_super_admin(user):
        return

    rules = _matched_rules(db, path, str(conn.scope.get("method", "GET")).upper())
    if not rules:
        return
    allowed = rbac_service.user_menu_codes(db, user)
    # 命中多个菜单时，只要有一个有权限即可（例如同一前缀被多个页面共用）
    if any(r.code in allowed for r in rules):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="没有该功能的访问权限（{}）".format("/".join(r.title for r in rules)),
    )
