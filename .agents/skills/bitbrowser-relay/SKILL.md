---
name: bitbrowser-relay
description: BitBrowser 中继（Local API + CDP WebSocket 反向隧道）的架构、协议与排障指南。凡是涉及「后端连不上 BitBrowser / CDP」「邮箱登录、Apify 注册等自动化失败」「中继 agent 部署」的任务，先读本文档。
---

# BitBrowser 中继（Browser Relay / Shared Relay Agent）

## 要解决的问题

- 系统后端部署在云服务器；BitBrowser（比特指纹浏览器）跑在另一台普通 Windows 电脑上。
- BitBrowser 的两条通道都只监听本机回环地址，云端后端直连必然失败（WinError 10061 / Connection refused）：
  1. **Local API**：`http://127.0.0.1:54345`（/browser/open、/browser/list 等）；
  2. **CDP**：`/browser/open` 返回的 `ws://127.0.0.1:<随机端口>/devtools/...`（自动化真正操作页面用的 Chrome DevTools Protocol）。
- ngrok 只能反代 Local API 那个固定端口；CDP 端口每次打开窗口都变，且 DevTools 校验 Host/Origin，公网反代不可行。

## 技术原理：反向 WebSocket 隧道

方向反过来：不是后端去连 BitBrowser，而是 BitBrowser 那台电脑上的「中继」**主动**连到后端并保持一条 WebSocket 长连接。后端要访问 BitBrowser 时，把请求打包成消息发给中继，中继在 BitBrowser 本机就地执行（fetch Local API / 连本机 CDP WS），再把结果原路回传。因为出站连接不受 NAT/防火墙限制，所以不需要 ngrok/frp/公网 IP。

中继有两种实现，后端按优先级路由（`bitbrowser_relay.py::_route_key`）：

1. **页面中继**（per-user）：管理端前端登录后自动连 `/api/v1/bitbrowser/relay/ws?token=<JWT>`（`useBitBrowserRelay.ts`）。只有当管理页面开在 BitBrowser 同一台电脑上才有用。
2. **共享 agent 中继**（推荐，全体用户共用）：`backend/scripts/bitbrowser_relay_agent.py` 常驻在 BitBrowser 电脑上，连 `/api/v1/bitbrowser/relay/agent/ws?token=<BITBROWSER_RELAY_AGENT_TOKEN>`，在 `relay_manager` 里注册为 `SHARED_RELAY_KEY = 0`。用户没有自己的页面中继时自动回退到它。
3. 都没有时：后端直连（仅后端与 BitBrowser 同机的开发场景可用），失败会抛带指引的 RuntimeError。

## WS 消息协议（backend/app/services/bitbrowser_relay.py 顶部注释为准）

Local API / HTTP 转发：

```json
后端→中继: {"type":"req","id":"<uuid>","method":"POST","path":"/browser/list","body":{...},"headers":{"x-api-key":"..."},"url":"<可选，绝对地址>"}
中继→后端: {"type":"res","id":"<uuid>","status":200,"body":{...}}  或  {"type":"res","id":"<uuid>","error":"..."}
```

CDP 隧道（每个隧道 id 对应中继侧一条到本机 DevTools 的嵌套 WebSocket）：

```json
后端→中继: {"type":"cdp_open","id":"<tid>","url":"ws://127.0.0.1:.../devtools/page/..."}
中继→后端: {"type":"cdp_opened","id":"<tid>"}  或  {"type":"cdp_opened","id":"<tid>","error":"..."}
双向:      {"type":"cdp_msg","id":"<tid>","data":"<CDP JSON 文本>"}
关闭:      {"type":"cdp_close","id":"<tid>"}（后端发） / {"type":"cdp_closed","id":"<tid>"}（中继通知）
```

后端同步代码（FastAPI 线程池里的自动化）通过 `relay_manager.call_sync(...)` 与 `relay_manager.connect_cdp_sync(...)`（返回 `RelayCdpSocket`，接口对齐 `websockets.sync` 的 send/recv/close）使用这两类隧道。

## 关键设计决策（踩过的坑）

1. **标签页管理不用 DevTools 的 `/json/*` HTTP 接口**，统一用浏览器级 CDP 的 `Target.*` 命令（`cdp_transport.py`：`create_page`/`list_pages`/`close_target`/`activate_target`）。原因：`/json/*` 响应没有 CORS 头，页面中继里的 fetch 会被浏览器拦截（Failed to fetch）。
2. **窗口启动参数必须带 `--remote-allow-origins=*`**（`bitbrowser_service._build_open_payload` 会自动加）。Chrome 111+ 默认拒绝跨源 DevTools WebSocket 握手；改参数后**已开的窗口要先关再开**才生效。
3. **Local API 鉴权**：BitBrowser 客户端开启「Local API 鉴权」后所有请求要带 `x-api-key` 头。后端从用户配置或 `.env` 的 `BITBROWSER_API_KEY` 取值，经 `req.headers` 下发；agent 也可用 `--bb-api-key` 自带。
4. **自动化全部走原生 CDP（websockets 库），不是 Playwright**。`open_cdp(ws_url, user_id)` 是唯一连接入口：有中继走隧道，没有走直连。
5. 中继断开时，隧道以 `OSError` 失败，自动化层把它转成 `CdpConnectionClosed` 快速失败。
6. Vite dev 代理需要 `ws: true`（`vite.config.ts`），否则前端页面中继的 WS 永远连不上；nginx 反代需要 `proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade";`。

## 部署共享 agent（BitBrowser 电脑上）

```bash
pip install websockets httpx
python bitbrowser_relay_agent.py --server https://后端域名或IP:端口 --token <BITBROWSER_RELAY_AGENT_TOKEN> --bb-api-key <LocalAPI Token>
```

- 后端 `.env`：`BITBROWSER_RELAY_AGENT_TOKEN=<同一令牌>`（留空则禁用 agent 入口），改后重启后端。
- `--server` 写 http/https 会自动换成 ws/wss；断线 5 秒自动重连。
- 用户在系统「本机连接」里地址填 `http://127.0.0.1:54345` 即可（相对路径由 agent 在 BitBrowser 本机解析）。

## 排障速查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| WinError 10061 / Connection refused | 无任何中继，后端直连了 127.0.0.1 | 启动 agent 或打开管理页面 |
| `API Token错误，请检查` | Local API 鉴权开了但请求没带 x-api-key | 配 `BITBROWSER_API_KEY` 或 `--bb-api-key` |
| `Failed to fetch`（list targets） | 走了 `/json/*` HTTP（旧代码）被 CORS 拦截 | 升级到 Target.* 方案 |
| `无法连接本机 CDP WebSocket` | 页面中继开在别的电脑；或窗口没带 `--remote-allow-origins=*` | agent 跑在 BitBrowser 同机；窗口先关再开 |
| agent 连接被拒 HTTP 403 | 后端没有 agent 路由（代码旧）或 token 不匹配/未配置 | 更新后端代码、核对 `.env` 令牌并重启 |
| agent 连接报 HTTP 500 | 后端正在重启/热重载中 | 等 agent 自动重连 |
