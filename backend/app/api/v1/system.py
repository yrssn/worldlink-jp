"""系统管理：用户列表、角色权限、路由（菜单）列表，以及「我的权限」。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_admin, get_current_user, get_db
from app.core.permission_guard import invalidate_menu_cache
from app.core.security import hash_password, verify_password
from app.models.rbac import DataScope, Menu, Role
from app.models.user import User, UserRole
from app.schemas.rbac import (
    MenuCreate,
    MenuOut,
    MenuTreeOut,
    MenuUpdate,
    MyPermissionOut,
    PasswordChangeIn,
    PasswordResetIn,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    SysUserCreate,
    SysUserOut,
    SysUserUpdate,
)
from app.services import rbac_service

router = APIRouter(prefix="/system", tags=["system"])


# --------------------------------------------------------------------------- #
# 我的权限（所有登录用户）
# --------------------------------------------------------------------------- #
def _build_tree(menus: list[Menu]) -> list[MenuTreeOut]:
    # ORM 的 Menu.children 会被 model_validate 一起带出来，这里必须清空后自己挂，
    # 否则每个子菜单会出现两次（ORM 带的 + 下面 append 的）
    nodes: dict[int, MenuTreeOut] = {}
    for m in menus:
        node = MenuTreeOut.model_validate(m)
        node.children = []
        nodes[m.id] = node
    roots: list[MenuTreeOut] = []
    for menu in menus:
        node = nodes[menu.id]
        parent = nodes.get(menu.parent_id) if menu.parent_id else None
        if parent is None:
            roots.append(node)
        else:
            parent.children.append(node)
    for node in nodes.values():
        node.children.sort(key=lambda n: (n.sort_order, n.id))
    roots.sort(key=lambda n: (n.sort_order, n.id))
    return roots


@router.get("/profile/permissions", response_model=MyPermissionOut)
def my_permissions(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> MyPermissionOut:
    menus = rbac_service.user_menus(db, user)
    return MyPermissionOut(
        user=_user_out(user),
        is_super_admin=rbac_service.is_super_admin(user),
        data_scope=(
            DataScope.all if rbac_service.has_full_data_scope(user) else DataScope.own
        ),
        menu_codes=sorted(m.code for m in menus),
        menus=_build_tree(menus),
    )


@router.post("/profile/password")
def change_my_password(
    payload: PasswordChangeIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"msg": "ok"}


# --------------------------------------------------------------------------- #
# 菜单 / 路由
# --------------------------------------------------------------------------- #
@router.get("/menus", response_model=list[MenuOut])
def list_menus(
    db: Session = Depends(get_db), _: User = Depends(get_current_admin)
) -> list[MenuOut]:
    menus = db.query(Menu).order_by(Menu.sort_order, Menu.id).all()
    return [MenuOut.model_validate(m) for m in menus]


@router.get("/menus/tree", response_model=list[MenuTreeOut])
def menu_tree(
    db: Session = Depends(get_db), _: User = Depends(get_current_admin)
) -> list[MenuTreeOut]:
    return _build_tree(db.query(Menu).order_by(Menu.sort_order, Menu.id).all())


@router.post("/menus", response_model=MenuOut, status_code=status.HTTP_201_CREATED)
def create_menu(
    payload: MenuCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> MenuOut:
    if db.query(Menu).filter(Menu.code == payload.code).first():
        raise HTTPException(status_code=400, detail="权限编码已存在")
    menu = Menu(**payload.model_dump())
    db.add(menu)
    db.commit()
    invalidate_menu_cache()
    # 新增菜单自动授予超级管理员
    rbac_service.seed_roles(db)
    return MenuOut.model_validate(menu)


@router.put("/menus/{menu_id}", response_model=MenuOut)
def update_menu(
    menu_id: int,
    payload: MenuUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> MenuOut:
    menu = db.get(Menu, menu_id)
    if not menu:
        raise HTTPException(status_code=404, detail="菜单不存在")
    data = payload.model_dump(exclude_unset=True)
    if "code" in data and data["code"] != menu.code:
        if menu.is_builtin:
            raise HTTPException(status_code=400, detail="内置菜单不允许修改权限编码")
        if db.query(Menu).filter(Menu.code == data["code"]).first():
            raise HTTPException(status_code=400, detail="权限编码已存在")
    if data.get("parent_id") == menu.id:
        raise HTTPException(status_code=400, detail="父级不能是自己")
    if "code" in data:
        menu.code = data["code"]
    if "title" in data:
        menu.title = data["title"]
    if "parent_id" in data:
        menu.parent_id = data["parent_id"]
    if "path" in data:
        menu.path = data["path"]
    if "icon" in data:
        menu.icon = data["icon"]
    if "sort_order" in data:
        menu.sort_order = data["sort_order"]
    if "type" in data:
        menu.type = data["type"]
    if "is_hidden" in data:
        menu.is_hidden = data["is_hidden"]
    if "is_active" in data:
        menu.is_active = data["is_active"]
    if "api_prefixes" in data:
        menu.api_prefixes = data["api_prefixes"]
    if "api_enforce_mode" in data:
        menu.api_enforce_mode = data["api_enforce_mode"]
    if "remark" in data:
        menu.remark = data["remark"]
    db.commit()
    invalidate_menu_cache()
    return MenuOut.model_validate(menu)


@router.delete("/menus/{menu_id}")
def delete_menu(
    menu_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    menu = db.get(Menu, menu_id)
    if not menu:
        raise HTTPException(status_code=404, detail="菜单不存在")
    if menu.is_builtin:
        raise HTTPException(status_code=400, detail="内置菜单不允许删除，可改为停用")
    db.delete(menu)
    db.commit()
    invalidate_menu_cache()
    return {"msg": "ok"}


# --------------------------------------------------------------------------- #
# 角色
# --------------------------------------------------------------------------- #
def _role_out(db: Session, role: Role) -> RoleOut:
    out = RoleOut.model_validate(role)
    out.menu_ids = sorted(m.id for m in role.menus)
    out.user_count = len(role.users)
    return out


@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    db: Session = Depends(get_db), _: User = Depends(get_current_admin)
) -> list[RoleOut]:
    roles = db.query(Role).order_by(Role.sort_order, Role.id).all()
    return [_role_out(db, r) for r in roles]


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(
    payload: RoleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> RoleOut:
    if db.query(Role).filter(Role.code == payload.code).first():
        raise HTTPException(status_code=400, detail="角色编码已存在")
    role = Role(**payload.model_dump(exclude={"menu_ids"}, mode="json"))
    role.menus = db.query(Menu).filter(Menu.id.in_(payload.menu_ids)).all()
    db.add(role)
    db.commit()
    return _role_out(db, role)


@router.put("/roles/{role_id}", response_model=RoleOut)
def update_role(
    role_id: int,
    payload: RoleUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> RoleOut:
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    data = payload.model_dump(exclude_unset=True)
    menu_ids = data.pop("menu_ids", None)
    if role.is_builtin and role.code == rbac_service.SUPER_ADMIN_ROLE_CODE:
        # 超级管理员的菜单与数据范围固定，避免把自己锁死在系统外
        menu_ids = None
        data.pop("data_scope", None)
        data.pop("menu_data_scopes", None)
        data.pop("is_active", None)
    if "name" in data:
        role.name = data["name"]
    if "remark" in data:
        role.remark = data["remark"]
    if "data_scope" in data:
        role.data_scope = data["data_scope"]
    if "menu_data_scopes" in data:
        role.menu_data_scopes = payload.model_dump(mode="json")["menu_data_scopes"] or None
    if "is_active" in data:
        role.is_active = data["is_active"]
    if "sort_order" in data:
        role.sort_order = data["sort_order"]
    if menu_ids is not None:
        role.menus = db.query(Menu).filter(Menu.id.in_(menu_ids)).all()
    db.commit()
    return _role_out(db, role)


@router.delete("/roles/{role_id}")
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    if role.is_builtin:
        raise HTTPException(status_code=400, detail="内置角色不允许删除")
    if role.users:
        raise HTTPException(status_code=400, detail="该角色下仍有用户，请先调整用户角色")
    db.delete(role)
    db.commit()
    return {"msg": "ok"}


# --------------------------------------------------------------------------- #
# 用户
# --------------------------------------------------------------------------- #
def _sync_legacy_role_field(user: User) -> None:
    """保持旧的 ``users.role`` 字段与 RBAC 角色一致，兼容历史代码。"""
    is_super = any(
        r.code == rbac_service.SUPER_ADMIN_ROLE_CODE for r in user.roles
    )
    user.role = UserRole.admin if is_super else UserRole.user


def _user_out(user: User) -> SysUserOut:
    out = SysUserOut.model_validate(user)
    out.is_super_admin = rbac_service.is_super_admin(user)
    out.dedupe_against_user_ids = [int(x) for x in (user.dedupe_against_user_ids or [])]
    return out


@router.get("/users", response_model=list[SysUserOut])
def list_users(
    db: Session = Depends(get_db), _: User = Depends(get_current_admin)
) -> list[SysUserOut]:
    users = db.query(User).order_by(User.id).all()
    return [_user_out(u) for u in users]


@router.post("/users", response_model=SysUserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: SysUserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> SysUserOut:
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="登录名已存在")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        email=payload.email,
        full_name=payload.full_name,
        is_active=payload.is_active,
        role=UserRole.user,
        dedupe_against_user_ids=payload.dedupe_against_user_ids or None,
    )
    user.roles = db.query(Role).filter(Role.id.in_(payload.role_ids)).all()
    _sync_legacy_role_field(user)
    db.add(user)
    db.commit()
    return _user_out(user)


@router.put("/users/{user_id}", response_model=SysUserOut)
def update_user(
    user_id: int,
    payload: SysUserUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_admin),
) -> SysUserOut:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    data = payload.model_dump(exclude_unset=True)
    role_ids = data.pop("role_ids", None)
    if user.id == current.id and data.get("is_active") is False:
        raise HTTPException(status_code=400, detail="不能停用当前登录账号")
    if "email" in data:
        user.email = data["email"]
    if "full_name" in data:
        user.full_name = data["full_name"]
    if "is_active" in data:
        user.is_active = data["is_active"]
    if "dedupe_against_user_ids" in data:
        user.dedupe_against_user_ids = [
            i for i in (data["dedupe_against_user_ids"] or []) if i != user.id
        ] or None
    if role_ids is not None:
        if user.id == current.id and not any(
            r.code == rbac_service.SUPER_ADMIN_ROLE_CODE
            for r in db.query(Role).filter(Role.id.in_(role_ids)).all()
        ):
            raise HTTPException(status_code=400, detail="不能移除当前登录账号的超级管理员角色")
        user.roles = db.query(Role).filter(Role.id.in_(role_ids)).all()
        _sync_legacy_role_field(user)
    db.commit()
    return _user_out(user)


@router.post("/users/{user_id}/password")
def reset_password(
    user_id: int,
    payload: PasswordResetIn,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.password_hash = hash_password(payload.password)
    db.commit()
    return {"msg": "ok"}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")
    # 业务数据 owner_id 是 CASCADE 外键，直接删用户会连带删数据，故只做停用
    user.is_active = False
    db.commit()
    return {"msg": "已停用该账号（为避免级联删除业务数据，不做物理删除）"}
