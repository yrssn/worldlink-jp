<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { influencerApi, type Influencer } from '@/api/influencer'

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
    country: 'JP',
    region: '',
    city: '',
    bio: '',
    notes: '',
    status: 'pre_contact'
  })
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
</script>

<template>
  <div class="page-card">
    <div style="display: flex; justify-content: space-between; margin-bottom: 12px">
      <h3 style="margin: 0">建联达人</h3>
      <div style="display: flex; gap: 8px">
        <el-button type="success" :icon="'Download'" @click="exportList">
          导出（CSV）
        </el-button>
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
  </div>
</template>
