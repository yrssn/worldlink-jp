"""CDP 传输层：直连或经浏览器中继访问窗口的 DevTools。

BitBrowser ``/browser/open`` 返回的 ``ws`` / ``http`` 地址是用户本机的
``127.0.0.1:<port>``。当后端部署在云服务器时无法直连，此时若该用户的
浏览器中继在线，则把 CDP WebSocket 通过中继（管理端页面）转发到用户
本机执行。

标签页管理（新建/列出/关闭/激活）统一走浏览器级 CDP WebSocket 的
``Target.*`` 命令，而不是 DevTools 的 ``/json/*`` HTTP 接口——后者没有
CORS 头，中继页面 fetch 会被浏览器拦截（Failed to fetch）。
"""
from __future__ import annotations

import json
import time
from itertools import count
from typing import Any
from urllib.parse import urlparse

from websockets.sync.client import connect

from app.services.bitbrowser_relay import relay_manager

_RELAY_HINT = (
    "无法直连窗口 CDP（{host}），且当前用户的浏览器中继未连接。"
    "若 BitBrowser 与后端不在同一台电脑：请在 BitBrowser 所在电脑用浏览器打开管理端页面"
    "（比特抓取 → 本机连接），确认中继显示「已连接」后重试；"
    "若在同一台电脑：请确认该窗口仍在运行（可先关再开该环境后重试）。"
)


def _loopback_hint(url: str, cause: Exception) -> RuntimeError:
    host = urlparse(url).hostname or url
    return RuntimeError(_RELAY_HINT.format(host=host) + f"（原始错误: {cause}）")


def open_cdp(ws_url: str, user_id: int | None = None, *, open_timeout: float = 15.0):
    """连接 CDP WebSocket。返回对象提供 ``send``/``recv``/``close``。"""
    if user_id is not None and relay_manager.has_relay(user_id):
        return relay_manager.connect_cdp_sync(user_id, ws_url, open_timeout=open_timeout)
    try:
        return connect(ws_url, open_timeout=open_timeout)
    except (OSError, TimeoutError) as e:
        raise _loopback_hint(ws_url, e) from e


def extract_browser_ws(open_data: dict[str, Any]) -> str:
    """从 ``/browser/open`` 返回中取浏览器级 CDP WebSocket 地址。"""
    raw_ws = str(open_data.get("ws") or "").strip()
    if raw_ws:
        return raw_ws
    raw_http = str(open_data.get("http") or "").strip()
    if raw_http:
        # 极端兜底：只有 http 地址时无法得到 browser GUID，直接报错更清晰
        raise RuntimeError("BitBrowser /browser/open 未返回 ws CDP 地址（仅有 http）；请先关再开该环境后重试")
    raise RuntimeError("BitBrowser /browser/open 返回中缺少 ws CDP 地址")


def page_ws_url(browser_ws: str, target_id: str) -> str:
    netloc = urlparse(browser_ws).netloc
    return f"ws://{netloc}/devtools/page/{target_id}"


def browser_cdp_call(
    browser_ws: str,
    method: str,
    params: dict[str, Any] | None = None,
    user_id: int | None = None,
    *,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """在浏览器级 CDP WebSocket 上执行单个命令并返回 result。"""
    sock = open_cdp(browser_ws, user_id, open_timeout=timeout)
    try:
        msg_id = next(count(1))
        sock.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f"浏览器 CDP 调用超时: {method}")
            try:
                raw = sock.recv(timeout=remaining)
            except TimeoutError:
                continue
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("id") != msg_id:
                continue
            if data.get("error"):
                raise RuntimeError(f"浏览器 CDP 调用失败 {method}: {data['error']}")
            result = data.get("result") or {}
            return result if isinstance(result, dict) else {}
    finally:
        try:
            sock.close()
        except Exception:  # noqa: BLE001
            pass


def create_page(
    browser_ws: str, url: str, user_id: int | None = None
) -> tuple[str, str]:
    """新建标签页（Target.createTarget），返回 (page_ws, target_id)。"""
    result = browser_cdp_call(
        browser_ws, "Target.createTarget", {"url": url}, user_id
    )
    target_id = str(result.get("targetId") or "")
    if not target_id:
        raise RuntimeError("Target.createTarget 未返回 targetId")
    return page_ws_url(browser_ws, target_id), target_id


def list_pages(browser_ws: str, user_id: int | None = None) -> list[dict[str, Any]]:
    """列出 page 类型 target，返回兼容 ``/json/list`` 的字段结构。"""
    result = browser_cdp_call(browser_ws, "Target.getTargets", None, user_id)
    infos = result.get("targetInfos")
    pages: list[dict[str, Any]] = []
    if not isinstance(infos, list):
        return pages
    for info in infos:
        if not isinstance(info, dict) or str(info.get("type") or "") != "page":
            continue
        target_id = str(info.get("targetId") or "")
        pages.append(
            {
                "id": target_id,
                "type": "page",
                "url": str(info.get("url") or ""),
                "webSocketDebuggerUrl": page_ws_url(browser_ws, target_id) if target_id else "",
            }
        )
    return pages


def close_target(browser_ws: str, target_id: str, user_id: int | None = None) -> None:
    browser_cdp_call(browser_ws, "Target.closeTarget", {"targetId": target_id}, user_id)


def activate_target(browser_ws: str, target_id: str, user_id: int | None = None) -> None:
    browser_cdp_call(browser_ws, "Target.activateTarget", {"targetId": target_id}, user_id)
