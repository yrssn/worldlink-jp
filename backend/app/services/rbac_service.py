"""RBAC 服务：种子数据初始化、权限解析。"""
from __future__ import annotations

from contextvars import ContextVar

from loguru import logger
from sqlalchemy.orm import Session

from app.core.rbac import (
    DEFAULT_USER_ROLE_CODE,
    MENU_SEEDS,
    ROLE_SEEDS,
    SHARED_TABLES,
    SUPER_ADMIN_ROLE_CODE,
    flatten_seeds,
)
from app.models.rbac import DataScope, Menu, Role
from app.models.user import User, UserRole


# --------------------------------------------------------------------------- #
# 种子数据
# --------------------------------------------------------------------------- #
def seed_menus(db: Session) -> dict[str, Menu]:
    """写入/补齐内置菜单（按 code 幂等）。已存在的菜单只补结构，不覆盖管理员改过的标题。"""
    existing = {m.code: m for m in db.query(Menu).all()}
    for seed, parent in flatten_seeds():
        parent_id = existing[parent.code].id if parent else None
        menu = existing.get(seed.code)
        if menu is None:
            menu = Menu(
                code=seed.code,
                title=seed.title,
                parent_id=parent_id,
                path=seed.path,
                icon=seed.icon,
                sort_order=len(existing) * 10,
                type=seed.type,
                is_hidden=seed.is_hidden,
                is_builtin=True,
                api_prefixes=seed.api_prefixes or None,
                api_enforce_mode=seed.api_enforce_mode,
            )
            db.add(menu)
            db.flush()
            existing[seed.code] = menu
            continue
        # 已存在：只维护「结构性」字段，标题/排序留给管理员自行调整
        menu.parent_id = parent_id
        menu.path = seed.path
        menu.type = seed.type
        menu.is_builtin = True
        if not menu.api_prefixes:
            menu.api_prefixes = seed.api_prefixes or None
    db.commit()
    return {m.code: m for m in db.query(Menu).all()}


def seed_roles(db: Session) -> dict[str, Role]:
    """写入/补齐内置角色，并保证超级管理员始终拥有全部菜单。"""
    menus = {m.code: m for m in db.query(Menu).all()}
    for spec in ROLE_SEEDS:
        role = db.query(Role).filter(Role.code == spec["code"]).first()
        if role is None:
            role = Role(
                code=spec["code"],
                name=spec["name"],
                remark=spec["remark"],
                data_scope=spec["data_scope"],
                is_builtin=True,
                sort_order=spec["sort_order"],
            )
            db.add(role)
            db.flush()
            codes = spec["menu_codes"]
            role.menus = (
                list(menus.values())
                if codes is None
                else [menus[c] for c in codes if c in menus]
            )
        else:
            role.is_builtin = True
            if role.code == SUPER_ADMIN_ROLE_CODE:
                # 新增菜单后超级管理员自动获得权限
                role.data_scope = DataScope.all
                role.menus = list(menus.values())
    db.commit()
    return {r.code: r for r in db.query(Role).all()}


def seed_rbac(db: Session) -> None:
    seed_menus(db)
    seed_roles(db)


def sync_legacy_admin_roles(db: Session) -> None:
    """存量用户没有角色关联：admin → 超级管理员，其他 → 普通用户。"""
    super_role = db.query(Role).filter(Role.code == SUPER_ADMIN_ROLE_CODE).first()
    user_role = db.query(Role).filter(Role.code == DEFAULT_USER_ROLE_CODE).first()
    if not super_role or not user_role:
        return
    changed = 0
    for user in db.query(User).all():
        if user.roles:
            continue
        user.roles = [super_role if user.role == UserRole.admin else user_role]
        changed += 1
    if changed:
        db.commit()
        logger.info("[rbac] 为 {} 个存量用户补齐角色关联", changed)


# --------------------------------------------------------------------------- #
# 权限解析
# --------------------------------------------------------------------------- #
def active_roles(user: User) -> list[Role]:
    return [r for r in user.roles if r.is_active]


def is_super_admin(user: User) -> bool:
    """超级管理员：拥有 ``super_admin`` 角色，或旧数据里 ``users.role == admin``。"""
    if user.role == UserRole.admin:
        return True
    return any(r.code == SUPER_ADMIN_ROLE_CODE for r in active_roles(user))


#: 本次请求路径命中的菜单 code（由 ``permission_guard`` 在每次请求开头写入），
#: 用于按路由解析角色的“单路由数据范围”。
current_menu_codes: ContextVar[tuple[str, ...]] = ContextVar(
    "current_menu_codes", default=()
)

SCOPE_ALL = "all"
SCOPE_USERS = "users"


def _route_scopes(user: User) -> list[dict]:
    """当前路由上，用户各启用角色配置的单路由数据范围。"""
    codes = current_menu_codes.get()
    if not codes:
        return []
    found: list[dict] = []
    for role in active_roles(user):
        cfg = role.menu_data_scopes or {}
        for code in codes:
            item = cfg.get(code)
            if isinstance(item, dict) and item.get("scope") in (SCOPE_ALL, SCOPE_USERS):
                found.append(item)
    return found


def has_full_data_scope(user: User) -> bool:
    """是否可以看全部用户的数据（全局，或者当前路由被单独放宽为“全部”）。"""
    if is_super_admin(user):
        return True
    if any(r.data_scope == DataScope.all for r in active_roles(user)):
        return True
    return any(item.get("scope") == SCOPE_ALL for item in _route_scopes(user))


def visible_owner_ids(user: User) -> set[int] | None:
    """当前路由上可见数据的 owner_id 集合；``None`` = 不限（全部数据）。"""
    if has_full_data_scope(user):
        return None
    ids = {user.id}
    for item in _route_scopes(user):
        if item.get("scope") == SCOPE_USERS:
            ids.update(int(x) for x in (item.get("user_ids") or []) if str(x).isdigit())
    return ids


def user_menus(db: Session, user: User) -> list[Menu]:
    """用户可见菜单（超级管理员 = 全部启用菜单）。"""
    if is_super_admin(user):
        return db.query(Menu).filter(Menu.is_active.is_(True)).all()
    seen: dict[int, Menu] = {}
    for role in active_roles(user):
        for menu in role.menus:
            if menu.is_active:
                seen[menu.id] = menu
    # 补齐父级目录，否则子菜单挂不上去
    all_menus = {m.id: m for m in db.query(Menu).all()}
    for menu in list(seen.values()):
        parent_id = menu.parent_id
        while parent_id and parent_id not in seen:
            parent = all_menus.get(parent_id)
            if parent is None or not parent.is_active:
                break
            seen[parent.id] = parent
            parent_id = parent.parent_id
    return list(seen.values())


def user_menu_codes(db: Session, user: User) -> set[str]:
    return {m.code for m in user_menus(db, user)}


def is_shared_table(table_name: str) -> bool:
    return table_name in SHARED_TABLES
