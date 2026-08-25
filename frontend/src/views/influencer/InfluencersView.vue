<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  influencerApi,
  PLATFORM_LABELS,
  type Influencer,
  type InfluencerScrapeTask,
  type PlatformDetectItem,
  type ScrapePlatform,
} from '@/api/influencer'
import {
  bitbrowserApi,
  type BitBrowserPlatform,
  type BitBrowserWindow,
} from '@/api/bitbrowser'
import { dmApi, type DmContent } from '@/api/dm'
import { countryApi, type Country } from '@/api/country'

// 可自动抓资料的平台（对应 Apify actor）
const SCRAPE_PLATFORMS: { value: ScrapePlatform; label: string; placeholder: string }[] = [
  { value: 'facebook', label: 'Facebook', placeholder: '粘贴 Facebook 主页链接，发起后台抓取任务' },
  {
    value: 'instagram',
    label: 'Instagram',
    placeholder: '输入 Instagram 用户名或主页链接，如 nasa 或 https://www.instagram.com/nasa/',
  },
]
// 可预分类/暂存的全部平台（非 FB/IG 的只能暂存，不能自动抓资料）
const ALL_PLATFORMS = (Object.keys(PLATFORM_LABELS) as ScrapePlatform[]).map((value) => ({
  value,
  label: PLATFORM_LABELS[value],
}))
const PLATFORM_LABEL: Record<string, string> = { ...PLATFORM_LABELS }

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
const loading = ref(false)

// 关联平台字典（「平台管理」）与国家字典（「国家管理」）
const platforms = ref<BitBrowserPlatform[]>([])
const countries = ref<Country[]>([])

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
const scrapeStatus = ref<'' | 'staged' | 'pending' | 'running' | 'done' | 'failed' | 'contacted'>('')
const scrapeError = ref('')
let scrapeTimer: ReturnType<typeof setTimeout> | null = null

const SCRAPE_STATUS_TEXT: Record<string, string> = {
  staged: '待处理',
  pending: '排队中…',
  running: '抓取中…',
  done: '抓取完成',
  failed: '抓取失败',
  contacted: '已私信'
}
const SCRAPE_STATUS_TAG: Record<string, '' | 'success' | 'warning' | 'info' | 'danger'> = {
  staged: 'info',
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
const taskTab = ref<'single' | 'batch'>('batch')
const taskScrapeUrl = ref('')
const taskPlatform = ref<ScrapePlatform>('facebook')
const taskPlaceholder = computed(
  () => SCRAPE_PLATFORMS.find((p) => p.value === taskPlatform.value)?.placeholder || '',
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
  return (p && PLATFORM_LABEL[p]) || p || '—'
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
const batchName = ref('')
// 'auto' = 后端按链接正则逐条识别平台
const batchPlatform = ref<ScrapePlatform | 'auto'>('auto')
const batchImporting = ref(false)
const filterPlatform = ref<'' | ScrapePlatform>('')
// '' = 全部批次；'__none__' = 未分组
const filterBatch = ref<string>('')
const filterStatus = ref<string>('')
const batches = ref<
  {
    platform: string
    batch?: string | null
    total: number
    staged: number
    running: number
    failed: number
    done: number
  }[]
>([])
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
    label: key === '__unknown__' ? '未识别' : PLATFORM_LABEL[key] || key,
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

/** 筛选条件下传给接口的批次参数：undefined=不限，''=未分组 */
const batchParam = computed(() => {
  if (filterBatch.value === '') return undefined
  return filterBatch.value === '__none__' ? '' : filterBatch.value
})

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
      batch: batchParam.value,
      status: filterStatus.value || undefined,
    })
  } finally {
    tasksLoading.value = false
  }
  scheduleTaskPolling()
}

async function loadBatches() {
  try {
    batches.value = await influencerApi.listScrapeBatches()
  } catch {
    /* 拦截器已提示 */
  }
}

function batchLabel(b: {
  platform: string
  batch?: string | null
  total: number
  staged: number
  done: number
}) {
  const name = b.batch || '（未分组）'
  const plat = PLATFORM_LABEL[b.platform] || b.platform
  return `${plat} · ${name}（共 ${b.total}，待抓 ${b.staged}，已完成 ${b.done}）`
}

function openTaskDialog() {
  taskDialogVisible.value = true
  taskScrapeUrl.value = ''
  taskPlatform.value = 'facebook'
  batchImportUrls.value = ''
  detectItems.value = []
  loadTasks()
  loadBatches()
}

/** 整批抓取：对当前选中批次里所有待抓/失败的行一键发起 */
async function runWholeBatch() {
  if (batchParam.value === undefined) {
    ElMessage.warning('请先在上方选一个批次')
    return
  }
  batchActing.value = true
  try {
    const r = await influencerApi.runScrapeBatch({
      batch: batchParam.value,
      platform: filterPlatform.value || null,
    })
    if (r.affected === 0 && r.skipped === 0) {
      ElMessage.info('该批次没有待抓取的行')
    } else {
      ElMessage.success(
        `已发起 ${r.affected} 条抓取` +
          (r.skipped ? `，${r.skipped} 条平台暂不支持自动抓取已跳过` : ''),
      )
    }
    await Promise.all([loadTasks(), loadBatches()])
  } catch {
    /* 拦截器已提示 */
  } finally {
    batchActing.value = false
  }
}

/** 整批删除：删掉当前选中批次里的全部行（抓取中的除外） */
async function deleteWholeBatch() {
  if (batchParam.value === undefined) {
    ElMessage.warning('请先在上方选一个批次')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认删除批次「${filterBatch.value === '__none__' ? '（未分组）' : filterBatch.value}」的全部任务？已入库达人不受影响。`,
      '提示',
      { type: 'warning' },
    )
  } catch {
    return
  }
  batchActing.value = true
  try {
    const r = await influencerApi.deleteScrapeBatch({
      batch: batchParam.value,
      platform: filterPlatform.value || null,
    })
    ElMessage.success(
      `已删除 ${r.affected} 条` + (r.skipped ? `，${r.skipped} 条正在抓取中已跳过` : ''),
    )
    filterBatch.value = ''
    await Promise.all([loadTasks(), loadBatches()])
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
      batch: batchName.value.trim() || null,
    })
    batchImportUrls.value = ''
    detectItems.value = []
    batchName.value = ''
    const batch = created[0]?.batch || ''
    ElMessage.success(`已暂存 ${created.length} 条到批次「${batch || '未分组'}」`)
    // 直接把筛选定到新导入的批次，方便接着整批抓取
    filterPlatform.value = ''
    filterBatch.value = batch || '__none__'
    await Promise.all([loadTasks(), loadBatches()])
  } catch {
    /* 拦截器已提示 */
  } finally {
    batchImporting.value = false
  }
}

async function runTaskScrape(row: InfluencerScrapeTask) {
  runningTaskId.value = row.id
  try {
    await influencerApi.runScrapeProfile(row.id)
    await loadTasks()
  } catch {
    /* 拦截器已提示 */
  } finally {
    runningTaskId.value = null
  }
}

async function batchRunScrape() {
  const rows = selectedTasks.value.filter(
    (t) => t.status === 'staged' || t.status === 'failed' || t.status === 'done',
  )
  if (!rows.length) {
    ElMessage.warning('请勾选要抓取的行（待处理/失败/已完成可重抓）')
    return
  }
  batchRunning.value = true
  try {
    for (const r of rows) {
      try {
        await influencerApi.runScrapeProfile(r.id)
      } catch {
        /* 单条失败继续 */
      }
    }
    ElMessage.success(`已发起 ${rows.length} 条抓取`)
    await loadTasks()
  } finally {
    batchRunning.value = false
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
    await Promise.all([loadTasks(), loadBatches()])
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
    await Promise.all([loadTasks(), loadBatches()])
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
      platform_id: platformFilter.value ?? undefined
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
    country_id: defaultCountryId.value,
    region: '',
    city: '',
    address: '',
    bio: '',
    notes: '',
    progress: '',
    platform_id: undefined,
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
    country_id: countryFilter.value ?? undefined,
    platform_id: platformFilter.value ?? undefined,
  })
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
  loadCountries()
})
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
      <el-button type="primary" @click="(page = 1), refresh()">搜索</el-button>
    </div>

    <el-table v-loading="loading" :data="list" border>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column label="昵称">
        <template #default="{ row }">
          <span>{{ row.display_name }}</span>
          <el-tag v-if="row.has_outreach" size="small" type="success" style="margin-left: 6px">
            已私信
          </el-tag>
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
      <el-table-column prop="fb_followers" label="FB 粉丝" width="90" />
      <el-table-column label="FB 主页" min-width="200">
        <template #default="{ row }">
          <a v-if="row.fb_page_url" :href="row.fb_page_url" target="_blank">{{ row.fb_page_url }}</a>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="170" fixed="right">
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
        <el-form-item label="建联进度">
          <el-input v-model="form.progress" placeholder="如「已报价待回」，列表里也可直接改" />
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
      width="90%"
      top="5vh"
      @closed="closeTaskDialog"
    >
      <el-tabs v-model="taskTab" style="margin-bottom: 4px">
        <!-- 单个：抓取 / 私信 -->
        <el-tab-pane label="单个操作" name="single">
          <div style="display: flex; gap: 8px">
            <el-select v-model="taskPlatform" style="width: 130px">
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
                v-for="p in ALL_PLATFORMS"
                :key="p.value"
                :label="p.label"
                :value="p.value"
              />
            </el-select>
            <el-input
              v-model="batchName"
              placeholder="批次名，留空自动编号（如 20260825-第1批）"
              clearable
              style="width: 280px"
            />
            <el-button :loading="detecting" @click="previewDetect">识别平台</el-button>
            <el-button type="primary" :loading="batchImporting" @click="importBatch">
              导入暂存（{{ parsedBatchUrls.length }} 条）
            </el-button>
          </div>
          <el-input
            v-model="batchImportUrls"
            type="textarea"
            :rows="4"
            placeholder="每行一个链接 / 用户名，默认按链接自动识别平台（FB / IG / TikTok / 小红书…）；导入后只暂存，可整批抓取"
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
              暂只有 Facebook / Instagram 可自动抓资料，其余平台只入暂存；未识别的按上方选择的平台归类（默认 Facebook）
            </span>
          </div>
        </el-tab-pane>
      </el-tabs>

      <!-- 工具条：筛选 + 刷新 -->
      <div style="display: flex; gap: 8px; margin-bottom: 10px; align-items: center">
        <el-select v-model="filterPlatform" placeholder="全部平台" clearable style="width: 120px" @change="loadTasks">
          <el-option
            v-for="p in ALL_PLATFORMS"
            :key="p.value"
            :label="p.label"
            :value="p.value"
          />
        </el-select>
        <el-select v-model="filterBatch" placeholder="全部批次" clearable filterable style="width: 300px" @change="loadTasks">
          <el-option
            v-for="b in batches"
            :key="`${b.platform}::${b.batch || ''}`"
            :label="batchLabel(b)"
            :value="b.batch || '__none__'"
          />
        </el-select>
        <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width: 120px" @change="loadTasks">
          <el-option label="待处理" value="staged" />
          <el-option label="抓取中" value="running" />
          <el-option label="已完成" value="done" />
          <el-option label="失败" value="failed" />
        </el-select>
        <el-button :loading="tasksLoading" @click="loadTasks">刷新</el-button>
        <el-button
          type="primary"
          :loading="batchActing"
          :disabled="filterBatch === ''"
          @click="runWholeBatch"
        >
          整批抓取
        </el-button>
        <el-button
          type="danger"
          plain
          :loading="batchActing"
          :disabled="filterBatch === ''"
          @click="deleteWholeBatch"
        >
          整批删除
        </el-button>
        <div style="flex: 1" />
        <span style="font-size: 13px; color: #909399">已选 {{ selectedTasks.length }} 项</span>
        <el-button
          type="primary"
          plain
          size="small"
          :loading="batchRunning"
          :disabled="selectedTasks.length === 0"
          @click="batchRunScrape"
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
                v-for="p in ALL_PLATFORMS"
                :key="p.value"
                :label="p.label"
                :value="p.value"
              />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="批次" width="150">
          <template #default="{ row }">
            <span style="font-size: 12px; color: #606266">{{ row.batch || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="主页链接 / 用户名" min-width="200">
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
                @click="runTaskScrape(row)"
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
  </div>
</template>
