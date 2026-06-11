<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  bitbrowserApi,
  type BitBrowserCatalogRow,
  type BitBrowserPlatform,
  type BitBrowserSettings
} from '@/api/bitbrowser'
import { useBitBrowserRunning } from '@/composables/useBitBrowserRunning'
import BitBrowserRunningPanel from '@/components/bitbrowser/BitBrowserRunningPanel.vue'

const list = ref<BitBrowserCatalogRow[]>([])
const loading = ref(false)
const bbSettings = ref<BitBrowserSettings | null>(null)
const connReady = computed(() => !!(bbSettings.value?.local_url || '').trim())
const { runningList, runningLoading, runningPidMap, runningById, loadRunning, closeRunning } =
  useBitBrowserRunning(connReady)

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
  coreVersion: '内核版本',
  relay_cdp: 'CDP 中继'
}
const openResultVisible = ref(false)
const openResultTitle = ref('')
const openResultHint = ref('')
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
    await loadRunning()
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
  const priority = ['ws', 'http', 'relay_cdp', 'driver', 'webdriver', 'coreVersion']
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

async function presentOpenResult(
  row: BitBrowserCatalogRow,
  data: Record<string, unknown>,
  headless: boolean,
  hint?: string | null
) {
  openResultTitle.value = `${displayName(row)}（${row.browser_id}）`
  openResultHint.value = hint || (headless ? '无头模式不会显示浏览器界面。' : '')
  openResultKv.value = buildOpenResultKv(data)
  openResultJson.value = JSON.stringify(data, null, 2)
  if (!headless) {
    await new Promise((r) => setTimeout(r, 400))
  }
  await nextTick()
  openResultVisible.value = true
}

async function openWindow(row: BitBrowserCatalogRow, headless = false, restart = false) {
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
    const r = await bitbrowserApi.openWindow(row.browser_id, { headless, restart })
    const d = (r.data ?? {}) as Record<string, unknown>
    if (r.already_open) {
      if (Object.keys(d).length) {
        await presentOpenResult(row, d, headless, r.hint)
        ElMessage.success(r.reconnected ? '已唤起并刷新连接信息' : '已显示缓存的连接信息')
      } else {
        openResultTitle.value = `${displayName(row)}（${row.browser_id}）`
        openResultHint.value = r.hint || `已在运行（PID ${r.pid ?? '—'}）`
        openResultKv.value = []
        openResultJson.value = ''
        openResultVisible.value = true
        ElMessage.info(r.hint || '该环境已在运行')
      }
      await loadRunning()
      return
    }
    await presentOpenResult(row, d, headless, r.hint)
    if (r.mode_switched) {
      ElMessage.success('已切换无头/可见模式并重新打开')
    } else if (headless) {
      ElMessage.success('已打开（无头，无界面）')
    } else if (r.restarted || restart) {
      ElMessage.success('已先关再开')
    } else {
      ElMessage.success('已打开窗口（可见）')
    }
    await loadRunning()
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
      <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap">
        <el-button @click="refresh">刷新</el-button>
      </div>
    </div>

    <BitBrowserRunningPanel
      v-if="connReady"
      :list="runningList"
      :loading="runningLoading"
      :disabled="!connReady"
      @close="closeRunning"
      @refresh="loadRunning"
    />

    <p style="margin: 0 0 10px; font-size: 12px; color: #909399">
      同一环境仅一个进程（无头/可见不能并存）；不同环境可同时运行。同模式「打开」= 唤起并返回连接信息；切换模式会自动先关再开。
    </p>

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
      <el-table-column label="运行" width="120" align="center">
        <template #default="{ row }">
          <template v-if="runningPidMap[row.browser_id]">
            <el-tag type="success" size="small">PID {{ runningPidMap[row.browser_id] }}</el-tag>
            <el-tag
              v-if="runningById[row.browser_id]"
              :type="runningById[row.browser_id].headless ? 'warning' : 'success'"
              size="small"
              style="margin-left: 4px"
            >
              {{ runningById[row.browser_id].headless ? '无头' : '可见' }}
            </el-tag>
          </template>
          <el-tag v-else type="info" size="small">未运行</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="360" fixed="right">
        <template #default="{ row }">
          <div class="bb-saved-actions">
            <el-button size="small" type="success" plain @click="openCatalogDialog(row)">调整登记</el-button>
            <el-button size="small" type="warning" plain @click="removeFromCatalog(row)">取消登记</el-button>
            <el-button
              size="small"
              type="primary"
              :disabled="!connReady || !row.in_local_cache"
              :loading="openingId === row.browser_id"
              @click="openWindow(row, false, false)"
            >
              打开
            </el-button>
            <el-button
              size="small"
              plain
              :disabled="!connReady || !row.in_local_cache"
              :loading="openingId === row.browser_id"
              @click="openWindow(row, true, false)"
            >
              无头
            </el-button>
            <el-button
              size="small"
              type="warning"
              plain
              :disabled="!connReady || !row.in_local_cache"
              :loading="openingId === row.browser_id"
              @click="openWindow(row, false, true)"
            >
              先关再开
            </el-button>
          </div>
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

    <el-dialog
      v-model="openResultVisible"
      title="拉起窗口 · /browser/open 返回"
      width="720px"
      append-to-body
      :z-index="10050"
      destroy-on-close
    >
      <p style="margin: 0 0 12px; font-size: 13px; color: #606266">窗口：{{ openResultTitle }}</p>
      <el-alert
        v-if="openResultHint"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
        :title="openResultHint"
      />
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
      <template #footer>
        <el-button type="primary" @click="openResultVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.open-result-json :deep(textarea) {
  font-family: ui-monospace, monospace;
  font-size: 12px;
}

.bb-saved-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
  align-items: center;
}

</style>
