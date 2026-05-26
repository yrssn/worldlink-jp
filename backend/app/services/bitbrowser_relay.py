"""BitBrowser 浏览器中继管理器。

工作流程
--------
1. 浏览器前端在登录后自动建立 WebSocket 连接（``/api/v1/bitbrowser/relay/ws``）。
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
import uuid
from typing import Any

from loguru import logger


class BitBrowserRelayManager:
    def __init__(self) -> None:
        self._connections: dict[int, Any] = {}          # user_id -> WebSocket
        self._pending: dict[str, asyncio.Future] = {}   # req_id  -> Future
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── 事件循环引用（在 lifespan / startup 中保存）─────────────────
    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ── 连接状态 ────────────────────────────────────────────────────
    def has_relay(self, user_id: int) -> bool:
        return user_id in self._connections

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
                fut = self._pending.pop(req_id, None)
                if fut is None or fut.done():
                    continue
                if "error" in data:
                    fut.set_exception(RuntimeError(data["error"]))
                else:
                    fut.set_result(data.get("body") or {})
        except Exception as e:  # noqa: BLE001
            logger.info("[BitBrowserRelay] user {} relay disconnected: {}", user_id, e)
        finally:
            self._connections.pop(user_id, None)
            # 让等待中的请求立即失败
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_exception(RuntimeError("BitBrowser 中继连接已断开"))
            self._pending.clear()

    # ── 异步调用（供 async 路由使用）───────────────────────────────
    async def call_async(
        self,
        user_id: int,
        path: str,
        body: dict[str, Any],
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        ws = self._connections.get(user_id)
        if ws is None:
            raise RuntimeError(
                "BitBrowser 中继未连接——请确保管理端页面已打开且中继已启用"
            )
        req_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut
        try:
            await ws.send_json(
                {"type": "req", "id": req_id, "method": "POST", "path": path, "body": body}
            )
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
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """从同步代码中阻塞式调用异步中继（线程安全）。"""
        loop = self._loop
        if loop is None or not loop.is_running():
            raise RuntimeError("BitBrowser 中继事件循环未就绪，请重启后端服务")
        future = asyncio.run_coroutine_threadsafe(
            self.call_async(user_id, path, body, timeout=timeout), loop
        )
        try:
            return future.result(timeout=timeout + 5)
        except TimeoutError:
            raise RuntimeError(f"BitBrowser 中继同步调用超时（{timeout + 5:.0f}s）")


relay_manager = BitBrowserRelayManager()
