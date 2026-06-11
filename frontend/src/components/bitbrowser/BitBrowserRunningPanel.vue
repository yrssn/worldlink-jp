<script setup lang="ts">
import { computed } from 'vue'
import type { BitBrowserRunningRow } from '@/api/bitbrowser'

const props = defineProps<{
  list: BitBrowserRunningRow[]
  loading?: boolean
  disabled?: boolean
  subtitle?: string
}>()

const emit = defineEmits<{
  close: [browserId: string]
  refresh: []
}>()

const OPEN_RESULT_LABELS: Record<string, string> = {
  ws: 'WebSocket（CDP）',
  http: '调试 HTTP',
  driver: 'ChromeDriver 路径',
  webdriver: 'WebDriver 地址',
  coreVersion: '内核版本',
  relay_cdp: 'CDP 中继'
}

function buildOpenDataKv(data: Record<string, unknown>) {
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

function openDataJson(row: BitBrowserRunningRow) {
  const d = row.open_data
  if (!d || !Object.keys(d).length) return ''
  return JSON.stringify(d, null, 2)
}

function hasOpenData(row: BitBrowserRunningRow) {
  return !!(row.open_data && Object.keys(row.open_data).length)
}

const defaultSubtitle = computed(
  () =>
    props.subtitle ||
    '运行状态来自 POST /browser/pids/all；连接信息按「窗口ID + 无头/可见」分别缓存在 Redis（同账号隔离）'
)
</script>

<template>
  <el-card shadow="never" style="margin-bottom: 12px">
    <template #header>
      <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px">
        <div>
          <span style="font-weight: 600">本机运行中的浏览器（当前账号）</span>
          <span style="margin-left: 8px; font-size: 12px; color: #909399">{{ defaultSubtitle }}</span>
        </div>
        <el-button size="small" :disabled="disabled" :loading="loading" @click="emit('refresh')">刷新运行中</el-button>
      </div>
    </template>

    <el-table
      v-loading="loading"
      :data="list"
      border
      size="small"
      row-key="browser_id"
      max-height="420"
    >
      <el-table-column type="expand" width="44">
        <template #default="{ row }">
          <div v-if="hasOpenData(row)" class="bb-running-expand">
            <el-alert
              v-if="row.hint"
              type="info"
              :closable="false"
              show-icon
              style="margin-bottom: 10px"
              :title="row.hint"
            />
            <p v-if="row.opened_at" style="margin: 0 0 8px; font-size: 12px; color: #909399">
              缓存时间（UTC）：{{ row.opened_at }}
              <el-tag v-if="row.headless" size="small" type="warning" style="margin-left: 8px">无头</el-tag>
            </p>
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item
                v-for="item in buildOpenDataKv(row.open_data as Record<string, unknown>)"
                :key="item.key"
                :label="item.label"
              >
                <span class="bb-mono bb-break">{{ item.value }}</span>
              </el-descriptions-item>
            </el-descriptions>
            <div style="margin-top: 10px">
              <span style="font-size: 12px; font-weight: 500">完整 open data JSON</span>
              <el-input
                :model-value="openDataJson(row)"
                type="textarea"
                :rows="8"
                readonly
                class="bb-running-json"
                style="margin-top: 6px"
              />
            </div>
          </div>
          <el-empty v-else description="暂无连接缓存（请在「系统登记」页打开环境）" :image-size="40" />
        </template>
      </el-table-column>
      <el-table-column prop="seq" label="#" width="56" />
      <el-table-column prop="name" label="名称" min-width="90" show-overflow-tooltip />
      <el-table-column prop="browser_id" label="窗口 ID" min-width="160" show-overflow-tooltip />
      <el-table-column prop="pid" label="PID" width="88" />
      <el-table-column label="模式" width="72" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.headless" type="warning" size="small">无头</el-tag>
          <el-tag v-else type="success" size="small">可见</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="连接" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <template v-if="hasOpenData(row)">
            <span v-if="row.open_data?.ws" class="bb-mono bb-conn-line">ws: {{ row.open_data.ws }}</span>
            <span v-else-if="row.open_data?.http" class="bb-mono bb-conn-line">http: {{ row.open_data.http }}</span>
            <span v-else class="bb-muted">展开查看</span>
          </template>
          <span v-else class="bb-muted">无缓存</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="80" align="center" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="danger" plain @click="emit('close', row.browser_id)">关闭</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && !list.length" description="当前无运行中窗口" :image-size="48" />
  </el-card>
</template>

<style scoped>
.bb-running-expand {
  padding: 8px 12px 12px;
}

.bb-mono {
  font-family: ui-monospace, monospace;
  font-size: 12px;
}

.bb-break {
  word-break: break-all;
}

.bb-conn-line {
  font-size: 11px;
}

.bb-muted {
  font-size: 12px;
  color: #909399;
}

.bb-running-json :deep(textarea) {
  font-family: ui-monospace, monospace;
  font-size: 12px;
}
</style>
