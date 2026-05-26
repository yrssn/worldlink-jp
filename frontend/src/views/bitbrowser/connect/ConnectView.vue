<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { bitbrowserApi, type BitBrowserSettings } from '@/api/bitbrowser'
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
  await checkHealth()
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
        <strong style="color: #67c23a">✓ 推荐方案（内置，无需外部工具）</strong>：保持此管理端页面在浏览器中<strong>保持打开</strong>，
        系统会自动建立「浏览器中继」——后端的请求通过你的浏览器转发到本机 BitBrowser，下方中继状态显示绿色「已连接」即可正常使用。<br />
        其他方案：内网穿透（frp/ngrok）或前后端均跑在本机。
      </div>
    </el-alert>

    <!-- 浏览器中继状态卡片 -->
    <el-card shadow="never" style="margin-bottom: 14px; max-width: 900px">
      <template #header>
        <div style="display:flex;align-items:center;gap:10px">
          <span style="font-weight:600">浏览器中继状态</span>
          <el-tag :type="relayConnected ? 'success' : 'info'" size="small" effect="plain">
            {{ relayConnected ? '✓ 已连接' : '未连接' }}
          </el-tag>
        </div>
      </template>
      <div style="font-size:12px;color:#606266;line-height:1.8">
        <p style="margin:0 0 6px">
          中继运行时，后端调用 BitBrowser 会自动通过此页面的 WebSocket 连接转发到你本机的
          <code>{{ bbSettings?.local_url || 'http://127.0.0.1:54345' }}</code>，
          无需任何外部工具。<strong>保持此浏览器标签页打开即可</strong>。
        </p>
        <div v-if="relayConnected" style="color:#67c23a">✓ 中继已连接，本机 BitBrowser 请求将通过浏览器转发。</div>
        <div v-else style="color:#909399">中继未连接。若已配置本地服务地址，点「重新连接」或刷新页面。</div>
      </div>
      <div style="margin-top:12px">
        <el-button size="small" type="primary" plain :disabled="relayConnected" @click="relayReconnect">重新连接中继</el-button>
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
