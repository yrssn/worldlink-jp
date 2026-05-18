<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { bitbrowserApi, type BitBrowserSettings } from '@/api/bitbrowser'

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

    <el-card shadow="never">
      <template #header>
        <span style="font-weight: 600">连接参数（按当前登录用户保存）</span>
      </template>
      <p style="margin: 0 0 12px; font-size: 12px; color: #606266">
        本地服务地址一般为
        <code>http://127.0.0.1:54345</code>
        ；若客户端开启「鉴权控制」，请填写与「设置 → 本地 API」一致的 API Token。不会写入共享
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
