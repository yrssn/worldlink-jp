<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import {
  scraperApi,
  TASK_TYPES,
  type ScrapeTask,
  type ScrapeTaskType
} from '@/api/scraper'
import { llmApi, promptApi, type LlmProvider, type PromptTemplate } from '@/api/llm'

const router = useRouter()
const list = ref<ScrapeTask[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const providers = ref<LlmProvider[]>([])
const prompts = ref<PromptTemplate[]>([])

const form = reactive({
  name: '',
  task_type: 'fb_search' as ScrapeTaskType,
  keywordsText: '',
  locationsText: '',
  hashtagsText: '',
  start_urlsText: '',
  max_items: 50,
  posts_per_page: 10,
  page_limit: 50,
  enable_ai_filter: false,
  llm_provider_id: undefined as number | undefined,
  prompt_template_id: undefined as number | undefined,
  // fb_posts_by_search 专属
  location_uid: '',
  search_type: 'posts' as 'posts' | 'pages' | 'groups' | 'people' | 'videos' | 'events',
  start_date: '',
  end_date: '',
  recent_posts: false
})

const currentMeta = computed(() =>
  TASK_TYPES.find((t) => t.value === form.task_type) || TASK_TYPES[0]
)
const needs = computed(() => currentMeta.value.needs)

const statusType: Record<string, string> = {
  pending: 'info',
  running: 'warning',
  success: 'success',
  failed: 'danger',
  partial: 'warning',
  canceled: 'info'
}

const taskTypeLabel: Record<ScrapeTaskType, string> = TASK_TYPES.reduce(
  (acc, t) => ({ ...acc, [t.value]: t.label }),
  {} as Record<ScrapeTaskType, string>
)

async function refresh() {
  loading.value = true
  try {
    list.value = await scraperApi.listTasks()
  } finally {
    loading.value = false
  }
}

async function openCreate() {
  if (!providers.value.length) providers.value = await llmApi.list().catch(() => [])
  if (!prompts.value.length) prompts.value = await promptApi.list().catch(() => [])
  dialogVisible.value = true
}

function splitMulti(s: string): string[] {
  return s
    .split(/[,，\n]/)
    .map((x) => x.trim())
    .filter(Boolean)
}

async function submit() {
  const keywords = splitMulti(form.keywordsText)
  const locations = splitMulti(form.locationsText)
  const hashtags = splitMulti(form.hashtagsText).map((h) => h.replace(/^#/, ''))
  const start_urls = form.start_urlsText
    .split(/[\n,，]/)
    .map((s) => s.trim())
    .filter(Boolean)

  const n = needs.value
  if (n.keywords && keywords.length === 0) {
    return ElMessage.warning('请填写关键词')
  }
  if (n.hashtags && hashtags.length === 0) {
    return ElMessage.warning('请填写至少一个 hashtag')
  }
  if (n.startUrls && start_urls.length === 0) {
    return ElMessage.warning('请填写至少一个主页 URL')
  }
  if (form.enable_ai_filter && (!form.llm_provider_id || !form.prompt_template_id)) {
    return ElMessage.warning('启用 AI 时必须选择大模型与提示词模板')
  }

  // 组装 extra_input：fb_search 用 locations；fb_posts_by_search 用 location_uid 等
  const extra_input: Record<string, unknown> = {}
  if (locations.length) extra_input.locations = locations
  if (needs.value.searchPostsOptions) {
    if (form.location_uid) extra_input.location_uid = form.location_uid
    if (form.search_type) extra_input.search_type = form.search_type
    if (form.start_date) extra_input.start_date = form.start_date
    if (form.end_date) extra_input.end_date = form.end_date
    if (form.recent_posts) extra_input.recent_posts = true
  }

  const payload: Partial<ScrapeTask> = {
    name: form.name,
    task_type: form.task_type,
    keywords,
    hashtags,
    start_urls,
    max_items: form.max_items,
    posts_per_page: form.posts_per_page,
    page_limit: form.page_limit,
    enable_ai_filter: form.enable_ai_filter,
    llm_provider_id: form.enable_ai_filter ? form.llm_provider_id : null,
    prompt_template_id: form.enable_ai_filter ? form.prompt_template_id : null,
    extra_input: Object.keys(extra_input).length ? extra_input : null
  }

  await scraperApi.createTask(payload)
  ElMessage.success('任务已创建，正在后台执行')
  dialogVisible.value = false
  refresh()
}

onMounted(refresh)
</script>

<template>
  <div class="page-card">
    <div style="display: flex; justify-content: space-between; margin-bottom: 12px">
      <h3 style="margin: 0">抓取任务</h3>
      <div>
        <el-button @click="refresh">刷新</el-button>
        <el-button type="primary" @click="openCreate">新建任务</el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="list" border>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="名称" />
      <el-table-column label="类型" width="200">
        <template #default="{ row }">
          <el-tag size="small">{{ taskTypeLabel[row.task_type as ScrapeTaskType] || row.task_type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="(statusType[row.status] as any) || 'info'">
            {{ row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="输入">
        <template #default="{ row }">
          <div v-if="row.keywords?.length" style="margin-bottom: 2px">
            <span style="color: #999">关键词：</span>
            <el-tag v-for="k in row.keywords" :key="k" size="small" style="margin-right: 4px">
              {{ k }}
            </el-tag>
          </div>
          <div v-if="row.hashtags?.length" style="margin-bottom: 2px">
            <span style="color: #999">tag：</span>
            <el-tag
              v-for="h in row.hashtags"
              :key="h"
              size="small"
              type="warning"
              style="margin-right: 4px"
            >
              #{{ h }}
            </el-tag>
          </div>
          <div v-if="row.extra_input?.locations">
            <span style="color: #999">位置：</span>
            <el-tag
              v-for="l in (row.extra_input.locations as string[])"
              :key="l"
              size="small"
              type="info"
              style="margin-right: 4px"
            >
              {{ l }}
            </el-tag>
          </div>
          <div v-if="row.start_urls?.length" style="font-size: 12px; color: #666">
            URL × {{ row.start_urls.length }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="AI" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="row.enable_ai_filter ? 'success' : 'info'">
            {{ row.enable_ai_filter ? '开启' : '关闭' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="result_count" label="抓到" width="80" />
      <el-table-column prop="filtered_count" label="AI通过" width="90" />
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button size="small" @click="router.push(`/scraper/tasks/${row.id}`)">查看</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" title="新建抓取任务" width="720px">
      <el-form :model="form" label-width="120px">
        <el-form-item label="任务名称">
          <el-input v-model="form.name" placeholder="便于自己识别的名字" />
        </el-form-item>
        <el-form-item label="任务类型">
          <el-radio-group v-model="form.task_type">
            <div
              v-for="t in TASK_TYPES"
              :key="t.value"
              style="display: block; margin-bottom: 6px"
            >
              <el-radio :value="t.value" style="margin-right: 6px">{{ t.label }}</el-radio>
            </div>
          </el-radio-group>
        </el-form-item>
        <el-alert
          :title="currentMeta.label"
          type="info"
          show-icon
          :closable="false"
          style="margin-bottom: 12px"
        >
          <div style="font-size: 12px">{{ currentMeta.summary }}</div>
          <div style="font-size: 12px; color: #b88230; margin-top: 4px">
            💰 费用估算：{{ currentMeta.pricing }}
          </div>
        </el-alert>

        <el-form-item v-if="needs.keywords" label="关键词">
          <el-input
            v-model="form.keywordsText"
            type="textarea"
            :rows="2"
            placeholder="多个用逗号/换行分隔，如：cafe, restaurant"
          />
        </el-form-item>
        <el-form-item v-if="needs.locations" label="位置 (可选)">
          <el-input
            v-model="form.locationsText"
            type="textarea"
            :rows="2"
            placeholder="多个用逗号/换行分隔，如：Tokyo, Osaka"
          />
        </el-form-item>
        <el-form-item v-if="needs.hashtags" label="Hashtag">
          <el-input
            v-model="form.hashtagsText"
            type="textarea"
            :rows="2"
            placeholder="多个用逗号/换行分隔，不需要 # 前缀，如：tokyocafe, japankol"
          />
        </el-form-item>
        <el-form-item v-if="needs.startUrls" label="主页 URLs">
          <el-input
            v-model="form.start_urlsText"
            type="textarea"
            :rows="4"
            placeholder="每行一个 Facebook 主页 URL，如：https://www.facebook.com/humansofnewyork/"
          />
        </el-form-item>

        <template v-if="needs.searchPostsOptions">
          <el-form-item label="搜索类型">
            <el-select v-model="form.search_type" style="width: 200px">
              <el-option label="帖子 posts" value="posts" />
              <el-option label="主页 pages" value="pages" />
              <el-option label="群组 groups" value="groups" />
              <el-option label="人 people" value="people" />
              <el-option label="视频 videos" value="videos" />
              <el-option label="活动 events" value="events" />
            </el-select>
            <span style="margin-left: 6px; font-size: 12px; color: #999">
              默认 posts（建联场景一般选 posts）
            </span>
          </el-form-item>
          <el-form-item label="Location UID">
            <el-input
              v-model="form.location_uid"
              placeholder="可选；Facebook 内部地区 ID（不是国家名）"
              style="width: 320px"
            />
            <div style="font-size: 12px; color: #999; margin-top: 2px">
              ⚠️ 这里只接受 Facebook 内部的数字 UID。获取方法：在 facebook.com 搜某地点
              → 浏览器地址栏会带 ID；或在 Apify 上跑 apify/facebook-url-to-id 解析。
              留空 = 全球搜索。
            </div>
          </el-form-item>
          <el-form-item label="日期区间 (可选)">
            <el-input v-model="form.start_date" placeholder="YYYY-MM-DD" style="width: 140px" />
            <span style="margin: 0 6px">~</span>
            <el-input v-model="form.end_date" placeholder="YYYY-MM-DD" style="width: 140px" />
          </el-form-item>
          <el-form-item label="按最新排序">
            <el-switch v-model="form.recent_posts" />
            <span style="margin-left: 8px; font-size: 12px; color: #999">
              开启后返回最新的帖子（相关性会降低）
            </span>
          </el-form-item>
        </template>

        <el-form-item label="最大条数">
          <el-input-number v-model="form.max_items" :min="1" :max="1000" />
          <span style="margin-left: 6px; font-size: 12px; color: #999">
            第一步抓取上限（actor resultsLimit）
          </span>
        </el-form-item>
        <el-form-item v-if="needs.postsPerPage" label="每页帖子数">
          <el-input-number v-model="form.posts_per_page" :min="1" :max="200" />
          <span style="margin-left: 6px; font-size: 12px; color: #999">
            每个主页抓多少条最近的帖子
          </span>
        </el-form-item>

        <el-form-item label="启用 AI 过滤">
          <el-switch v-model="form.enable_ai_filter" />
          <span style="margin-left: 8px; font-size: 12px; color: #999">
            启用后将逐条调用大模型评估，会增加 LLM token 费用
          </span>
        </el-form-item>
        <template v-if="form.enable_ai_filter">
          <el-form-item label="大模型">
            <el-select v-model="form.llm_provider_id" placeholder="选择已配置的大模型" style="width: 100%">
              <el-option
                v-for="p in providers"
                :key="p.id"
                :label="`${p.name} (${p.provider}/${p.model})`"
                :value="p.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="提示词模板">
            <el-select v-model="form.prompt_template_id" placeholder="选择提示词模板" style="width: 100%">
              <el-option v-for="p in prompts" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
          </el-form-item>
        </template>
        <el-form-item v-if="needs.postsPerPage || needs.hashtags || needs.keywords" label="主页上限">
          <el-input-number v-model="form.page_limit" :min="1" :max="500" />
          <span style="margin-left: 6px; font-size: 12px; color: #999">
            AI 过滤后，第二步去抓主页的最大 URL 数（控制费用）
          </span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>
