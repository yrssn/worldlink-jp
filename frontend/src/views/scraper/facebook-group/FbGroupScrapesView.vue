<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  fbGroupScrapeApi,
  type FbGroupPost,
  type FbGroupPullTask,
  type FbGroupScrape,
  type FbGroupViewOption,
  type FbGroupScheduleTask
} from '@/api/fbGroupScrape'
import { useAuthStore } from '@/store/auth'
import FbGroupScheduleView from './FbGroupScheduleView.vue'

const auth = useAuthStore()
const isAdmin = computed(() => auth.isAdmin)

// ─── 群组配置列表 ────────────────────────────────────────────────
const list = ref<FbGroupScrape[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const filter = reactive({ keyword: '', include_deleted: false })
const form = reactive({ connection: '', title: '', remark: '' })

async function refresh() {
  loading.value = true
  try {
    list.value = await fbGroupScrapeApi.list({
      keyword: filter.keyword.trim() || undefined,
      include_deleted: isAdmin.value && filter.include_deleted ? true : undefined
    })
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.connection = ''
  form.title = ''
  form.remark = ''
  dialogVisible.value = true
}

function openEdit(row: FbGroupScrape) {
  if (row.deleted_at) { ElMessage.warning('已删除记录不可编辑，可点「恢复」'); return }
  editingId.value = row.id
  form.connection = row.connection
  form.title = row.title
  form.remark = row.remark || ''
  dialogVisible.value = true
}

async function submitForm() {
  const connection = form.connection.trim()
  const title = form.title.trim()
  if (!connection) { ElMessage.warning('请填写连接'); return }
  if (!title) { ElMessage.warning('请填写标题'); return }
  try {
    const payload = { connection, title, remark: form.remark.trim() || undefined }
    if (editingId.value == null) {
      await fbGroupScrapeApi.create(payload); ElMessage.success('已创建')
    } else {
      await fbGroupScrapeApi.update(editingId.value, payload); ElMessage.success('已更新')
    }
    dialogVisible.value = false
    await refresh()
  } catch { /* 拦截器 */ }
}

async function removeRow(row: FbGroupScrape) {
  try {
    await ElMessageBox.confirm(`确定删除「${row.title}」？（软删除，可恢复）`, '删除', { type: 'warning' })
    await fbGroupScrapeApi.remove(row.id); ElMessage.success('已删除')
    await refresh()
  } catch { /* 取消 */ }
}

async function restoreRow(row: FbGroupScrape) {
  try {
    await fbGroupScrapeApi.restore(row.id); ElMessage.success('已恢复')
    await refresh()
  } catch { /* 拦截器 */ }
}

// ─── 多选 ──────────────────────────────────────────────────────
const selectedConfigs = ref<FbGroupScrape[]>([])
function onSelectionChange(rows: FbGroupScrape[]) {
  selectedConfigs.value = rows
}

// ─── 批量拉取 ────────────────────────────────────────────────────
const batchPullVisible = ref(false)
const batchSubmitting = ref(false)
const batchPullForm = reactive({
  results_limit: 20,
  view_option: 'CHRONOLOGICAL' as FbGroupViewOption,
  search_group_keyword: '',
  search_group_year: '',
  only_posts_newer_than: ''
})

function openBatchPull() {
  batchPullForm.results_limit = 20
  batchPullForm.view_option = 'CHRONOLOGICAL'
  batchPullForm.search_group_keyword = ''
  batchPullForm.search_group_year = ''
  batchPullForm.only_posts_newer_than = ''
  batchPullVisible.value = true
}

async function confirmBatchPull() {
  if (!selectedConfigs.value.length) return
  batchSubmitting.value = true
  try {
    const tasks = await fbGroupScrapeApi.batchPull({
      config_ids: selectedConfigs.value.map(c => c.id),
      results_limit: batchPullForm.results_limit,
      view_option: batchPullForm.view_option,
      search_group_keyword: batchPullForm.search_group_keyword.trim() || undefined,
      search_group_year: batchPullForm.search_group_year.trim() || undefined,
      only_posts_newer_than: batchPullForm.only_posts_newer_than.trim() || undefined
    })
    batchPullVisible.value = false
    ElMessage.success(`已为 ${tasks.length} 个群组创建拉取任务，正在后台执行`)
    selectedConfigs.value = []
  } catch { /* 拦截器 */ } finally {
    batchSubmitting.value = false
  }
}

// ─── 后台拉取任务 ────────────────────────────────────────────────
const pullDialogVisible = ref(false)
const pullTarget = ref<FbGroupScrape | null>(null)
const pullSubmitting = ref(false)
const pullForm = reactive({
  results_limit: 20,
  view_option: 'CHRONOLOGICAL' as FbGroupViewOption,
  search_group_keyword: '',
  search_group_year: '',
  only_posts_newer_than: ''
})

const taskPanelVisible = ref(false)
const taskPanelConfig = ref<FbGroupScrape | null>(null)
const tasks = ref<FbGroupPullTask[]>([])
const tasksLoading = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

function openPull(row: FbGroupScrape) {
  pullTarget.value = row
  pullForm.results_limit = 20
  pullForm.view_option = 'CHRONOLOGICAL'
  pullForm.search_group_keyword = ''
  pullForm.search_group_year = ''
  pullForm.only_posts_newer_than = ''
  pullDialogVisible.value = true
}

async function confirmPull() {
  if (!pullTarget.value) return
  pullSubmitting.value = true
  try {
    const task = await fbGroupScrapeApi.pull(pullTarget.value.id, {
      results_limit: pullForm.results_limit,
      view_option: pullForm.view_option,
      search_group_keyword: pullForm.search_group_keyword.trim() || undefined,
      search_group_year: pullForm.search_group_year.trim() || undefined,
      only_posts_newer_than: pullForm.only_posts_newer_than.trim() || undefined
    })
    pullDialogVisible.value = false
    ElMessage.success(`任务已提交（#${task.id}），正在后台拉取，可在「任务列表」查看进度`)
    openTaskPanel(pullTarget.value)
  } catch { /* 拦截器 */ } finally {
    pullSubmitting.value = false
  }
}

async function openTaskPanel(row: FbGroupScrape) {
  taskPanelConfig.value = row
  taskPanelVisible.value = true
  await loadTasks()
  startPoll()
}

async function loadTasks() {
  if (!taskPanelConfig.value) return
  tasksLoading.value = true
  try {
    tasks.value = await fbGroupScrapeApi.listTasks(taskPanelConfig.value.id)
  } catch { /* 拦截器 */ } finally {
    tasksLoading.value = false
  }
}

function startPoll() {
  stopPoll()
  pollTimer = setInterval(async () => {
    const hasActive = tasks.value.some(t => t.status === 'pending' || t.status === 'running')
    if (!hasActive) { stopPoll(); return }
    await loadTasks()
  }, 4000)
}

function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

function onTaskPanelClose() {
  stopPoll()
  tasks.value = []
  taskPanelConfig.value = null
}

async function markTaskFailed(task: FbGroupPullTask) {
  try {
    await ElMessageBox.confirm(
      `确定将任务 #${task.id} 标记为失败？此操作不可撤销。`,
      '标记失败',
      { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' }
    )
    const updated = await fbGroupScrapeApi.markFailed(task.id)
    const idx = tasks.value.findIndex(t => t.id === task.id)
    if (idx !== -1) tasks.value[idx] = updated
    ElMessage.success(`任务 #${task.id} 已标记为失败`)
  } catch { /* 取消 */ }
}

function taskStatusType(status: string) {
  if (status === 'done') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

function taskStatusLabel(status: string) {
  if (status === 'done') return '完成'
  if (status === 'failed') return '失败'
  if (status === 'running') return '执行中'
  return '等待'
}

// ─── 帖子预览 ────────────────────────────────────────────────────
const postsDrawerVisible = ref(false)
const postsTask = ref<FbGroupPullTask | null>(null)
const posts = ref<FbGroupPost[]>([])
const postsTotal = ref(0)
const postsPage = ref(1)
const postsPageSize = ref(20)
const postsKeyword = ref('')
const postsLoading = ref(false)
const postsDetailRow = ref<FbGroupPost | null>(null)
const postsDetailVisible = ref(false)

// ─── 定时任务 ────────────────────────────────────────────────────
const scheduleDrawerVisible = ref(false)
const scheduleConfig = ref<FbGroupScrape | null>(null)
const schedules = ref<FbGroupScheduleTask[]>([])
const schedulesLoading = ref(false)

async function openSchedule(row: FbGroupScrape) {
  scheduleConfig.value = row
  scheduleDrawerVisible.value = true
  await loadSchedules()
}

async function loadSchedules() {
  if (!scheduleConfig.value) return
  schedulesLoading.value = true
  try {
    schedules.value = await fbGroupScrapeApi.listSchedules(scheduleConfig.value.id)
  } catch {
    /* 拦截器 */
  } finally {
    schedulesLoading.value = false
  }
}

async function openPosts(task: FbGroupPullTask) {
  postsTask.value = task
  postsPage.value = 1
  postsKeyword.value = ''
  postsDrawerVisible.value = true
  await loadPosts()
}

async function loadPosts() {
  if (!postsTask.value) return
  postsLoading.value = true
  try {
    const r = await fbGroupScrapeApi.listTaskPosts(postsTask.value.id, {
      page: postsPage.value,
      page_size: postsPageSize.value,
      keyword: postsKeyword.value.trim() || undefined
    })
    posts.value = r.items
    postsTotal.value = r.total
  } catch { /* 拦截器 */ } finally {
    postsLoading.value = false
  }
}

function onPostsPageChange(p: number) {
  postsPage.value = p
  loadPosts()
}

function showPostDetail(row: FbGroupPost) {
  postsDetailRow.value = row
  postsDetailVisible.value = true
}

// ─── 通用工具 ────────────────────────────────────────────────────
function formatTime(iso: string | null | undefined) {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false })
}

function truncate(s: string | null | undefined, n = 80) {
  if (!s) return '—'
  return s.length > n ? s.slice(0, n) + '…' : s
}

onMounted(refresh)
onUnmounted(stopPoll)
</script>

<template>
  <div class="page-card">
    <!-- 标题栏 -->
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;gap:8px">
      <div>
        <h3 style="margin:0 0 6px 0">Facebook 群组维度抓取</h3>
        <p style="margin:0;font-size:12px;color:#666">
          维护群组连接后，点「拉取」提交后台任务（立即返回），再点「任务」查看进度与结果。
        </p>
      </div>
      <el-button type="primary" @click="openCreate">新建记录</el-button>
    </div>

    <!-- 批量操作栏 -->
    <div v-if="selectedConfigs.length" style="display:flex;align-items:center;gap:8px;margin-bottom:10px;padding:8px 12px;background:#ecf5ff;border-radius:6px;border:1px solid #b3d8ff">
      <span style="font-size:13px;color:#409eff;font-weight:500">已选 {{ selectedConfigs.length }} 个群组</span>
      <el-button size="small" type="primary" @click="openBatchPull">批量拉取</el-button>
      <el-button size="small" plain @click="selectedConfigs = []">取消选择</el-button>
    </div>

    <!-- 筛选 -->
    <el-card shadow="never" style="margin-bottom:12px">
      <el-form :inline="true" @submit.prevent="refresh">
        <el-form-item label="关键词">
          <el-input v-model="filter.keyword" clearable placeholder="标题/连接/备注" style="width:220px" />
        </el-form-item>
        <el-form-item v-if="isAdmin">
          <el-checkbox v-model="filter.include_deleted">含已删除</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="refresh">查询</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 群组配置表格 -->
    <el-table v-loading="loading" :data="list" border stripe row-key="id" @selection-change="onSelectionChange">
      <el-table-column type="selection" width="44" :selectable="(row: FbGroupScrape) => !row.deleted_at" />
      <el-table-column prop="id" label="ID" width="72" />
      <el-table-column prop="title" label="标题" min-width="140" show-overflow-tooltip />
      <el-table-column prop="connection" label="连接" min-width="220" show-overflow-tooltip>
        <template #default="{ row }">
          <a v-if="row.connection.startsWith('http')" :href="row.connection" target="_blank" rel="noopener noreferrer" class="fb-link">
            {{ row.connection }}
          </a>
          <span v-else>{{ row.connection }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="remark" label="备注" min-width="120" show-overflow-tooltip />
      <el-table-column label="创建人" width="100">
        <template #default="{ row }">{{ row.created_by_username || row.created_by_id }}</template>
      </el-table-column>
      <el-table-column label="创建时间" width="168">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="88" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.deleted_at" type="info" size="small">已删除</el-tag>
          <el-tag v-else type="success" size="small">正常</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="320" fixed="right">
        <template #default="{ row }">
          <template v-if="!row.deleted_at">
            <el-button size="small" type="primary" plain @click="openPull(row)">拉取</el-button>
            <el-button size="small" type="success" plain @click="openTaskPanel(row)">任务</el-button>
            <el-button size="small" type="info" plain @click="openSchedule(row)">定时</el-button>
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="removeRow(row)">删除</el-button>
          </template>
          <el-button v-else size="small" type="warning" plain @click="restoreRow(row)">恢复</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && !list.length" description="暂无记录" style="margin-top:24px" />

    <!-- 新建/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="editingId == null ? '新建群组维度' : '编辑群组维度'" width="640px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" maxlength="200" show-word-limit placeholder="便于识别的名称" />
        </el-form-item>
        <el-form-item label="连接" required>
          <el-input v-model="form.connection" type="textarea" :rows="3" placeholder="Facebook 群组 URL 或连接标识" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="500" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>

    <!-- 拉取参数对话框 -->
    <el-dialog v-model="pullDialogVisible" title="提交后台拉取任务" width="560px" destroy-on-close>
      <p v-if="pullTarget" style="margin:0 0 12px;font-size:12px;color:#606266">
        群组：<code>{{ pullTarget.connection }}</code>
      </p>
      <el-alert type="success" :closable="false" show-icon style="margin-bottom:12px"
        title="点击「提交」后任务在后台运行，页面立即返回，可通过「任务」按钮查看进度和结果。" />
      <el-form label-width="120px">
        <el-form-item label="帖子条数">
          <el-input-number v-model="pullForm.results_limit" :min="1" :max="500" />
        </el-form-item>
        <el-form-item label="排序 viewOption">
          <el-select v-model="pullForm.view_option" style="width:100%">
            <el-option label="CHRONOLOGICAL（时间序）" value="CHRONOLOGICAL" />
            <el-option label="RECENT_ACTIVITY（最新活动）" value="RECENT_ACTIVITY" />
            <el-option label="TOP_POSTS（热门）" value="TOP_POSTS" />
            <el-option label="CHRONOLOGICAL_LISTINGS（买卖类）" value="CHRONOLOGICAL_LISTINGS" />
          </el-select>
        </el-form-item>
        <el-form-item label="搜索字母">
          <el-input v-model="pullForm.search_group_keyword" placeholder="可选，如 a" />
        </el-form-item>
        <el-form-item label="搜索年份">
          <el-input v-model="pullForm.search_group_year" placeholder="需配合搜索字母，如 2024" />
        </el-form-item>
        <el-form-item label="不早于">
          <el-input v-model="pullForm.only_posts_newer_than" placeholder="如 2024-01-01 或 7 days" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pullDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="pullSubmitting" @click="confirmPull">提交任务</el-button>
      </template>
    </el-dialog>

    <!-- 任务列表抽屉 -->
    <el-drawer
      v-model="taskPanelVisible"
      :title="`拉取任务列表 — ${taskPanelConfig?.title || ''}`"
      size="720px"
      destroy-on-close
      @close="onTaskPanelClose"
    >
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <span style="font-size:13px;color:#606266">自动每 4 秒刷新进行中的任务</span>
        <div style="display:flex;gap:8px">
          <el-button size="small" @click="loadTasks">手动刷新</el-button>
          <el-button size="small" type="primary" plain @click="openPull(taskPanelConfig!)">新建拉取</el-button>
        </div>
      </div>
      <el-table v-loading="tasksLoading" :data="tasks" border stripe row-key="id" size="small">
        <el-table-column prop="id" label="ID" width="64" />
        <el-table-column label="状态" width="84" align="center">
          <template #default="{ row }">
            <el-tag :type="taskStatusType(row.status)" size="small">{{ taskStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="帖数" prop="result_count" width="72" align="center" />
        <el-table-column label="参数" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">
            <span style="font-size:12px">
              {{ row.params?.results_limit }} 条 / {{ row.params?.view_option }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="提交时间" width="148">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="完成时间" width="148">
          <template #default="{ row }">{{ formatTime(row.finished_at) }}</template>
        </el-table-column>
        <el-table-column label="错误" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.error" style="color:#f56c6c;font-size:12px">{{ row.error }}</span>
            <span v-else class="fb-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <div style="display:flex;gap:4px;flex-wrap:wrap">
              <el-button
                v-if="row.status === 'done' && row.result_count > 0"
                size="small"
                type="primary"
                plain
                @click="openPosts(row)"
              >查看帖子</el-button>
              <el-button
                v-if="row.status === 'running' || row.status === 'pending'"
                size="small"
                type="danger"
                plain
                @click="markTaskFailed(row)"
              >标记失败</el-button>
              <span v-if="row.status === 'failed' || (row.status === 'done' && row.result_count === 0)" class="fb-muted" style="font-size:12px">—</span>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!tasksLoading && !tasks.length" description="暂无任务，点「新建拉取」开始" style="margin-top:24px" />
    </el-drawer>

    <!-- 帖子列表抽屉 -->
    <el-drawer
      v-model="postsDrawerVisible"
      :title="`帖子列表 — 任务 #${postsTask?.id} (${postsTask?.result_count} 条)`"
      size="90%"
      destroy-on-close
    >
      <div style="display:flex;gap:8px;margin-bottom:12px;align-items:center">
        <el-input
          v-model="postsKeyword"
          clearable
          placeholder="文本/用户名关键词"
          style="width:240px"
          @keyup.enter="loadPosts"
          @clear="loadPosts"
        />
        <el-button type="primary" @click="loadPosts">搜索</el-button>
        <span style="font-size:12px;color:#909399;margin-left:8px">共 {{ postsTotal }} 条</span>
      </div>
      <el-table v-loading="postsLoading" :data="posts" border stripe row-key="id" size="small">
        <el-table-column prop="legacy_id" label="FB 帖子 ID" width="160" show-overflow-tooltip />
        <el-table-column label="发布时间" width="148">
          <template #default="{ row }">{{ formatTime(row.post_time) }}</template>
        </el-table-column>
        <el-table-column label="用户" width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.user_name || row.user_id || '—' }}</template>
        </el-table-column>
        <el-table-column label="内容" min-width="260" show-overflow-tooltip>
          <template #default="{ row }">{{ truncate(row.text, 100) }}</template>
        </el-table-column>
        <el-table-column label="👍" prop="likes_count" width="60" align="center" />
        <el-table-column label="💬" prop="comments_count" width="60" align="center" />
        <el-table-column label="图/视频" width="80" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.has_attachments" size="small" type="info">有</el-tag>
            <span v-else class="fb-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="转发" width="72" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.has_shared_post" size="small">转</el-tag>
            <span v-else class="fb-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="链接" width="80" align="center">
          <template #default="{ row }">
            <a v-if="row.post_url" :href="row.post_url" target="_blank" rel="noopener noreferrer" class="fb-link" style="font-size:12px">原文</a>
            <span v-else class="fb-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button size="small" plain @click="showPostDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div style="margin-top:12px;display:flex;justify-content:flex-end">
        <el-pagination
          v-model:current-page="postsPage"
          :page-size="postsPageSize"
          :total="postsTotal"
          layout="total, prev, pager, next"
          @current-change="onPostsPageChange"
        />
      </div>
    </el-drawer>

    <!-- 批量拉取对话框 -->
    <el-dialog v-model="batchPullVisible" title="批量拉取任务" width="600px" destroy-on-close>
      <el-alert type="success" :closable="false" show-icon style="margin-bottom:14px"
        :title="`将为以下 ${selectedConfigs.length} 个群组各创建一个后台拉取任务`" />
      <el-descriptions :column="1" border size="small" style="margin-bottom:14px">
        <el-descriptions-item v-for="c in selectedConfigs" :key="c.id" :label="c.title">
          <span style="font-size:12px;color:#606266">{{ c.connection }}</span>
        </el-descriptions-item>
      </el-descriptions>
      <el-form label-width="120px">
        <el-form-item label="帖子条数">
          <el-input-number v-model="batchPullForm.results_limit" :min="1" :max="500" />
        </el-form-item>
        <el-form-item label="排序 viewOption">
          <el-select v-model="batchPullForm.view_option" style="width:100%">
            <el-option label="CHRONOLOGICAL（时间序）" value="CHRONOLOGICAL" />
            <el-option label="RECENT_ACTIVITY（最新活动）" value="RECENT_ACTIVITY" />
            <el-option label="TOP_POSTS（热门）" value="TOP_POSTS" />
            <el-option label="CHRONOLOGICAL_LISTINGS（买卖类）" value="CHRONOLOGICAL_LISTINGS" />
          </el-select>
        </el-form-item>
        <el-form-item label="搜索字母">
          <el-input v-model="batchPullForm.search_group_keyword" placeholder="可选，如 a" />
        </el-form-item>
        <el-form-item label="搜索年份">
          <el-input v-model="batchPullForm.search_group_year" placeholder="需配合搜索字母，如 2024" />
        </el-form-item>
        <el-form-item label="不早于">
          <el-input v-model="batchPullForm.only_posts_newer_than" placeholder="如 2024-01-01 或 7 days" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchPullVisible = false">取消</el-button>
        <el-button type="primary" :loading="batchSubmitting" @click="confirmBatchPull">提交 {{ selectedConfigs.length }} 个任务</el-button>
      </template>
    </el-dialog>

    <!-- 定时任务抽屉 -->
    <el-drawer v-model="scheduleDrawerVisible" title="定时拉取任务" size="60%" destroy-on-close>
      <FbGroupScheduleView v-if="scheduleConfig" :key="scheduleConfig.id" />
    </el-drawer>

    <!-- 帖子详情弹窗 -->
    <el-dialog v-model="postsDetailVisible" title="帖子原始 JSON" width="720px" destroy-on-close>
      <pre class="fb-json-pre" style="max-height:520px">{{ postsDetailRow ? JSON.stringify(postsDetailRow.raw_data, null, 2) : '' }}</pre>
    </el-dialog>
  </div>
</template>

<style scoped>
.fb-link {
  color: var(--el-color-primary);
  word-break: break-all;
}

.fb-muted {
  color: #909399;
  font-size: 12px;
}

.fb-json-pre {
  margin: 0;
  padding: 8px 12px;
  font-size: 11px;
  max-height: 320px;
  overflow: auto;
  background: #f5f7fa;
  border-radius: 4px;
}
</style>
