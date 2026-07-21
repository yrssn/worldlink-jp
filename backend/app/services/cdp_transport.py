"""CDP 传输层：直连或经浏览器中继访问窗口的 DevTools（WebSocket + /json/* HTTP）。

BitBrowser ``/browser/open`` 返回的 ``ws`` / ``http`` 地址是用户本机的
``127.0.0.1:<port>``。当后端部署在云服务器时无法直连，此时若该用户的
浏览器中继在线，则把 CDP WebSocket 与 DevTools HTTP 请求都通过中继
（管理端页面）转发到用户本机执行。
"""
from __future__ import annotations

from typing import Any

import httpx
from websockets.sync.client import connect

from app.services.bitbrowser_relay import relay_manager


def open_cdp(ws_url: str, user_id: int | None = None, *, open_timeout: float = 15.0):
    """连接页面 CDP WebSocket。返回对象提供 ``send``/``recv``/``close``。"""
    if user_id is not None and relay_manager.has_relay(user_id):
        return relay_manager.connect_cdp_sync(user_id, ws_url, open_timeout=open_timeout)
    return connect(ws_url, open_timeout=open_timeout)


def devtools_json(
    url: str,
    user_id: int | None = None,
    *,
    method: str = "GET",
    timeout: float = 15.0,
) -> Any:
    """请求 DevTools ``/json/*`` 接口，返回解析后的 JSON（dict/list），非 JSON 返回 None。"""
    if user_id is not None and relay_manager.has_relay(user_id):
        body = relay_manager.call_sync(
            user_id, "", None, method=method, url=url, timeout=timeout
        )
        return body if isinstance(body, (dict, list)) else None
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        r = client.request(method, url)
        if method == "PUT" and r.status_code in (404, 405):
            r = client.get(url)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:  # noqa: BLE001
            return None
