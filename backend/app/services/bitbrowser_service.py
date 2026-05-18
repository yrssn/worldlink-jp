"""比特浏览器 BitBrowser 本地 HTTP 客户端（连接信息按用户存储，见 User.bitbrowser_*）。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.bitbrowser import BitBrowserWindow, BitBrowserWindowCatalog
from app.models.user import User


@dataclass(frozen=True)
class BitBrowserClientContext:
    """单次请求使用的 BitBrowser Local 连接参数（来自当前登录用户）。"""

    base_url: str
    api_key: str | None
    http_timeout_sec: float
    list_page_size: int


def client_context_from_user(user: User) -> BitBrowserClientContext:
    raw = (getattr(user, "bitbrowser_local_url", None) or "").strip()
    if not raw:
        raise ValueError(
            "请先在「本机连接配置」中填写 BitBrowser 本地服务地址（与客户端「设置 → 本地 API」中的地址一致，例如 http://127.0.0.1:54345）"
        )
    base = raw.rstrip("/")
    tok = (getattr(user, "bitbrowser_api_key", None) or "").strip() or None
    return BitBrowserClientContext(
        base_url=base,
        api_key=tok,
        http_timeout_sec=float(settings.bitbrowser_http_timeout_sec),
        list_page_size=int(settings.bitbrowser_list_page_size),
    )


def _local_headers(ctx: BitBrowserClientContext) -> dict[str, str]:
    if not ctx.api_key:
        return {}
    return {"x-api-key": ctx.api_key}


def _post_local(
    ctx: BitBrowserClientContext,
    path: str,
    body: dict[str, Any],
    *,
    timeout_sec: float | None = None,
) -> dict[str, Any]:
    """调用 BitBrowser 本地服务。必须禁用走系统代理，否则可能请求失败。"""
    url = f"{ctx.base_url}{path}"
    headers = _local_headers(ctx)
    t = float(timeout_sec) if timeout_sec is not None else ctx.http_timeout_sec
    with httpx.Client(timeout=t, trust_env=False) as client:
        r = client.post(url, json=body, headers=headers or None)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code in (401, 403):
                if not headers:
                    raise RuntimeError(
                        "BitBrowser 返回未授权：客户端已开启本地 API 鉴权，请在「本机连接配置」中填写与比特浏览器「设置 → 本地 API」一致的 API Token"
                    ) from e
                raise RuntimeError(
                    "BitBrowser 返回未授权：请检查「本机连接配置」中的 API Token 是否与客户端完全一致"
                ) from e
            raise
        if not (r.content or b"").strip():
            return {}
        try:
            data = r.json()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"BitBrowser 返回非 JSON: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError("BitBrowser 返回非 JSON 对象")
    return data


def fetch_all_windows_from_local(ctx: BitBrowserClientContext) -> list[dict[str, Any]]:
    """分页调用 ``POST /browser/list``，拉取当前本地全部窗口。

    参考：<https://doc.bitbrowser.net/zh/api-jie-kou-wen-dang/liu-lan-qi-jie-kou>
    """
    all_rows: list[dict[str, Any]] = []
    page = 0
    page_size = min(100, max(1, ctx.list_page_size))
    while True:
        resp = _post_local(
            ctx,
            "/browser/list",
            {"page": page, "pageSize": page_size},
        )
        if not resp.get("success"):
            msg = resp.get("msg") or resp.get("message") or str(resp)
            raise RuntimeError(f"BitBrowser /browser/list 失败: {msg}")
        data = resp.get("data") or {}
        chunk = data.get("list") or []
        if not isinstance(chunk, list):
            raise RuntimeError("BitBrowser 返回 data.list 格式异常")
        all_rows.extend([x for x in chunk if isinstance(x, dict)])
        if len(chunk) < page_size:
            break
        page += 1
    logger.info("[BitBrowser] fetched {} windows from local service", len(all_rows))
    return all_rows


def _row_from_item(item: dict[str, Any]) -> dict[str, Any]:
    port = item.get("port")
    if port is not None and not isinstance(port, str):
        port = str(port)
    return {
        "browser_id": str(item.get("id") or "").strip(),
        "seq": item.get("seq") if item.get("seq") is not None else None,
        "name": (str(item["name"]).strip() if item.get("name") else None),
        "remark": (str(item["remark"]) if item.get("remark") else None),
        "platform": (str(item["platform"]) if item.get("platform") else None),
        "group_id": (str(item["groupId"]) if item.get("groupId") else None)
        or (str(item["group_id"]) if item.get("group_id") else None),
        "proxy_method": item.get("proxyMethod"),
        "proxy_type": (str(item["proxyType"]) if item.get("proxyType") else None),
        "host": (str(item["host"]) if item.get("host") else None),
        "port": port,
        "last_ip": (str(item["lastIp"]) if item.get("lastIp") else None)
        or (str(item["last_ip"]) if item.get("last_ip") else None),
        "account_username": (str(item["userName"]) if item.get("userName") else None)
        or (str(item["username"]) if item.get("username") else None),
        "status": item.get("status") if item.get("status") is not None else None,
        "raw_snapshot": item,
    }


def sync_windows_to_db(db: Session, user: User) -> dict[str, Any]:
    """从本地 BitBrowser 拉全量列表，按 owner 写入 ``bitbrowser_windows``（多出的旧行删除）。"""
    ctx = client_context_from_user(user)
    items = fetch_all_windows_from_local(ctx)
    fetched_ids: set[str] = set()

    upserted = 0
    for item in items:
        fields = _row_from_item(item)
        bid = fields["browser_id"]
        if not bid:
            continue
        fetched_ids.add(bid)
        row = (
            db.query(BitBrowserWindow)
            .filter(
                BitBrowserWindow.owner_id == user.id,
                BitBrowserWindow.browser_id == bid,
            )
            .one_or_none()
        )
        if row:
            for k, v in fields.items():
                setattr(row, k, v)
        else:
            db.add(BitBrowserWindow(owner_id=user.id, **fields))
        upserted += 1

    removed = 0
    if fetched_ids:
        res = db.execute(
            delete(BitBrowserWindow).where(
                BitBrowserWindow.owner_id == user.id,
                BitBrowserWindow.browser_id.not_in(fetched_ids),
            )
        )
        removed = res.rowcount or 0
    else:
        res = db.execute(delete(BitBrowserWindow).where(BitBrowserWindow.owner_id == user.id))
        removed = res.rowcount or 0

    owner_id = user.id
    if fetched_ids:
        db.execute(
            update(BitBrowserWindowCatalog)
            .where(
                BitBrowserWindowCatalog.owner_id == owner_id,
                BitBrowserWindowCatalog.browser_id.not_in(fetched_ids),
            )
            .values(in_local_cache=False)
        )
        db.execute(
            update(BitBrowserWindowCatalog)
            .where(
                BitBrowserWindowCatalog.owner_id == owner_id,
                BitBrowserWindowCatalog.browser_id.in_(fetched_ids),
            )
            .values(in_local_cache=True)
        )
    else:
        db.execute(
            update(BitBrowserWindowCatalog)
            .where(BitBrowserWindowCatalog.owner_id == owner_id)
            .values(in_local_cache=False)
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    u = db.get(User, user.id)
    if u is not None:
        u.bitbrowser_last_sync_at = now

    db.commit()
    return {
        "fetched": len(items),
        "upserted": upserted,
        "removed_stale": removed,
        "last_sync_at": now,
    }


def health_check_local(user: User) -> dict[str, Any]:
    """``POST /health`` 检测本地服务是否可用。"""
    ctx = client_context_from_user(user)
    return _post_local(ctx, "/health", {})


def open_browser_window(browser_id: str, user: User) -> dict[str, Any]:
    """``POST /browser/open`` 打开指定窗口，返回 ws / http / driver 等（见官方文档）。"""
    ctx = client_context_from_user(user)
    bid = (browser_id or "").strip()
    if not bid:
        raise ValueError("browser_id 不能为空")
    resp = _post_local(ctx, "/browser/open", {"id": bid}, timeout_sec=120.0)
    if not resp.get("success"):
        msg = resp.get("msg") or resp.get("message") or str(resp)
        raise RuntimeError(f"BitBrowser /browser/open 失败: {msg}")
    data = resp.get("data")
    if not isinstance(data, dict):
        return {}
    return data
