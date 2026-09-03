"""RBAC 出入参：菜单（路由）、角色、用户管理。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.rbac import ApiEnforceMode, DataScope, MenuType
from app.models.user import UserRole


# --------------------------------------------------------------------------- #
# 菜单 / 路由
# --------------------------------------------------------------------------- #
class MenuBase(BaseModel):
    code: str = Field(..., min_length=2, max_length=128)
    title: str = Field(..., min_length=1, max_length=128)
    parent_id: Optional[int] = None
    path: Optional[str] = None
    icon: Optional[str] = None
    sort_order: int = 0
    type: MenuType = MenuType.menu
    is_hidden: bool = False
    is_active: bool = True
    api_prefixes: Optional[list[str]] = None
    api_enforce_mode: ApiEnforceMode = ApiEnforceMode.all
    remark: Optional[str] = None


class MenuCreate(MenuBase):
    pass


class MenuUpdate(BaseModel):
    code: Optional[str] = Field(default=None, min_length=2, max_length=128)
    title: Optional[str] = None
    parent_id: Optional[int] = None
    path: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None
    type: Optional[MenuType] = None
    is_hidden: Optional[bool] = None
    is_active: Optional[bool] = None
    api_prefixes: Optional[list[str]] = None
    api_enforce_mode: Optional[ApiEnforceMode] = None
    remark: Optional[str] = None


class MenuOut(MenuBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_builtin: bool
    created_at: datetime


class MenuTreeOut(MenuOut):
    children: list["MenuTreeOut"] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 角色
# --------------------------------------------------------------------------- #
class MenuDataScope(BaseModel):
    """单个路由上放宽的数据范围：all = 该路由看全部人的数据；users = 只多看指定用户的数据。"""

    scope: str = Field(..., pattern="^(all|users)$")
    user_ids: list[int] = Field(default_factory=list)


class RoleBase(BaseModel):
    code: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=1, max_length=64)
    remark: Optional[str] = None
    data_scope: DataScope = DataScope.own
    #: ``{menu_code: MenuDataScope}``，未列出的路由按 data_scope
    menu_data_scopes: Optional[dict[str, MenuDataScope]] = None
    is_active: bool = True
    sort_order: int = 0


class RoleCreate(RoleBase):
    menu_ids: list[int] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    remark: Optional[str] = None
    data_scope: Optional[DataScope] = None
    menu_data_scopes: Optional[dict[str, MenuDataScope]] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    menu_ids: Optional[list[int]] = None


class RoleOut(RoleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_builtin: bool
    created_at: datetime
    menu_ids: list[int] = Field(default_factory=list)
    user_count: int = 0


# --------------------------------------------------------------------------- #
# 用户管理
# --------------------------------------------------------------------------- #
class SysUserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=64)
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_active: bool = True
    role_ids: list[int] = Field(default_factory=list)
    dedupe_against_user_ids: list[int] = Field(default_factory=list)


class SysUserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    role_ids: Optional[list[int]] = None
    dedupe_against_user_ids: Optional[list[int]] = None


class PasswordResetIn(BaseModel):
    password: str = Field(..., min_length=6, max_length=64)


class PasswordChangeIn(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=64)


class RoleBriefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    data_scope: DataScope


class SysUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: UserRole
    is_active: bool
    created_at: datetime
    roles: list[RoleBriefOut] = Field(default_factory=list)
    is_super_admin: bool = False
    #: 导入 / 批量导入时按主页链接“区别开”的对照账号
    dedupe_against_user_ids: list[int] = Field(default_factory=list)


class MyPermissionOut(BaseModel):
    """登录后前端拿它渲染菜单 / 做路由守卫。"""

    user: SysUserOut
    is_super_admin: bool
    data_scope: DataScope
    menu_codes: list[str]
    menus: list[MenuTreeOut]


MenuTreeOut.model_rebuild()
