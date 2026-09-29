<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  aiWorkshopApi,
  type AiApiKey,
  type AiApiCallLog,
  type AiApiCallLogPage
} from '@/api/aiWorkshop'

// ---------- 密钥管理 ----------
const keys = ref<AiApiKey[]>([])
const keysLoading = ref(false)
const createDialogVisible = ref(false)
const submitting = ref(false)
const createdKey = ref<AiApiKey | null>(null)

const createForm = reactive({
  name: '',
  expires_at: ''
})

const agentBaseUrl = window.location.origin
const mcpEndpoint = `${agentBaseUrl}/api/v1/ai/mcp`

const codexSnippet = computed(
  () => `# ~/.codex/config.toml
[mcp_servers.spider-jp]
url = "${mcpEndpoint}"
# 方式一（推荐）：密钥放环境变量 SPIDER_JP_API_KEY
bearer_token_env_var = "SPIDER_JP_API_KEY"
# 方式二：直接写死请求头
# http_headers = { "Authorization" = "Bearer skjw-你的密钥" }`
)

const claudeSnippet = computed(
  () =>
    `claude mcp add --transport http spider-jp ${mcpEndpoint} \\\n  --header "Authorization: Bearer skjw-你的密钥"`
)

const curlSnippet = computed(
  () => `# 查询系统里已有的达人（按你的账号权限过滤）
curl -X POST ${agentBaseUrl}/api/v1/ai/agent/influencers/search \\
  -H "Authorization: Bearer skjw-你的密钥" \\
  -H "Content-Type: application/json" \\
  -d '{"keyword":"东京","platform":"instagram"}'

# 自动存入找到的达人（已存在会自动补全更新，不会重复）
curl -X POST ${agentBaseUrl}/api/v1/ai/agent/influencers/upsert \\
  -H "Authorization: Bearer skjw-你的密钥" \\
  -H "Content-Type: application/json" \\
  -d '{"display_name":"示例达人","platform":"instagram","url":"https://instagram.com/xxx","followers":12000,"country":"JP","source_channel":"codex 寻客"}'`
)

async function loadKeys() {
  keysLoading.value = true
  try {
    keys.value = await aiWorkshopApi.listKeys()
  } catch {
    // 错误提示由 http 拦截器统一弹出
  } finally {
    keysLoading.value = false
  }
}

function openCreate() {
  createForm.name = ''
  createForm.expires_at = ''
  createdKey.value = null
  createDialogVisible.value = true
}

async function handleCreate() {
  if (!createForm.name.trim()) return ElMessage.warning('请填写密钥名称')
  submitting.value = true
  try {
    const created = await aiWorkshopApi.createKey({
      name: createForm.name.trim(),
      expires_at: createForm.expires_at ? new Date(createForm.expires_at).toISOString() : null
    })
    createDialogVisible.value = false
    createdKey.value = created
    await loadKeys()
  } catch {
    // 拦截器已提示
  } finally {
    submitting.value = false
  }
}

async function handleToggle(row: AiApiKey) {
  try {
    await aiWorkshopApi.updateKey(row.id, { is_active: !row.is_active })
    row.is_active = !row.is_active
    ElMessage.success(row.is_active ? '已启用' : '已停用')
  } catch {
    await loadKeys()
  }
}

async function handleDelete(row: AiApiKey) {
  await ElMessageBox.confirm(
    `确认删除密钥「${row.name}」？使用该密钥的 Agent 将立即失去访问能力。`,
    '删除确认',
    { type: 'warning', confirmButtonText: '删除', confirmButtonClass: 'el-button--danger' }
  )
  try {
    await aiWorkshopApi.removeKey(row.id)
    ElMessage.success('已删除')
    await loadKeys()
    if (logKeyId.value === row.id) {
      logKeyId.value = ''
    }
    await loadLogs()
  } catch {
    // 拦截器已提示
  }
}

async function copyText(text: string, tip = '已复制') {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(tip)
  } catch {
    ElMessage.error('复制失败，请手动选择复制')
  }
}

function formatDate(value?: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString('zh-CN')
}

// ---------- 调用记录 ----------
const logs = ref<AiApiCallLog[]>([])
const logsLoading = ref(false)
const logsTotal = ref(0)
const logsPage = ref(1)
const logsPageSize = ref(10)
const logKeyId = ref<number | ''>('')

async function loadLogs() {
  logsLoading.value = true
  try {
    const page: AiApiCallLogPage = await aiWorkshopApi.listLogs({
      page: logsPage.value,
      page_size: logsPageSize.value,
      key_id: typeof logKeyId.value === 'number' ? logKeyId.value : undefined
    })
    logs.value = page.items
    logsTotal.value = page.total
  } catch {
    // 拦截器已提示
  } finally {
    logsLoading.value = false
  }
}

function handleLogFilterChange() {
  logsPage.value = 1
  loadLogs()
}

function handleLogPageSizeChange() {
  logsPage.value = 1
  loadLogs()
}

function detailText(detail?: Record<string, unknown> | null) {
  if (!detail || !Object.keys(detail).length) return '—'
  return JSON.stringify(detail)
}

onMounted(() => {
  loadKeys()
  loadLogs()
})
</script>

<template>
  <div>
    <!-- Agent 接入说明 -->
    <el-card shadow="never" style="margin-bottom: 16px">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span>Agent 接入说明</span>
          <el-text type="info" size="small">
            MCP 端点：<el-text style="font-family: monospace">{{ mcpEndpoint }}</el-text>
            <el-button link type="primary" @click="copyText(mcpEndpoint, '端点已复制')">复制</el-button>
          </el-text>
        </div>
      </template>

      <el-row :gutter="16">
        <el-col :xs="24" :md="8">
          <el-text tag="div" strong style="margin-bottom: 6px">Codex CLI（config.toml）</el-text>
          <div class="snippet">
            <pre>{{ codexSnippet }}</pre>
            <el-button class="snippet-copy" link type="primary" @click="copyText(codexSnippet)">
              复制
            </el-button>
          </div>
        </el-col>
        <el-col :xs="24" :md="8">
          <el-text tag="div" strong style="margin-bottom: 6px">Claude Code（CLI 命令）</el-text>
          <div class="snippet">
            <pre>{{ claudeSnippet }}</pre>
            <el-button class="snippet-copy" link type="primary" @click="copyText(claudeSnippet)">
              复制
            </el-button>
          </div>
        </el-col>
        <el-col :xs="24" :md="8">
          <el-text tag="div" strong style="margin-bottom: 6px">通用 HTTP（任意脚本/平台）</el-text>
          <div class="snippet">
            <pre>{{ curlSnippet }}</pre>
            <el-button class="snippet-copy" link type="primary" @click="copyText(curlSnippet)">
              复制
            </el-button>
          </div>
        </el-col>
      </el-row>

      <el-alert
        style="margin-top: 12px"
        type="info"
        :closable="false"
        show-icon
        title="Agent 拿到密钥后，能查到、能写入的数据范围与你当前账号完全一致：普通账号只能查/存自己的数据，超管账号可见全部。"
      />
    </el-card>

    <!-- 密钥管理 -->
    <el-card shadow="never" style="margin-bottom: 16px">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span>我的密钥</span>
          <el-button type="primary" @click="openCreate">+ 新建密钥</el-button>
        </div>
      </template>

      <el-table :data="keys" v-loading="keysLoading" border stripe>
        <el-table-column label="名称" prop="name" min-width="140" />

        <el-table-column label="密钥前缀" min-width="150">
          <template #default="{ row }">
            <el-text style="font-family: monospace">{{ row.key_prefix }}********</el-text>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-switch :model-value="row.is_active" @change="handleToggle(row)" />
          </template>
        </el-table-column>

        <el-table-column label="过期时间" width="160" align="center">
          <template #default="{ row }">
            <span v-if="row.expires_at">{{ formatDate(row.expires_at) }}</span>
            <el-text v-else type="info">永不过期</el-text>
          </template>
        </el-table-column>

        <el-table-column label="最近使用" min-width="190" align="center">
          <template #default="{ row }">
            <div v-if="row.last_used_at">
              <el-text tag="div">{{ formatDate(row.last_used_at) }}</el-text>
              <el-text v-if="row.last_used_ip" tag="div" type="info" size="small">
                {{ row.last_used_ip }}
              </el-text>
            </div>
            <el-text v-else type="info">从未使用</el-text>
          </template>
        </el-table-column>

        <el-table-column label="创建时间" width="160" align="center">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>

        <el-table-column label="操作" width="90" align="center" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 调用记录 -->
    <el-card shadow="never">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span>调用记录</span>
          <el-space>
            <el-select
              v-model="logKeyId"
              placeholder="全部密钥"
              clearable
              style="width: 180px"
              @change="handleLogFilterChange"
            >
              <el-option
                v-for="key in keys"
                :key="key.id"
                :label="key.name"
                :value="key.id"
              />
            </el-select>
            <el-button @click="loadLogs">刷新</el-button>
          </el-space>
        </div>
      </template>

      <el-table :data="logs" v-loading="logsLoading" border stripe>
        <el-table-column label="时间" width="160" align="center">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>

        <el-table-column label="密钥" width="130">
          <template #default="{ row }">{{ row.key_name || '—' }}</template>
        </el-table-column>

        <el-table-column label="操作" prop="action" width="170">
          <template #default="{ row }">
            <el-text style="font-family: monospace">{{ row.action }}</el-text>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === 'ok' ? 'success' : 'danger'" effect="plain">
              {{ row.status === 'ok' ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="摘要" min-width="260">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.detail && Object.keys(row.detail).length"
              :content="detailText(row.detail)"
              placement="top"
            >
              <el-text size="small" truncated style="max-width: 100%">
                {{ detailText(row.detail) }}
              </el-text>
            </el-tooltip>
            <el-text v-else type="info">—</el-text>
          </template>
        </el-table-column>

        <el-table-column label="错误" min-width="200">
          <template #default="{ row }">
            <el-tooltip v-if="row.error" :content="row.error" placement="top">
              <el-text type="danger" size="small" truncated style="max-width: 100%">
                {{ row.error }}
              </el-text>
            </el-tooltip>
            <el-text v-else type="info">—</el-text>
          </template>
        </el-table-column>
      </el-table>

      <div style="display: flex; justify-content: flex-end; margin-top: 12px">
        <el-pagination
          v-model:current-page="logsPage"
          v-model:page-size="logsPageSize"
          :total="logsTotal"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          @current-change="loadLogs"
          @size-change="handleLogPageSizeChange"
        />
      </div>
    </el-card>

    <!-- 新建密钥 -->
    <el-dialog v-model="createDialogVisible" title="新建 Agent 密钥" width="460px">
      <el-form label-width="90px" @submit.prevent>
        <el-form-item label="名称" required>
          <el-input
            v-model="createForm.name"
            placeholder="用途备注，如：codex 寻客"
            maxlength="64"
          />
        </el-form-item>
        <el-form-item label="过期时间">
          <el-date-picker
            v-model="createForm.expires_at"
            type="datetime"
            placeholder="留空则永不过期"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 创建成功：展示完整密钥（仅一次） -->
    <el-dialog
      :model-value="!!createdKey"
      title="密钥创建成功"
      width="520px"
      :close-on-click-modal="false"
      @close="createdKey = null"
    >
      <el-alert
        type="warning"
        show-icon
        :closable="false"
        title="请立即复制保存，关闭后将无法再次查看完整密钥"
        style="margin-bottom: 12px"
      />
      <div class="created-key">
        <el-text style="font-family: monospace; word-break: break-all">
          {{ createdKey?.key }}
        </el-text>
      </div>
      <template #footer>
        <el-button type="primary" @click="copyText(createdKey?.key || '', '密钥已复制')">
          复制密钥
        </el-button>
        <el-button @click="createdKey = null">我已保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.snippet {
  position: relative;
  background: var(--el-fill-color-light, #f5f7fa);
  border-radius: 6px;
  padding: 10px 12px;
}

.snippet pre {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  white-space: pre-wrap;
  word-break: break-all;
}

.snippet-copy {
  position: absolute;
  top: 6px;
  right: 10px;
  background: inherit;
}

.created-key {
  background: var(--el-fill-color-light, #f5f7fa);
  border-radius: 6px;
  padding: 12px;
}
</style>
