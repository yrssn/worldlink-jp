<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  influencerApi,
  type InfluencerDetail,
  type InfluencerSourcePost,
  type SocialPlatform
} from '@/api/influencer'

const route = useRoute()
const router = useRouter()
const id = computed(() => Number(route.params.id))
const detail = ref<InfluencerDetail | null>(null)
const sourcePosts = ref<InfluencerSourcePost[]>([])

const socialDialog = ref(false)
const socialForm = reactive<{
  platform: SocialPlatform
  handle: string
  url: string
  followers?: number
}>({
  platform: 'instagram',
  handle: '',
  url: ''
})

const STATUS_LABELS: Record<string, string> = {
  pre_contact: '预建联',
  contacting: '建联中',
  signed: '已签约',
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

const PLATFORMS: { label: string; value: SocialPlatform }[] = [
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

const hasFb = computed(() => {
  const d = detail.value
  if (!d) return false
  return !!(
    d.fb_page_url ||
    d.fb_page_id ||
    d.fb_followers ||
    d.fb_likes ||
    d.fb_rating ||
    d.fb_rating_count
  )
})

async function refresh() {
  detail.value = await influencerApi.detail(id.value)
  sourcePosts.value = await influencerApi.listPosts(id.value).catch(() => [])
}

async function addSocial() {
  if (!socialForm.platform) return
  await influencerApi.addSocial(id.value, socialForm)
  ElMessage.success('已添加')
  socialDialog.value = false
  refresh()
}

async function removeSocial(sid: number) {
  await influencerApi.removeSocial(id.value, sid)
  ElMessage.success('已删除')
  refresh()
}

onMounted(refresh)
</script>

<template>
  <div class="page-card" v-if="detail">
    <el-page-header @back="router.back()" :content="detail.display_name" />
    <el-descriptions :column="3" border style="margin-top: 16px">
      <el-descriptions-item label="昵称">{{ detail.display_name }}</el-descriptions-item>
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
      <el-descriptions-item label="国家/地区">{{ detail.country }}</el-descriptions-item>
      <el-descriptions-item label="城市">{{ detail.city }}</el-descriptions-item>
      <el-descriptions-item label="邮箱">{{ detail.email }}</el-descriptions-item>
      <el-descriptions-item label="电话">{{ detail.phone }}</el-descriptions-item>
      <el-descriptions-item label="网站">
        <a v-if="detail.website" :href="detail.website" target="_blank">{{ detail.website }}</a>
      </el-descriptions-item>
      <el-descriptions-item label="Messenger">{{ detail.messenger }}</el-descriptions-item>
      <el-descriptions-item v-if="hasFb" label="FB 主页" :span="3">
        <a v-if="detail.fb_page_url" :href="detail.fb_page_url" target="_blank">
          {{ detail.fb_page_url }}
        </a>
      </el-descriptions-item>
      <el-descriptions-item v-if="hasFb" label="FB 粉丝">{{ detail.fb_followers }}</el-descriptions-item>
      <el-descriptions-item v-if="hasFb" label="FB 点赞">{{ detail.fb_likes }}</el-descriptions-item>
      <el-descriptions-item v-if="hasFb" label="FB 评分">
        {{ detail.fb_rating ?? '—' }}<span v-if="detail.fb_rating_count">（{{ detail.fb_rating_count }}）</span>
      </el-descriptions-item>
      <el-descriptions-item label="简介" :span="3">{{ detail.bio }}</el-descriptions-item>
      <el-descriptions-item label="备注" :span="3">{{ detail.notes }}</el-descriptions-item>
    </el-descriptions>

    <div style="margin: 20px 0 12px; display: flex; justify-content: space-between">
      <h4 style="margin: 0">社交账号</h4>
      <el-button type="primary" size="small" @click="socialDialog = true">添加账号</el-button>
    </div>
    <el-table :data="detail.social_accounts" border>
      <el-table-column prop="platform" label="平台" width="120" />
      <el-table-column prop="handle" label="账号/Handle" />
      <el-table-column label="链接">
        <template #default="{ row }">
          <a v-if="row.url" :href="row.url" target="_blank">{{ row.url }}</a>
        </template>
      </el-table-column>
      <el-table-column prop="followers" label="粉丝" width="100" />
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
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


    <el-dialog v-model="socialDialog" title="添加社交账号" width="480px">
      <el-form :model="socialForm" label-width="100px">
        <el-form-item label="平台">
          <el-select v-model="socialForm.platform" style="width: 100%">
            <el-option v-for="p in PLATFORMS" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="账号">
          <el-input v-model="socialForm.handle" />
        </el-form-item>
        <el-form-item label="链接">
          <el-input v-model="socialForm.url" />
        </el-form-item>
        <el-form-item label="粉丝数">
          <el-input-number v-model="socialForm.followers" :min="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="socialDialog = false">取消</el-button>
        <el-button type="primary" @click="addSocial">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
