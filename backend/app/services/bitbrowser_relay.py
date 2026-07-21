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
  （若带 ``url`` 则直接请求该绝对地址，用于 DevTools ``/json/*`` 接口）
- 前端 → 后端：``{"type":"res","id":"<uuid>","body":{...}}``
                  或 ``{"type":"res","id":"<uuid>","error":"Connection refused"}``

CDP 隧道（让后端能操作用户本机窗口的 DevTools WebSocket）
------------------------------------------------------------
- 后端 → 前端：``{"type":"cdp_open","id":"<tid>","url":"ws://127.0.0.1:.../devtools/page/..."}``
- 前端 → 后端：``{"type":"cdp_opened","id":"<tid>"}`` 或 ``{"type":"cdp_opened","id":"<tid>","error":"..."}``
- 双向消息：``{"type":"cdp_msg","id":"<tid>","data":"<CDP JSON 文本>"}``
- 关闭：``{"type":"cdp_close","id":"<tid>"}``（后端发起）/ ``{"type":"cdp_closed","id":"<tid>"}``（前端通知）
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from loguru import logger


class _CdpTunnel:
    def __init__(self, user_id: int, loop: asyncio.AbstractEventLoop) -> None:
        self.user_id = user_id
        self.opened: asyncio.Future = loop.create_future()
        self.inbox: asyncio.Queue[str | None] = asyncio.Queue()
        self.closed = False


class BitBrowserRelayManager:
    def __init__(self) -> None:
        self._connections: dict[int, Any] = {}          # user_id -> WebSocket
        self._pending: dict[str, asyncio.Future] = {}   # req_id  -> Future
        self._tunnels: dict[str, _CdpTunnel] = {}       # tunnel_id -> _CdpTunnel
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
                msg_type = data.get("type")
                if msg_type == "res":
                    req_id = data.get("id")
                    fut = self._pending.pop(req_id, None)
                    if fut is None or fut.done():
                        continue
                    if "error" in data:
                        fut.set_exception(RuntimeError(data["error"]))
                    else:
                        fut.set_result(data.get("body") or {})
                elif msg_type == "cdp_opened":
                    tunnel = self._tunnels.get(str(data.get("id")))
                    if tunnel is None or tunnel.opened.done():
                        continue
                    if "error" in data:
                        tunnel.opened.set_exception(RuntimeError(str(data["error"])))
                    else:
                        tunnel.opened.set_result(True)
                elif msg_type == "cdp_msg":
                    tunnel = self._tunnels.get(str(data.get("id")))
                    if tunnel is not None and not tunnel.closed:
                        tunnel.inbox.put_nowait(str(data.get("data") or ""))
                elif msg_type == "cdp_closed":
                    tid = str(data.get("id"))
                    tunnel = self._tunnels.pop(tid, None)
                    if tunnel is not None:
                        tunnel.closed = True
                        tunnel.inbox.put_nowait(None)
                        if not tunnel.opened.done():
                            tunnel.opened.set_exception(
                                RuntimeError(str(data.get("error") or "CDP 隧道已关闭"))
                            )
        except Exception as e:  # noqa: BLE001
            logger.info("[BitBrowserRelay] user {} relay disconnected: {}", user_id, e)
        finally:
            self._connections.pop(user_id, None)
            # 让等待中的请求立即失败
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_exception(RuntimeError("BitBrowser 中继连接已断开"))
            self._pending.clear()
            # 关闭该用户的全部 CDP 隧道
            for tid in [t for t, tu in self._tunnels.items() if tu.user_id == user_id]:
                tunnel = self._tunnels.pop(tid, None)
                if tunnel is None:
                    continue
                tunnel.closed = True
                tunnel.inbox.put_nowait(None)
                if not tunnel.opened.done():
                    tunnel.opened.set_exception(RuntimeError("BitBrowser 中继连接已断开"))

    # ── 异步调用（供 async 路由使用）───────────────────────────────
    async def call_async(
        self,
        user_id: int,
        path: str,
        body: dict[str, Any] | None,
        *,
        method: str = "POST",
        url: str | None = None,
        timeout: float = 30.0,
    ) -> Any:
        ws = self._connections.get(user_id)
        if ws is None:
            raise RuntimeError(
                "BitBrowser 中继未连接——请确保管理端页面已打开且中继已启用"
            )
        req_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut
        msg: dict[str, Any] = {
            "type": "req",
            "id": req_id,
            "method": method,
            "path": path,
            "body": body,
        }
        if url:
            msg["url"] = url
        try:
            await ws.send_json(msg)
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise RuntimeError(f"BitBrowser 中继请求超时（{timeout:.0f}s）")

    # ── 同步调用（供 FastAPI 线程池中的同步端点使用）────────────────
    def call_sync(
        self,
        user_id: int,
        path: str,
        body: dict[str, Any] | None,
        *,
        method: str = "POST",
        url: str | None = None,
        timeout: float = 30.0,
    ) -> Any:
        """从同步代码中阻塞式调用异步中继（线程安全）。"""
        loop = self._loop
        if loop is None or not loop.is_running():
            raise RuntimeError("BitBrowser 中继事件循环未就绪，请重启后端服务")
        future = asyncio.run_coroutine_threadsafe(
            self.call_async(user_id, path, body, method=method, url=url, timeout=timeout),
            loop,
        )
        try:
            return future.result(timeout=timeout + 5)
        except TimeoutError:
            raise RuntimeError(f"BitBrowser 中继同步调用超时（{timeout + 5:.0f}s）")

    # ── CDP 隧道 ─────────────────────────────────────────────
    async def _cdp_open_async(self, user_id: int, ws_url: str, open_timeout: float) -> str:
        ws = self._connections.get(user_id)
        if ws is None:
            raise RuntimeError(
                "BitBrowser 中继未连接——请确保管理端页面已打开且中继已启用"
            )
        tid = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        tunnel = _CdpTunnel(user_id, loop)
        self._tunnels[tid] = tunnel
        try:
            await ws.send_json({"type": "cdp_open", "id": tid, "url": ws_url})
            await asyncio.wait_for(asyncio.shield(tunnel.opened), timeout=open_timeout)
            return tid
        except Exception:
            self._tunnels.pop(tid, None)
            raise

    async def _cdp_send_async(self, tid: str, data: str) -> None:
        tunnel = self._tunnels.get(tid)
        if tunnel is None or tunnel.closed:
            raise OSError("CDP 隧道已关闭")
        ws = self._connections.get(tunnel.user_id)
        if ws is None:
            raise OSError("BitBrowser 中继连接已断开")
        await ws.send_json({"type": "cdp_msg", "id": tid, "data": data})

    async def _cdp_recv_async(self, tid: str, timeout: float | None) -> str:
        tunnel = self._tunnels.get(tid)
        if tunnel is None:
            raise OSError("CDP 隧道已关闭")
        item = await asyncio.wait_for(tunnel.inbox.get(), timeout=timeout)
        if item is None:
            raise OSError("CDP 隧道已关闭")
        return item

    async def _cdp_close_async(self, tid: str) -> None:
        tunnel = self._tunnels.pop(tid, None)
        if tunnel is None:
            return
        tunnel.closed = True
        tunnel.inbox.put_nowait(None)
        ws = self._connections.get(tunnel.user_id)
        if ws is not None:
            try:
                await ws.send_json({"type": "cdp_close", "id": tid})
            except Exception:  # noqa: BLE001
                pass

    def connect_cdp_sync(
        self, user_id: int, ws_url: str, *, open_timeout: float = 15.0
    ) -> "RelayCdpSocket":
        """通过中继建立到用户本机 CDP WebSocket 的隧道（同步接口）。"""
        loop = self._loop
        if loop is None or not loop.is_running():
            raise RuntimeError("BitBrowser 中继事件循环未就绪，请重启后端服务")
        future = asyncio.run_coroutine_threadsafe(
            self._cdp_open_async(user_id, ws_url, open_timeout), loop
        )
        try:
            tid = future.result(timeout=open_timeout + 5)
        except TimeoutError:
            raise RuntimeError(f"CDP 中继隧道建立超时（{open_timeout + 5:.0f}s）")
        return RelayCdpSocket(self, tid)


class RelayCdpSocket:
    """中继 CDP 隧道的同步包装，接口对齐 ``websockets.sync`` 连接。"""

    def __init__(self, manager: BitBrowserRelayManager, tunnel_id: str) -> None:
        self._manager = manager
        self._tunnel_id = tunnel_id

    def _loop(self) -> asyncio.AbstractEventLoop:
        loop = self._manager._loop
        if loop is None or not loop.is_running():
            raise RuntimeError("BitBrowser 中继事件循环未就绪，请重启后端服务")
        return loop

    def send(self, data: str) -> None:
        asyncio.run_coroutine_threadsafe(
            self._manager._cdp_send_async(self._tunnel_id, data), self._loop()
        ).result(timeout=15)

    def recv(self, timeout: float | None = None) -> str:
        future = asyncio.run_coroutine_threadsafe(
            self._manager._cdp_recv_async(self._tunnel_id, timeout), self._loop()
        )
        return future.result(timeout=None if timeout is None else timeout + 5)

    def close(self) -> None:
        try:
            asyncio.run_coroutine_threadsafe(
                self._manager._cdp_close_async(self._tunnel_id), self._loop()
            ).result(timeout=10)
        except Exception:  # noqa: BLE001
            pass


relay_manager = BitBrowserRelayManager()
