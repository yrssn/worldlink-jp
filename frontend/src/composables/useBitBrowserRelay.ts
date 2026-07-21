/**
 * BitBrowser 浏览器中继（Browser Relay）
 *
 * 原理：前端页面在登录后自动与后端建立 WebSocket 长连接。当后端需要调用用户
 * 本机上的 BitBrowser Local API 时，通过此连接把请求转发给前端；前端在用户
 * 自己的浏览器里执行 fetch（127.0.0.1:54345），再把结果回传给后端。
 *
 * 这样不需要 frp/ngrok 等外部工具，公网部署同样可以使用本机指纹浏览器。
 */
import { ref } from 'vue'
import { useAuthStore } from '@/store/auth'
import { bitbrowserApi } from '@/api/bitbrowser'

export const relayConnected = ref(false)

let ws: WebSocket | null = null
let localBbUrl = ''
const cdpSockets = new Map<string, WebSocket>()

function closeAllCdpSockets() {
  cdpSockets.forEach((sock) => {
    try { sock.close() } catch { /* ignore */ }
  })
  cdpSockets.clear()
}
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let destroyed = false
let currentToken = ''

function buildWsUrl(token: string): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/api/v1/bitbrowser/relay/ws?token=${encodeURIComponent(token)}`
}

function stopReconnect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

async function connect(): Promise<void> {
  if (destroyed) return
  const auth = useAuthStore()
  if (!auth.isAuthed || !auth.accessToken) return

  currentToken = auth.accessToken

  // 拉取用户配置的 BitBrowser 地址；若没配置则不需要中继
  try {
    const settings = await bitbrowserApi.getSettings()
    if (!settings?.local_url) return
    localBbUrl = settings.local_url.replace(/\/$/, '')
  } catch {
    return
  }

  if (ws) {
    try { ws.close() } catch { /* ignore */ }
    ws = null
  }

  const socket = new WebSocket(buildWsUrl(currentToken))
  ws = socket

  socket.onopen = () => {
    if (socket !== ws) return
    relayConnected.value = true
  }

  socket.onclose = () => {
    if (socket !== ws) return
    relayConnected.value = false
    ws = null
    closeAllCdpSockets()
    if (!destroyed) {
      reconnectTimer = setTimeout(connect, 5000)
    }
  }

  socket.onerror = () => {
    relayConnected.value = false
  }

  socket.onmessage = async (event: MessageEvent) => {
    if (socket !== ws) return
    let req: Record<string, unknown>
    try {
      req = JSON.parse(event.data as string)
    } catch {
      return
    }
    if (typeof req.id !== 'string') return
    const reqId = req.id

    // ── CDP 隧道：后端通过此页面连接本机窗口的 DevTools WebSocket ──
    if (req.type === 'cdp_open' && typeof req.url === 'string') {
      try {
        const cdp = new WebSocket(req.url)
        let opened = false
        cdp.onopen = () => {
          opened = true
          cdpSockets.set(reqId, cdp)
          socket.send(JSON.stringify({ type: 'cdp_opened', id: reqId }))
        }
        cdp.onmessage = (ev: MessageEvent) => {
          socket.send(JSON.stringify({ type: 'cdp_msg', id: reqId, data: String(ev.data) }))
        }
        cdp.onclose = () => {
          if (opened) {
            cdpSockets.delete(reqId)
            socket.send(JSON.stringify({ type: 'cdp_closed', id: reqId }))
          } else {
            socket.send(JSON.stringify({ type: 'cdp_opened', id: reqId, error: '无法连接本机 CDP WebSocket（窗口可能已关闭）' }))
          }
        }
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        socket.send(JSON.stringify({ type: 'cdp_opened', id: reqId, error: msg }))
      }
      return
    }
    if (req.type === 'cdp_msg') {
      const sock = cdpSockets.get(reqId)
      if (sock && sock.readyState === WebSocket.OPEN) {
        sock.send(String(req.data ?? ''))
      }
      return
    }
    if (req.type === 'cdp_close') {
      const sock = cdpSockets.get(reqId)
      cdpSockets.delete(reqId)
      if (sock) {
        try { sock.close() } catch { /* ignore */ }
      }
      return
    }

    if (req.type !== 'req') return

    const path = req.path as string
    const body = req.body
    // 若后端指定了绝对地址（DevTools /json/* 接口），则直接请求该地址
    const isAbsolute = typeof req.url === 'string' && !!req.url
    const targetUrl = isAbsolute ? (req.url as string) : `${localBbUrl}${path}`
    const method = (req.method as string) || 'POST'

    try {
      const extraHeaders = (req.headers && typeof req.headers === 'object')
        ? (req.headers as Record<string, string>)
        : {}
      const init: RequestInit = {
        method,
        headers: { ...extraHeaders },
        signal: AbortSignal.timeout(30000)
      }
      if (method !== 'GET' && body != null) {
        init.headers = { ...extraHeaders, 'Content-Type': 'application/json' }
        init.body = JSON.stringify(body)
      }
      let resp = await fetch(targetUrl, init)
      // DevTools 旧版内核不支持 PUT /json/new，回退 GET
      if (isAbsolute && method === 'PUT' && (resp.status === 404 || resp.status === 405)) {
        resp = await fetch(targetUrl, { method: 'GET', signal: AbortSignal.timeout(30000) })
      }
      if (isAbsolute && !resp.ok) {
        socket.send(JSON.stringify({ type: 'res', id: reqId, error: `HTTP ${resp.status}` }))
        return
      }
      let respBody: unknown = {}
      try { respBody = await resp.json() } catch { /* empty body */ }
      socket.send(JSON.stringify({ type: 'res', id: reqId, status: resp.status, body: respBody }))
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      socket.send(JSON.stringify({ type: 'res', id: reqId, error: msg }))
    }
  }
}

function disconnect(): void {
  destroyed = true
  stopReconnect()
  closeAllCdpSockets()
  if (ws) {
    try { ws.close() } catch { /* ignore */ }
    ws = null
  }
  relayConnected.value = false
}

/** 重置并重新连接（例如用户切换账号后调用） */
function reconnect(): void {
  destroyed = false
  stopReconnect()
  if (ws) {
    try { ws.close() } catch { /* ignore */ }
    ws = null
  }
  relayConnected.value = false
  connect()
}

export function useBitBrowserRelay() {
  return { relayConnected, connect, disconnect, reconnect }
}
