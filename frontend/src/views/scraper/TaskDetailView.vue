<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  scraperApi,
  TASK_TYPES,
  type PageItem,
  type PostItem,
  type ScrapeTask
} from '@/api/scraper'
import { influencerApi } from '@/api/influencer'

const route = useRoute()
const router = useRouter()
const id = computed(() => Number(route.params.id))

const task = ref<ScrapeTask | null>(null)
const loading = ref(false)

// pages
const pages = ref<PageItem[]>([])
const pageTotal = ref(0)
const pagePage = ref(1)
const pagePageSize = ref(20)
const pageOnlyPassed = ref(false)
const linkedKeys = ref<Set<string>>(new Set())

// posts
const posts = ref<PostItem[]>([])
const postTotal = ref(0)
const postPage = ref(1)
const postPageSize = ref(20)
const postOnlyPassed = ref(false)
const selectedPostIds = ref<number[]>([])
const scrapingAuthorPages = ref(false)

const activeTab = ref<'pages' | 'posts'>('pages')

const isPostsTask = computed(() =>
  task.value?.task_type?.startsWith('fb_posts_') ?? false
)

const deferHomepageScrape = computed(
  () => !!(task.value?.extra_input && (task.value.extra_input as Record<string, unknown>).defer_homepage_scrape)
)

const meta = computed(() =>
  TASK_TYPES.find((t) => t.value === task.value?.task_type)
)

const statusType: Record<string, string> = {
  pending: 'info',
  running: 'warning',
  success: 'success',
  failed: 'danger',
  partial: 'warning',
  canceled: 'info'
}

function pageKey(p: PageItem): string {
  return (p.pageUrl || p.facebookUrl || p.pageId || p.facebookId || '') as string
}

async function loadTask() {
  task.value = await scraperApi.getTask(id.value)
  if (isPostsTask.value) activeTab.value = 'posts'
  else activeTab.value = 'pages'
}

async function loadPages() {
  const r = await scraperApi.listPages(id.value, {
    page: pagePage.value,
    page_size: pagePageSize.value,
    only_passed: pageOnlyPassed.value
  })
  pages.value = r.items
  pageTotal.value = r.total
}

async function loadPosts() {
  const r = await scraperApi.listPosts(id.value, {
    page: postPage.value,
    page_size: postPageSize.value,
    only_passed: postOnlyPassed.value
  })
  posts.value = r.items
  postTotal.value = r.total
}

async function refresh() {
  loading.value = true
  try {
    await loadTask()
    await Promise.all([loadPages(), isPostsTask.value ? loadPosts() : Promise.resolve()])
  } finally {
    loading.value = false
  }
}

async function exportPosts() {
  await scraperApi.exportPosts(id.value, postOnlyPassed.value)
}

async function exportPages() {
  await scraperApi.exportPages(id.value, pageOnlyPassed.value)
}

async function contactPage(p: PageItem) {
  await influencerApi.fromScrape({
    author_url: (p.pageUrl || p.facebookUrl) as string,
    page_profile: p as unknown as Record<string, unknown>,
    source_post_ids: (p._source_post_ids as number[]) || undefined
  })
  linkedKeys.value.add(pageKey(p))
  ElMessage.success('已加入建联模块')
}

async function contactPost(row: PostItem) {
  await influencerApi.fromScrape({ post_id: row.id })
  ElMessage.success('已加入建联模块')
  refresh()
}

function postRowSelectable(row: PostItem) {
  return !!(row.author_url && String(row.author_url).trim())
}

function onPostsSelectionChange(rows: PostItem[]) {
  selectedPostIds.value = rows.map((r) => r.id)
}

async function scrapeAuthorPagesFromSelected() {
  if (!selectedPostIds.value.length) {
    ElMessage.warning('请先勾选至少一条带作者主页链接的帖子')
    return
  }
  scrapingAuthorPages.value = true
  try {
    const r = await scraperApi.scrapeAuthorPagesFromPosts(id.value, selectedPostIds.value)
    ElMessage.success(r.msg || '完成')
    selectedPostIds.value = []
    await refresh()
  } finally {
    scrapingAuthorPages.value = false
  }
}

watch([pagePage, pageOnlyPassed], () => loadPages())
watch([postPage, postOnlyPassed], () => loadPosts())

onMounted(refresh)
</script>

<template>
  <div v-if="!task" class="page-card" v-loading="loading">
    <el-empty v-if="!loading" description="任务不存在或加载失败" />
  </div>
  <div v-else class="page-card">
    <el-page-header
      @back="router.back()"
      :content="`任务 #${task.id} · ${meta?.label || task.task_type}`"
    />
    <el-alert
      v-if="meta"
      :title="meta.label"
      type="info"
      show-icon
      :closable="false"
      style="margin: 12px 0"
    >
      <div style="font-size: 12px">{{ meta.summary }}</div>
      <div style="font-size: 12px; color: #b88230; margin-top: 4px">
        💰 费用估算：{{ meta.pricing }}
      </div>
    </el-alert>

    <el-descriptions :column="3" border>
      <el-descriptions-item label="名称">{{ task.name || '-' }}</el-descriptions-item>
      <el-descriptions-item label="状态">
        <el-tag :type="(statusType[task.status] as any) || 'info'">{{ task.status }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="启用 AI">
        {{ task.enable_ai_filter ? '是' : '否' }}
      </el-descriptions-item>
      <el-descriptions-item label="关键词">
        <el-tag
          v-for="k in task.keywords || []"
          :key="k"
          size="small"
          style="margin-right: 4px"
        >
          {{ k }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="Hashtag">
        <el-tag
          v-for="h in task.hashtags || []"
          :key="h"
          size="small"
          type="warning"
          style="margin-right: 4px"
        >
          #{{ h }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="位置">
        <el-tag
          v-for="l in (task.extra_input?.locations as string[]) || []"
          :key="l"
          size="small"
          type="info"
          style="margin-right: 4px"
        >
          {{ l }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="主页 URLs">
        <span v-if="task.start_urls?.length">{{ task.start_urls.length }} 条</span>
      </el-descriptions-item>
      <el-descriptions-item label="结果数">
        {{ task.result_count }}
        <span v-if="task.enable_ai_filter">/ AI 通过 {{ task.filtered_count }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="主页上限">{{ task.page_limit }}</el-descriptions-item>
      <el-descriptions-item label="错误信息" :span="3">
        {{ task.error || '-' }}
      </el-descriptions-item>
    </el-descriptions>

    <el-tabs v-model="activeTab" style="margin-top: 16px">
      <el-tab-pane v-if="isPostsTask" label="帖子列表（第一步）" name="posts">
        <el-alert
          v-if="deferHomepageScrape"
          type="success"
          show-icon
          :closable="false"
          style="margin-bottom: 10px"
          title="本任务为「先抓帖」模式"
          description="系统不会自动抓博主主页。请在下表勾选你认可的帖子，再点「对选中作者抓主页」；抓到的主页会出现在「待审核博主」标签页。"
        />
        <div style="display: flex; justify-content: flex-end; margin-bottom: 8px; gap: 8px; flex-wrap: wrap">
          <el-button
            v-if="isPostsTask"
            type="primary"
            :loading="scrapingAuthorPages"
            :disabled="!selectedPostIds.length"
            @click="scrapeAuthorPagesFromSelected"
          >
            对选中作者抓主页
          </el-button>
          <el-switch
            v-if="task.enable_ai_filter"
            v-model="postOnlyPassed"
            active-text="只看 AI 通过"
          />
          <el-button @click="loadPosts">刷新</el-button>
          <el-button type="success" :icon="'Download'" @click="exportPosts">
            导出帖子（CSV）
          </el-button>
        </div>
        <el-table :data="posts" border @selection-change="onPostsSelectionChange">
          <el-table-column type="selection" width="42" :selectable="postRowSelectable" />
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="author_name" label="作者" width="150" />
          <el-table-column label="文本">
            <template #default="{ row }">
              <div style="max-width: 360px; white-space: pre-wrap">
                {{ (row.text || '').slice(0, 160) }}{{ (row.text || '').length > 160 ? '…' : '' }}
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="likes" label="点赞" width="80" />
          <el-table-column prop="comments_count" label="评论" width="80" />
          <el-table-column prop="shares" label="分享" width="80" />
          <el-table-column label="AI" width="160">
            <template #default="{ row }">
              <el-tag
                v-if="row.ai_passed !== null && row.ai_passed !== undefined"
                size="small"
                :type="row.ai_passed ? 'success' : 'info'"
              >
                {{ row.ai_passed ? '通过' : '不通过' }}
                <span v-if="row.ai_score != null"> ({{ row.ai_score }})</span>
              </el-tag>
              <el-tooltip v-if="row.ai_reason" :content="row.ai_reason" placement="top">
                <el-icon style="margin-left: 4px"><component :is="'InfoFilled'" /></el-icon>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200">
            <template #default="{ row }">
              <el-button size="small" tag="a" :href="row.url" target="_blank">原帖</el-button>
              <el-button
                size="small"
                type="primary"
                :disabled="!!row.influencer_id"
                @click="contactPost(row)"
              >
                {{ row.influencer_id ? '已建联' : '建联' }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="postPage"
          v-model:page-size="postPageSize"
          :total="postTotal"
          style="margin-top: 12px; justify-content: flex-end; display: flex"
        />
      </el-tab-pane>

      <el-tab-pane
        :label="isPostsTask ? '待审核博主（第二步）' : '待审核博主'"
        name="pages"
      >
        <div style="display: flex; justify-content: flex-end; margin-bottom: 8px; gap: 8px">
          <el-switch
            v-if="task.enable_ai_filter && !isPostsTask"
            v-model="pageOnlyPassed"
            active-text="只看 AI 通过"
          />
          <el-button @click="loadPages">刷新</el-button>
          <el-button type="success" :icon="'Download'" @click="exportPages">
            导出博主（CSV）
          </el-button>
        </div>
        <el-table :data="pages" border>
          <el-table-column label="名称" min-width="180">
            <template #default="{ row }">
              <div style="font-weight: 500">{{ row.title || row.pageName }}</div>
              <div style="font-size: 12px; color: #999">
                {{ (row.categories || []).join(' / ') }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="简介" min-width="220">
            <template #default="{ row }">
              <div style="max-width: 320px; white-space: pre-wrap">
                {{ (row.intro || row.about_me?.text || '').slice(0, 140) }}
                {{ (row.intro || row.about_me?.text || '').length > 140 ? '…' : '' }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="粉丝" width="90">
            <template #default="{ row }">{{ row.followers }}</template>
          </el-table-column>
          <el-table-column label="点赞" width="90">
            <template #default="{ row }">{{ row.likes }}</template>
          </el-table-column>
          <el-table-column label="评分" width="120">
            <template #default="{ row }">
              <span v-if="row.ratingOverall != null">
                {{ row.ratingOverall }}% ({{ row.ratingCount }})
              </span>
              <span v-else-if="row.rating">{{ row.rating }}</span>
            </template>
          </el-table-column>
          <el-table-column label="联系" min-width="160">
            <template #default="{ row }">
              <div v-if="row.email" style="font-size: 12px">📧 {{ row.email }}</div>
              <div v-if="row.phone" style="font-size: 12px">📞 {{ row.phone }}</div>
              <div v-if="row.website" style="font-size: 12px">
                🌐
                <a
                  :href="row.website.startsWith('http') ? row.website : `https://${row.website}`"
                  target="_blank"
                >
                  {{ row.website }}
                </a>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-if="!isPostsTask && task.enable_ai_filter" label="AI" width="140">
            <template #default="{ row }">
              <el-tag
                v-if="row._ai_passed !== undefined"
                size="small"
                :type="row._ai_passed ? 'success' : 'info'"
              >
                {{ row._ai_passed ? '通过' : '不通过' }}
                <span v-if="row._ai_score != null"> ({{ row._ai_score }})</span>
              </el-tag>
              <el-tooltip v-if="row._ai_reason" :content="row._ai_reason" placement="top">
                <el-icon style="margin-left: 4px"><component :is="'InfoFilled'" /></el-icon>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="来源帖子" width="120" v-if="isPostsTask">
            <template #default="{ row }">
              <el-tag
                v-for="pid in (row._source_post_ids || [])"
                :key="pid"
                size="small"
                style="margin-right: 4px"
              >
                #{{ pid }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <el-button
                size="small"
                tag="a"
                :href="row.pageUrl || row.facebookUrl"
                target="_blank"
              >
                主页
              </el-button>
              <el-button
                size="small"
                type="primary"
                :disabled="linkedKeys.has(pageKey(row))"
                @click="contactPage(row)"
              >
                {{ linkedKeys.has(pageKey(row)) ? '已建联' : '建联' }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="pagePage"
          v-model:page-size="pagePageSize"
          :total="pageTotal"
          style="margin-top: 12px; justify-content: flex-end; display: flex"
        />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
