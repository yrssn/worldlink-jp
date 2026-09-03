<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  accountFromScrapeResult,
  influencerApi,
  PLATFORM_LABELS,
  SCRAPABLE_PLATFORMS,
  SOCIAL_PLATFORM_OPTIONS,
  type ImportFieldOption,
  type ImportPreview,
  type Influencer,
  type InfluencerScrapeTask,
  type PlatformDetectItem,
  type PlatformOption,
  type ScrapePlatform,
  type ScrapeTaskResult,
  type SocialAccount,
} from '@/api/influencer'
import InfluencerProfileFields from './InfluencerProfileFields.vue'
import {
  bitbrowserApi,
  type BitBrowserPlatform,
  type BitBrowserWindow,
} from '@/api/bitbrowser'
import { dmApi, type DmContent } from '@/api/dm'
import { countryApi, type Country } from '@/api/country'

// 各平台的输入提示（只有能自动抓资料的需要特别说明）
const PLATFORM_PLACEHOLDERS: Partial<Record<ScrapePlatform, string>> = {
  facebook: '粘贴 Facebook 主页链接，发起后台抓取任务',
  instagram: '输入 Instagram 用户名或主页链接，如 nasa 或 https://www.instagram.com/nasa/',
}

const router = useRouter()
const list = ref<Influencer[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const statusFilter = ref<string>('')
/** 国家筛选：0 = 未关联 */
const countryFilter = ref<number | undefined>(undefined)
const platformFilter = ref<number | undefined>(undefined)
/** 粉丝数区间筛选（口径：各关联账号粉丝取最大值） */
const followersMin = ref<number | undefined>(undefined)
const followersMax = ref<number | undefined>(undefined)
const sort = ref<'id_desc' | 'followers_desc' | 'followers_asc'>('id_desc')
const loading = ref(false)

// 关联平台字典（「平台管理」）与国家字典（「国家管理」）
const platforms = ref<BitBrowserPlatform[]>([])
const countries = ref<Country[]>([])
/** 抓取任务用的平台选项：后端按「平台管理」的代码/名称对齐后下发 */
const platformOptions = ref<PlatformOption[]>([])
/** 可自动抓资料的平台（对应 Apify actor） */
const scrapablePlatformOptions = computed(() => platformOptions.value.filter((p) => p.scrapable))
/** 平台规范名 -> 「平台管理」里的展示名（没维护则回退内置名） */
const platformNameMap = computed<Record<string, string>>(() => {
  const map: Record<string, string> = { ...PLATFORM_LABELS }
  for (const p of platformOptions.value) map[p.platform] = p.name
  return map
})

async function loadPlatformOptions() {
  try {
    platformOptions.value = await influencerApi.listPlatformOptions()
  } catch {
    /* 拦截器已提示 */
  }
}

/** 列表展示的关联账号：平台 + 账号名（title 优先，其次 handle）+ 链接 + 粉丝 */
function accountRows(row: Influencer) {
  return (row.accounts || []).map((a) => ({
    platform: a.platform_name || platformNameMap.value[a.platform] || a.platform,
    handle: a.title || a.handle || '',
    url: a.url || '',
    followers: a.followers ?? null,
  }))
}

// ─── 列表「一键抓取」：选中某条 FB / IG 关联账号链接后抓取，结果回写到该账号 ───
const quickScrapeVisible = ref(false)
const quickScrapeRow = ref<Influencer | null>(null)
const quickScrapeAccountId = ref<number | undefined>(undefined)
const quickScrapeStarting = ref(false)
const quickScrapeTask = ref<InfluencerScrapeTask | null>(null)
let quickScrapeTimer: ReturnType<typeof setTimeout> | null = null

/** 可一键抓取的账号：仅 Facebook / Instagram，且要有链接（IG 可只有用户名） */
const quickScrapeAccounts = computed<SocialAccount[]>(() =>
  (quickScrapeRow.value?.accounts || []).filter(
    (a) =>
      (SCRAPABLE_PLATFORMS as string[]).includes(a.platform) &&
      (a.url || (a.platform === 'instagram' && a.handle)),
  ),
)

function stopQuickScrapePolling() {
  if (quickScrapeTimer) {
    clearTimeout(quickScrapeTimer)
    quickScrapeTimer = null
  }
}

function openQuickScrape(row: Influencer) {
  stopQuickScrapePolling()
  quickScrapeRow.value = row
  quickScrapeTask.value = null
  // 必须由用户明确选中要抓的账号链接，不默认选
  quickScrapeAccountId.value = undefined
  quickScrapeVisible.value = true
}

function closeQuickScrape() {
  stopQuickScrapePolling()
  quickScrapeRow.value = null
  quickScrapeTask.value = null
}

async function pollQuickScrape() {
  const t = quickScrapeTask.value
  if (!t) return
  try {
    const next = await influencerApi.getScrapeProfile(t.id)
    quickScrapeTask.value = next
    if (next.status === 'done') {
      stopQuickScrapePolling()
      ElMessage.success('抓取完成，已回写到该关联账号')
      refresh()
    } else if (next.status === 'failed') {
      stopQuickScrapePolling()
      ElMessage.warning(next.error || '抓取失败')
    } else {
      quickScrapeTimer = setTimeout(pollQuickScrape, 3000)
    }
  } catch {
    stopQuickScrapePolling()
  }
}

async function startQuickScrape() {
  const row = quickScrapeRow.value
  const sid = quickScrapeAccountId.value
  if (!row || sid == null) {
    ElMessage.warning('请先选择要抓取的账号链接')
    return
  }
  quickScrapeStarting.value = true
  try {
    quickScrapeTask.value = await influencerApi.scrapeSocial(row.id, sid)
    ElMessage.success('已发起抓取，完成后自动回写到该账号')
    quickScrapeTimer = setTimeout(pollQuickScrape, 2000)
  } catch {
    /* 拦截器已提示 */
  } finally {
    quickScrapeStarting.value = false
  }
}

/** 达人行上展示的国家文案：优先用关联国家的「中文 / English」，否则回退旧文本 */
function countryLabel(row: Influencer): string {
  if (row.country_name) {
    return row.country_name_en ? `${row.country_name} / ${row.country_name_en}` : row.country_name
  }
  return row.country || ''
}

async function loadPlatforms() {
  try {
    platforms.value = await bitbrowserApi.listPlatforms()
  } catch {
    /* 拦截器已提示 */
  }
}

async function loadCountries() {
  try {
    countries.value = await countryApi.list()
  } catch {
    /* 拦截器已提示 */
  }
}

/** 默认国家：日本（JP），没有则不预选 */
const defaultCountryId = computed<number | undefined>(
  () => countries.value.find((c) => (c.code || '').toUpperCase() === 'JP')?.id,
)

const dialogVisible = ref(false)
const form = reactive<Partial<Influencer>>({
  display_name: '',
  country_id: undefined,
  status: 'pre_contact'
})

// ─── 自动抓取（手工新增时按主页 URL 异步抓资料填表） ──────────────
const scrapeUrl = ref('')
const scrapeTaskId = ref<number | null>(null)
const scrapeStatus = ref<'' | 'staged' | 'skipped' | 'pending' | 'running' | 'done' | 'failed' | 'contacted'>('')
const scrapeError = ref('')
let scrapeTimer: ReturnType<typeof setTimeout> | null = null

const SCRAPE_STATUS_TEXT: Record<string, string> = {
  staged: '待处理',
  skipped: '已区别开',
  pending: '排队中…',
  running: '抓取中…',
  done: '抓取完成',
  failed: '抓取失败',
  contacted: '已私信'
}
const SCRAPE_STATUS_TAG: Record<string, '' | 'success' | 'warning' | 'info' | 'danger'> = {
  staged: 'info',
  skipped: 'warning',
  pending: 'info',
  running: 'warning',
  done: 'success',
  failed: 'danger',
  contacted: 'success'
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

/** 抓取结果里落到主表的「人」维度字段；账号维度（fb_* / ig_*）单独填到 formAccount */
const SCRAPE_FILL_KEYS: (keyof Influencer)[] = [
  'display_name', 'real_name', 'bio', 'address', 'phone', 'email', 'website',
  'avatar_url', 'cover_url'
]

/** 手工新增时一并建的关联账号（自动抓取结果回填到这里） */
const formAccount = reactive<SocialAccount>({ platform: 'facebook', url: '', followers: null })

function resetFormAccount() {
  Object.assign(formAccount, {
    platform: 'facebook',
    platform_id: null,
    title: null,
    handle: null,
    url: '',
    followers: null,
    page_id: null,
    categories: null,
    likes: null,
    rating: null,
    rating_count: null,
    checkins_mentions: null,
    page_created_at: null,
    ad_library_id: null,
    ad_status: null,
    messenger: null,
    avatar_url: null,
    notes: null,
  } satisfies SocialAccount)
}

function applyScrapeResult(result: ScrapeTaskResult | null | undefined) {
  if (!result) return
  for (const key of SCRAPE_FILL_KEYS) {
    const v = result[key]
    if (v !== null && v !== undefined && v !== '') {
      // 抓取结果覆盖对应字段
      ;(form as Record<string, unknown>)[key] = v
    }
  }
  const acc = accountFromScrapeResult(result)
  for (const [k, v] of Object.entries(acc)) {
    if (v !== null && v !== undefined && v !== '') {
      ;(formAccount as Record<string, unknown>)[k] = v
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
    ElMessage.warning('请粘贴 Facebook / Instagram 主页链接')
    return
  }
  stopScrapePolling()
  scrapeError.value = ''
  try {
    const platform: ScrapePlatform = /instagram\.com/i.test(url) ? 'instagram' : 'facebook'
    const t = await influencerApi.startScrapeProfile(url, platform)
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
const taskTab = ref<'single' | 'batch'>('batch')
const taskScrapeUrl = ref('')
const taskPlatform = ref<ScrapePlatform>('facebook')
const taskPlaceholder = computed(
  () =>
    PLATFORM_PLACEHOLDERS[taskPlatform.value] ||
    `粘贴${platformNameMap.value[taskPlatform.value] || taskPlatform.value}主页链接`,
)
const taskStarting = ref(false)
const tasks = ref<InfluencerScrapeTask[]>([])
const tasksLoading = ref(false)
const savingTaskId = ref<number | null>(null)
const runningTaskId = ref<number | null>(null)
const selectedTasks = ref<InfluencerScrapeTask[]>([])
const batchRunning = ref(false)
let taskListTimer: ReturnType<typeof setTimeout> | null = null

function onTaskSelectionChange(rows: InfluencerScrapeTask[]) {
  selectedTasks.value = rows
}

function platformLabel(p?: string | null) {
  return (p && platformNameMap.value[p]) || p || '—'
}

async function updateTaskPlatform(row: InfluencerScrapeTask, platform: ScrapePlatform) {
  try {
    await influencerApi.updateScrapeProfile(row.id, { platform })
    row.platform = platform
    ElMessage.success('已修改平台')
  } catch {
    await loadTasks()
  }
}

// 批量导入（暂存）与筛选
const batchImportUrls = ref('')
// 'auto' = 后端按链接正则逐条识别平台
const batchPlatform = ref<ScrapePlatform | 'auto'>('auto')
const batchImporting = ref(false)
const uploading = ref(false)
const filterPlatform = ref<'' | ScrapePlatform>('')
const filterStatus = ref<string>('')
const batchActing = ref(false)

// 导入前预分类：按链接正则识别每条链接的平台
const detectItems = ref<PlatformDetectItem[]>([])
const detecting = ref(false)

const parsedBatchUrls = computed(() =>
  batchImportUrls.value
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean),
)

const detectSummary = computed(() => {
  const counts = new Map<string, number>()
  for (const it of detectItems.value) {
    const key = it.platform || '__unknown__'
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  return Array.from(counts.entries()).map(([key, count]) => ({
    key,
    count,
    label: key === '__unknown__' ? '未识别' : platformNameMap.value[key] || key,
    scrapable: key === 'facebook' || key === 'instagram',
  }))
})

async function previewDetect() {
  const urls = parsedBatchUrls.value
  if (!urls.length) {
    detectItems.value = []
    return
  }
  detecting.value = true
  try {
    detectItems.value = await influencerApi.detectPlatforms(urls)
  } catch {
    detectItems.value = []
  } finally {
    detecting.value = false
  }
}

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
    tasks.value = await influencerApi.listScrapeProfiles({
      platform: filterPlatform.value || undefined,
      status: filterStatus.value || undefined,
    })
  } finally {
    tasksLoading.value = false
  }
  scheduleTaskPolling()
}

function openTaskDialog() {
  taskDialogVisible.value = true
  taskScrapeUrl.value = ''
  taskPlatform.value = scrapablePlatformOptions.value[0]?.platform || 'facebook'
  batchImportUrls.value = ''
  detectItems.value = []
  loadPlatformOptions()
  loadTasks()
}

// ─── 抓取选项弹窗（抓完是否直接入库 / 入库状态）────────────────────
const scrapeOptVisible = ref(false)
const scrapeOptAutoSave = ref(true)
const scrapeOptStatus = ref('pre_contact')
/** row=单条，selected=勾选的行，all=当前筛选下全部待处理/失败 */
const scrapeOptMode = ref<'row' | 'selected' | 'all' | 'failed'>('row')
const scrapeOptRow = ref<InfluencerScrapeTask | null>(null)

const scrapeOptCount = computed(() => {
  if (scrapeOptMode.value === 'row') return 1
  if (scrapeOptMode.value === 'selected') return runnableSelected.value.length
  if (scrapeOptMode.value === 'failed') return failedTasks.value.length
  return tasks.value.filter((t) => t.status === 'staged' || t.status === 'failed').length
})

/** 当前列表里抓取失败的任务（导入后链接抓不到的都在这） */
const failedTasks = computed(() => tasks.value.filter((t) => t.status === 'failed'))

const runnableSelected = computed(() =>
  selectedTasks.value.filter(
    (t) => t.status === 'staged' || t.status === 'failed' || t.status === 'done',
  ),
)

function openScrapeOptions(
  mode: 'row' | 'selected' | 'all' | 'failed',
  row?: InfluencerScrapeTask,
) {
  if (mode === 'selected' && !runnableSelected.value.length) {
    ElMessage.warning('请勾选要抓取的行（待处理/失败/已完成可重抓）')
    return
  }
  scrapeOptMode.value = mode
  scrapeOptRow.value = row || null
  scrapeOptVisible.value = true
}

/** 弹窗确认后按选项发起抓取 */
async function confirmScrape() {
  const opts = {
    auto_save: scrapeOptAutoSave.value,
    save_status: scrapeOptAutoSave.value ? scrapeOptStatus.value : null,
  }
  scrapeOptVisible.value = false
  if (scrapeOptMode.value === 'all') {
    batchActing.value = true
    try {
      const r = await influencerApi.runScrapeBatch({
        platform: filterPlatform.value || null,
        ...opts,
      })
      if (r.affected === 0 && r.skipped === 0) {
        ElMessage.info('没有待抓取的任务')
      } else {
        ElMessage.success(
          `已发起 ${r.affected} 条抓取` +
            (r.skipped ? `，${r.skipped} 条平台暂不支持自动抓取已跳过` : ''),
        )
      }
      await loadTasks()
    } catch {
      /* 拦截器已提示 */
    } finally {
      batchActing.value = false
    }
    return
  }
  let rows: InfluencerScrapeTask[]
  if (scrapeOptMode.value === 'row' && scrapeOptRow.value) rows = [scrapeOptRow.value]
  else if (scrapeOptMode.value === 'failed') rows = failedTasks.value.slice()
  else rows = runnableSelected.value
  if (rows.length === 1) {
    runningTaskId.value = rows[0].id
  } else {
    batchRunning.value = true
  }
  try {
    for (const r of rows) {
      try {
        await influencerApi.runScrapeProfile(r.id, opts)
      } catch {
        /* 单条失败继续 */
      }
    }
    if (rows.length > 1) ElMessage.success(`已发起 ${rows.length} 条抓取`)
    await loadTasks()
  } finally {
    runningTaskId.value = null
    batchRunning.value = false
  }
}

/** 删除当前筛选下的全部任务（抓取中的除外） */
async function deleteAllTasks() {
  try {
    await ElMessageBox.confirm('确认删除当前列表里的全部任务？已入库达人不受影响。', '提示', {
      type: 'warning',
    })
  } catch {
    return
  }
  batchActing.value = true
  try {
    const r = await influencerApi.deleteScrapeBatch({ platform: filterPlatform.value || null })
    ElMessage.success(
      `已删除 ${r.affected} 条` + (r.skipped ? `，${r.skipped} 条正在抓取中已跳过` : ''),
    )
    await loadTasks()
  } catch {
    /* 拦截器已提示 */
  } finally {
    batchActing.value = false
  }
}

async function importBatch() {
  const urls = parsedBatchUrls.value
  if (!urls.length) {
    ElMessage.warning('请粘贴要导入的链接（每行一个）')
    return
  }
  batchImporting.value = true
  try {
    const created = await influencerApi.batchStageScrapeProfiles({
      urls,
      platform: batchPlatform.value,
    })
    batchImportUrls.value = ''
    detectItems.value = []
    ElMessage.success(`已导入 ${created.length} 条到待处理列表`)
    filterPlatform.value = ''
    filterStatus.value = ''
    await loadTasks()
  } catch {
    /* 拦截器已提示 */
  } finally {
    batchImporting.value = false
  }
}

// ─── 暂存区上传表格：先回显列名，让用户选哪一列是主页链接 ──────────
const stageFile = ref<File | null>(null)
const stagePreview = ref<ImportPreview | null>(null)
const stageVisible = ref(false)
const stageForm = reactive({ url_column: undefined as number | undefined, has_header: true })
const stageColumnOptions = computed(() =>
  (stagePreview.value?.columns || []).map((c) => ({
    value: c.index,
    label: c.samples.length ? `${c.name}（如：${c.samples[0]}）` : c.name,
  })),
)

/** 选表格后先读表头/样例，弹出选列；返回 false 阻止 el-upload 自己发请求 */
async function onPickImportFile(file: File) {
  uploading.value = true
  try {
    stageFile.value = file
    stagePreview.value = await influencerApi.previewImport(file)
    stageForm.url_column = stagePreview.value.suggested_url_column ?? undefined
    stageForm.has_header = true
    stageVisible.value = true
  } catch {
    /* 拦截器已提示 */
  } finally {
    uploading.value = false
  }
  return false
}

/** 按选定的主页链接列导入到暂存区 */
async function submitStageUpload() {
  if (!stageFile.value || stageForm.url_column === undefined) {
    ElMessage.warning('请选择主页链接列')
    return
  }
  uploading.value = true
  try {
    const created = await influencerApi.uploadScrapeBatch(stageFile.value, batchPlatform.value, {
      url_column: stageForm.url_column,
      has_header: stageForm.has_header,
    })
    ElMessage.success(`已从表格导入 ${created.length} 条到待处理列表`)
    stageVisible.value = false
    stageFile.value = null
    filterPlatform.value = ''
    filterStatus.value = ''
    await loadTasks()
  } catch {
    /* 拦截器已提示 */
  } finally {
    uploading.value = false
  }
}

async function deleteTask(row: InfluencerScrapeTask) {
  try {
    await ElMessageBox.confirm(`确认删除该条暂存/任务？\n${row.url}`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    await influencerApi.deleteScrapeProfile(row.id)
    ElMessage.success('已删除')
    await loadTasks()
  } catch {
    /* 拦截器已提示 */
  }
}

async function batchDelete() {
  const rows = selectedTasks.value.slice()
  if (!rows.length) {
    ElMessage.warning('请先勾选要删除的行')
    return
  }
  try {
    await ElMessageBox.confirm(`确认删除选中的 ${rows.length} 条？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  batchRunning.value = true
  try {
    for (const r of rows) {
      try {
        await influencerApi.deleteScrapeProfile(r.id)
      } catch {
        /* 单条失败继续 */
      }
    }
    ElMessage.success(`已删除 ${rows.length} 条`)
    await loadTasks()
  } finally {
    batchRunning.value = false
  }
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

// ─── 私信建联（选窗口 + 选内容库，自动进主页点「发消息」） ────────
const dmDialogVisible = ref(false)
const dmWindows = ref<BitBrowserWindow[]>([])
const dmContents = ref<DmContent[]>([])
const dmBrowserId = ref('')
const dmContentId = ref<number | null>(null)
const dmLoading = ref(false)
const dmRunning = ref(false)
const dmUrl = ref('')
const dmPlatform = ref<ScrapePlatform>('facebook')
const dmSourceTaskId = ref<number | null>(null)
const dmBatchRows = ref<InfluencerScrapeTask[]>([])

async function loadDmOptions() {
  dmLoading.value = true
  try {
    const [windows, contents] = await Promise.all([
      bitbrowserApi.listWindows(),
      dmApi.listContents({ active_only: true }),
    ])
    dmWindows.value = windows
    dmContents.value = contents
  } finally {
    dmLoading.value = false
  }
}

async function openDmDialog(row?: InfluencerScrapeTask) {
  dmBatchRows.value = []
  let url: string
  if (row) {
    url = (row.url || '').trim()
    dmPlatform.value = row.platform
    dmSourceTaskId.value = row.id
  } else {
    url = taskScrapeUrl.value.trim()
    dmPlatform.value = taskPlatform.value
    dmSourceTaskId.value = null
  }
  if (!url) {
    ElMessage.warning(
      dmPlatform.value === 'instagram'
        ? '请先输入 Instagram 用户名或主页链接'
        : '请先粘贴达人主页链接',
    )
    return
  }
  dmUrl.value = url
  dmDialogVisible.value = true
  await loadDmOptions()
}

async function openDmDialogBatch() {
  const rows = selectedTasks.value.slice()
  if (!rows.length) {
    ElMessage.warning('请先勾选要批量私信的达人')
    return
  }
  const platforms = new Set(rows.map((r) => r.platform))
  if (platforms.size > 1) {
    ElMessage.warning('批量私信要求所选达人平台一致，请分开操作或在表格内改成同一平台')
    return
  }
  dmBatchRows.value = rows
  dmPlatform.value = rows[0].platform
  dmSourceTaskId.value = null
  dmUrl.value = ''
  dmDialogVisible.value = true
  await loadDmOptions()
}

function windowLabel(w: BitBrowserWindow) {
  const parts = [w.seq != null ? `#${w.seq}` : '', w.name || '', w.remark || '']
  return parts.filter(Boolean).join(' ') || w.browser_id
}

async function startDmOutreach() {
  if (!dmBrowserId.value) {
    ElMessage.warning('请选择浏览器窗口')
    return
  }
  if (dmContentId.value == null) {
    ElMessage.warning('请选择私信内容')
    return
  }
  dmRunning.value = true
  try {
    // 批量：对所选达人依次发送同一内容（同一窗口、同平台）
    if (dmBatchRows.value.length > 0) {
      let ok = 0
      let fail = 0
      for (const row of dmBatchRows.value) {
        try {
          const r = await dmApi.startOutreach({
            url: row.url,
            browser_id: dmBrowserId.value,
            content_id: dmContentId.value,
            platform: row.platform,
            source_task_id: row.id,
          })
          if (r.text_sent || r.images_sent > 0) ok += 1
          else fail += 1
        } catch {
          fail += 1
        }
      }
      ElMessage.success(`批量私信完成：成功 ${ok}，未成功 ${fail}（成功的已自动抓取入库）`)
      dmDialogVisible.value = false
      loadTasks()
      return
    }
    const r = await dmApi.startOutreach({
      url: dmUrl.value,
      browser_id: dmBrowserId.value,
      content_id: dmContentId.value,
      platform: dmPlatform.value,
      source_task_id: dmSourceTaskId.value ?? undefined,
    })
    if (r.text_sent || r.images_sent > 0) {
      const parts = [
        r.text_sent ? '正文' : '',
        r.images_sent > 0 ? `${r.images_sent} 张图片` : '',
      ].filter(Boolean)
      ElMessage.success(
        `私信已发送（${parts.join(' + ')}）${r.scrape_task_id != null ? '，已自动抓取并入库' : ''}`,
      )
      dmDialogVisible.value = false
      loadTasks()
    } else if (r.message_clicked) {
      ElMessage.warning('已打开聊天窗，但发送未确认成功，请在窗口内检查')
    } else {
      const site = dmPlatform.value === 'instagram' ? 'Instagram' : 'Facebook'
      ElMessage.warning(`已进入主页，但未找到「发消息」按钮（请确认窗口内已登录 ${site}）`)
    }
  } catch {
    /* 拦截器已提示 */
  } finally {
    dmRunning.value = false
  }
}

function viewTask(task: InfluencerScrapeTask) {
  detailTask.value = task
  detailVisible.value = true
}

async function saveTask(task: InfluencerScrapeTask) {
  savingTaskId.value = task.id
  try {
    const { influencer, created } = await influencerApi.saveScrapeProfile(task.id)
    if (created) {
      ElMessage.success(`已存入达人库：${influencer.display_name}`)
    } else {
      ElMessage.warning(`该达人已在库中，已复用未重复创建：${influencer.display_name}`)
    }
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
  { label: '建联成功', value: 'signed' },
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

/** 列表内直接改字段（备注 / 建联进度 / 国家 / 关联平台）。 */
async function patchInfluencer(row: Influencer, patch: Partial<Influencer>) {
  try {
    const updated = await influencerApi.update(row.id, patch)
    Object.assign(row, updated)
    ElMessage.success('已保存')

  } catch {
    refresh()
  }
}

async function refresh() {
  loading.value = true
  try {
    const r = await influencerApi.list({
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value || undefined,
      status: statusFilter.value || undefined,
      country_id: countryFilter.value ?? undefined,
      platform_id: platformFilter.value ?? undefined,
      followers_min: followersMin.value ?? undefined,
      followers_max: followersMax.value ?? undefined,
      sort: sort.value,
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
    country_id: defaultCountryId.value,
    region: '',
    city: '',
    address: '',
    bio: '',
    notes: '',
    progress: '',
    platform_id: undefined,
    status: 'pre_contact',
    avatar_url: '',
    cover_url: '',
    code: '',
    company: '',
    gender: null,
    contact_owner: '',
    landing_owner: '',
    source_channel: '',
    contact_started_at: null,
    planned_visit_at: null,
    has_twitter: null,
    twitter_channel: '',
    group_name: ''
  })
  resetFormAccount()
  resetScrape()
  dialogVisible.value = true
}

async function submit() {
  if (!form.display_name) {
    ElMessage.warning('请填写昵称')
    return
  }
  const social_accounts: SocialAccount[] = []
  if (formAccount.url || formAccount.handle || formAccount.page_id) {
    social_accounts.push({ ...formAccount, url: formAccount.url || null })
  }
  const payload: Partial<Influencer> = {}
  for (const [k, v] of Object.entries(form)) {
    ;(payload as Record<string, unknown>)[k] = v === '' ? null : v
  }
  await influencerApi.create({ ...payload, social_accounts })
  ElMessage.success('已新增')
  dialogVisible.value = false
  refresh()
}

async function exportList() {
  await influencerApi.exportList({
    keyword: keyword.value || undefined,
    status: statusFilter.value || undefined,
    country_id: countryFilter.value ?? undefined,
    platform_id: platformFilter.value ?? undefined,
    followers_min: followersMin.value ?? undefined,
    followers_max: followersMax.value ?? undefined,
  })
}

/** 清空全部筛选条件并回到第一页 */
function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  countryFilter.value = undefined
  platformFilter.value = undefined
  followersMin.value = undefined
  followersMax.value = undefined
  sort.value = 'id_desc'
  page.value = 1
  refresh()
}

/** 点击「粉丝数」列表头排序 */
function onSortChange({ prop, order }: { prop: string; order: string | null }) {
  if (prop !== 'followers' || !order) sort.value = 'id_desc'
  else sort.value = order === 'ascending' ? 'followers_asc' : 'followers_desc'
  page.value = 1
  refresh()
}

/** 粉丝数千分位展示 */
function formatFollowers(v?: number | null) {
  return v == null ? '—' : v.toLocaleString('en-US')
}

// ─── 存量数据导入（选主页链接列 → 选状态 → 选是否抓取）──────────
const importVisible = ref(false)
const importFile = ref<File | null>(null)
const importPreview = ref<ImportPreview | null>(null)
const importLoading = ref(false)
const importSubmitting = ref(false)
const importForm = reactive({
  has_header: true,
  status: 'pre_contact',
  scrape: true,
  fallback_platform: 'other' as ScrapePlatform | 'other',
  create_missing: true,
})
/** 字段 key -> 列下标（含 url），每个字段都可手动改 / 清空 */
const importColumnMap = reactive<Record<string, number | undefined>>({})
const importFields = computed<ImportFieldOption[]>(() => importPreview.value?.fields || [])

const importColumnOptions = computed(() =>
  (importPreview.value?.columns || []).map((c) => ({
    value: c.index,
    label: c.samples.length ? `${c.name}（如：${c.samples[0]}）` : c.name,
  })),
)

function openImport() {
  importFile.value = null
  importPreview.value = null
  Object.assign(importForm, {
    has_header: true,
    status: 'pre_contact',
    scrape: true,
    fallback_platform: 'other',
  })
  for (const k of Object.keys(importColumnMap)) delete importColumnMap[k]
  importVisible.value = true
}

/** 选文件后先读表头/样例，返回 false 阻止 el-upload 自己发请求 */
async function onPickImportTable(file: File) {
  importFile.value = file
  importLoading.value = true
  try {
    const preview = await influencerApi.previewImport(file)
    importPreview.value = preview
    for (const k of Object.keys(importColumnMap)) delete importColumnMap[k]
    Object.assign(importColumnMap, preview.suggested_columns || {})
    if (preview.suggested_url_column != null) importColumnMap.url = preview.suggested_url_column
  } catch {
    importPreview.value = null
  } finally {
    importLoading.value = false
  }
  return false
}

async function submitImport() {
  const urlColumn = importColumnMap.url
  if (!importFile.value || urlColumn === undefined) {
    ElMessage.warning('请先上传表格并选择「账号链接」对应的列')
    return
  }
  importSubmitting.value = true
  try {
    const mapping: Record<string, number> = {}
    for (const [k, v] of Object.entries(importColumnMap)) {
      if (k !== 'url' && typeof v === 'number') mapping[k] = v
    }
    const r = await influencerApi.importTable(importFile.value, {
      url_column: urlColumn,
      column_map: JSON.stringify(mapping),
      has_header: importForm.has_header,
      status: importForm.status,
      scrape: importForm.scrape,
      fallback_platform: importForm.fallback_platform,
      create_missing: importForm.create_missing,
    })
    ElMessage.success(
      `导入完成：新增 ${r.created} 条，已有达人补资料 ${r.updated || 0} 条，无变化 ${r.duplicated} 条` +
        (r.skipped
          ? `，跳过 ${r.skipped} 条（空链接${importForm.create_missing ? '' : ' / 未匹配到已有达人'}）`
          : '') +
        (r.scrape_tasks
          ? `，已发起 ${r.scrape_tasks} 条抓取（抓取失败的可在「抓取任务」里重跑）`
          : '') +
        (r.cross_user_skipped
          ? `，${r.cross_user_skipped} 条链接已在对照账号名下，已区别开未入库`
          : ''),
    )
    if (r.cross_user_conflicts?.length) {
      const owners = [...new Set(r.cross_user_conflicts.map((c) => c.owner))].join('、')
      ElMessage.warning(`与账号「${owners}」重复的链接：${r.cross_user_conflicts.slice(0, 5).map((c) => c.url).join('，')}${r.cross_user_conflicts.length > 5 ? ' …' : ''}`)
    }
    importVisible.value = false
    page.value = 1
    refresh()
  } catch {
    /* 拦截器已提示 */
  } finally {
    importSubmitting.value = false
  }
}


async function remove(row: Influencer) {
  await ElMessageBox.confirm(`确认删除「${row.display_name}」？`, '提示', { type: 'warning' })
  await influencerApi.remove(row.id)
  ElMessage.success('已删除')
  refresh()
}

onMounted(() => {
  refresh()
  loadPlatforms()
  loadPlatformOptions()
  loadCountries()
})
onUnmounted(() => {
  stopScrapePolling()
  stopTaskPolling()
  stopQuickScrapePolling()
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
        <el-button type="warning" @click="openImport">导入存量数据</el-button>
        <el-button @click="openTaskDialog">抓取任务</el-button>
        <el-button type="primary" @click="openCreate">手工新增</el-button>
      </div>
    </div>
    <div style="display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap">
      <el-input v-model="keyword" placeholder="名称 / 邮箱 / 主页 URL" style="width: 280px" clearable />
      <el-select v-model="statusFilter" placeholder="状态" clearable style="width: 140px">
        <el-option v-for="o in STATUS_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
      </el-select>
      <el-select
        v-model="countryFilter"
        placeholder="国家"
        clearable
        filterable
        style="width: 130px"
      >
        <el-option label="未关联" :value="0" />
        <el-option v-for="c in countries" :key="c.id" :label="c.label" :value="c.id" />
      </el-select>
      <el-select
        v-model="platformFilter"
        placeholder="关联平台"
        clearable
        style="width: 150px"
      >
        <el-option label="未关联" :value="0" />
        <el-option v-for="p in platforms" :key="p.id" :label="p.name" :value="p.id" />
      </el-select>
      <div style="display: flex; align-items: center; gap: 4px">
        <el-input-number
          v-model="followersMin"
          :min="0"
          :controls="false"
          placeholder="粉丝≥"
          style="width: 110px"
        />
        <span style="color: #909399">-</span>
        <el-input-number
          v-model="followersMax"
          :min="0"
          :controls="false"
          placeholder="粉丝≤"
          style="width: 110px"
        />
      </div>
      <el-button type="primary" @click="(page = 1), refresh()">搜索</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </div>

    <el-table v-loading="loading" :data="list" border @sort-change="onSortChange">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column label="昵称" min-width="190">
        <template #default="{ row }">
          <el-popover placement="right" :width="340" trigger="hover">
            <template #reference>
              <div style="display: flex; align-items: center; gap: 8px; cursor: default">
                <el-image
                  v-if="row.avatar_url"
                  :src="row.avatar_url"
                  :preview-src-list="[row.avatar_url]"
                  preview-teleported
                  fit="cover"
                  style="width: 48px; height: 48px; border-radius: 50%; flex: none; cursor: zoom-in"
                />
                <el-avatar v-else :size="48">
                  {{ (row.display_name || '?').slice(0, 1) }}
                </el-avatar>
                <div>
                  <div>{{ row.display_name }}</div>
                  <el-tag v-if="row.has_outreach" size="small" type="success">已私信</el-tag>
                </div>
              </div>
            </template>
            <div style="font-size: 12px; line-height: 1.7">
              <div
                v-if="row.avatar_url"
                style="display: flex; justify-content: center; margin-bottom: 6px"
              >
                <el-image
                  :src="row.avatar_url"
                  :preview-src-list="[row.avatar_url]"
                  preview-teleported
                  fit="cover"
                  style="width: 120px; height: 120px; border-radius: 8px; cursor: zoom-in"
                />
              </div>
              <div style="font-weight: 600; margin-bottom: 4px">关联账号</div>
              <div v-if="!accountRows(row).length" style="color: #909399">暂无关联账号</div>
              <div v-for="(a, idx) in accountRows(row)" :key="idx">
                <b>{{ a.platform }}</b>
                <span v-if="a.handle"> · {{ a.handle }}</span>
                <span v-if="a.followers != null"> · 粉丝 {{ a.followers }}</span>
                <div v-if="a.url" style="word-break: break-all">
                  <a :href="a.url" target="_blank">{{ a.url }}</a>
                </div>
              </div>
              <div v-if="row.email" style="margin-top: 4px; color: #606266">
                邮箱：{{ row.email }}
              </div>
            </div>
          </el-popover>
        </template>
      </el-table-column>
      <el-table-column prop="followers" label="粉丝数" width="110" sortable="custom">
        <template #default="{ row }">
          <span style="font-weight: 600">{{ formatFollowers(row.followers) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="关联账号" min-width="230">
        <template #default="{ row }">
          <div v-if="!accountRows(row).length" style="color: #909399">—</div>
          <div
            v-for="(a, idx) in accountRows(row)"
            :key="idx"
            style="display: flex; align-items: center; gap: 6px; line-height: 1.9"
          >
            <el-tag size="small" type="info">{{ a.platform }}</el-tag>
            <a v-if="a.url" :href="a.url" target="_blank" class="account-link">
              {{ a.handle || a.url }}
            </a>
            <span v-else>{{ a.handle || '—' }}</span>
            <span style="color: #909399">{{ formatFollowers(a.followers) }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="来源" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="row.source === 'scrape' ? 'warning' : 'info'">
            {{ row.source === 'scrape' ? '抓取' : '手工' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="建联用户" width="110">
        <template #default="{ row }">
          <span>{{ row.owner_name || `#${row.owner_id}` }}</span>
        </template>
      </el-table-column>
      <el-table-column label="关联平台" width="140">
        <template #default="{ row }">
          <el-select
            :model-value="row.platform_id ?? undefined"
            size="small"
            clearable
            placeholder="未关联"
            style="width: 120px"
            @change="(v: number | undefined) => patchInfluencer(row, { platform_id: v ?? null })"
          >
            <el-option v-for="p in platforms" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="国家" width="180">
        <template #default="{ row }">
          <el-select
            :model-value="row.country_id ?? undefined"
            size="small"
            clearable
            filterable
            :placeholder="countryLabel(row) || '未关联'"
            style="width: 160px"
            @change="(v: number | undefined) => patchInfluencer(row, { country_id: v ?? null })"
          >
            <el-option v-for="c in countries" :key="c.id" :label="c.label" :value="c.id" />
          </el-select>
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
      <el-table-column label="建联进度" min-width="220">
        <template #default="{ row }">
          <el-input
            :model-value="row.progress || ''"
            type="textarea"
            :autosize="{ minRows: 3, maxRows: 8 }"
            resize="vertical"
            placeholder="可直接填，如「已报价待回」"
            @change="(v: string) => patchInfluencer(row, { progress: v.trim() || null })"
          />
        </template>
      </el-table-column>
      <el-table-column label="备注" min-width="260">
        <template #default="{ row }">
          <el-input
            :model-value="row.notes || ''"
            type="textarea"
            :autosize="{ minRows: 4, maxRows: 10 }"
            resize="vertical"
            placeholder="可直接填"
            @change="(v: string) => patchInfluencer(row, { notes: v.trim() || null })"
          />
        </template>
      </el-table-column>
      <el-table-column prop="email" label="邮箱" min-width="150" />
      <el-table-column label="操作" width="250" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="router.push(`/influencers/${row.id}`)">详情</el-button>
          <el-button size="small" type="primary" plain @click="openQuickScrape(row)">一键抓取</el-button>
          <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="quickScrapeVisible"
      :title="`一键抓取：${quickScrapeRow?.display_name || ''}`"
      width="620px"
      @closed="closeQuickScrape"
    >
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="选择要抓取的关联账号链接（目前仅支持 Facebook / Instagram），抓取结果会回写到这条账号。"
        style="margin-bottom: 12px"
      />
      <el-empty
        v-if="!quickScrapeAccounts.length"
        description="该达人没有可抓取的 Facebook / Instagram 账号链接，请先在详情页添加账号"
        :image-size="70"
      />
      <el-radio-group v-else v-model="quickScrapeAccountId" style="display: block">
        <div
          v-for="a in quickScrapeAccounts"
          :key="a.id"
          style="display: flex; align-items: flex-start; gap: 8px; padding: 8px 0; border-bottom: 1px solid #f0f0f0"
        >
          <el-radio :value="a.id" style="margin-right: 0; height: auto">
            <span style="display: inline-flex; flex-direction: column; gap: 2px; line-height: 1.5">
              <span>
                <el-tag size="small" type="info">{{ a.platform_name || platformNameMap[a.platform] || a.platform }}</el-tag>
                <b style="margin-left: 6px">{{ a.title || a.handle || '—' }}</b>
                <span v-if="a.followers != null" style="color: #909399; margin-left: 6px">粉丝 {{ formatFollowers(a.followers) }}</span>
              </span>
              <span style="color: #606266; font-size: 12px; word-break: break-all">{{ a.url || `@${a.handle}` }}</span>
            </span>
          </el-radio>
        </div>
      </el-radio-group>
      <div v-if="quickScrapeTask" style="margin-top: 12px; display: flex; align-items: center; gap: 8px">
        <el-tag size="small" :type="SCRAPE_STATUS_TAG[quickScrapeTask.status] || 'info'">
          {{ SCRAPE_STATUS_TEXT[quickScrapeTask.status] || quickScrapeTask.status }}
        </el-tag>
        <span v-if="quickScrapeTask.status === 'pending' || quickScrapeTask.status === 'running'" style="color: #909399; font-size: 12px">
          后台抓取中，完成后自动回写并刷新列表，可关闭此窗口
        </span>
        <span v-if="quickScrapeTask.error" style="color: #f56c6c; font-size: 12px">{{ quickScrapeTask.error }}</span>
      </div>
      <template #footer>
        <el-button @click="quickScrapeVisible = false">关闭</el-button>
        <el-button
          type="primary"
          :disabled="quickScrapeAccountId == null || !quickScrapeAccounts.length"
          :loading="quickScrapeStarting || quickScrapeTask?.status === 'pending' || quickScrapeTask?.status === 'running'"
          @click="startQuickScrape"
        >
          开始抓取
        </el-button>
      </template>
    </el-dialog>
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
        <el-form-item label="国家">
          <el-select
            v-model="form.country_id"
            filterable
            clearable
            placeholder="在「国家管理」里维护"
            style="width: 100%"
          >
            <el-option v-for="c in countries" :key="c.id" :label="c.label" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="关联平台">
          <el-select v-model="form.platform_id" clearable placeholder="选择平台" style="width: 100%">
            <el-option
              v-for="p in platforms"
              :key="p.id"
              :label="`${p.name}（${p.code}）`"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="城市">
          <el-input v-model="form.city" />
        </el-form-item>
        <el-divider content-position="left" style="margin: 8px 0 16px">关联账号（可在详情页继续添加更多账号）</el-divider>
        <el-form-item label="账号平台">
          <el-select v-model="formAccount.platform" style="width: 100%">
            <el-option v-for="o in SOCIAL_PLATFORM_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="账号链接">
          <el-input v-model="formAccount.url" placeholder="自动抓取后回填，可手动修改" />
        </el-form-item>
        <el-form-item label="账号名">
          <el-input v-model="formAccount.title" placeholder="页面 / 账号名称" />
        </el-form-item>
        <el-form-item label="粉丝数">
          <el-input-number v-model="formAccount.followers" :min="0" :controls="false" style="width: 160px" />
        </el-form-item>
        <el-form-item label="Messenger">
          <el-input v-model="formAccount.messenger" placeholder="该账号的 Messenger / 私信入口" />
        </el-form-item>
        <el-divider style="margin: 4px 0 16px" />
        <el-form-item label="简介">
          <el-input v-model="form.bio" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.notes" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="建联进度">
          <el-input v-model="form.progress" placeholder="如「已报价待回」，列表里也可直接改" />
        </el-form-item>
        <el-divider content-position="left">建联资料（KOL 编号 / 公司 / 负责人 / 日期…）</el-divider>
        <InfluencerProfileFields v-model="form" />
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
      width="90%"
      top="5vh"
      @closed="closeTaskDialog"
    >
      <el-tabs v-model="taskTab" style="margin-bottom: 4px">
        <!-- 单个：抓取 / 私信 -->
        <el-tab-pane label="单个操作" name="single">
          <div style="display: flex; gap: 8px">
            <el-select v-model="taskPlatform" style="width: 150px">
              <el-option
                v-for="p in scrapablePlatformOptions"
                :key="p.platform"
                :label="p.name"
                :value="p.platform"
              />
            </el-select>
            <el-input
              v-model="taskScrapeUrl"
              :placeholder="taskPlaceholder"
              clearable
              style="flex: 1"
              @keyup.enter="startTaskScrape"
            />
            <el-button type="primary" :loading="taskStarting" @click="startTaskScrape">
              发起抓取
            </el-button>
            <el-button type="success" @click="openDmDialog()">私信建联</el-button>
          </div>
        </el-tab-pane>

        <!-- 批量导入（只暂存不跑抓取） -->
        <el-tab-pane label="批量导入暂存" name="batch">
          <div style="display: flex; gap: 8px; margin-bottom: 8px; align-items: center">
            <el-select v-model="batchPlatform" style="width: 150px">
              <el-option label="自动识别平台" value="auto" />
              <el-option
                v-for="p in platformOptions"
                :key="p.platform"
                :label="p.name"
                :value="p.platform"
              />
            </el-select>
            <el-button :loading="detecting" @click="previewDetect">识别平台</el-button>
            <el-button type="primary" :loading="batchImporting" @click="importBatch">
              导入（{{ parsedBatchUrls.length }} 条）
            </el-button>
            <el-upload
              :show-file-list="false"
              :before-upload="onPickImportFile"
              accept=".xlsx,.xlsm,.csv,.txt"
            >
              <el-button :loading="uploading">上传表格（Excel / CSV）</el-button>
            </el-upload>
          </div>
          <el-input
            v-model="batchImportUrls"
            type="textarea"
            :rows="4"
            placeholder="每行一个链接 / 用户名，默认按链接自动识别平台（FB / IG / TikTok / 小红书…）；导入后先放在下方列表，勾选后再抓取"
            @change="previewDetect"
          />
          <div
            v-if="detectSummary.length"
            style="margin-top: 8px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap"
          >
            <span style="font-size: 12px; color: #909399">预分类：</span>
            <el-tag
              v-for="s in detectSummary"
              :key="s.key"
              size="small"
              :type="s.key === '__unknown__' ? 'danger' : s.scrapable ? 'success' : 'warning'"
            >
              {{ s.label }} {{ s.count }}
            </el-tag>
            <span style="font-size: 12px; color: #909399">
              平台下拉来自「平台管理」（按平台代码对齐）；暂只有 Facebook / Instagram 可自动抓资料，其余平台只入暂存
            </span>
          </div>
        </el-tab-pane>
      </el-tabs>

      <!-- 工具条：筛选 + 刷新 -->
      <div style="display: flex; gap: 8px; margin-bottom: 10px; align-items: center">
        <el-select v-model="filterPlatform" placeholder="全部平台" clearable style="width: 140px" @change="loadTasks">
          <el-option
            v-for="p in platformOptions"
            :key="p.platform"
            :label="p.name"
            :value="p.platform"
          />
        </el-select>
        <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width: 120px" @change="loadTasks">
          <el-option label="待处理" value="staged" />
          <el-option label="已区别开" value="skipped" />
          <el-option label="抓取中" value="running" />
          <el-option label="已完成" value="done" />
          <el-option label="失败" value="failed" />
        </el-select>
        <el-button :loading="tasksLoading" @click="loadTasks">刷新</el-button>
        <el-button
          type="primary"
          :loading="batchActing"
          @click="openScrapeOptions('all')"
        >
          抓取全部待处理
        </el-button>
        <el-button
          type="warning"
          plain
          :loading="batchRunning"
          :disabled="failedTasks.length === 0"
          @click="openScrapeOptions('failed')"
        >
          重跑失败（{{ failedTasks.length }}）
        </el-button>
        <el-button
          type="danger"
          plain
          :loading="batchActing"
          @click="deleteAllTasks"
        >
          删除全部
        </el-button>
        <div style="flex: 1" />
        <span style="font-size: 13px; color: #909399">已选 {{ selectedTasks.length }} 项</span>
        <el-button
          type="primary"
          plain
          size="small"
          :loading="batchRunning"
          :disabled="selectedTasks.length === 0"
          @click="openScrapeOptions('selected')"
        >
          批量抓取
        </el-button>
        <el-button
          type="success"
          size="small"
          :disabled="selectedTasks.length === 0"
          @click="openDmDialogBatch"
        >
          批量私信
        </el-button>
        <el-button
          type="danger"
          plain
          size="small"
          :disabled="selectedTasks.length === 0"
          @click="batchDelete"
        >
          批量删除
        </el-button>
      </div>

      <el-table
        v-loading="tasksLoading"
        :data="tasks"
        border
        max-height="60vh"
        @selection-change="onTaskSelectionChange"
      >
        <el-table-column type="selection" width="44" />
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column label="平台" width="130">
          <template #default="{ row }">
            <el-select
              :model-value="row.platform"
              size="small"
              style="width: 112px"
              @change="(v: ScrapePlatform) => updateTaskPlatform(row, v)"
            >
              <el-option
                v-for="p in platformOptions"
                :key="p.platform"
                :label="p.name"
                :value="p.platform"
              />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="主页链接 / 用户名" min-width="200">
          <template #default="{ row }">
            <a :href="row.url" target="_blank" style="word-break: break-all">{{ row.url }}</a>
          </template>
        </el-table-column>
        <el-table-column label="抓到的昵称" min-width="160">
          <template #default="{ row }">
            <div v-if="row.result" style="display: flex; align-items: center; gap: 6px">
              <el-image
                v-if="row.result?.avatar_url"
                :src="row.result.avatar_url"
                :preview-src-list="[row.result.avatar_url]"
                preview-teleported
                fit="cover"
                style="width: 32px; height: 32px; border-radius: 50%; flex: none; cursor: zoom-in"
              />
              <el-avatar v-else :size="32">
                {{ (row.result?.display_name || '?').slice(0, 1) }}
              </el-avatar>
              <span>{{ row.result?.display_name || '—' }}</span>
            </div>
            <span v-else>—</span>
          </template>
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
        <el-table-column label="操作" width="270" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'done'">
              <el-button link type="primary" size="small" @click="viewTask(row)">查看</el-button>
              <el-button
                v-if="row.influencer_id"
                link
                type="success"
                size="small"
                @click="router.push(`/influencers/${row.influencer_id}`)"
              >
                已入库
              </el-button>
              <el-button
                v-else
                link
                type="primary"
                size="small"
                :loading="savingTaskId === row.id"
                @click="saveTask(row)"
              >
                入库
              </el-button>
            </template>
            <template v-else-if="row.status === 'staged' || row.status === 'failed'">
              <el-button
                link
                type="primary"
                size="small"
                :loading="runningTaskId === row.id"
                @click="openScrapeOptions('row', row)"
              >
                {{ row.status === 'failed' ? '重抓' : '抓取' }}
              </el-button>
              <el-button link type="success" size="small" @click="openDmDialog(row)">私信</el-button>
              <el-tooltip
                v-if="row.status === 'failed' && row.error"
                :content="row.error"
                placement="top"
              >
                <span style="color: #f56c6c; font-size: 12px; cursor: help">失败原因</span>
              </el-tooltip>
            </template>
            <span v-else style="color: #909399; font-size: 12px">抓取中…</span>
            <el-button link type="danger" size="small" @click="deleteTask(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="scrapeOptVisible" title="抓取选项" width="460px">
      <el-form label-width="120px">
        <el-form-item label="本次抓取">
          <span style="font-size: 13px">共 {{ scrapeOptCount }} 条</span>
        </el-form-item>
        <el-form-item label="抓完直接入库">
          <el-switch v-model="scrapeOptAutoSave" />
        </el-form-item>
        <el-form-item v-if="scrapeOptAutoSave" label="入库状态">
          <el-select v-model="scrapeOptStatus" style="width: 100%">
            <el-option v-for="o in STATUS_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <div style="color: #909399; font-size: 12px; margin-left: 120px">
          抓到的头像会自动下载到服务器；不勾选直接入库时，结果留在列表里可先查看再手动入库
        </div>
      </el-form>
      <template #footer>
        <el-button @click="scrapeOptVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmScrape">开始抓取</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dmDialogVisible" title="私信建联" width="520px">
      <el-form label-width="100px" v-loading="dmLoading">
        <el-form-item label="平台">
          <el-tag :type="dmPlatform === 'instagram' ? 'warning' : 'primary'" size="small">
            {{ platformLabel(dmPlatform) }}
          </el-tag>
        </el-form-item>
        <el-form-item v-if="dmBatchRows.length > 0" label="批量对象">
          <span style="font-size: 13px">将对选中的 {{ dmBatchRows.length }} 个达人依次发送同一内容</span>
        </el-form-item>
        <el-form-item v-else label="主页链接">
          <span style="word-break: break-all">{{ dmUrl }}</span>
        </el-form-item>
        <el-form-item label="浏览器窗口">
          <el-select v-model="dmBrowserId" placeholder="选择用于发私信的窗口" filterable style="width: 100%">
            <el-option
              v-for="w in dmWindows"
              :key="w.browser_id"
              :label="windowLabel(w)"
              :value="w.browser_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="私信内容">
          <el-select v-model="dmContentId" placeholder="选择内容库中的私信内容" filterable style="width: 100%">
            <el-option v-for="c in dmContents" :key="c.id" :label="c.title" :value="c.id" />
          </el-select>
        </el-form-item>
        <div style="color: #909399; font-size: 12px; margin-left: 100px">
          将在选中窗口自动打开达人主页、点「发消息」并发送所选内容（含图片），成功后自动发起主页抓取
        </div>
      </el-form>
      <template #footer>
        <el-button @click="dmDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="dmRunning" @click="startDmOutreach">开始建联</el-button>
      </template>
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

    <el-dialog v-model="stageVisible" title="选择主页链接列" width="520px" append-to-body>
      <el-form label-width="110px">
        <el-form-item label="数据表">
          <span style="font-size: 12px; color: #606266">
            {{ stagePreview?.filename }}（{{ stagePreview?.total_rows }} 行）
          </span>
        </el-form-item>
        <el-form-item label="首行是表头">
          <el-switch v-model="stageForm.has_header" />
        </el-form-item>
        <el-form-item label="主页链接列" required>
          <el-select
            v-model="stageForm.url_column"
            placeholder="选择哪一列是主页链接"
            style="width: 100%"
          >
            <el-option
              v-for="c in stageColumnOptions"
              :key="c.value"
              :label="c.label"
              :value="c.value"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="stageVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="submitStageUpload">
          导入到暂存
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="importVisible" title="导入存量数据" width="720px" top="4vh">
      <el-form label-width="150px" v-loading="importLoading" style="max-height: 70vh; overflow-y: auto; padding-right: 8px">
        <el-form-item label="数据表">
          <el-upload
            :show-file-list="false"
            :before-upload="onPickImportTable"
            accept=".xlsx,.xlsm,.csv,.txt"
          >
            <el-button>{{ importFile ? '重新选择文件' : '选择 Excel / CSV' }}</el-button>
          </el-upload>
          <span v-if="importPreview" style="margin-left: 10px; font-size: 12px; color: #606266">
            {{ importPreview.filename }}（{{ importPreview.total_rows }} 行）
          </span>
        </el-form-item>
        <template v-if="importPreview">
          <el-form-item label="首行是表头">
            <el-switch v-model="importForm.has_header" />
          </el-form-item>
          <el-divider content-position="left">
            表头 → 字段映射（已按表头名自动预选，可逐个修改；不导入的字段清空即可）
          </el-divider>
          <el-form-item
            v-for="f in importFields"
            :key="f.key"
            :label="f.label"
            :required="!!f.required"
          >
            <el-select
              v-model="importColumnMap[f.key]"
              :clearable="!f.required"
              filterable
              :placeholder="f.required ? '必选' : '不导入'"
              style="width: 100%"
            >
              <el-option
                v-for="c in importColumnOptions"
                :key="c.value"
                :label="c.label"
                :value="c.value"
              />
            </el-select>
          </el-form-item>
          <el-divider />
          <el-form-item label="导入后状态">
            <el-select v-model="importForm.status" style="width: 100%">
              <el-option
                v-for="o in STATUS_OPTIONS"
                :key="o.value"
                :label="o.label"
                :value="o.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="识别不出的链接">
            <el-select v-model="importForm.fallback_platform" style="width: 100%">
              <el-option label="归为「其他」平台" value="other" />
              <el-option
                v-for="p in platformOptions"
                :key="p.platform"
                :label="`归为 ${p.name}`"
                :value="p.platform"
              />
            </el-select>
            <span style="font-size: 12px; color: #909399">
              平台按链接自动识别（FB / IG / TikTok / 小红书 / YouTube / X / LINE），
              导入时同时写入达人和对应的社交账号记录
            </span>
          </el-form-item>
          <el-form-item label="只更新已有">
            <el-switch v-model="importForm.create_missing" :active-value="false" :inactive-value="true" />
            <span style="margin-left: 10px; font-size: 12px; color: #909399">
              按账号链接匹配已有达人（含之前导入 / 抓取时用的原始链接），命中只补空字段；
              开启后匹配不到的行直接跳过，不新建记录
            </span>
          </el-form-item>
          <el-form-item label="导入后抓取">
            <el-switch v-model="importForm.scrape" />
            <span style="margin-left: 10px; font-size: 12px; color: #909399">
              关掉就只入库不抓取；开启则 FB / IG 自动抓资料回填，其余平台只建暂存任务
            </span>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="!importPreview"
          :loading="importSubmitting"
          @click="submitImport"
        >
          开始导入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.account-link {
  color: var(--el-color-primary);
  word-break: break-all;
}
</style>
