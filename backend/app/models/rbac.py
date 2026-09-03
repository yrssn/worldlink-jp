"""RBAC：角色、菜单（路由）、角色-菜单、用户-角色。

只做「路由/菜单级」权限：一个菜单节点即一个前端路由 + 可选的后端 API 前缀集合。
按钮级权限暂不实现（预留 ``Menu.type == MenuType.button``）。
"""
from __future__ import annotations

import enum

from sqlalchemy import (
    JSON,
    Boolean,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    Column,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class DataScope(str, enum.Enum):
    """数据可见范围。

    - ``own``：只能看自己创建的数据（共享模块除外，见 ``app.core.data_scope``）
    - ``all``：可以看全部用户的数据
    """

    own = "own"
    all = "all"


class MenuType(str, enum.Enum):
    catalog = "catalog"  # 目录（只做分组，无页面）
    menu = "menu"  # 菜单（对应一个前端路由）
    button = "button"  # 预留：按钮级权限


class ApiEnforceMode(str, enum.Enum):
    """该菜单对应后端接口的校验强度。"""

    all = "all"  # 所有请求方法都要求有此菜单权限
    write = "write"  # 只校验写操作（POST/PUT/PATCH/DELETE），读接口放开
    off = "off"  # 不校验后端接口（仅前端隐藏）


role_menus = Table(
    "role_menus",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("menu_id", ForeignKey("menus.id", ondelete="CASCADE"), primary_key=True),
)

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Menu(Base, TimestampMixin):
    """菜单 / 路由节点。"""

    __tablename__ = "menus"
    __table_args__ = (UniqueConstraint("code", name="uq_menus_code"),)

    #: 权限编码，前端路由 meta.code 与之对应，如 ``llm:providers``
    code: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("menus.id", ondelete="CASCADE"), nullable=True, index=True
    )
    #: 前端路由 path（目录为空）
    path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    type: Mapped[MenuType] = mapped_column(
        Enum(MenuType), default=MenuType.menu, nullable=False
    )
    #: 侧边栏是否隐藏（详情页这类子路由隐藏，但仍参与权限判断）
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: 内置菜单不允许删除（升级时由 seed 维护）
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: 该菜单对应的后端接口前缀列表，如 ``["/api/v1/llm/providers"]``
    api_prefixes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    api_enforce_mode: Mapped[ApiEnforceMode] = mapped_column(
        Enum(ApiEnforceMode), default=ApiEnforceMode.all, nullable=False
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)

    parent: Mapped["Menu | None"] = relationship(
        "Menu", remote_side=lambda: Menu.id, back_populates="children"
    )
    children: Mapped[list["Menu"]] = relationship(
        "Menu", back_populates="parent", cascade="all, delete-orphan"
    )
    roles: Mapped[list["Role"]] = relationship(
        "Role", secondary=role_menus, back_populates="menus"
    )


class Role(Base, TimestampMixin):
    """角色：一组菜单权限 + 数据可见范围。"""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("code", name="uq_roles_code"),)

    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data_scope: Mapped[DataScope] = mapped_column(
        Enum(DataScope), default=DataScope.own, nullable=False
    )
    #: 按路由单独放宽的数据范围：``{menu_code: {"scope": "all" | "users", "user_ids": [..]}}``。
    #: 只对写在这里的路由生效，其余路由仍按 ``data_scope``。
    menu_data_scopes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: 内置角色（超级管理员）不允许删除，且始终拥有全部菜单
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    menus: Mapped[list[Menu]] = relationship(
        "Menu", secondary=role_menus, back_populates="roles"
    )
    users: Mapped[list["User"]] = relationship(  # noqa: F821
        "User", secondary=user_roles, back_populates="roles"
    )
