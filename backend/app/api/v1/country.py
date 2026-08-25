"""国家管理：达人国家分类的字典表（中文名 + 英文名 + 代码）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.country import Country
from app.models.influencer import Influencer
from app.models.user import User
from app.schemas.country import CountryCreate, CountryOut, CountryUpdate

router = APIRouter(prefix="/countries", tags=["country"])


def _get_or_404(db: Session, country_id: int) -> Country:
    row = db.query(Country).filter(Country.id == country_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="国家不存在")
    return row


def _norm_code(code: str | None) -> str | None:
    return (code.strip().upper() or None) if code else None


@router.get("", response_model=list[CountryOut])
def list_countries(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """国家字典（团队共享），按排序号再按 id 升序。"""
    return (
        db.query(Country)
        .order_by(Country.sort_order.asc(), Country.id.asc())
        .all()
    )


@router.post("", response_model=CountryOut)
def create_country(
    body: CountryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = Country(
        owner_id=user.id,
        name_zh=body.name_zh.strip(),
        name_en=(body.name_en.strip() if body.name_en else None) or None,
        code=_norm_code(body.code),
        remark=body.remark,
        sort_order=body.sort_order,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/{country_id}", response_model=CountryOut)
def update_country(
    country_id: int,
    body: CountryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _get_or_404(db, country_id)
    if body.name_zh is not None:
        row.name_zh = body.name_zh.strip()
    if "name_en" in body.model_fields_set:
        row.name_en = (body.name_en.strip() if body.name_en else None) or None
    if "code" in body.model_fields_set:
        row.code = _norm_code(body.code)
    if "remark" in body.model_fields_set:
        row.remark = body.remark
    if "sort_order" in body.model_fields_set and body.sort_order is not None:
        row.sort_order = body.sort_order
    db.commit()
    db.refresh(row)
    # 代码改了要同步达人上的兼容字段，导出/筛选才不会对不上
    db.query(Influencer).filter(Influencer.country_id == row.id).update(
        {Influencer.country: row.code}, synchronize_session=False
    )
    db.commit()
    return row


@router.delete("/{country_id}")
def delete_country(
    country_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _get_or_404(db, country_id)
    # 手动解绑：country_id 在存量库里是补列加的，不一定带 ON DELETE SET NULL
    db.query(Influencer).filter(Influencer.country_id == row.id).update(
        {Influencer.country_id: None}, synchronize_session=False
    )
    db.delete(row)
    db.commit()
    return {"ok": True}
