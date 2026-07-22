"""BitBrowser 共享中继 agent。

跑在装有 BitBrowser 的电脑上（普通 Windows 电脑即可），主动连接云端后端的
``/api/v1/bitbrowser/relay/agent/ws``，替系统所有用户转发：

1. BitBrowser Local API 请求（/browser/open、/browser/list 等）
2. 窗口 DevTools 的 CDP WebSocket 消息（邮箱登录、Apify 注册等自动化）

不需要 ngrok / frp，也不需要保持管理页面打开。

用法（在 BitBrowser 电脑上）::

    pip install websockets httpx
    python bitbrowser_relay_agent.py --server wss://你的后端域名或IP:8014 --token <BITBROWSER_RELAY_AGENT_TOKEN>

可选参数::

    --bb-url http://127.0.0.1:54345   # BitBrowser Local API 地址（默认此值）
    --bb-api-key <token>              # 客户端开启「Local API 鉴权」时的 API Token

断线自动重连。--server 用 http/https 开头也可以，会自动换成 ws/wss。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any
from urllib.parse import quote

import httpx
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bb-relay-agent")


def _ws_endpoint(server: str, token: str) -> str:
    base = server.strip().rstrip("/")
    if base.startswith("http://"):
        base = "ws://" + base[len("http://"):]
    elif base.startswith("https://"):
        base = "wss://" + base[len("https://"):]
    elif not base.startswith(("ws://", "wss://")):
        base = "ws://" + base
    return f"{base}/api/v1/bitbrowser/relay/agent/ws?token={quote(token, safe='')}"


class Agent:
    def __init__(self, server: str, token: str, bb_url: str, bb_api_key: str | None) -> None:
        self.endpoint = _ws_endpoint(server, token)
        self.bb_url = bb_url.rstrip("/")
        self.bb_api_key = (bb_api_key or "").strip() or None
        self.cdp_sockets: dict[str, Any] = {}
        self.cdp_tasks: dict[str, asyncio.Task] = {}

    async def run_forever(self) -> None:
        while True:
            try:
                await self._run_once()
            except Exception as e:  # noqa: BLE001
                log.warning("连接断开/失败：%s，5 秒后重连", e)
            await self._close_all_cdp()
            await asyncio.sleep(5)

    async def _run_once(self) -> None:
        log.info("连接后端中继入口 ...")
        # ping 保活：定期发送 ping，既能撑住中间代理的空闲超时，也能快速发现掉线重连
        async with websockets.connect(
            self.endpoint,
            max_size=32 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=60,
            close_timeout=10,
        ) as ws:
            log.info("已连接，等待任务")
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:  # noqa: BLE001
                    continue
                if not isinstance(msg, dict):
                    continue
                asyncio.create_task(self._handle(ws, msg))

    async def _handle(self, ws: Any, msg: dict[str, Any]) -> None:
        msg_type = msg.get("type")
        msg_id = str(msg.get("id") or "")
        try:
            if msg_type == "req":
                await self._handle_req(ws, msg_id, msg)
            elif msg_type == "cdp_open":
                await self._handle_cdp_open(ws, msg_id, str(msg.get("url") or ""))
            elif msg_type == "cdp_msg":
                sock = self.cdp_sockets.get(msg_id)
                if sock is not None:
                    await sock.send(str(msg.get("data") or ""))
            elif msg_type == "cdp_close":
                await self._close_cdp(msg_id)
        except Exception as e:  # noqa: BLE001
            log.warning("处理消息失败 type=%s id=%s: %s", msg_type, msg_id, e)

    # ── Local API / DevTools HTTP 转发 ─────────────────────────────
    async def _handle_req(self, ws: Any, msg_id: str, msg: dict[str, Any]) -> None:
        method = str(msg.get("method") or "POST").upper()
        url = str(msg.get("url") or "") or f"{self.bb_url}{msg.get('path') or ''}"
        body = msg.get("body")
        headers: dict[str, str] = {}
        extra = msg.get("headers")
        if isinstance(extra, dict):
            headers.update({str(k): str(v) for k, v in extra.items()})
        if self.bb_api_key and "x-api-key" not in {k.lower() for k in headers}:
            headers["x-api-key"] = self.bb_api_key
        try:
            async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
                if method != "GET" and body is not None:
                    resp = await client.request(method, url, json=body, headers=headers)
                else:
                    resp = await client.request(method, url, headers=headers)
                if method == "PUT" and resp.status_code in (404, 405):
                    resp = await client.get(url, headers=headers)
            try:
                resp_body: Any = resp.json()
            except Exception:  # noqa: BLE001
                resp_body = {}
            await ws.send(json.dumps(
                {"type": "res", "id": msg_id, "status": resp.status_code, "body": resp_body}
            ))
        except Exception as e:  # noqa: BLE001
            await ws.send(json.dumps({"type": "res", "id": msg_id, "error": str(e)}))

    # ── CDP 隧道 ────────────────────────────────────────────────────
    async def _handle_cdp_open(self, ws: Any, tid: str, url: str) -> None:
        try:
            sock = await websockets.connect(url, max_size=32 * 1024 * 1024)
        except Exception as e:  # noqa: BLE001
            await ws.send(json.dumps(
                {"type": "cdp_opened", "id": tid, "error": f"无法连接本机 CDP WebSocket: {e}"}
            ))
            return
        self.cdp_sockets[tid] = sock
        await ws.send(json.dumps({"type": "cdp_opened", "id": tid}))
        self.cdp_tasks[tid] = asyncio.create_task(self._pump_cdp(ws, tid, sock))

    async def _pump_cdp(self, ws: Any, tid: str, sock: Any) -> None:
        try:
            async for data in sock:
                text = data if isinstance(data, str) else data.decode("utf-8", "replace")
                await ws.send(json.dumps({"type": "cdp_msg", "id": tid, "data": text}))
        except Exception:  # noqa: BLE001
            pass
        finally:
            self.cdp_sockets.pop(tid, None)
            self.cdp_tasks.pop(tid, None)
            try:
                await ws.send(json.dumps({"type": "cdp_closed", "id": tid}))
            except Exception:  # noqa: BLE001
                pass

    async def _close_cdp(self, tid: str) -> None:
        sock = self.cdp_sockets.pop(tid, None)
        task = self.cdp_tasks.pop(tid, None)
        if sock is not None:
            try:
                await sock.close()
            except Exception:  # noqa: BLE001
                pass
        if task is not None:
            task.cancel()

    async def _close_all_cdp(self) -> None:
        for tid in list(self.cdp_sockets.keys()):
            await self._close_cdp(tid)


def main() -> None:
    parser = argparse.ArgumentParser(description="BitBrowser 共享中继 agent")
    parser.add_argument("--server", required=True, help="后端地址，如 https://example.com 或 http://1.2.3.4:8014")
    parser.add_argument("--token", required=True, help="后端 .env 中的 BITBROWSER_RELAY_AGENT_TOKEN")
    parser.add_argument("--bb-url", default="http://127.0.0.1:54345", help="BitBrowser Local API 地址")
    parser.add_argument("--bb-api-key", default="", help="BitBrowser Local API 鉴权 Token（未开启鉴权可不填）")
    args = parser.parse_args()
    agent = Agent(args.server, args.token, args.bb_url, args.bb_api_key)
    asyncio.run(agent.run_forever())


if __name__ == "__main__":
    main()
