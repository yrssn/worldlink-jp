"""比特浏览器（BitBrowser）本地窗口缓存、自建平台与「保存到系统」登记。"""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class BitBrowserWindow(Base, TimestampMixin):
    """从 BitBrowser 本地服务 ``POST /browser/list`` 同步的浏览器窗口。"""

    __tablename__ = "bitbrowser_windows"
    __table_args__ = (
        UniqueConstraint("owner_id", "browser_id", name="uq_bitbrowser_owner_browser_id"),
    )

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # BitBrowser 窗口 id（非本表自增 id）
    browser_id: Mapped[str] = mapped_column(String(64), nullable=False)

    seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform: Mapped[str | None] = mapped_column(String(512), nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    proxy_method: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proxy_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    port: Mapped[str | None] = mapped_column(String(32), nullable=True)

    last_ip: Mapped[str | None] = mapped_column(String(128), nullable=True)
    account_username: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[int | None] = mapped_column(Integer, nullable=True)

    raw_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class BitBrowserPlatform(Base, TimestampMixin):
    """用户自建业务平台（用于窗口分类，与 BitBrowser 环境里的 platform 字段无关）。"""

    __tablename__ = "bitbrowser_platforms"

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    catalog_entries: Mapped[list["BitBrowserWindowCatalog"]] = relationship(
        "BitBrowserWindowCatalog", back_populates="platform"
    )


class BitBrowserWindowCatalog(Base, TimestampMixin):
    """以 BitBrowser 窗口 ``browser_id`` 为唯一键，登记到本系统并归类到自建平台。"""

    __tablename__ = "bitbrowser_window_catalog"
    __table_args__ = (
        UniqueConstraint("owner_id", "browser_id", name="uq_bb_catalog_owner_browser"),
    )

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    browser_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    platform_id: Mapped[int | None] = mapped_column(
        ForeignKey("bitbrowser_platforms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 保存时的窗口名称，便于本机列表已无缓存时仍能展示
    cached_window_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    #: 保存时的环境平台（BitBrowser ``platform`` 字段快照）
    cached_env_platform: Mapped[str | None] = mapped_column(String(512), nullable=True)
    #: 最近一次同步时该 ``browser_id`` 是否仍出现在本机 ``/browser/list`` 结果中
    in_local_cache: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    platform: Mapped["BitBrowserPlatform | None"] = relationship(back_populates="catalog_entries")
