<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  bitbrowserApi,
  type BitBrowserCatalogRow,
  type BitBrowserPlatform,
  type BitBrowserSettings
} from '@/api/bitbrowser'

const list = ref<BitBrowserCatalogRow[]>([])
const loading = ref(false)
const bbSettings = ref<BitBrowserSettings | null>(null)
const connReady = computed(() => !!(bbSettings.value?.local_url || '').trim())

const platforms = ref<BitBrowserPlatform[]>([])
const catalogDialogVisible = ref(false)
const catalogSaving = ref(false)
const catalogRow = ref<BitBrowserCatalogRow | null>(null)
const catalogForm = reactive<{ platform_id: number | null; note: string }>({
  platform_id: null,
  note: ''
})

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

async function loadBbSettings() {
  try {
    bbSettings.value = await bitbrowserApi.getSettings()
  } catch {
    bbSettings.value = null
  }
}

async function loadPlatforms() {
  try {
    platforms.value = await bitbrowserApi.listPlatforms()
  } catch {
    platforms.value = []
  }
}

async function refresh() {
  loading.value = true
  try {
    list.value = await bitbrowserApi.listCatalog()
  } finally {
    loading.value = false
  }
}

function displayName(row: BitBrowserCatalogRow) {
  return row.name || row.cached_window_name || '—'
}

async function openCatalogDialog(row: BitBrowserCatalogRow) {
  await loadPlatforms()
  catalogRow.value = row
  catalogForm.platform_id = row.platform_id ?? null
  catalogForm.note = row.note || ''
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
    ElMessage.success('已更新')
    catalogDialogVisible.value = false
    await refresh()
  } catch {
    /* 拦截器已提示 */
  } finally {
    catalogSaving.value = false
  }
}

async function removeFromCatalog(row: BitBrowserCatalogRow) {
  try {
    await ElMessageBox.confirm('确定从系统中移除该窗口登记？（不删除 BitBrowser 本地环境）', '取消登记', {
      type: 'warning'
    })
    await bitbrowserApi.deleteWindowCatalog(row.browser_id)
    ElMessage.success('已移除')
    await refresh()
  } catch {
    /* 取消 */
  }
}

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

async function openWindow(row: BitBrowserCatalogRow) {
  if (!row.in_local_cache) {
    ElMessage.warning('该窗口已不在当前本机同步列表中，请先在比特浏览器恢复环境后，到「浏览器窗口」重新同步再打开')
    return
  }
  if (!connReady.value) {
    ElMessage.warning('请先到「比特抓取 → 本机连接」配置地址与 Token')
    return
  }
  openingId.value = row.browser_id
  try {
    const r = await bitbrowserApi.openWindow(row.browser_id)
    const d = (r.data ?? {}) as Record<string, unknown>
    openResultTitle.value = `${displayName(row)}（${row.browser_id}）`
    openResultKv.value = buildOpenResultKv(d)
    openResultJson.value = JSON.stringify(d, null, 2)
    openResultVisible.value = true
    ElMessage.success('已打开窗口')
  } catch (e: unknown) {
    const ax = e as { response?: { data?: { detail?: string } }; message?: string }
    const detail =
      ax.response?.data?.detail ||
      (typeof ax.response?.data === 'string' ? ax.response.data : undefined) ||
      ax.message ||
      '打开窗口失败'
    ElMessage.error(`${detail}。若无权限或环境已被收回，请到「浏览器窗口」重新同步后再试。`)
  } finally {
    openingId.value = null
  }
}

onMounted(async () => {
  await loadBbSettings()
  await refresh()
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
      title="尚未配置本机连接"
    >
      <template #default>
        <router-link to="/bitbrowser/connect">前往本机连接</router-link>
      </template>
    </el-alert>

    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; flex-wrap: wrap; gap: 8px">
      <div>
        <h3 style="margin: 0 0 6px 0">比特抓取 · 系统登记</h3>
        <p style="margin: 0; font-size: 12px; color: #666; max-width: 800px">
          以 BitBrowser
          <strong>窗口 ID</strong>
          为唯一键。每次在「浏览器窗口」
          <strong>从本机同步</strong>
          时，会与当前本机列表比对：若登记过的窗口已不在本机列表中，此处会显示为「本机列表已无」（仅改状态，不自动删登记）。新建登记请在
          <router-link to="/bitbrowser/windows">浏览器窗口</router-link>
          点击「保存到系统」。
        </p>
      </div>
      <el-button @click="refresh">刷新</el-button>
    </div>

    <el-table v-loading="loading" :data="list" border stripe>
      <el-table-column label="本机列表" width="120" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.in_local_cache" type="success" size="small">在列表中</el-tag>
          <el-tag v-else type="warning" size="small">本机已无</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="platform_name" label="分类平台" min-width="120" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.platform_name || '—' }}
        </template>
      </el-table-column>
      <el-table-column prop="note" label="系统备注" min-width="120" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.note || '—' }}
        </template>
      </el-table-column>
      <el-table-column prop="browser_id" label="窗口 ID" min-width="200" show-overflow-tooltip />
      <el-table-column label="名称" min-width="130" show-overflow-tooltip>
        <template #default="{ row }">
          {{ displayName(row) }}
        </template>
      </el-table-column>
      <el-table-column prop="platform" label="环境平台" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.platform || row.cached_env_platform || '—' }}
        </template>
      </el-table-column>
      <el-table-column prop="remark" label="备注" min-width="100" show-overflow-tooltip />
      <el-table-column prop="proxy_type" label="代理类型" width="100" />
      <el-table-column prop="host" label="代理主机" width="110" show-overflow-tooltip />
      <el-table-column prop="port" label="端口" width="70" />
      <el-table-column prop="last_ip" label="最近 IP" width="120" show-overflow-tooltip />
      <el-table-column prop="updated_at" label="登记更新时间" width="170" />
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="success" plain @click="openCatalogDialog(row)">调整登记</el-button>
          <el-button size="small" type="warning" plain @click="removeFromCatalog(row)">取消登记</el-button>
          <el-button
            size="small"
            type="primary"
            :disabled="!connReady || !row.in_local_cache"
            :loading="openingId === row.browser_id"
            @click="openWindow(row)"
          >
            打开
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && !list.length" description="暂无登记" style="margin-top: 24px" />

    <el-dialog v-model="catalogDialogVisible" title="调整系统登记" width="480px" destroy-on-close>
      <p v-if="catalogRow" style="margin: 0 0 12px; font-size: 12px; color: #606266">
        窗口 ID：
        <code>{{ catalogRow.browser_id }}</code>
      </p>
      <el-form label-width="100px">
        <el-form-item label="分类平台">
          <el-select v-model="catalogForm.platform_id" clearable placeholder="不归类" style="width: 100%">
            <el-option v-for="p in platforms" :key="p.id" :label="p.name" :value="p.id" />
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
      <p style="margin: 0 0 12px; font-size: 13px; color: #606266">窗口：{{ openResultTitle }}</p>
      <p style="margin: 0 0 12px; font-size: 12px; color: #909399">以下为 BitBrowser 本地服务返回的连接信息（勿泄露）。</p>
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
</style>
