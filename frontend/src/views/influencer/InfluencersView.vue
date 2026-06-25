<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  influencerApi,
  type Influencer,
  type InfluencerScrapeTask,
  type ScrapePlatform,
} from '@/api/influencer'

// 抓取平台（为以后更多平台预留，只需在此追加一项）
const SCRAPE_PLATFORMS: { value: ScrapePlatform; label: string; placeholder: string }[] = [
  { value: 'facebook', label: 'Facebook', placeholder: '粘贴 Facebook 主页链接，发起后台抓取任务' },
  {
    value: 'instagram',
    label: 'Instagram',
    placeholder: '输入 Instagram 用户名或主页链接，如 nasa 或 https://www.instagram.com/nasa/',
  },
]
const PLATFORM_LABEL: Record<string, string> = Object.fromEntries(
  SCRAPE_PLATFORMS.map((p) => [p.value, p.label]),
)

const router = useRouter()
const list = ref<Influencer[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const statusFilter = ref<string>('')
const loading = ref(false)

const dialogVisible = ref(false)
const form = reactive<Partial<Influencer>>({
  display_name: '',
  country: 'JP',
  status: 'pre_contact'
})

// ─── 自动抓取（手工新增时按主页 URL 异步抓资料填表） ──────────────
const scrapeUrl = ref('')
const scrapeTaskId = ref<number | null>(null)
const scrapeStatus = ref<'' | 'pending' | 'running' | 'done' | 'failed'>('')
const scrapeError = ref('')
let scrapeTimer: ReturnType<typeof setTimeout> | null = null

const SCRAPE_STATUS_TEXT: Record<string, string> = {
  pending: '排队中…',
  running: '抓取中…',
  done: '抓取完成',
  failed: '抓取失败'
}
const SCRAPE_STATUS_TAG: Record<string, '' | 'success' | 'warning' | 'info' | 'danger'> = {
  pending: 'info',
  running: 'warning',
  done: 'success',
  failed: 'danger'
}

function stopScrapePolling() {
  if (scrapeTimer) {
    clearTimeout(scrapeTimer)
    scrapeTimer = null
  }
}

function resetScrape() {
  stopScrapePolling()
  scrapeUrl.value = ''
  scrapeTaskId.value = null
  scrapeStatus.value = ''
  scrapeError.value = ''
}

const SCRAPE_FILL_KEYS: (keyof Influencer)[] = [
  'display_name', 'bio', 'address', 'phone', 'email', 'website', 'messenger',
  'fb_page_id', 'fb_page_url', 'fb_page_title', 'fb_categories', 'fb_followers',
  'fb_likes', 'fb_rating', 'fb_rating_count', 'avatar_url', 'cover_url'
]

function applyScrapeResult(result: Partial<Influencer> | null | undefined) {
  if (!result) return
  for (const key of SCRAPE_FILL_KEYS) {
    const v = result[key]
    if (v !== null && v !== undefined && v !== '') {
      // 抓取结果覆盖对应字段
      ;(form as Record<string, unknown>)[key] = v
    }
  }
}

async function pollScrape() {
  if (scrapeTaskId.value == null) return
  try {
    const t = await influencerApi.getScrapeProfile(scrapeTaskId.value)
    scrapeStatus.value = t.status
    if (t.status === 'done') {
      stopScrapePolling()
      applyScrapeResult(t.result)
      ElMessage.success('抓取完成，已自动填充')
    } else if (t.status === 'failed') {
      stopScrapePolling()
      scrapeError.value = t.error || '抓取失败'
      ElMessage.warning(scrapeError.value)
    } else {
      scrapeTimer = setTimeout(pollScrape, 3000)
    }
  } catch {
    stopScrapePolling()
    scrapeStatus.value = 'failed'
    scrapeError.value = '查询任务失败，请重试'
  }
}

async function startScrape() {
  const url = scrapeUrl.value.trim()
  if (!url) {
    ElMessage.warning('请粘贴 Facebook 主页链接')
    return
  }
  stopScrapePolling()
  scrapeError.value = ''
  try {
    const t = await influencerApi.startScrapeProfile(url)
    scrapeTaskId.value = t.id
    scrapeStatus.value = t.status
    ElMessage.success('已发起抓取任务，完成后自动填充')
    scrapeTimer = setTimeout(pollScrape, 2000)
  } catch {
    /* 拦截器已提示 */
  }
}

// ─── 抓取任务列表（独立面板：发起抓取 → 看资料 → 存入达人库） ────────
const taskDialogVisible = ref(false)
const taskScrapeUrl = ref('')
const taskPlatform = ref<ScrapePlatform>('facebook')
const taskPlaceholder = computed(
  () => SCRAPE_PLATFORMS.find((p) => p.value === taskPlatform.value)?.placeholder || '',
)
const taskStarting = ref(false)
const tasks = ref<InfluencerScrapeTask[]>([])
const tasksLoading = ref(false)
const savingTaskId = ref<number | null>(null)
let taskListTimer: ReturnType<typeof setTimeout> | null = null

const detailVisible = ref(false)
const detailTask = ref<InfluencerScrapeTask | null>(null)

const DETAIL_FIELDS: { label: string; key: string }[] = [
  { label: '昵称', key: 'display_name' },
  { label: 'FB 主页标题', key: 'fb_page_title' },
  { label: '简介', key: 'bio' },
  { label: '邮箱', key: 'email' },
  { label: '电话', key: 'phone' },
  { label: '网站', key: 'website' },
  { label: 'Messenger', key: 'messenger' },
  { label: '地址', key: 'address' },
  { label: 'FB 粉丝', key: 'fb_followers' },
  { label: 'FB 点赞', key: 'fb_likes' },
  { label: 'FB 评分', key: 'fb_rating' },
  { label: 'FB 主页', key: 'fb_page_url' },
  { label: 'FB 主页ID', key: 'fb_page_id' }
]

const IG_DETAIL_FIELDS: { label: string; key: string }[] = [
  { label: '昵称', key: 'display_name' },
  { label: '真实姓名', key: 'real_name' },
  { label: '简介', key: 'bio' },
  { label: 'IG 用户名', key: 'ig_username' },
  { label: '粉丝', key: 'followers' },
  { label: '网站', key: 'website' },
  { label: 'IG 主页', key: 'ig_url' }
]

function detailRows(task: InfluencerScrapeTask | null) {
  const r = task?.result as Record<string, unknown> | null | undefined
  if (!r) return [] as { label: string; value: string }[]
  const fields = task?.platform === 'instagram' ? IG_DETAIL_FIELDS : DETAIL_FIELDS
  const rows: { label: string; value: string }[] = []
  for (const f of fields) {
    const v = r[f.key]
    if (v !== null && v !== undefined && v !== '') {
      rows.push({ label: f.label, value: Array.isArray(v) ? v.join('、') : String(v) })
    }
  }
  return rows
}

function stopTaskPolling() {
  if (taskListTimer) {
    clearTimeout(taskListTimer)
    taskListTimer = null
  }
}

function scheduleTaskPolling() {
  stopTaskPolling()
  const hasActive = tasks.value.some((t) => t.status === 'pending' || t.status === 'running')
  if (taskDialogVisible.value && hasActive) {
    taskListTimer = setTimeout(loadTasks, 3000)
  }
}

async function loadTasks() {
  tasksLoading.value = true
  try {
    tasks.value = await influencerApi.listScrapeProfiles(50)
  } finally {
    tasksLoading.value = false
  }
  scheduleTaskPolling()
}

function openTaskDialog() {
  taskDialogVisible.value = true
  taskScrapeUrl.value = ''
  taskPlatform.value = 'facebook'
  loadTasks()
}

function closeTaskDialog() {
  stopTaskPolling()
}

async function startTaskScrape() {
  const url = taskScrapeUrl.value.trim()
  if (!url) {
    ElMessage.warning(
      taskPlatform.value === 'instagram'
        ? '请输入 Instagram 用户名或主页链接'
        : '请粘贴 Facebook 主页链接',
    )
    return
  }
  taskStarting.value = true
  try {
    await influencerApi.startScrapeProfile(url, taskPlatform.value)
    taskScrapeUrl.value = ''
    ElMessage.success('已发起抓取任务，完成后可查看并存入达人库')
    await loadTasks()
  } catch {
    /* 拦截器已提示 */
  } finally {
    taskStarting.value = false
  }
}

function viewTask(task: InfluencerScrapeTask) {
  detailTask.value = task
  detailVisible.value = true
}

async function saveTask(task: InfluencerScrapeTask) {
  savingTaskId.value = task.id
  try {
    const inf = await influencerApi.saveScrapeProfile(task.id)
    ElMessage.success(`已存入达人库：${inf.display_name}`)
    await loadTasks()
    refresh()
  } catch {
    /* 拦截器已提示 */
  } finally {
    savingTaskId.value = null
  }
}

const STATUS_OPTIONS = [
  { label: '预建联', value: 'pre_contact' },
  { label: '建联中', value: 'contacting' },
  { label: '已签约', value: 'signed' },
  { label: '已放弃', value: 'dropped' }
]

const STATUS_TAG_TYPE: Record<string, '' | 'success' | 'warning' | 'info' | 'danger'> = {
  pre_contact: 'info',
  contacting: 'warning',
  signed: 'success',
  dropped: 'danger'
}

function statusLabel(status?: string) {
  return STATUS_OPTIONS.find((o) => o.value === status)?.label || status || '—'
}

async function changeStatus(row: Influencer, status: string) {
  const prev = row.status
  if (prev === status) return
  try {
    await influencerApi.update(row.id, { status: status as Influencer['status'] })
    row.status = status as Influencer['status']
    ElMessage.success(`已更新为「${statusLabel(status)}」`)
  } catch {
    row.status = prev
  }
}

async function refresh() {
  loading.value = true
  try {
    const r = await influencerApi.list({
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value || undefined,
      status: statusFilter.value || undefined
    })
    list.value = r.items
    total.value = r.total
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, {
    display_name: '',
    real_name: '',
    email: '',
    phone: '',
    website: '',
    messenger: '',
    country: 'JP',
    region: '',
    city: '',
    address: '',
    bio: '',
    notes: '',
    status: 'pre_contact',
    fb_page_url: '',
    fb_page_id: '',
    fb_page_title: '',
    fb_followers: undefined,
    fb_likes: undefined,
    fb_categories: undefined,
    avatar_url: '',
    cover_url: ''
  })
  resetScrape()
  dialogVisible.value = true
}

async function submit() {
  if (!form.display_name) {
    ElMessage.warning('请填写昵称')
    return
  }
  await influencerApi.create(form)
  ElMessage.success('已新增')
  dialogVisible.value = false
  refresh()
}

async function exportList() {
  await influencerApi.exportList({
    keyword: keyword.value || undefined,
    status: statusFilter.value || undefined,
  })
}

async function remove(row: Influencer) {
  await ElMessageBox.confirm(`确认删除「${row.display_name}」？`, '提示', { type: 'warning' })
  await influencerApi.remove(row.id)
  ElMessage.success('已删除')
  refresh()
}

onMounted(refresh)
onUnmounted(() => {
  stopScrapePolling()
  stopTaskPolling()
})
</script>

<template>
  <div class="page-card">
    <div style="display: flex; justify-content: space-between; margin-bottom: 12px">
      <h3 style="margin: 0">建联达人</h3>
      <div style="display: flex; gap: 8px">
        <el-button type="success" :icon="'Download'" @click="exportList">
          导出（CSV）
        </el-button>
        <el-button @click="openTaskDialog">抓取任务</el-button>
        <el-button type="primary" @click="openCreate">手工新增</el-button>
      </div>
    </div>
    <div style="display: flex; gap: 8px; margin-bottom: 12px">
      <el-input v-model="keyword" placeholder="名称 / 邮箱 / 主页 URL" style="width: 280px" clearable />
      <el-select v-model="statusFilter" placeholder="状态" clearable style="width: 160px">
        <el-option v-for="o in STATUS_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
      </el-select>
      <el-button type="primary" @click="(page = 1), refresh()">搜索</el-button>
    </div>

    <el-table v-loading="loading" :data="list" border>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="display_name" label="昵称" />
      <el-table-column label="来源" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.source === 'scrape' ? 'warning' : 'info'">
            {{ row.source === 'scrape' ? '抓取' : '手工' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="130">
        <template #default="{ row }">
          <el-select
            :model-value="row.status"
            size="small"
            style="width: 110px"
            :class="`status-select status-${row.status}`"
            @change="(v: string) => changeStatus(row, v)"
          >
            <el-option v-for="o in STATUS_OPTIONS" :key="o.value" :label="o.label" :value="o.value">
              <el-tag size="small" :type="STATUS_TAG_TYPE[o.value] || 'info'" effect="plain">{{ o.label }}</el-tag>
            </el-option>
          </el-select>
        </template>
      </el-table-column>
      <el-table-column prop="email" label="邮箱" />
      <el-table-column prop="fb_followers" label="FB 粉丝" width="100" />
      <el-table-column label="FB 主页" min-width="220">
        <template #default="{ row }">
          <a v-if="row.fb_page_url" :href="row.fb_page_url" target="_blank">{{ row.fb_page_url }}</a>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180">
        <template #default="{ row }">
          <el-button size="small" @click="router.push(`/influencers/${row.id}`)">详情</el-button>
          <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      style="margin-top: 12px; justify-content: flex-end; display: flex"
      @current-change="refresh"
    />

    <el-dialog v-model="dialogVisible" title="手工新增达人" width="640px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="自动抓取">
          <div style="width: 100%">
            <div style="display: flex; gap: 8px">
              <el-input
                v-model="scrapeUrl"
                placeholder="粘贴 Facebook 主页链接，自动识别并填充资料"
                clearable
                @keyup.enter="startScrape"
              />
              <el-button
                type="primary"
                :loading="scrapeStatus === 'pending' || scrapeStatus === 'running'"
                @click="startScrape"
              >
                {{ scrapeStatus === 'pending' || scrapeStatus === 'running' ? '抓取中…' : '自动抓取' }}
              </el-button>
            </div>
            <div v-if="scrapeStatus" style="margin-top: 6px; display: flex; align-items: center; gap: 8px">
              <el-tag size="small" :type="SCRAPE_STATUS_TAG[scrapeStatus] || 'info'">
                {{ SCRAPE_STATUS_TEXT[scrapeStatus] || scrapeStatus }}
              </el-tag>
              <span v-if="scrapeStatus === 'pending' || scrapeStatus === 'running'" style="color: #909399; font-size: 12px">
                抓取作为后台任务执行，完成后自动填充，期间可继续编辑其它字段
              </span>
              <span v-if="scrapeError" style="color: #f56c6c; font-size: 12px">{{ scrapeError }}</span>
            </div>
          </div>
        </el-form-item>
        <el-divider style="margin: 4px 0 16px" />
        <el-form-item label="昵称">
          <el-input v-model="form.display_name" />
        </el-form-item>
        <el-form-item label="真实姓名">
          <el-input v-model="form.real_name" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" />
        </el-form-item>
        <el-form-item label="电话">
          <el-input v-model="form.phone" />
        </el-form-item>
        <el-form-item label="网站">
          <el-input v-model="form.website" />
        </el-form-item>
        <el-form-item label="国家/地区">
          <el-input v-model="form.country" />
        </el-form-item>
        <el-form-item label="城市">
          <el-input v-model="form.city" />
        </el-form-item>
        <el-form-item label="FB 主页">
          <el-input v-model="form.fb_page_url" placeholder="自动抓取后回填，可手动修改" />
        </el-form-item>
        <el-form-item label="FB 粉丝">
          <el-input-number v-model="form.fb_followers" :min="0" :controls="false" style="width: 160px" />
        </el-form-item>
        <el-form-item label="简介">
          <el-input v-model="form.bio" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.notes" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option v-for="o in STATUS_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="taskDialogVisible"
      title="自动抓取任务"
      width="1080px"
      @closed="closeTaskDialog"
    >
      <div style="display: flex; gap: 8px; margin-bottom: 12px">
        <el-select v-model="taskPlatform" style="width: 140px">
          <el-option
            v-for="p in SCRAPE_PLATFORMS"
            :key="p.value"
            :label="p.label"
            :value="p.value"
          />
        </el-select>
        <el-input
          v-model="taskScrapeUrl"
          :placeholder="taskPlaceholder"
          clearable
          @keyup.enter="startTaskScrape"
        />
        <el-button type="primary" :loading="taskStarting" @click="startTaskScrape">发起抓取</el-button>
        <el-button :loading="tasksLoading" @click="loadTasks">刷新</el-button>
      </div>
      <el-table v-loading="tasksLoading" :data="tasks" border max-height="420">
        <el-table-column prop="id" label="ID" width="64" />
        <el-table-column label="平台" width="96">
          <template #default="{ row }">
            <el-tag size="small" :type="row.platform === 'instagram' ? 'danger' : 'primary'" effect="plain">
              {{ PLATFORM_LABEL[row.platform] || row.platform }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="主页链接 / 用户名" min-width="220">
          <template #default="{ row }">
            <a :href="row.url" target="_blank" style="word-break: break-all">{{ row.url }}</a>
          </template>
        </el-table-column>
        <el-table-column label="抓到的昵称" min-width="140">
          <template #default="{ row }">{{ row.result?.display_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="粉丝" width="90">
          <template #default="{ row }">{{ row.result?.fb_followers ?? row.result?.followers ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="SCRAPE_STATUS_TAG[row.status] || 'info'">
              {{ SCRAPE_STATUS_TEXT[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230">
          <template #default="{ row }">
            <template v-if="row.status === 'done'">
              <el-button size="small" @click="viewTask(row)">查看资料</el-button>
              <el-button
                v-if="row.influencer_id"
                size="small"
                type="success"
                @click="router.push(`/influencers/${row.influencer_id}`)"
              >
                已入库
              </el-button>
              <el-button
                v-else
                size="small"
                type="primary"
                :loading="savingTaskId === row.id"
                @click="saveTask(row)"
              >
                存入达人库
              </el-button>
            </template>
            <span v-else-if="row.status === 'failed'" style="color: #f56c6c; font-size: 12px">
              {{ row.error || '抓取失败' }}
            </span>
            <span v-else style="color: #909399; font-size: 12px">抓取中…</span>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="detailVisible" title="抓取资料" width="560px">
      <el-descriptions :column="1" border>
        <el-descriptions-item v-for="r in detailRows(detailTask)" :key="r.label" :label="r.label">
          {{ r.value }}
        </el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button
          v-if="detailTask && !detailTask.influencer_id"
          type="primary"
          :loading="savingTaskId === detailTask?.id"
          @click="detailTask && saveTask(detailTask).then(() => (detailVisible = false))"
        >
          存入达人库
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>
