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
    if (req.type !== 'req' || typeof req.id !== 'string') return

    const path = req.path as string
    const body = req.body ?? {}
    const reqId = req.id

    try {
      const resp = await fetch(`${localBbUrl}${path}`, {
        method: (req.method as string) || 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(30000)
      })
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
