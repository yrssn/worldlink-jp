"""BitBrowser 浏览器中继管理器。

工作流程
--------
1. 浏览器前端在登录后自动建立中继连接（优先 WebSocket，失败后 HTTP polling）。
2. 后端需要调用 BitBrowser Local API 时，若当前用户有中继连接，
   则通过 WebSocket 把请求转发给前端；前端在用户本机上执行 fetch，
   再把结果原路回传。
3. 若无中继连接，降级为直接 HTTP（即原有行为）。

WS 协议
-------
- 后端 → 前端：``{"type":"req","id":"<uuid>","method":"POST","path":"/browser/list","body":{...}}``
- 前端 → 后端：``{"type":"res","id":"<uuid>","body":{...}}``
                  或 ``{"type":"res","id":"<uuid>","error":"Connection refused"}``
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from loguru import logger


class BitBrowserRelayManager:
    def __init__(self) -> None:
        self._connections: dict[int, Any] = {}          # user_id -> WebSocket
        self._pending: dict[str, tuple[asyncio.Future, int]] = {}   # req_id -> (Future, user_id)
        self._poll_queues: dict[int, asyncio.Queue] = {}
        self._poll_last_seen: dict[int, float] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── 事件循环引用（在 lifespan / startup 中保存）─────────────────
    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ── 连接状态 ────────────────────────────────────────────────────
    def has_relay(self, user_id: int) -> bool:
        if user_id in self._connections:
            return True
        last_seen = self._poll_last_seen.get(user_id)
        if last_seen is None:
            return False
        if time.monotonic() - last_seen <= 45:
            return True
        self._poll_last_seen.pop(user_id, None)
        self._poll_queues.pop(user_id, None)
        return False

    def connected_user_ids(self) -> list[int]:
        return list(self._connections.keys())

    # ── WebSocket 生命周期（async，在路由中 await）──────────────────
    async def connect(self, user_id: int, ws: Any) -> None:
        """持续接收前端消息，直到 WebSocket 断开。"""
        old = self._connections.get(user_id)
        if old is not None:
            try:
                await old.close()
            except Exception:  # noqa: BLE001
                pass
        self._connections[user_id] = ws
        logger.info("[BitBrowserRelay] user {} relay connected", user_id)
        try:
            while True:
                data = await ws.receive_json()
                if not isinstance(data, dict):
                    continue
                if data.get("type") != "res":
                    continue
                req_id = data.get("id")
                if isinstance(req_id, str):
                    self._finish_pending(req_id, data)
        except Exception as e:  # noqa: BLE001
            logger.info("[BitBrowserRelay] user {} relay disconnected: {}", user_id, e)
        finally:
            self._connections.pop(user_id, None)
            # 让该 WebSocket 上等待中的请求立即失败；polling 兜底会接管后续请求
            for req_id, (fut, pending_user_id) in list(self._pending.items()):
                if pending_user_id != user_id:
                    continue
                if not fut.done():
                    fut.set_exception(RuntimeError("BitBrowser 中继连接已断开"))
                self._pending.pop(req_id, None)

    # ── HTTP polling 兜底（适配服务器/反代不支持 WebSocket Upgrade 的部署）────
    async def poll(self, user_id: int, *, timeout: float = 25.0) -> dict[str, Any]:
        self._poll_last_seen[user_id] = time.monotonic()
        queue = self._poll_queues.setdefault(user_id, asyncio.Queue())
        try:
            req = await asyncio.wait_for(queue.get(), timeout=timeout)
            self._poll_last_seen[user_id] = time.monotonic()
            return req
        except asyncio.TimeoutError:
            self._poll_last_seen[user_id] = time.monotonic()
            return {"type": "noop"}

    async def respond(self, user_id: int, data: dict[str, Any]) -> None:
        req_id = data.get("id")
        if not isinstance(req_id, str):
            return
        entry = self._pending.get(req_id)
        if entry is None or entry[1] != user_id:
            return
        self._finish_pending(req_id, data)

    def _finish_pending(self, req_id: str, data: dict[str, Any]) -> None:
        entry = self._pending.pop(req_id, None)
        if entry is None:
            return
        fut, _user_id = entry
        if fut.done():
            return
        if "error" in data:
            fut.set_exception(RuntimeError(str(data["error"])))
        elif int(data.get("status") or 0) >= 400:
            status = int(data.get("status") or 0)
            body = data.get("body")
            if status in (401, 403):
                fut.set_exception(
                    RuntimeError(
                        "BitBrowser 返回未授权：请检查「本机连接配置」中的 API Token "
                        "是否与比特浏览器「设置 → 本地 API」完全一致"
                    )
                )
            else:
                fut.set_exception(RuntimeError(f"BitBrowser 本地接口返回 HTTP {status}: {body}"))
        else:
            fut.set_result(data.get("body") or {})

    # ── 异步调用（供 async 路由使用）───────────────────────────────
    async def call_async(
        self,
        user_id: int,
        path: str,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        ws = self._connections.get(user_id)
        polling_connected = self.has_relay(user_id)
        if ws is None and not polling_connected:
            raise RuntimeError(
                "BitBrowser 中继未连接——请确保管理端页面已打开且中继已启用"
            )
        req_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = (fut, user_id)
        req = {
            "type": "req",
            "id": req_id,
            "method": "POST",
            "path": path,
            "body": body,
            "headers": headers or {},
        }
        try:
            if ws is not None:
                await ws.send_json(req)
            else:
                queue = self._poll_queues.setdefault(user_id, asyncio.Queue())
                await queue.put(req)
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise RuntimeError(f"BitBrowser 中继请求超时（{timeout:.0f}s）")

    # ── 同步调用（供 FastAPI 线程池中的同步端点使用）────────────────
    def call_sync(
        self,
        user_id: int,
        path: str,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """从同步代码中阻塞式调用异步中继（线程安全）。"""
        loop = self._loop
        if loop is None or not loop.is_running():
            raise RuntimeError("BitBrowser 中继事件循环未就绪，请重启后端服务")
        future = asyncio.run_coroutine_threadsafe(
            self.call_async(user_id, path, body, headers=headers, timeout=timeout), loop
        )
        try:
            return future.result(timeout=timeout + 5)
        except TimeoutError:
            raise RuntimeError(f"BitBrowser 中继同步调用超时（{timeout + 5:.0f}s）")


relay_manager = BitBrowserRelayManager()
