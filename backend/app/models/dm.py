"""私信内容：分类 + 模板（标题、正文、图片等）。"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class DmCategory(Base, TimestampMixin):
    """私信内容分类（按用户隔离）。"""

    __tablename__ = "dm_categories"

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="标签色，如 #409EFF")
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    contents: Mapped[list["DmContent"]] = relationship(
        "DmContent", back_populates="category", foreign_keys="DmContent.category_id"
    )


class DmContent(Base, TimestampMixin):
    """私信内容模板。"""

    __tablename__ = "dm_contents"

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("dm_categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="列表摘要")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="私信正文")
    images: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="图片列表 [{url,path,name,sort}]")
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="标签字符串数组")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True)

    category: Mapped[DmCategory | None] = relationship(
        "DmCategory", back_populates="contents", foreign_keys=[category_id]
    )


class DmOutreachLog(Base, TimestampMixin):
    """私信建联发送记录：某次「私信建联」实际发给了哪个达人、发的哪条内容。

    按发送人隔离（owner_id）。达人可能在发送时还没入库，故 influencer_id 可空，
    先按主页 URL 记录，达人入库后回填关联。content_* 为发送时的内容快照，
    即使模板后续被改/删也能追溯。
    """

    __tablename__ = "dm_outreach_logs"

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    influencer_id: Mapped[int | None] = mapped_column(
        ForeignKey("influencers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    url: Mapped[str] = mapped_column(String(512), nullable=False, index=True, comment="达人主页链接")
    browser_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="发送所用指纹浏览器窗口")
    content_id: Mapped[int | None] = mapped_column(
        ForeignKey("dm_contents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    content_title: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="内容标题快照")
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="私信正文快照")
    images_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="内容含图片数")
    text_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="正文是否发出")
    images_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="实际发出图片数")
