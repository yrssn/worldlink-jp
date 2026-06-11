from __future__ import annotations

import json
import time
from itertools import count
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from websockets.sync.client import connect


class CdpPage:
    def __init__(self, ws_url: str, user_id: int | None = None, *, relay_only: bool = False):
        self.ws_url = ws_url
        self.user_id = user_id
        self.relay_only = relay_only
        self._ids = count(1)
        self._ws = None

    def __enter__(self) -> "CdpPage":
        if self.relay_only:
            self._ensure_relay()
            return self
        try:
            self._ws = connect(self.ws_url, open_timeout=15)
        except Exception:
            if not self._use_relay():
                raise
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._ws is not None:
            self._ws.close()

    def _use_relay(self) -> bool:
        if self.user_id is None:
            return False
        from app.services.bitbrowser_relay import relay_manager

        return relay_manager.has_relay(self.user_id)

    def _ensure_relay(self) -> None:
        if not self._use_relay():
            raise RuntimeError("服务器无法直连本机 BitBrowser CDP，请保持管理后台页面打开以建立浏览器中继")

    def call(
        self,
        method: str,
        params: dict[str, object] | None = None,
        *,
        timeout: float = 15,
    ) -> dict[str, object]:
        msg_id = next(self._ids)
        message = {"id": msg_id, "method": method, "params": params or {}}
        if self._ws is not None:
            try:
                return self._call_direct(message, msg_id, method, timeout)
            except Exception:
                if not self._use_relay():
                    raise
        if self._use_relay():
            from app.services.bitbrowser_relay import relay_manager

            data = relay_manager.call_sync(
                self.user_id,
                "__cdp/call",
                {"ws_url": self.ws_url, "message": message},
                timeout=timeout,
            )
            if data.get("error"):
                raise RuntimeError(f"CDP 调用失败 {method}: {data['error']}")
            result = data.get("result") or {}
            return result if isinstance(result, dict) else {}

        raise RuntimeError("CDP 未连接")

    def _call_direct(
        self,
        message: dict[str, object],
        msg_id: int,
        method: str,
        timeout: float,
    ) -> dict[str, object]:
        if self._ws is None:
            raise RuntimeError("CDP 未连接")
        self._ws.send(json.dumps(message))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f"CDP 调用超时: {method}")
            raw = self._ws.recv(timeout=remaining)
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                continue
            data: dict[str, object] = parsed
            if data.get("id") != msg_id:
                continue
            if data.get("error"):
                raise RuntimeError(f"CDP 调用失败 {method}: {data['error']}")
            result = data.get("result") or {}
            return result if isinstance(result, dict) else {}

    def evaluate(self, expression: str, *, timeout: float = 15) -> object:
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
            timeout=timeout,
        )
        remote = result.get("result") or {}
        if not isinstance(remote, dict):
            return None
        return remote.get("value")

    def click(self, x: float, y: float) -> None:
        params = {"x": x, "y": y, "button": "left", "clickCount": 1}
        self.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y}, timeout=5)
        self.call("Input.dispatchMouseEvent", {"type": "mousePressed", **params}, timeout=5)
        self.call("Input.dispatchMouseEvent", {"type": "mouseReleased", **params}, timeout=5)


def devtools_request(
    http_base: str,
    path: str,
    *,
    method: str = "GET",
    user_id: int | None = None,
    timeout: float = 15,
) -> Any:
    base = http_base.rstrip("/") + "/"
    url = urljoin(base, path.lstrip("/"))
    if user_id is not None:
        from app.services.bitbrowser_relay import relay_manager

        if relay_manager.has_relay(user_id):
            data = relay_manager.call_sync(
                user_id,
                "__http/request",
                {"url": url, "method": method},
                timeout=timeout,
            )
            status = int(data.get("status") or 0)
            if status >= 400:
                raise RuntimeError(f"DevTools HTTP {method} {url} 失败: {status}")
            return data.get("body")

    with httpx.Client(timeout=timeout, trust_env=False) as client:
        response = client.request(method, url)
        response.raise_for_status()
        if not (response.content or b"").strip():
            return None
        return response.json()


def _is_loopback_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def target_ws_url(browser_ws_url: str, target_id: str) -> str:
    prefix, _, _browser_id = browser_ws_url.rpartition("/devtools/browser/")
    if not prefix:
        raise RuntimeError("BitBrowser CDP WebSocket 地址格式异常")
    return f"{prefix}/devtools/page/{target_id}"


def create_cdp_target(
    browser_ws_url: str,
    url: str,
    *,
    user_id: int | None = None,
    relay_only: bool = False,
) -> str:
    with CdpPage(browser_ws_url, user_id=user_id, relay_only=relay_only) as browser:
        result = browser.call("Target.createTarget", {"url": url}, timeout=15)
    target_id = str(result.get("targetId") or "")
    if not target_id:
        raise RuntimeError("创建浏览器页面失败：CDP 未返回 targetId")
    return target_ws_url(browser_ws_url, target_id)


def list_cdp_targets(
    browser_ws_url: str,
    *,
    user_id: int | None = None,
    relay_only: bool = False,
) -> list[dict[str, Any]]:
    with CdpPage(browser_ws_url, user_id=user_id, relay_only=relay_only) as browser:
        result = browser.call("Target.getTargets", timeout=10)
    targets = result.get("targetInfos") or []
    return [t for t in targets if isinstance(t, dict)]


def activate_cdp_target(
    browser_ws_url: str,
    target_id: str,
    *,
    user_id: int | None = None,
    relay_only: bool = False,
) -> None:
    with CdpPage(browser_ws_url, user_id=user_id, relay_only=relay_only) as browser:
        browser.call("Target.activateTarget", {"targetId": target_id}, timeout=10)


def close_cdp_target(
    browser_ws_url: str,
    target_id: str,
    *,
    user_id: int | None = None,
    relay_only: bool = False,
) -> None:
    with CdpPage(browser_ws_url, user_id=user_id, relay_only=relay_only) as browser:
        browser.call("Target.closeTarget", {"targetId": target_id}, timeout=10)
