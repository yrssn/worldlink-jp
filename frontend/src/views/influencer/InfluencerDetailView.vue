<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  influencerApi,
  type DmOutreachLog,
  PROFILE_FIELD_LABELS,
  type InfluencerDetail,
  type InfluencerProfileFields as ProfileFields,
  type InfluencerSourcePost,
  type PlatformOption,
  type SocialAccount,
  type SocialPlatform
} from '@/api/influencer'
import InfluencerProfileFields from './InfluencerProfileFields.vue'
import { bitbrowserApi, type BitBrowserWindow } from '@/api/bitbrowser'
import { dmApi, type DmContent, type DmOutreachJobDetail } from '@/api/dm'

const route = useRoute()
const router = useRouter()
const id = computed(() => Number(route.params.id))
const detail = ref<InfluencerDetail | null>(null)
const sourcePosts = ref<InfluencerSourcePost[]>([])
const outreachLogs = ref<DmOutreachLog[]>([])

// ─── 对当前达人（再次）私信：后台任务，成功/失败都记到下方私信记录 ───
const dmDialogVisible = ref(false)
const dmWindows = ref<BitBrowserWindow[]>([])
const dmContents = ref<DmContent[]>([])
const dmBrowserId = ref('')
const dmContentId = ref<number | null>(null)
const dmPlatform = ref<'facebook' | 'instagram'>('facebook')
const dmLoading = ref(false)
const dmRunning = ref(false)
const dmJob = ref<DmOutreachJobDetail | null>(null)
let dmJobTimer: ReturnType<typeof setInterval> | null = null

const dmPlatformAvailable = computed(() => {
  const accounts = detail.value?.social_accounts || []
  return {
    facebook: accounts.some((a) => a.platform === 'facebook' && a.url),
    instagram: accounts.some((a) => a.platform === 'instagram' && (a.url || a.handle)),
  }
})

function windowLabel(w: BitBrowserWindow) {
  const parts = [w.seq != null ? `#${w.seq}` : '', w.name || '', w.remark || '']
  return parts.filter(Boolean).join(' ') || w.browser_id
}

async function openDmDialog() {
  dmPlatform.value = dmPlatformAvailable.value.facebook || !dmPlatformAvailable.value.instagram ? 'facebook' : 'instagram'
  dmDialogVisible.value = true
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

function stopDmJobPolling() {
  if (dmJobTimer) {
    clearInterval(dmJobTimer)
    dmJobTimer = null
  }
}

async function pollDmJob(jobId: number) {
  try {
    const j = await dmApi.getOutreachJob(jobId)
    dmJob.value = j
    if (j.status === 'done' || j.status === 'cancelled') {
      stopDmJobPolling()
      outreachLogs.value = await influencerApi.listOutreachLogs(id.value).catch(() => [])
      const log = j.logs[0]
      if (log?.status === 'success') ElMessage.success('私信已发送')
      else ElMessage.error(`私信失败：${log?.error || j.error || '未知原因'}`)
    }
  } catch {
    stopDmJobPolling()
  }
}

async function startDm() {
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
    const job = await dmApi.createOutreachJob({
      influencer_ids: [id.value],
      browser_id: dmBrowserId.value,
      content_id: dmContentId.value,
      platform: dmPlatform.value,
    })
    dmDialogVisible.value = false
    dmJob.value = { ...job, logs: [] }
    stopDmJobPolling()
    dmJobTimer = setInterval(() => pollDmJob(job.id), 3000)
  } catch {
    /* 拦截器已提示 */
  } finally {
    dmRunning.value = false
  }
}

onUnmounted(stopDmJobPolling)

const socialDialog = ref(false)
/** 正在编辑的账号 id；undefined = 新增 */
const editingSocialId = ref<number | undefined>(undefined)
const socialSaving = ref(false)

interface SocialAccountForm {
  platform: SocialPlatform
  platform_id?: number
  title: string
  handle: string
  url: string
  followers?: number
  likes?: number
  rating?: number
  rating_count?: number
  checkins_mentions?: number
  page_id: string
  author_id: string
  avatar_url: string
  categoriesText: string
  page_created_at?: string
  ad_library_id: string
  ad_status: string
  messenger: string
  notes: string
}

function emptySocialForm(): SocialAccountForm {
  return {
    platform: 'facebook',
    platform_id: undefined,
    title: '',
    handle: '',
    url: '',
    followers: undefined,
    likes: undefined,
    rating: undefined,
    rating_count: undefined,
    checkins_mentions: undefined,
    page_id: '',
    author_id: '',
    avatar_url: '',
    categoriesText: '',
    page_created_at: undefined,
    ad_library_id: '',
    ad_status: '',
    messenger: '',
    notes: ''
  }
}

const socialForm = reactive<SocialAccountForm>(emptySocialForm())

const STATUS_LABELS: Record<string, string> = {
  pre_contact: '预建联',
  contacting: '建联中',
  signed: '建联成功',
  dropped: '已放弃'
}
const STATUS_TAG_TYPE: Record<string, '' | 'success' | 'warning' | 'info' | 'danger'> = {
  pre_contact: 'info',
  contacting: 'warning',
  signed: 'success',
  dropped: 'danger'
}
const SOURCE_LABELS: Record<string, string> = {
  scrape: '抓取',
  manual: '手工'
}

// 平台选项统一读「平台管理」，接口没数据时才用内置名单兜底
const FALLBACK_PLATFORMS: { label: string; value: SocialPlatform }[] = [
  { label: 'Facebook', value: 'facebook' },
  { label: 'Instagram', value: 'instagram' },
  { label: 'TikTok', value: 'tiktok' },
  { label: 'YouTube', value: 'youtube' },
  { label: 'Twitter/X', value: 'twitter' },
  { label: 'WeChat', value: 'wechat' },
  { label: '小红书', value: 'xiaohongshu' },
  { label: 'LINE', value: 'line' },
  { label: '其他', value: 'other' }
]

const platformOptions = ref<PlatformOption[]>([])
const platformSelectOptions = computed<{ label: string; value: SocialPlatform }[]>(() =>
  platformOptions.value.length
    ? platformOptions.value.map((p) => ({ label: p.name, value: p.platform }))
    : FALLBACK_PLATFORMS
)
/** 可给账号关联的平台（必须是「平台管理」里真实存在的记录） */
const accountPlatformOptions = computed(() =>
  platformOptions.value.filter((p) => p.platform_id != null)
)
const platformNameMap = computed<Record<string, string>>(() =>
  Object.fromEntries(platformSelectOptions.value.map((p) => [p.value, p.label]))
)

async function loadPlatformOptions() {
  platformOptions.value = await influencerApi.listPlatformOptions().catch(() => [])
}

/** 选了平台后，没手动选关联平台就自动对齐到「平台管理」里同名的记录 */
function onSocialPlatformChange(p: SocialPlatform) {
  const hit = platformOptions.value.find((o) => o.platform === p && o.platform_id != null)
  socialForm.platform_id = hit?.platform_id ?? undefined
}

function openAddSocial() {
  editingSocialId.value = undefined
  Object.assign(socialForm, emptySocialForm())
  const first = platformSelectOptions.value[0]?.value
  if (first) socialForm.platform = first
  onSocialPlatformChange(socialForm.platform)
  socialDialog.value = true
}

function openEditSocial(row: SocialAccount) {
  editingSocialId.value = row.id
  Object.assign(socialForm, emptySocialForm(), {
    platform: row.platform,
    platform_id: row.platform_id ?? undefined,
    title: row.title || '',
    handle: row.handle || '',
    url: row.url || '',
    followers: row.followers ?? undefined,
    likes: row.likes ?? undefined,
    rating: row.rating ?? undefined,
    rating_count: row.rating_count ?? undefined,
    checkins_mentions: row.checkins_mentions ?? undefined,
    page_id: row.page_id || '',
    author_id: row.author_id || '',
    avatar_url: row.avatar_url || '',
    categoriesText: (row.categories || []).join(', '),
    page_created_at: row.page_created_at || undefined,
    ad_library_id: row.ad_library_id || '',
    ad_status: row.ad_status || '',
    messenger: row.messenger || '',
    notes: row.notes || ''
  })
  socialDialog.value = true
}

function socialPayload(): SocialAccount {
  const text = (v: string) => (v.trim() ? v.trim() : null)
  const categories = socialForm.categoriesText
    .split(/[,，\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
  return {
    platform: socialForm.platform,
    platform_id: socialForm.platform_id ?? null,
    title: text(socialForm.title),
    handle: text(socialForm.handle),
    url: text(socialForm.url),
    followers: socialForm.followers ?? null,
    likes: socialForm.likes ?? null,
    rating: socialForm.rating ?? null,
    rating_count: socialForm.rating_count ?? null,
    checkins_mentions: socialForm.checkins_mentions ?? null,
    page_id: text(socialForm.page_id),
    author_id: text(socialForm.author_id),
    avatar_url: text(socialForm.avatar_url),
    categories: categories.length ? categories : null,
    page_created_at: socialForm.page_created_at || null,
    ad_library_id: text(socialForm.ad_library_id),
    ad_status: text(socialForm.ad_status),
    messenger: text(socialForm.messenger),
    notes: text(socialForm.notes)
  }
}

/** 账号名优先 title，其次 handle */
function accountName(row: SocialAccount) {
  return row.title || row.handle || '—'
}

function fmtNum(v?: number | null) {
  return v == null ? '—' : v.toLocaleString('en-US')
}

async function refresh() {
  detail.value = await influencerApi.detail(id.value)
  sourcePosts.value = await influencerApi.listPosts(id.value).catch(() => [])
  outreachLogs.value = await influencerApi.listOutreachLogs(id.value).catch(() => [])
}

async function saveSocial() {
  if (!socialForm.platform) return
  const payload = socialPayload()
  if (!payload.url && !payload.handle && !payload.title) {
    ElMessage.warning('请至少填写链接、账号或账号名')
    return
  }
  socialSaving.value = true
  try {
    if (editingSocialId.value != null) {
      await influencerApi.updateSocial(id.value, editingSocialId.value, payload)
      ElMessage.success('已保存')
    } else {
      await influencerApi.addSocial(id.value, payload)
      ElMessage.success('已添加')
    }
    socialDialog.value = false
    refresh()
  } finally {
    socialSaving.value = false
  }
}

/** 平台挂在账号上：改这里只影响这个社交账号的平台归属 */
async function bindAccountPlatform(sid: number, platformId: number | undefined) {
  await influencerApi.updateSocial(id.value, sid, { platform_id: platformId ?? null })
  ElMessage.success('已更新关联平台')
  refresh()
}

// ─── 达人基本资料编辑（人 / 建联维度，含 KOL 编号 / 公司 / 负责人 / 日期…）──────────
const profileDialog = ref(false)
const profileSaving = ref(false)
const profileForm = reactive<Partial<InfluencerDetail>>({})

function openEditProfile() {
  if (!detail.value) return
  const d = detail.value
  Object.assign(profileForm, {
    display_name: d.display_name,
    real_name: d.real_name ?? '',
    email: d.email ?? '',
    phone: d.phone ?? '',
    website: d.website ?? '',
    city: d.city ?? '',
    address: d.address ?? '',
    bio: d.bio ?? '',
    notes: d.notes ?? '',
    progress: d.progress ?? '',
    code: d.code ?? '',
    company: d.company ?? '',
    gender: d.gender ?? null,
    contact_owner: d.contact_owner ?? '',
    landing_owner: d.landing_owner ?? '',
    source_channel: d.source_channel ?? '',
    contact_started_at: d.contact_started_at ?? null,
    planned_visit_at: d.planned_visit_at ?? null,
    has_twitter: d.has_twitter ?? null,
    twitter_channel: d.twitter_channel ?? '',
    group_name: d.group_name ?? '',
  })
  profileDialog.value = true
}

async function saveProfile() {
  if (!profileForm.display_name) {
    ElMessage.warning('请填写昵称')
    return
  }
  profileSaving.value = true
  try {
    const payload: Partial<InfluencerDetail> = {}
    for (const [k, v] of Object.entries(profileForm)) {
      ;(payload as Record<string, unknown>)[k] = v === '' ? null : v
    }
    await influencerApi.update(id.value, payload)
    ElMessage.success('已保存')
    profileDialog.value = false
    refresh()
  } finally {
    profileSaving.value = false
  }
}

function profileValue(key: keyof ProfileFields): string {
  const v = detail.value?.[key]
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? '是' : '否'
  if (key === 'contact_started_at' || key === 'planned_visit_at') return String(v).slice(0, 10)
  return String(v)
}

async function removeSocial(sid: number) {
  await influencerApi.removeSocial(id.value, sid)
  ElMessage.success('已删除')
  refresh()
}

onMounted(() => {
  loadPlatformOptions()
  refresh()
})
</script>

<template>
  <div class="page-card" v-if="detail">
    <el-page-header @back="router.back()" :content="detail.display_name">
      <template #extra>
        <el-button type="primary" size="small" @click="openEditProfile">编辑资料</el-button>
      </template>
    </el-page-header>
    <el-descriptions :column="3" border style="margin-top: 16px">
      <el-descriptions-item label="昵称">
        <div style="display: flex; align-items: center; gap: 8px">
          <el-image
            v-if="detail.avatar_url"
            :src="detail.avatar_url"
            :preview-src-list="[detail.avatar_url]"
            preview-teleported
            fit="cover"
            style="width: 64px; height: 64px; border-radius: 50%; flex: none; cursor: zoom-in"
          />
          <el-avatar v-else :size="64">
            {{ (detail.display_name || '?').slice(0, 1) }}
          </el-avatar>
          <span>{{ detail.display_name }}</span>
        </div>
      </el-descriptions-item>
      <el-descriptions-item label="状态">
        <el-tag :type="STATUS_TAG_TYPE[detail.status] || 'info'">
          {{ STATUS_LABELS[detail.status] || detail.status }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="来源">
        <el-tag size="small" :type="detail.source === 'scrape' ? 'warning' : 'info'">
          {{ SOURCE_LABELS[detail.source] || detail.source }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="类型">{{ detail.platform_name || '—' }}</el-descriptions-item>
      <el-descriptions-item label="国家/地区">
        {{ detail.country_name
          ? [detail.country_name, detail.country_name_en].filter(Boolean).join(' / ')
          : detail.country || '—' }}
      </el-descriptions-item>
      <el-descriptions-item label="城市">{{ detail.city }}</el-descriptions-item>
      <el-descriptions-item label="邮箱">{{ detail.email }}</el-descriptions-item>
      <el-descriptions-item label="电话">{{ detail.phone }}</el-descriptions-item>
      <el-descriptions-item label="网站">
        <a v-if="detail.website" :href="detail.website" target="_blank">{{ detail.website }}</a>
      </el-descriptions-item>
      <el-descriptions-item label="地址" :span="2">{{ detail.address || '—' }}</el-descriptions-item>
      <el-descriptions-item label="建联进度">{{ detail.progress || '—' }}</el-descriptions-item>
      <el-descriptions-item
        v-for="f in PROFILE_FIELD_LABELS"
        :key="f.key"
        :label="f.label"
      >
        {{ profileValue(f.key) }}
      </el-descriptions-item>
      <el-descriptions-item label="简介" :span="3">{{ detail.bio }}</el-descriptions-item>
      <el-descriptions-item label="备注" :span="3">{{ detail.notes }}</el-descriptions-item>
    </el-descriptions>

    <el-dialog v-model="profileDialog" title="编辑达人资料" width="760px" top="4vh">
      <el-form label-width="110px" style="max-height: 70vh; overflow-y: auto; padding-right: 8px">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="昵称" required>
              <el-input v-model="profileForm.display_name" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="真实姓名">
              <el-input v-model="profileForm.real_name" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="邮箱">
              <el-input v-model="profileForm.email" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="电话">
              <el-input v-model="profileForm.phone" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="常居地">
              <el-input v-model="profileForm.city" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="网站">
              <el-input v-model="profileForm.website" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="地址">
              <el-input v-model="profileForm.address" placeholder="常居地址 / 收发地址" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="建联进度">
              <el-input v-model="profileForm.progress" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-divider content-position="left">建联资料</el-divider>
        <InfluencerProfileFields v-model="profileForm" />
        <el-form-item label="简介">
          <el-input v-model="profileForm.bio" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="profileForm.notes" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="profileDialog = false">取消</el-button>
        <el-button type="primary" :loading="profileSaving" @click="saveProfile">保存</el-button>
      </template>
    </el-dialog>

    <div style="margin: 20px 0 12px; display: flex; justify-content: space-between">
      <h4 style="margin: 0">社交账号</h4>
      <el-button type="primary" size="small" @click="openAddSocial">添加账号</el-button>
    </div>
    <el-table :data="detail.social_accounts" border>
      <el-table-column label="平台" width="110">
        <template #default="{ row }">{{ row.platform_name || platformNameMap[row.platform] || row.platform }}</template>
      </el-table-column>
      <el-table-column label="关联平台" width="160">
        <template #default="{ row }">
          <el-select
            :model-value="row.platform_id ?? undefined"
            clearable
            placeholder="未关联"
            size="small"
            @change="(v: number | undefined) => bindAccountPlatform(row.id, v)"
          >
            <el-option
              v-for="p in accountPlatformOptions"
              :key="p.platform_id as number"
              :label="p.name"
              :value="p.platform_id as number"
            />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="账号名" min-width="140">
        <template #default="{ row }">
          <div style="display: flex; align-items: center; gap: 6px">
            <el-avatar v-if="row.avatar_url" :src="row.avatar_url" :size="24" />
            <span>{{ accountName(row) }}</span>
          </div>
          <div v-if="row.title && row.handle" style="color: #909399; font-size: 12px">@{{ row.handle }}</div>
        </template>
      </el-table-column>
      <el-table-column label="链接" min-width="200">
        <template #default="{ row }">
          <a v-if="row.url" :href="row.url" target="_blank">{{ row.url }}</a>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="粉丝" width="100" align="right">
        <template #default="{ row }">{{ fmtNum(row.followers) }}</template>
      </el-table-column>
      <el-table-column label="点赞" width="100" align="right">
        <template #default="{ row }">{{ fmtNum(row.likes) }}</template>
      </el-table-column>
      <el-table-column label="评分" width="110">
        <template #default="{ row }">
          <span v-if="row.rating != null">{{ row.rating }}<span v-if="row.rating_count">（{{ row.rating_count }}）</span></span>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="Messenger" min-width="120">
        <template #default="{ row }">
          <a v-if="row.messenger && /^https?:/.test(row.messenger)" :href="row.messenger" target="_blank">{{ row.messenger }}</a>
          <span v-else>{{ row.messenger || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="备注" min-width="120">
        <template #default="{ row }">{{ row.notes || '—' }}</template>
      </el-table-column>
      <el-table-column label="最近抓取" width="160">
        <template #default="{ row }">{{ row.last_scraped_at ? String(row.last_scraped_at).replace('T', ' ').slice(0, 16) : '—' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEditSocial(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="removeSocial(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <h4 style="margin: 20px 0 8px">来源帖子（追溯：是从哪条帖子建联到这个达人的）</h4>
    <el-table v-if="sourcePosts.length" :data="sourcePosts" border>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="task_id" label="任务" width="80" />
      <el-table-column label="文本">
        <template #default="{ row }">
          <div style="max-width: 360px; white-space: pre-wrap">
            {{ (row.text || '').slice(0, 140) }}{{ (row.text || '').length > 140 ? '…' : '' }}
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="likes" label="点赞" width="80" />
      <el-table-column prop="comments_count" label="评论" width="80" />
      <el-table-column prop="shares" label="分享" width="80" />
      <el-table-column label="AI" width="120">
        <template #default="{ row }">
          <el-tag
            v-if="row.ai_passed !== null"
            size="small"
            :type="row.ai_passed ? 'success' : 'info'"
          >
            {{ row.ai_passed ? '通过' : '不通过' }}
            <span v-if="row.ai_score != null"> ({{ row.ai_score }})</span>
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button v-if="row.url" size="small" tag="a" :href="row.url" target="_blank">
            原帖
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else description="暂无来源帖子" />

    <div style="display: flex; justify-content: space-between; align-items: center; margin: 20px 0 8px">
      <h4 style="margin: 0">私信记录（谁发的、用哪个窗口、发了什么、成功/失败）</h4>
      <div style="display: flex; align-items: center; gap: 8px">
        <el-tag
          v-if="dmJob && (dmJob.status === 'pending' || dmJob.status === 'running')"
          size="small"
          type="primary"
        >
          私信任务 #{{ dmJob.id }} 发送中…
        </el-tag>
        <el-button
          type="success"
          plain
          size="small"
          :disabled="!dmPlatformAvailable.facebook && !dmPlatformAvailable.instagram"
          @click="openDmDialog"
        >
          {{ outreachLogs.length ? '再次私信' : '私信' }}
        </el-button>
      </div>
    </div>
    <el-table v-if="outreachLogs.length" :data="outreachLogs" border>
      <el-table-column prop="created_at" label="时间" width="170" />
      <el-table-column label="结果" width="80">
        <template #default="{ row }">
          <el-tooltip v-if="row.status === 'failed'" :content="row.error || '失败'" placement="top">
            <el-tag size="small" type="danger">失败</el-tag>
          </el-tooltip>
          <el-tag v-else size="small" type="success">成功</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="发送人" width="100">
        <template #default="{ row }">{{ row.owner_name || row.owner_id || '-' }}</template>
      </el-table-column>
      <el-table-column prop="content_title" label="内容" width="160" />
      <el-table-column label="正文">
        <template #default="{ row }">
          <div style="max-width: 360px; white-space: pre-wrap">
            {{ (row.content_text || '').slice(0, 140) }}{{ (row.content_text || '').length > 140 ? '…' : '' }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="发送" width="140">
        <template #default="{ row }">
          <el-tag v-if="row.text_sent" size="small" type="success">正文</el-tag>
          <el-tag v-if="row.images_sent > 0" size="small" type="warning" style="margin-left: 4px">
            {{ row.images_sent }} 图
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="窗口" width="160">
        <template #default="{ row }">
          <div>{{ row.browser_name || row.browser_id || '-' }}</div>
          <div v-if="row.browser_name && row.browser_id" style="color: #909399; font-size: 12px">{{ row.browser_id }}</div>
        </template>
      </el-table-column>
      <el-table-column label="失败原因 / 任务" min-width="160">
        <template #default="{ row }">
          <div v-if="row.error" style="color: #f56c6c; white-space: pre-wrap">{{ row.error }}</div>
          <div v-if="row.job_id" style="color: #909399; font-size: 12px">批量任务 #{{ row.job_id }}</div>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else description="暂无私信记录" />

    <el-dialog v-model="dmDialogVisible" title="私信该达人" width="520px">
      <el-form label-width="100px" v-loading="dmLoading">
        <el-form-item label="平台">
          <el-radio-group v-model="dmPlatform" size="small">
            <el-radio-button value="facebook" :disabled="!dmPlatformAvailable.facebook">Facebook</el-radio-button>
            <el-radio-button value="instagram" :disabled="!dmPlatformAvailable.instagram">Instagram</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="浏览器窗口">
          <el-select v-model="dmBrowserId" placeholder="选择用于发私信的窗口" filterable style="width: 100%">
            <el-option v-for="w in dmWindows" :key="w.browser_id" :label="windowLabel(w)" :value="w.browser_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="私信内容">
          <el-select v-model="dmContentId" placeholder="选择内容库中的私信内容" filterable style="width: 100%">
            <el-option v-for="c in dmContents" :key="c.id" :label="c.title" :value="c.id" />
          </el-select>
        </el-form-item>
        <div style="color: #909399; font-size: 12px; margin-left: 100px">
          后台在选中窗口打开达人主页、点「发消息」并发送所选内容（含图片），发送人、窗口、内容、成功/失败都会记入私信记录
        </div>
      </el-form>
      <template #footer>
        <el-button @click="dmDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="dmRunning" @click="startDm">开始发送</el-button>
      </template>
    </el-dialog>


    <el-dialog
      v-model="socialDialog"
      :title="editingSocialId != null ? '编辑社交账号' : '添加社交账号'"
      width="720px"
      top="5vh"
    >
      <el-form :model="socialForm" label-width="110px">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="平台">
              <el-select v-model="socialForm.platform" style="width: 100%" @change="onSocialPlatformChange">
                <el-option
                  v-for="p in platformSelectOptions"
                  :key="p.value"
                  :label="p.label"
                  :value="p.value"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="关联平台">
              <el-select v-model="socialForm.platform_id" clearable placeholder="未关联" style="width: 100%">
                <el-option
                  v-for="p in accountPlatformOptions"
                  :key="p.platform_id as number"
                  :label="p.name"
                  :value="p.platform_id as number"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="账号名">
              <el-input v-model="socialForm.title" placeholder="页面 / 账号名称" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="Handle">
              <el-input v-model="socialForm.handle" placeholder="用户名，不填则从链接末段解析" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="链接">
              <el-input v-model="socialForm.url" placeholder="主页链接" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="粉丝数">
              <el-input-number v-model="socialForm.followers" :min="0" :controls="false" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="点赞数">
              <el-input-number v-model="socialForm.likes" :min="0" :controls="false" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="打卡/提及">
              <el-input-number v-model="socialForm.checkins_mentions" :min="0" :controls="false" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="评分">
              <el-input-number v-model="socialForm.rating" :min="0" :max="100" :precision="2" :controls="false" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="评分人数">
              <el-input-number v-model="socialForm.rating_count" :min="0" :controls="false" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="Messenger">
              <el-input v-model="socialForm.messenger" placeholder="该账号的 Messenger / 私信入口" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="账号备注">
              <el-input v-model="socialForm.notes" type="textarea" :rows="2" placeholder="如：另一个账号" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-collapse>
          <el-collapse-item title="更多字段（页面 ID / 头像 / 分类 / 广告库…）" name="more">
            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="页面 ID">
                  <el-input v-model="socialForm.page_id" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="作者 ID">
                  <el-input v-model="socialForm.author_id" />
                </el-form-item>
              </el-col>
              <el-col :span="24">
                <el-form-item label="头像链接">
                  <el-input v-model="socialForm.avatar_url" />
                </el-form-item>
              </el-col>
              <el-col :span="24">
                <el-form-item label="分类">
                  <el-input v-model="socialForm.categoriesText" placeholder="多个用逗号分隔" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="账号创建时间">
                  <el-date-picker
                    v-model="socialForm.page_created_at"
                    type="datetime"
                    value-format="YYYY-MM-DDTHH:mm:ss"
                    style="width: 100%"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="广告库 ID">
                  <el-input v-model="socialForm.ad_library_id" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="广告状态">
                  <el-input v-model="socialForm.ad_status" />
                </el-form-item>
              </el-col>
            </el-row>
          </el-collapse-item>
        </el-collapse>
      </el-form>
      <template #footer>
        <el-button @click="socialDialog = false">取消</el-button>
        <el-button type="primary" :loading="socialSaving" @click="saveSocial">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
