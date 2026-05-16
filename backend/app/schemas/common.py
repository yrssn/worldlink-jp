from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageQuery(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=200)
    keyword: Optional[str] = None


class Page(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: List[T]


class Msg(BaseModel):
    msg: str = "ok"
