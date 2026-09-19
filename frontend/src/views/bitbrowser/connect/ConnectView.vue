<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { bitbrowserApi, type BitBrowserSettings, type RelayStatus } from '@/api/bitbrowser'
import { relayConnected, useBitBrowserRelay } from '@/composables/useBitBrowserRelay'

const { reconnect: relayReconnect } = useBitBrowserRelay()

const bbSettings = ref<BitBrowserSettings | null>(null)
const formLocalUrl = ref('')
const formApiKey = ref('')
const clearApiKey = ref(false)
const savingSettings = ref(false)

const health = ref<{
  ok: boolean
  error?: string
  hint?: string
  auth_hint?: string
} | null>(null)

const connReady = computed(() => !!(bbSettings.value?.local_url || '').trim())

const relayStatus = ref<RelayStatus | null>(null)
let relayStatusTimer: ReturnType<typeof setInterval> | null = null

async function loadRelayStatus() {
  try {
    relayStatus.value = await bitbrowserApi.relayStatus()
  } catch {
    relayStatus.value = null
  }
}

/** 后端实际会走的中继（与 bitbrowser_relay.py::_route_key 的优先级一致） */
const activeRelay = computed<'own_agent' | 'shared_agent' | 'page' | null>(() => {
  const s = relayStatus.value
  if (!s) return relayConnected.value ? 'page' : null
  if (s.own_agent) return 'own_agent'
  if (s.shared_agent) return 'shared_agent'
  if (s.page_relay || relayConnected.value) return 'page'
  return null
})

const backendOrigin = computed(() => (typeof window === 'undefined' ? '' : window.location.origin))

/** 当前页是否在「本机」打开（公网 IP / 域名访问管理端时，易误以为 127.0.0.1 指自己电脑） */
const accessFromRemoteHost = computed(() => {
  if (typeof window === 'undefined') return false
  const h = (window.location.hostname || '').toLowerCase()
  return h !== 'localhost' && h !== '127.0.0.1' && h !== '[::1]' && h !== ''
})

async function loadBbSettings() {
  try {
    bbSettings.value = await bitbrowserApi.getSettings()
    formLocalUrl.value = bbSettings.value.local_url || ''
    formApiKey.value = ''
    clearApiKey.value = false
  } catch {
    bbSettings.value = null
  }
}

async function checkHealth() {
  try {
    health.value = await bitbrowserApi.localHealth()
  } catch (e: unknown) {
    const ax = e as { response?: { status?: number; data?: { detail?: string } }; message?: string }
    const detail =
      ax.response?.data?.detail ||
      (typeof ax.response?.data === 'string' ? ax.response.data : undefined)
    const msg = detail || ax.message || `HTTP ${ax.response?.status ?? ''}`.trim() || '请求失败'
    health.value = { ok: false, error: msg }
  }
}

async function saveBbSettings() {
  const url = formLocalUrl.value.trim()
  if (!url) {
    ElMessage.warning('请填写 BitBrowser 本地服务地址')
    return
  }
  savingSettings.value = true
  try {
    const body: { local_url: string; api_key?: string } = { local_url: url }
    if (clearApiKey.value) body.api_key = ''
    else if (formApiKey.value.trim()) body.api_key = formApiKey.value.trim()
    bbSettings.value = await bitbrowserApi.updateSettings(body)
    formApiKey.value = ''
    clearApiKey.value = false
    ElMessage.success('已保存本机连接配置')
    await checkHealth()
  } catch (e: unknown) {
    const ax = e as { response?: { data?: { detail?: string } }; message?: string }
    const detail =
      ax.response?.data?.detail ||
      (typeof ax.response?.data === 'string' ? ax.response.data : undefined) ||
      ax.message ||
      '保存失败'
    ElMessage.error(detail)
  } finally {
    savingSettings.value = false
  }
}

onMounted(async () => {
  await loadBbSettings()
  await Promise.all([checkHealth(), loadRelayStatus()])
  relayStatusTimer = setInterval(loadRelayStatus, 5000)
})

onUnmounted(() => {
  if (relayStatusTimer) clearInterval(relayStatusTimer)
})
</script>

<template>
  <div class="page-card">
    <h3 style="margin: 0 0 8px 0">比特抓取 · 本机连接</h3>
    <p style="margin: 0 0 16px; font-size: 12px; color: #666; max-width: 720px">
      此页为「比特抓取」模块之一：每位员工在此配置本机 Local API 与 Token（按账号存库）。配置完成后请到
      <router-link to="/bitbrowser/windows">浏览器窗口</router-link>
      同步与使用环境。
    </p>

    <el-alert type="info" show-icon :closable="false" style="margin-bottom: 14px; max-width: 900px">
      <template #title>谁去连 BitBrowser？</template>
      <div style="font-size: 12px; line-height: 1.65; margin-top: 4px">
        「保存 / 检测」由<strong>后端服务器</strong>向你填写的地址发 HTTP 请求，<strong>不是</strong>在你自己浏览器里直连。
        因此填
        <code>http://127.0.0.1:54345</code>
        表示「<strong>后端那台机器</strong>上的本机端口」；若后端跑在云主机上，而 BitBrowser 装在你办公室电脑，就会
        <strong>连接被拒绝</strong>
        ——这是正常现象。请改为填写<strong>从服务器能访问到的</strong>地址（见下方公网部署说明），或在本机运行整套前后端仅供比特模块使用。
      </div>
    </el-alert>

    <el-alert
      v-if="accessFromRemoteHost"
      type="warning"
      show-icon
      :closable="false"
      style="margin-bottom: 14px; max-width: 900px"
    >
      <template #title>你正在通过公网访问管理端</template>
      <div style="font-size: 12px; line-height: 1.65; margin-top: 4px">
        当前站点不是 localhost，若仍使用 127.0.0.1，检测一定指向<strong>云服务器自己</strong>，无法直连你电脑上的比特浏览器。<br />
        <strong style="color: #67c23a">✓ 推荐方案</strong>：在你自己装有 BitBrowser 的电脑上跑「中继 Agent」小程序（见下方），
        用你的系统账号登录后它会主动反连后端，后端对你的所有 BitBrowser 调用都经它转发，不依赖别人的电脑，也不用保持网页打开。<br />
        备选：保持此管理端页面在 BitBrowser 同一台电脑的浏览器中打开，系统会自动建立「页面中继」；或内网穿透（frp/ngrok）。
      </div>
    </el-alert>

    <!-- 中继状态卡片 -->
    <el-card shadow="never" style="margin-bottom: 14px; max-width: 900px">
      <template #header>
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
          <span style="font-weight:600">中继状态</span>
          <el-tag v-if="activeRelay === 'own_agent'" type="success" size="small" effect="plain">✓ 专属 Agent 已连接</el-tag>
          <el-tag v-else-if="activeRelay === 'shared_agent'" type="success" size="small" effect="plain">✓ 共享 Agent 已连接</el-tag>
          <el-tag v-else-if="activeRelay === 'page'" type="warning" size="small" effect="plain">✓ 页面中继已连接</el-tag>
          <el-tag v-else type="info" size="small" effect="plain">未连接</el-tag>
        </div>
      </template>
      <div style="font-size:12px;color:#606266;line-height:1.8">
        <p style="margin:0 0 6px">
          后端调用 BitBrowser（Local API 与窗口 CDP）会按优先级走：
          <strong>你自己电脑上的专属 Agent</strong> → 全员共用的共享 Agent → 本页面中继。
          目标地址为中继所在电脑上的 <code>{{ bbSettings?.local_url || 'http://127.0.0.1:54345' }}</code>。
        </p>
        <div v-if="activeRelay === 'own_agent'" style="color:#67c23a">
          ✓ 你的专属 Agent 在线，BitBrowser 请求全部经你自己的电脑转发，不受其他人电脑断网影响。
        </div>
        <div v-else-if="activeRelay === 'shared_agent'" style="color:#e6a23c">
          目前走的是共享 Agent（别人电脑上的 BitBrowser）。建议在自己电脑上启动专属 Agent，启动后会自动优先使用。
        </div>
        <div v-else-if="activeRelay === 'page'" style="color:#e6a23c">
          目前走的是页面中继：仅当本页面开在 BitBrowser 同一台电脑上且<strong>标签页保持打开</strong>时可用。
        </div>
        <div v-else style="color:#909399">中继未连接。请按下方步骤启动专属 Agent，或点「重新连接页面中继」。</div>
      </div>
      <div style="margin-top:12px;display:flex;gap:8px">
        <el-button size="small" plain @click="loadRelayStatus">刷新状态</el-button>
        <el-button size="small" type="primary" plain :disabled="relayConnected" @click="relayReconnect">重新连接页面中继</el-button>
      </div>
    </el-card>

    <!-- 专属 Agent 安装指引 -->
    <el-card shadow="never" style="margin-bottom: 14px; max-width: 900px">
      <template #header>
        <span style="font-weight:600">在自己电脑上启动专属中继 Agent（Windows / macOS）</span>
      </template>
      <div style="font-size:12px;color:#606266;line-height:1.8">
        <ol style="margin:0;padding-left:18px">
          <li>
            从代码仓库 Releases 下载中继程序：Windows 用 <code>BitBrowserRelayAgent-windows-x64.exe</code>；
            Mac 用 <code>BitBrowserRelayAgent-macos-arm64.zip</code>（Apple 芯片 M1/M2/M3/M4）或
            <code>BitBrowserRelayAgent-macos-x86_64.zip</code>（Intel 芯片），解压后得到 <code>BitBrowserRelayAgent.app</code>。
          </li>
          <li>
            Mac 首次打开若提示「无法打开 / 已损坏」：右键→打开，或在终端执行
            <code>xattr -cr ~/Downloads/BitBrowserRelayAgent.app</code> 后再打开。
          </li>
          <li>
            在程序里填：后端地址 <code>{{ backendOrigin }}</code>；系统账号 / 密码 填你登录本管理端的账号密码；
            「共享 Token」留空；BitBrowser Local API 保持 <code>http://127.0.0.1:54345</code>（若 BitBrowser 开了鉴权再填 Local API Token）。
          </li>
          <li>点「启动」，日志出现「已连接（专属中继）」，本页上方状态变为「专属 Agent 已连接」即可。程序保持运行（可最小化），断网后会自动重连。</li>
        </ol>
        <p style="margin:6px 0 0">
          下方「本地服务地址」填 <code>http://127.0.0.1:54345</code> 即可——这个地址由你电脑上的 Agent 就地解析。
        </p>
      </div>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <span style="font-weight: 600">连接参数（按当前登录用户保存）</span>
      </template>
      <p style="margin: 0 0 12px; font-size: 12px; color: #606266">
        地址填 BitBrowser「设置 → 本地 API」里能访问到的根地址。仅当<strong>后端与 BitBrowser 在同一台机器</strong>时可用
        <code>http://127.0.0.1:54345</code>
        ；云服务器部署时请填穿透后的公网/内网 URL。若客户端开启「鉴权控制」，请填写 API Token。不会写入共享
        <code>.env</code>
        。
      </p>
      <el-form label-width="140px" style="max-width: 720px">
        <el-form-item label="本地服务地址" required>
          <el-input v-model="formLocalUrl" placeholder="http://127.0.0.1:54345" clearable />
        </el-form-item>
        <el-form-item label="API Token">
          <el-input
            v-model="formApiKey"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="留空表示不修改已保存的 Token"
            clearable
          />
        </el-form-item>
        <el-form-item label=" ">
          <el-checkbox v-model="clearApiKey">清除已保存的 API Token</el-checkbox>
        </el-form-item>
        <el-form-item label=" ">
          <el-button type="primary" :loading="savingSettings" @click="saveBbSettings">保存配置</el-button>
          <el-button :disabled="!connReady" @click="checkHealth">检测本地服务</el-button>
          <span v-if="bbSettings?.has_api_key" style="margin-left: 12px; font-size: 12px; color: #67c23a">
            已保存 Token
          </span>
        </el-form-item>
      </el-form>
    </el-card>

    <el-alert
      v-if="health"
      :title="health.ok ? 'BitBrowser 本地服务可访问' : 'BitBrowser 本地服务不可用'"
      :type="health.ok ? 'success' : 'error'"
      show-icon
      :closable="false"
      style="margin-top: 14px"
    >
      <template v-if="!health.ok">
        <div style="font-size: 12px">{{ health.error }}</div>
        <div v-if="health.hint" style="font-size: 12px; margin-top: 4px">配置地址：{{ health.hint }}</div>
        <div v-if="health.auth_hint" style="font-size: 12px; margin-top: 4px; color: #a67c00">{{ health.auth_hint }}</div>
      </template>
    </el-alert>
  </div>
</template>
