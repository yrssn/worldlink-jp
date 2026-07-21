"""比特浏览器 BitBrowser 本地 HTTP 客户端（连接信息按用户存储，见 User.bitbrowser_*）。"""
from __future__ import annotations

import time
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
from app.services import bitbrowser_open_cache as open_cache


@dataclass(frozen=True)
class BitBrowserClientContext:
    """单次请求使用的 BitBrowser Local 连接参数（来自当前登录用户）。"""

    base_url: str
    api_key: str | None
    http_timeout_sec: float
    list_page_size: int
    user_id: int | None = None  # 用于中继路由


def client_context_from_user(user: User) -> BitBrowserClientContext:
    raw = (getattr(user, "bitbrowser_local_url", None) or "").strip()
    if not raw:
        raise ValueError(
            "请先在「本机连接配置」中填写 BitBrowser 本地服务地址（与客户端「设置 → 本地 API」中的地址一致，例如 http://127.0.0.1:54345）"
        )
    base = raw.rstrip("/")
    tok = (
        (getattr(user, "bitbrowser_api_key", None) or "").strip()
        or (settings.bitbrowser_api_key or "").strip()
        or None
    )
    return BitBrowserClientContext(
        base_url=base,
        api_key=tok,
        http_timeout_sec=float(settings.bitbrowser_http_timeout_sec),
        list_page_size=int(settings.bitbrowser_list_page_size),
        user_id=user.id,
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
    """调用 BitBrowser 本地服务。若有浏览器中继则通过 WebSocket 转发，否则直连。"""
    # ── 优先走浏览器中继（公网部署 + 本地 BitBrowser 场景）──────────
    if ctx.user_id is not None:
        from app.services.bitbrowser_relay import relay_manager  # 延迟导入避免循环
        if relay_manager.has_relay(ctx.user_id):
            t = float(timeout_sec) if timeout_sec is not None else ctx.http_timeout_sec
            logger.debug("[BitBrowser] relay path: user={} {}", ctx.user_id, path)
            return relay_manager.call_sync(
                ctx.user_id, path, body, headers=_local_headers(ctx) or None, timeout=t
            )
    # ── 直连 ─────────────────────────────────────────────────────────
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


def _coerce_pids_map(m: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for k, v in m.items():
        ks = str(k).strip()
        if not ks:
            continue
        try:
            out[ks] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def _parse_pids_response(body: dict[str, Any]) -> dict[str, int]:
    if body.get("success") is False:
        msg = body.get("msg") or body.get("message") or str(body)
        raise RuntimeError(f"BitBrowser 查询运行中窗口失败: {msg}")
    data = body.get("data")
    if isinstance(data, dict) and data:
        return _coerce_pids_map(data)
    skip = {"success", "msg", "message", "code", "data"}
    cand = {k: v for k, v in body.items() if k not in skip}
    return _coerce_pids_map(cand) if cand else {}


def fetch_browser_pids(user: User, browser_ids: list[str]) -> dict[str, int]:
    """``POST /browser/pids``：查询给定窗口是否已在运行（browser_id -> pid）。"""
    ctx = client_context_from_user(user)
    ids = [str(x).strip() for x in browser_ids if str(x).strip()]
    if not ids:
        return {}
    body = _post_local(ctx, "/browser/pids", {"ids": ids}, timeout_sec=30.0)
    return _parse_pids_response(body)


def fetch_all_open_pids(user: User) -> dict[str, int]:
    """``POST /browser/pids/all``：本机所有存活已打开窗口（无参数，自动过滤死进程）。"""
    ctx = client_context_from_user(user)
    body = _post_local(ctx, "/browser/pids/all", {}, timeout_sec=30.0)
    return _parse_pids_response(body)


def user_browser_id_set(db: Session, user_id: int) -> set[str]:
    """当前登录用户在系统内出现过的 browser_id（缓存表 + 登记表）。"""
    w_ids = {
        r[0]
        for r in db.query(BitBrowserWindow.browser_id)
        .filter(BitBrowserWindow.owner_id == user_id)
        .all()
    }
    c_ids = {
        r[0]
        for r in db.query(BitBrowserWindowCatalog.browser_id)
        .filter(BitBrowserWindowCatalog.owner_id == user_id)
        .all()
    }
    return w_ids | c_ids


def list_running_windows_for_user(db: Session, user: User) -> list[dict[str, Any]]:
    """合并 ``pids/all`` 与当前用户窗口/登记，返回运行中列表。"""
    known = user_browser_id_set(db, user.id)
    if not known:
        return []
    try:
        all_pids = fetch_all_open_pids(user)
    except Exception as e:  # noqa: BLE001
        logger.warning("[BitBrowser] pids/all failed: {}", e)
        return []
    user_open = {k: v for k, v in all_pids.items() if k in known}
    open_cache.prune_stale(user.id, set(user_open.keys()))
    if not user_open:
        return []

    cached_opens = open_cache.list_open_results(user.id)
    bids = list(user_open.keys())
    win_rows = (
        db.query(BitBrowserWindow)
        .filter(BitBrowserWindow.owner_id == user.id, BitBrowserWindow.browser_id.in_(bids))
        .all()
    )
    id_to_win = {r.browser_id: r for r in win_rows}
    missing = [b for b in bids if b not in id_to_win]
    id_to_cat: dict[str, BitBrowserWindowCatalog] = {}
    if missing:
        cats = (
            db.query(BitBrowserWindowCatalog)
            .filter(
                BitBrowserWindowCatalog.owner_id == user.id,
                BitBrowserWindowCatalog.browser_id.in_(missing),
            )
            .all()
        )
        id_to_cat = {c.browser_id: c for c in cats}

    def _cache_for_bid(bid: str) -> dict[str, Any]:
        for headless in (True, False):
            fk = open_cache.field_key(bid, headless)
            if fk in cached_opens:
                return cached_opens[fk]
        legacy = cached_opens.get(bid)
        return legacy if isinstance(legacy, dict) else {}

    items: list[dict[str, Any]] = []
    for bid in sorted(user_open.keys()):
        pid = user_open[bid]
        w = id_to_win.get(bid)
        c = id_to_cat.get(bid)
        cached = _cache_for_bid(bid)
        open_data = cached.get("data") if isinstance(cached.get("data"), dict) else {}
        items.append(
            {
                "browser_id": bid,
                "pid": pid,
                "name": (w.name if w else None) or (c.cached_window_name if c else None),
                "seq": w.seq if w else None,
                "platform": (w.platform if w else None) or (c.cached_env_platform if c else None),
                "headless": bool(cached.get("headless")),
                "opened_at": cached.get("opened_at"),
                "hint": cached.get("hint"),
                "open_data": open_data,
            }
        )
    return items


def close_browser_window(browser_id: str, user: User) -> bool:
    """``POST /browser/close`` 关闭指定窗口（未打开时忽略失败）。"""
    ctx = client_context_from_user(user)
    bid = (browser_id or "").strip()
    if not bid:
        return False
    try:
        resp = _post_local(ctx, "/browser/close", {"id": bid}, timeout_sec=60.0)
        ok = bool(resp.get("success"))
        if ok:
            open_cache.remove_open_result(user.id, bid)
        return ok
    except Exception as e:  # noqa: BLE001
        logger.debug("[BitBrowser] close {} ignored: {}", bid, e)
        return False


def clear_browser_profile_cookies(browser_id: str, user: User) -> dict[str, bool]:
    """清理指定环境的 Cookie 缓存与配置 Cookie 字段，避免启动时重新注入旧登录态。"""
    ctx = client_context_from_user(user)
    bid = (browser_id or "").strip()
    if not bid:
        return {"cookies_cleared": False, "profile_cookie_cleared": False}

    cookies_cleared = False
    try:
        resp = _post_local(
            ctx,
            "/browser/cookies/clear",
            {"browserId": bid, "saveSynced": False},
            timeout_sec=60.0,
        )
        cookies_cleared = bool(resp.get("success"))
        if not cookies_cleared:
            logger.debug("[BitBrowser] cookies/clear {} returned: {}", bid, resp)
    except Exception as e:  # noqa: BLE001
        logger.debug("[BitBrowser] cookies/clear {} skipped: {}", bid, e)

    profile_cookie_cleared = False
    try:
        resp = _post_local(
            ctx,
            "/browser/update/partial",
            {
                "ids": [bid],
                "cookie": "",
                "clearCookiesBeforeLaunch": True,
                "clearCacheFilesBeforeLaunch": True,
            },
            timeout_sec=60.0,
        )
        profile_cookie_cleared = bool(resp.get("success"))
        if not profile_cookie_cleared:
            logger.debug("[BitBrowser] update/partial cookie {} returned: {}", bid, resp)
    except Exception as e:  # noqa: BLE001
        logger.debug("[BitBrowser] update/partial cookie {} skipped: {}", bid, e)

    return {
        "cookies_cleared": cookies_cleared,
        "profile_cookie_cleared": profile_cookie_cleared,
    }


def _build_open_payload(browser_id: str, *, headless: bool, ignore_default_urls: bool = False) -> dict[str, Any]:
    # --remote-allow-origins=*：允许任意 Origin 连接窗口的 DevTools WebSocket，
    # 浏览器中继（管理端页面）转发 CDP 时需要（Chrome 111+ 默认拒绝跨源握手）
    args: list[str] = ["--remote-allow-origins=*"]
    payload: dict[str, Any] = {"id": browser_id, "queue": True, "args": args}
    if ignore_default_urls:
        payload["ignoreDefaultUrls"] = True
    if headless:
        raw = (getattr(settings, "bitbrowser_headless_chrome_args", None) or "--headless").strip()
        parts = [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]
        args.extend(parts if parts else ["--headless"])
        payload["ignoreDefaultUrls"] = True
    return payload


def _post_browser_open(user: User, payload: dict[str, Any]) -> dict[str, Any]:
    """调用 ``POST /browser/open``，成功返回 data 字典，失败抛 RuntimeError。"""
    ctx = client_context_from_user(user)
    last_msg = ""
    for attempt in range(1, 4):
        resp = _post_local(ctx, "/browser/open", payload, timeout_sec=120.0)
        if resp.get("success"):
            raw = resp.get("data")
            return raw if isinstance(raw, dict) else {}
        last_msg = str(resp.get("msg") or resp.get("message") or resp)
        if attempt < 3 and _bb_open_should_retry(last_msg):
            time.sleep(2.0 * attempt)
            continue
        raise RuntimeError(f"BitBrowser /browser/open 失败: {last_msg}")
    raise RuntimeError(f"BitBrowser /browser/open 失败: {last_msg}")


def _bb_open_should_retry(msg: str) -> bool:
    if not msg:
        return False
    m = msg.lower()
    if any(k in msg for k in ("频率", "重试", "请稍后", "稍后再试", "过于频繁")):
        return True
    if any(k in m for k in ("rate", "too many", "try again", "busy", "throttl", "frequency")):
        return True
    return False


def open_browser_window(
    browser_id: str,
    user: User,
    db: Session,
    *,
    headless: bool = False,
    restart: bool = False,
    ignore_default_urls: bool = False,
) -> dict[str, Any]:
    """``POST /browser/open`` 打开指定窗口，返回 ws / http / driver 等（见官方文档）。

    策略说明（BitBrowser 同一 ``browser_id`` 在 ``pids`` 中仅一个进程，无头/可见不能并存）：
    - **不同环境**可同时运行，不会自动关闭其它窗口。
    - **同环境 + 同模式**已在运行：再次 ``open`` 以获取/刷新连接（官方已开时通常直接返回 ws/http），并返回 ``already_open=True``。
    - **同环境 + 切换无头/可见**：先 ``close`` 再以目标模式 ``open``（或 ``restart=True``）。
    """
    bid = (browser_id or "").strip()
    if not bid:
        raise ValueError("browser_id 不能为空")

    known = user_browser_id_set(db, user.id)
    user_running: dict[str, int] = {}
    try:
        all_pids = fetch_all_open_pids(user)
        user_running = {k: v for k, v in all_pids.items() if k in known}
    except Exception as e:  # noqa: BLE001
        logger.debug("[BitBrowser] pids/all before open skipped: {}", e)

    is_running = bid in user_running
    pid = user_running.get(bid)
    mode_cached = open_cache.get_open_result(user.id, bid, headless=headless)
    any_cached = open_cache.get_any_open_result(user.id, bid) if is_running else None
    restarted = False
    mode_switched = False

    if restart and is_running:
        close_browser_window(bid, user)
        open_cache.remove_open_result(user.id, bid, headless=None)
        restarted = True
        is_running = False
        time.sleep(0.6)

    # 运行中且要切换无头/可见：先关再开
    elif is_running and any_cached is not None and bool(any_cached.get("headless")) != headless:
        close_browser_window(bid, user)
        open_cache.remove_open_result(user.id, bid, headless=None)
        mode_switched = True
        is_running = False
        time.sleep(0.6)

    payload = _build_open_payload(bid, headless=headless, ignore_default_urls=ignore_default_urls)

    # 同模式已运行：再调 open 唤起/刷新连接（官方无单独 focus 接口）
    if is_running and not restart:
        reconnected = False
        data: dict[str, Any] = {}
        try:
            data = _post_browser_open(user, payload)
            reconnected = bool(data)
        except Exception as e:  # noqa: BLE001
            logger.debug("[BitBrowser] reopen while running failed: {}", e)
            if mode_cached and isinstance(mode_cached.get("data"), dict):
                data = mode_cached["data"]

        if not data and mode_cached and isinstance(mode_cached.get("data"), dict):
            data = mode_cached["data"]

        mode_label = "无头" if headless else "可见"
        if data:
            hint = (
                f"该环境已在运行（PID {pid}），已{'重新获取' if reconnected else '从缓存读取'} {mode_label} 模式连接信息。"
                " 可见模式请到 BitBrowser 客户端查看窗口是否被遮挡。"
            )
            open_cache.save_open_result(
                user.id, bid, data=data, pid=pid, headless=headless, hint=hint
            )
            return {
                "data": data,
                "headless": headless,
                "restarted": False,
                "already_open": True,
                "reconnected": reconnected,
                "pid": pid,
                "closed_other_ids": [],
                "mode_switched": False,
                "hint": hint,
            }

        hint = (
            f"该环境已在运行（PID {pid}），但未能获取 {mode_label} 连接信息。"
            " 请点「先关再开」后重试。"
        )
        return {
            "data": {},
            "headless": headless,
            "restarted": False,
            "already_open": True,
            "reconnected": False,
            "pid": pid,
            "closed_other_ids": [],
            "mode_switched": False,
            "hint": hint,
        }

    data = _post_browser_open(user, payload)

    hint_parts: list[str] = []
    if mode_switched:
        hint_parts.append(f"已从{'无头' if not headless else '可见'}切换为{'无头' if headless else '可见'}模式并重新打开。")
    if restarted:
        hint_parts.append("已先关闭再打开。")
    if headless:
        hint_parts.append("无头模式无界面；连接信息见 ws / http。")
    elif not mode_switched and not restarted:
        hint_parts.append("可见模式应弹出 BitBrowser 窗口。")
    hint = " ".join(hint_parts) if hint_parts else None

    open_pid: int | None = None
    try:
        open_pid = fetch_browser_pids(user, [bid]).get(bid)
    except Exception as e:  # noqa: BLE001
        logger.debug("[BitBrowser] pids after open skipped: {}", e)

    if data:
        open_cache.save_open_result(
            user.id, bid, data=data, pid=open_pid, headless=headless, hint=hint
        )

    return {
        "data": data,
        "headless": headless,
        "restarted": restarted,
        "already_open": False,
        "reconnected": False,
        "pid": open_pid,
        "closed_other_ids": [],
        "mode_switched": mode_switched,
        "hint": hint,
    }
