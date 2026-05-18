from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class UserRole(str, enum.Enum):
    admin = "admin"
    user = "user"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole), default=UserRole.user, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: 该用户本机 BitBrowser Local API 根地址（如 http://127.0.0.1:54345 或内网穿透 URL）
    bitbrowser_local_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    #: 与比特浏览器「设置 → 本地 API」中 API Token 一致；未开启鉴权可留空
    bitbrowser_api_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    #: 该用户最近一次从 BitBrowser 本地服务拉取并写入 ``bitbrowser_windows`` 的时间（UTC 存库）
    bitbrowser_last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
