from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import and_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from loguru import logger

from app.core.deps import get_current_user, get_db
from app.models.bitbrowser import BitBrowserPlatform, BitBrowserWindow, BitBrowserWindowCatalog
from app.models.user import User
from app.schemas.bitbrowser import (
    BitBrowserCatalogOut,
    BitBrowserCatalogRowOut,
    BitBrowserCatalogSave,
    BitBrowserOpenResponse,
    BitBrowserPlatformCreate,
    BitBrowserPlatformOut,
    BitBrowserPlatformUpdate,
    BitBrowserSettingsOut,
    BitBrowserSettingsUpdate,
    BitBrowserSyncMetaOut,
    BitBrowserSyncResult,
    BitBrowserWindowListOut,
    BitBrowserWindowOut,
)
from app.services import bitbrowser_service

router = APIRouter(prefix="/bitbrowser", tags=["bitbrowser"])


def _user_local_hint(user: User) -> str:
    u = (user.bitbrowser_local_url or "").strip()
    return u or "（尚未在「本机连接配置」中填写地址）"


def _row_to_window_list_out(
    w: BitBrowserWindow,
    cat: BitBrowserWindowCatalog | None,
    plat: BitBrowserPlatform | None,
) -> BitBrowserWindowListOut:
    base = BitBrowserWindowOut.model_validate(w).model_dump()
    base["saved_to_system"] = cat is not None
    base["catalog_platform_id"] = cat.platform_id if cat else None
    base["catalog_platform_name"] = plat.name if plat else None
    base["catalog_note"] = cat.note if cat else None
    base["catalog_in_local_cache"] = bool(cat.in_local_cache) if cat else None
    return BitBrowserWindowListOut(**base)


def _catalog_to_out(cat: BitBrowserWindowCatalog, plat: BitBrowserPlatform | None) -> BitBrowserCatalogOut:
    return BitBrowserCatalogOut(
        id=cat.id,
        owner_id=cat.owner_id,
        browser_id=cat.browser_id,
        platform_id=cat.platform_id,
        platform_name=plat.name if plat else None,
        note=cat.note,
        cached_window_name=cat.cached_window_name,
        cached_env_platform=cat.cached_env_platform,
        in_local_cache=bool(getattr(cat, "in_local_cache", True)),
        created_at=cat.created_at,
        updated_at=cat.updated_at,
    )


def _catalog_row_to_out(
    cat: BitBrowserWindowCatalog,
    w: BitBrowserWindow | None,
    plat: BitBrowserPlatform | None,
) -> BitBrowserCatalogRowOut:
    core = _catalog_to_out(cat, plat).model_dump()
    core["seq"] = w.seq if w else None
    core["name"] = w.name if w else None
    core["platform"] = w.platform if w else None
    core["remark"] = w.remark if w else None
    core["proxy_type"] = w.proxy_type if w else None
    core["host"] = w.host if w else None
    core["port"] = w.port if w else None
    core["last_ip"] = w.last_ip if w else None
    core["account_username"] = w.account_username if w else None
    core["status"] = w.status if w else None
    core["window_updated_at"] = w.updated_at if w else None
    return BitBrowserCatalogRowOut(**core)


@router.get("/catalog", response_model=list[BitBrowserCatalogRowOut])
def list_bitbrowser_catalog(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """当前用户全部系统登记（含本机列表已不存在的记录，``in_local_cache`` 由同步更新）。"""
    Cat = BitBrowserWindowCatalog
    try:
        q = (
            db.query(Cat, BitBrowserWindow, BitBrowserPlatform)
            .select_from(Cat)
            .outerjoin(
                BitBrowserWindow,
                and_(
                    BitBrowserWindow.owner_id == Cat.owner_id,
                    BitBrowserWindow.browser_id == Cat.browser_id,
                ),
            )
            .outerjoin(BitBrowserPlatform, BitBrowserPlatform.id == Cat.platform_id)
            .filter(Cat.owner_id == user.id)
            .order_by(Cat.in_local_cache.desc(), Cat.updated_at.desc())
        )
        rows = q.all()
        return [_catalog_row_to_out(cat, w, plat) for cat, w, plat in rows]
    except SQLAlchemyError as e:
        logger.exception("list bitbrowser catalog failed: {}", e)
        raise HTTPException(status_code=503, detail="读取系统登记失败") from e


@router.get("/platforms", response_model=list[BitBrowserPlatformOut])
def list_bitbrowser_platforms(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """当前用户自建平台列表（用于窗口分类）。"""
    rows = (
        db.query(BitBrowserPlatform)
        .filter(BitBrowserPlatform.owner_id == user.id)
        .order_by(BitBrowserPlatform.sort_order.asc(), BitBrowserPlatform.id.asc())
        .all()
    )
    return rows


@router.post("/platforms", response_model=BitBrowserPlatformOut)
def create_bitbrowser_platform(
    body: BitBrowserPlatformCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = BitBrowserPlatform(
        owner_id=user.id,
        name=body.name.strip(),
        code=(body.code.strip() if body.code else None) or None,
        remark=body.remark,
        sort_order=body.sort_order,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/platforms/{platform_id}", response_model=BitBrowserPlatformOut)
def update_bitbrowser_platform(
    platform_id: int,
    body: BitBrowserPlatformUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = (
        db.query(BitBrowserPlatform)
        .filter(BitBrowserPlatform.id == platform_id, BitBrowserPlatform.owner_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="平台不存在")
    if body.name is not None:
        row.name = body.name.strip()
    if "code" in body.model_fields_set:
        row.code = (body.code.strip() if body.code else None) or None
    if "remark" in body.model_fields_set:
        row.remark = body.remark
    if "sort_order" in body.model_fields_set and body.sort_order is not None:
        row.sort_order = body.sort_order
    db.commit()
    db.refresh(row)
    return row


@router.delete("/platforms/{platform_id}")
def delete_bitbrowser_platform(
    platform_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = (
        db.query(BitBrowserPlatform)
        .filter(BitBrowserPlatform.id == platform_id, BitBrowserPlatform.owner_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="平台不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/windows", response_model=list[BitBrowserWindowListOut])
def list_cached_windows(
    saved_only: bool = Query(False, description="仅返回已「保存到系统」的窗口"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """从数据库读取最近一次同步的 BitBrowser 窗口列表（可带自建平台归类与保存状态）。"""
    Cat = BitBrowserWindowCatalog
    Plat = BitBrowserPlatform
    try:
        q = (
            db.query(BitBrowserWindow, Cat, Plat)
            .outerjoin(
                Cat,
                and_(
                    Cat.owner_id == BitBrowserWindow.owner_id,
                    Cat.browser_id == BitBrowserWindow.browser_id,
                ),
            )
            .outerjoin(Plat, Plat.id == Cat.platform_id)
            .filter(BitBrowserWindow.owner_id == user.id)
        )
        if saved_only:
            q = q.filter(Cat.id.isnot(None))
        q = q.order_by(BitBrowserWindow.updated_at.desc(), BitBrowserWindow.browser_id)
        rows = q.all()
        return [_row_to_window_list_out(w, cat, plat) for w, cat, plat in rows]
    except SQLAlchemyError as e:
        logger.exception("list bitbrowser windows failed: {}", e)
        raise HTTPException(
            status_code=503,
            detail="读取比特浏览器窗口缓存失败（若刚升级含本模块，请重启后端以自动建表）",
        ) from e


@router.put("/windows/{browser_id}/catalog", response_model=BitBrowserCatalogOut)
def upsert_window_catalog(
    browser_id: str,
    body: BitBrowserCatalogSave,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """将窗口以 ``browser_id`` 为唯一键登记到本系统，并可归类到自建平台。"""
    bid = browser_id.strip()
    w = (
        db.query(BitBrowserWindow)
        .filter(BitBrowserWindow.owner_id == user.id, BitBrowserWindow.browser_id == bid)
        .first()
    )
    if not w:
        raise HTTPException(
            status_code=404,
            detail="该窗口不在你的缓存列表中，请先「从本机同步」后再保存到系统",
        )
    if "platform_id" in body.model_fields_set and body.platform_id is not None:
        plat = (
            db.query(BitBrowserPlatform)
            .filter(BitBrowserPlatform.id == body.platform_id, BitBrowserPlatform.owner_id == user.id)
            .first()
        )
        if not plat:
            raise HTTPException(status_code=400, detail="所选平台不存在或不属于你，请先在「平台管理」中创建")

    cat = (
        db.query(BitBrowserWindowCatalog)
        .filter(BitBrowserWindowCatalog.owner_id == user.id, BitBrowserWindowCatalog.browser_id == bid)
        .first()
    )
    if not cat:
        cat = BitBrowserWindowCatalog(owner_id=user.id, browser_id=bid)
        db.add(cat)
    if "platform_id" in body.model_fields_set:
        cat.platform_id = body.platform_id
    if "note" in body.model_fields_set:
        cat.note = body.note
    cat.cached_window_name = w.name
    cat.cached_env_platform = w.platform
    cat.in_local_cache = True
    db.commit()
    db.refresh(cat)
    plat_row = (
        db.query(BitBrowserPlatform)
        .filter(BitBrowserPlatform.id == cat.platform_id, BitBrowserPlatform.owner_id == user.id)
        .first()
        if cat.platform_id
        else None
    )
    return _catalog_to_out(cat, plat_row)


@router.delete("/windows/{browser_id}/catalog")
def delete_window_catalog(
    browser_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """取消将窗口登记到本系统（不影响 BitBrowser 本地环境）。"""
    bid = browser_id.strip()
    cat = (
        db.query(BitBrowserWindowCatalog)
        .filter(BitBrowserWindowCatalog.owner_id == user.id, BitBrowserWindowCatalog.browser_id == bid)
        .first()
    )
    if not cat:
        raise HTTPException(status_code=404, detail="该窗口未登记到系统")
    db.delete(cat)
    db.commit()
    return {"ok": True}


@router.get("/settings", response_model=BitBrowserSettingsOut)
def get_bitbrowser_settings(user: User = Depends(get_current_user)):
    """读取当前用户保存的本机 BitBrowser 地址与是否已配置 Token（不返回 Token 明文）。"""
    url = (user.bitbrowser_local_url or "").strip() or None
    has_key = bool((user.bitbrowser_api_key or "").strip())
    return BitBrowserSettingsOut(local_url=url, has_api_key=has_key)


@router.put("/settings", response_model=BitBrowserSettingsOut)
def update_bitbrowser_settings(
    body: BitBrowserSettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """保存本机 BitBrowser Local 地址；api_key 仅在请求体包含该字段时更新或清除。"""
    u = db.get(User, user.id)
    if not u:
        raise HTTPException(status_code=401, detail="User not found")
    u.bitbrowser_local_url = body.local_url.strip()
    if "api_key" in body.model_fields_set:
        if body.api_key is not None and body.api_key.strip():
            u.bitbrowser_api_key = body.api_key.strip()
        else:
            u.bitbrowser_api_key = None
    db.commit()
    db.refresh(u)
    url = (u.bitbrowser_local_url or "").strip() or None
    has_key = bool((u.bitbrowser_api_key or "").strip())
    return BitBrowserSettingsOut(local_url=url, has_api_key=has_key)


@router.post("/windows/sync", response_model=BitBrowserSyncResult)
def sync_windows_from_local_bitbrowser(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """调用本机 BitBrowser Local API（``POST /browser/list``）全量拉取并写入数据库。"""
    try:
        stats = bitbrowser_service.sync_windows_to_db(db, user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail=f"无法连接 BitBrowser 本地服务 ({_user_local_hint(user)}): {e}",
        ) from e
    return BitBrowserSyncResult(**stats)


@router.get("/sync-meta", response_model=BitBrowserSyncMetaOut)
def bitbrowser_sync_meta(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """当前用户缓存条数与上次成功同步时间（不调用 BitBrowser）。"""
    n = (
        db.query(BitBrowserWindow)
        .filter(BitBrowserWindow.owner_id == user.id)
        .count()
    )
    return BitBrowserSyncMetaOut(last_sync_at=user.bitbrowser_last_sync_at, cached_rows=n)


@router.post("/windows/{browser_id}/open", response_model=BitBrowserOpenResponse)
def open_bitbrowser_window(
    browser_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """对已同步到本库的窗口调用 BitBrowser ``POST /browser/open``（测试用）。"""
    row = (
        db.query(BitBrowserWindow)
        .filter(
            BitBrowserWindow.owner_id == user.id,
            BitBrowserWindow.browser_id == browser_id.strip(),
        )
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail="该窗口不在你的缓存列表中，请先点击「从本机同步」",
        )
    try:
        data = bitbrowser_service.open_browser_window(browser_id.strip(), user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail=f"无法连接 BitBrowser 本地服务 ({_user_local_hint(user)}): {e}",
        ) from e
    return BitBrowserOpenResponse(success=True, data=jsonable_encoder(data))


@router.get("/local-health")
def bitbrowser_local_health(user: User = Depends(get_current_user)):
    """探测 BitBrowser 本地服务是否在线（``POST /health``）。"""
    try:
        data = bitbrowser_service.health_check_local(user)
        return {"ok": True, "bitbrowser": jsonable_encoder(data)}
    except ValueError as e:
        return {
            "ok": False,
            "error": str(e),
            "hint": "",
            "auth_hint": "",
        }
    except BaseException as e:  # noqa: BLE001
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(e, HTTPException):
            raise
        logger.warning("BitBrowser local-health check failed: {}", e)
        return {
            "ok": False,
            "error": str(e),
            "hint": _user_local_hint(user),
            "auth_hint": "若客户端已开启鉴权，请在「本机连接配置」中填写 API Token",
        }
