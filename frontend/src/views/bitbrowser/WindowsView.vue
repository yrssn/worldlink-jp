<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  bitbrowserApi,
  type BitBrowserPlatform,
  type BitBrowserSettings,
  type BitBrowserSyncMeta,
  type BitBrowserWindow
} from '@/api/bitbrowser'

const list = ref<BitBrowserWindow[]>([])
const loading = ref(false)
const syncing = ref(false)
const autoSyncing = ref(false)
const syncMeta = ref<BitBrowserSyncMeta | null>(null)
const health = ref<{
  ok: boolean
  error?: string
  hint?: string
  auth_hint?: string
} | null>(null)

const bbSettings = ref<BitBrowserSettings | null>(null)

const connReady = computed(() => !!(bbSettings.value?.local_url || '').trim())

const platforms = ref<BitBrowserPlatform[]>([])

const catalogDialogVisible = ref(false)
const catalogSaving = ref(false)
const catalogRow = ref<BitBrowserWindow | null>(null)
const catalogForm = reactive<{ platform_id: number | null; note: string }>({
  platform_id: null,
  note: ''
})

async function loadPlatforms() {
  try {
    platforms.value = await bitbrowserApi.listPlatforms()
  } catch {
    platforms.value = []
  }
}

async function loadBbSettings() {
  try {
    bbSettings.value = await bitbrowserApi.getSettings()
  } catch {
    bbSettings.value = null
  }
}

async function refresh() {
  loading.value = true
  try {
    list.value = await bitbrowserApi.listWindows()
    await loadSyncMeta()
  } finally {
    loading.value = false
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

async function loadSyncMeta() {
  try {
    syncMeta.value = await bitbrowserApi.syncMeta()
  } catch {
    syncMeta.value = null
  }
}

function formatLastSync(iso: string | null | undefined): string {
  if (!iso) return '尚未成功从本机同步'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleString('zh-CN', { hour12: false })
}

function proxySummary(row: BitBrowserWindow): string {
  const t = (row.proxy_type || '').trim() || '—'
  const h = (row.host || '').trim()
  const p = (row.port || '').trim()
  if (!h && !p) return t
  return `${t} ${h}${p ? `:${p}` : ''}`.trim()
}

async function silentAutoSync() {
  if (!connReady.value) return
  if (health.value?.ok !== true) return
  autoSyncing.value = true
  try {
    const r = await bitbrowserApi.syncWindows()
    await refresh()
    if (r.removed_stale > 0) {
      ElMessage.info(`已与 BitBrowser 对齐：从缓存中移除了 ${r.removed_stale} 个本地列表中已不存在的窗口`)
    }
  } catch {
    ElMessage.warning('进入页面时自动同步失败：请确认本机已打开比特浏览器，或稍后手动点「从本机同步」')
  } finally {
    autoSyncing.value = false
  }
}

async function sync() {
  if (!connReady.value) {
    ElMessage.warning('请先到「比特抓取 → 本机连接」页面保存本地服务地址')
    return
  }
  syncing.value = true
  try {
    const r = await bitbrowserApi.syncWindows()
    ElMessage.success(
      `已同步：拉取 ${r.fetched} 条，写入/更新 ${r.upserted} 条，清理本地已删 ${r.removed_stale} 条`
    )
    await refresh()
    await checkHealth()
  } catch (e: unknown) {
    const ax = e as { response?: { data?: { detail?: string } }; message?: string }
    const detail =
      ax.response?.data?.detail ||
      (typeof ax.response?.data === 'string' ? ax.response.data : undefined) ||
      ax.message ||
      '同步失败'
    ElMessage.error(detail)
  } finally {
    syncing.value = false
  }
}

const openingId = ref<string | null>(null)

const OPEN_RESULT_LABELS: Record<string, string> = {
  ws: 'WebSocket（CDP）',
  http: '调试 HTTP',
  driver: 'ChromeDriver 路径',
  webdriver: 'WebDriver 地址',
  coreVersion: '内核版本'
}

const openResultVisible = ref(false)
const openResultTitle = ref('')
const openResultJson = ref('')
const openResultKv = ref<{ key: string; label: string; value: string }[]>([])

function buildOpenResultKv(data: Record<string, unknown>) {
  const priority = ['ws', 'http', 'driver', 'webdriver', 'coreVersion']
  const kv: { key: string; label: string; value: string }[] = []
  for (const k of priority) {
    const v = data[k]
    if (v != null && v !== '') kv.push({ key: k, label: OPEN_RESULT_LABELS[k] || k, value: String(v) })
  }
  for (const k of Object.keys(data)) {
    if (priority.includes(k)) continue
    const v = data[k]
    if (v != null && typeof v !== 'object') kv.push({ key: k, label: k, value: String(v) })
  }
  return kv
}

async function copyOpenResultJson() {
  try {
    await navigator.clipboard.writeText(openResultJson.value)
    ElMessage.success('已复制 JSON')
  } catch {
    ElMessage.warning('复制失败，请手动全选复制')
  }
}

async function openCatalogDialog(row: BitBrowserWindow) {
  await loadPlatforms()
  catalogRow.value = row
  catalogForm.platform_id = row.catalog_platform_id ?? null
  catalogForm.note = row.catalog_note || ''
  catalogDialogVisible.value = true
}

async function confirmCatalogSave() {
  if (!catalogRow.value) return
  catalogSaving.value = true
  try {
    await bitbrowserApi.saveWindowCatalog(catalogRow.value.browser_id, {
      platform_id: catalogForm.platform_id,
      note: catalogForm.note.trim() || null
    })
    ElMessage.success('已保存到系统')
    catalogDialogVisible.value = false
    await refresh()
  } catch {
    /* 拦截器已提示 */
  } finally {
    catalogSaving.value = false
  }
}

async function openWindow(row: BitBrowserWindow, headless = false) {
  if (!connReady.value) {
    ElMessage.warning('请先到「比特抓取 → 本机连接」页面配置本机地址与 Token')
    return
  }
  openingId.value = row.browser_id
  try {
    const r = await bitbrowserApi.openWindow(row.browser_id, { headless })
    const d = (r.data ?? {}) as Record<string, unknown>
    openResultTitle.value = row.name ? `${row.name}（${row.browser_id}）` : row.browser_id
    openResultKv.value = buildOpenResultKv(d)
    openResultJson.value = JSON.stringify(d, null, 2)
    openResultVisible.value = true
    ElMessage.success(headless ? '已打开窗口（无头模式）' : '已打开窗口（可见）')
  } catch (e: unknown) {
    const ax = e as { response?: { data?: { detail?: string } }; message?: string }
    const detail =
      ax.response?.data?.detail ||
      (typeof ax.response?.data === 'string' ? ax.response.data : undefined) ||
      ax.message ||
      '打开窗口失败'
    ElMessage.error(`${detail}。若无权限或环境已被收回，请先点「从本机同步」再试。`)
  } finally {
    openingId.value = null
  }
}

onMounted(async () => {
  await loadBbSettings()
  await checkHealth()
  await refresh()
  await silentAutoSync()
})
</script>

<template>
  <div class="page-card">
    <el-alert
      v-if="!connReady"
      type="warning"
      show-icon
      :closable="false"
      style="margin-bottom: 14px"
      title="尚未配置本机 BitBrowser 连接"
    >
      <template #default>
        <span style="font-size: 13px">
          请先到独立模块
          <router-link to="/bitbrowser/connect">本机连接</router-link>
          填写并保存 Local API 地址与 Token，再回到本页同步、打开窗口。
        </span>
      </template>
    </el-alert>

    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; flex-wrap: wrap; gap: 8px">
      <div>
        <h3 style="margin: 0 0 6px 0">比特抓取 · 浏览器窗口</h3>
        <div style="font-size: 12px; color: #888; margin-top: 6px">
          <span>上次成功同步：{{ formatLastSync(syncMeta?.last_sync_at) }}</span>
          <span style="margin-left: 12px">当前缓存：{{ syncMeta?.cached_rows ?? list.length }} 条</span>
          <span v-if="autoSyncing" style="margin-left: 12px; color: #409eff">正在从本机自动同步…</span>
        </div>
        <div style="font-size: 12px; color: #666; max-width: 720px; margin-top: 8px">
          数据来自 BitBrowser 本地服务
          <code>POST /browser/list</code>
          （见
          <a href="https://doc.bitbrowser.net/zh/api-jie-kou-wen-dang/liu-lan-qi-jie-kou" target="_blank" rel="noreferrer">官方文档</a>
          ）。在
          <router-link to="/bitbrowser/connect">本机连接</router-link>
          保存地址且<strong>本地服务可用</strong>时，进入本页会自动拉一次全量列表；也可手动「从本机同步」。「打开」为拆分按钮：主按钮
          <strong>可见窗口</strong>
          ；点右侧
          <strong>▼</strong>
          可选
          <strong>无头（--headless）</strong>
          ，调用
          <code>POST /browser/open</code>
          。弹窗展示
          <code>ws</code>
          /
          <code>http</code>
          /
          <code>driver</code>
          等连接信息。是否已登记到本系统以 BitBrowser
          <strong>窗口 ID</strong>
          为准；「本系统」列汇总登记状态与操作；未登记点「保存」。已登记请到独立页
          <router-link to="/bitbrowser/saved">系统登记</router-link>
          查看本机是否仍在列表（同步后会自动比对并更新）。分类请先在
          <router-link to="/bitbrowser/platforms">平台管理</router-link>
          中建平台。
        </div>
      </div>
      <div style="display: flex; gap: 8px; align-items: center">
        <el-button :disabled="!connReady" @click="checkHealth">检测本地服务</el-button>
        <el-button @click="refresh">刷新列表</el-button>
        <el-button type="primary" :loading="syncing || autoSyncing" :disabled="!connReady || autoSyncing" @click="sync">
          从本机同步
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="health"
      :title="health.ok ? 'BitBrowser 本地服务可访问' : 'BitBrowser 本地服务不可用'"
      :type="health.ok ? 'success' : 'error'"
      show-icon
      :closable="false"
      style="margin-bottom: 12px"
    >
      <template v-if="!health.ok">
        <div style="font-size: 12px">{{ health.error }}</div>
        <div v-if="health.hint" style="font-size: 12px; margin-top: 4px">配置地址：{{ health.hint }}</div>
        <div v-if="health.auth_hint" style="font-size: 12px; margin-top: 4px; color: #a67c00">{{ health.auth_hint }}</div>
      </template>
    </el-alert>

    <p class="bb-table-hint">点击表格最左侧的展开图标，可查看完整窗口 ID、备注、平台账号、比特状态、分组等。</p>

    <el-table
      v-loading="loading"
      class="bb-windows-table"
      :data="list"
      border
      stripe
      row-key="browser_id"
    >
      <el-table-column type="expand" width="44">
        <template #default="{ row }">
          <div class="bb-expand">
            <el-descriptions :column="2" border size="small" class="bb-expand-desc">
              <el-descriptions-item label="窗口 ID" :span="2">
                <code class="bb-mono">{{ row.browser_id }}</code>
              </el-descriptions-item>
              <el-descriptions-item label="备注">{{ row.remark || '—' }}</el-descriptions-item>
              <el-descriptions-item label="平台账号">{{ row.account_username || '—' }}</el-descriptions-item>
              <el-descriptions-item label="比特状态">{{ row.status ?? '—' }}</el-descriptions-item>
              <el-descriptions-item label="分组 ID">{{ row.group_id || '—' }}</el-descriptions-item>
            </el-descriptions>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="seq" label="#" width="56" align="center" />
      <el-table-column prop="name" label="名称" min-width="112" show-overflow-tooltip />
      <el-table-column label="本系统" width="124" align="center">
        <template #default="{ row }">
          <div class="bb-sys-cell">
            <el-tag v-if="row.saved_to_system" type="success" size="small">已登记</el-tag>
            <el-tag v-else type="info" size="small">未登记</el-tag>
            <el-button
              v-if="!row.saved_to_system"
              size="small"
              type="success"
              plain
              @click="openCatalogDialog(row)"
            >
              保存
            </el-button>
            <router-link v-else to="/bitbrowser/saved" class="bb-sys-link">管理</router-link>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="platform" label="环境平台" min-width="130" show-overflow-tooltip />
      <el-table-column label="窗口 ID" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="bb-mono bb-id-preview">{{ row.browser_id }}</span>
        </template>
      </el-table-column>
      <el-table-column label="代理" min-width="100" show-overflow-tooltip>
        <template #default="{ row }">
          {{ proxySummary(row) }}
        </template>
      </el-table-column>
      <el-table-column prop="last_ip" label="最近 IP" min-width="128" show-overflow-tooltip />
      <el-table-column prop="updated_at" label="同步时间" width="158" />
      <el-table-column label="打开" width="132" fixed="right" align="center">
        <template #default="{ row }">
          <el-dropdown
            split-button
            type="primary"
            size="small"
            class="bb-open-split"
            trigger="click"
            :disabled="!connReady"
            :loading="openingId === row.browser_id"
            @click="openWindow(row, false)"
            @command="(cmd: string) => cmd === 'headless' && openWindow(row, true)"
          >
            打开
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="headless">打开（无头 · --headless）</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && !list.length" description="暂无缓存，请点击「从本机同步」" style="margin-top: 24px" />

    <el-dialog v-model="catalogDialogVisible" title="保存到系统" width="480px" destroy-on-close>
      <p v-if="catalogRow" style="margin: 0 0 12px; font-size: 12px; color: #606266">
        唯一标识：
        <code>{{ catalogRow.browser_id }}</code>
      </p>
      <el-form label-width="100px">
        <el-form-item label="分类平台">
          <el-select v-model="catalogForm.platform_id" clearable placeholder="不归类到自建平台" style="width: 100%">
            <el-option
              v-for="p in platforms"
              :key="p.id"
              :label="p.name"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="catalogForm.note" type="textarea" :rows="2" maxlength="500" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="catalogDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="catalogSaving" @click="confirmCatalogSave">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="openResultVisible" title="拉起窗口 · /browser/open 返回" width="720px" destroy-on-close>
      <p style="margin: 0 0 12px; font-size: 13px; color: #606266">
        窗口：{{ openResultTitle }}
      </p>
      <p style="margin: 0 0 12px; font-size: 12px; color: #909399">
        以下为 BitBrowser 本地服务在窗口启动后返回的连接信息（勿泄露）；可用 CDP / Selenium 等按官方文档接入。
      </p>
      <el-descriptions v-if="openResultKv.length" :column="1" border size="small">
        <el-descriptions-item v-for="item in openResultKv" :key="item.key" :label="item.label">
          <span style="word-break: break-all; font-family: ui-monospace, monospace; font-size: 12px">{{ item.value }}</span>
        </el-descriptions-item>
      </el-descriptions>
      <div style="margin-top: 12px">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px">
          <span style="font-size: 13px; font-weight: 500">完整 JSON</span>
          <el-button size="small" @click="copyOpenResultJson">复制 JSON</el-button>
        </div>
        <el-input v-model="openResultJson" type="textarea" :rows="14" readonly class="open-result-json" />
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.open-result-json :deep(textarea) {
  font-family: ui-monospace, monospace;
  font-size: 12px;
}

.bb-table-hint {
  margin: 0 0 10px;
  font-size: 12px;
  color: #909399;
}

/* 拆分「打开」：主按钮 + 下拉箭头，避免用户找不到无头选项 */
.bb-open-split {
  max-width: 100%;
}

.bb-open-split :deep(.el-button:first-child) {
  padding-left: 10px;
  padding-right: 10px;
}

.bb-windows-table :deep(.el-table__cell) {
  padding: 6px 8px;
  vertical-align: middle;
}

.bb-mono {
  font-family: ui-monospace, 'Cascadia Mono', 'Consolas', monospace;
  font-size: 12px;
}

.bb-id-preview {
  word-break: break-all;
  line-height: 1.35;
}

.bb-sys-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.bb-sys-link {
  font-size: 12px;
  color: var(--el-color-primary);
}

.bb-expand {
  padding: 8px 12px 12px 36px;
  max-width: 900px;
}

.bb-expand-desc :deep(.el-descriptions__label) {
  width: 96px;
}
</style>
