<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fbGroupScrapeApi, type FbGroupScrape } from '@/api/fbGroupScrape'
import { useAuthStore } from '@/store/auth'

const auth = useAuthStore()
const isAdmin = computed(() => auth.isAdmin)

const list = ref<FbGroupScrape[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const filter = reactive({
  keyword: '',
  include_deleted: false
})

const form = reactive({
  connection: '',
  title: '',
  remark: ''
})

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
  if (row.deleted_at) {
    ElMessage.warning('已删除记录不可编辑，可点「恢复」')
    return
  }
  editingId.value = row.id
  form.connection = row.connection
  form.title = row.title
  form.remark = row.remark || ''
  dialogVisible.value = true
}

async function submitForm() {
  const connection = form.connection.trim()
  const title = form.title.trim()
  if (!connection) {
    ElMessage.warning('请填写连接')
    return
  }
  if (!title) {
    ElMessage.warning('请填写标题')
    return
  }
  try {
    const payload = {
      connection,
      title,
      remark: form.remark.trim() || undefined
    }
    if (editingId.value == null) {
      await fbGroupScrapeApi.create(payload)
      ElMessage.success('已创建')
    } else {
      await fbGroupScrapeApi.update(editingId.value, payload)
      ElMessage.success('已更新')
    }
    dialogVisible.value = false
    await refresh()
  } catch {
    /* 拦截器 */
  }
}

async function removeRow(row: FbGroupScrape) {
  try {
    await ElMessageBox.confirm(`确定删除「${row.title}」？（软删除，可恢复）`, '删除', {
      type: 'warning'
    })
    await fbGroupScrapeApi.remove(row.id)
    ElMessage.success('已删除')
    await refresh()
  } catch {
    /* 取消 */
  }
}

async function restoreRow(row: FbGroupScrape) {
  try {
    await fbGroupScrapeApi.restore(row.id)
    ElMessage.success('已恢复')
    await refresh()
  } catch {
    /* 拦截器 */
  }
}

function formatTime(iso: string | null | undefined) {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false })
}

onMounted(refresh)
</script>

<template>
  <div class="page-card">
    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; gap: 8px">
      <div>
        <h3 style="margin: 0 0 6px 0">Facebook 群组维度抓取</h3>
        <p style="margin: 0; font-size: 12px; color: #666">
          维护群组连接与说明，后续可在此维度下挂抓取任务。删除为软删除，保留创建人与时间记录。
        </p>
      </div>
      <el-button type="primary" @click="openCreate">新建记录</el-button>
    </div>

    <el-card shadow="never" style="margin-bottom: 12px">
      <el-form :inline="true" @submit.prevent="refresh">
        <el-form-item label="关键词">
          <el-input v-model="filter.keyword" clearable placeholder="标题/连接/备注" style="width: 220px" />
        </el-form-item>
        <el-form-item v-if="isAdmin">
          <el-checkbox v-model="filter.include_deleted">含已删除</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="refresh">查询</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-table v-loading="loading" :data="list" border stripe row-key="id">
      <el-table-column prop="id" label="ID" width="72" />
      <el-table-column prop="title" label="标题" min-width="140" show-overflow-tooltip />
      <el-table-column prop="connection" label="连接" min-width="220" show-overflow-tooltip>
        <template #default="{ row }">
          <a
            v-if="row.connection.startsWith('http')"
            :href="row.connection"
            target="_blank"
            rel="noopener noreferrer"
            class="fb-link"
          >
            {{ row.connection }}
          </a>
          <span v-else>{{ row.connection }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="remark" label="备注" min-width="120" show-overflow-tooltip />
      <el-table-column label="创建人" width="100">
        <template #default="{ row }">
          {{ row.created_by_username || row.created_by_id }}
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="168">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="更新时间" width="168">
        <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="删除时间" width="168">
        <template #default="{ row }">
          <span v-if="row.deleted_at" style="color: #f56c6c">{{ formatTime(row.deleted_at) }}</span>
          <span v-else class="fb-muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="88" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.deleted_at" type="info" size="small">已删除</el-tag>
          <el-tag v-else type="success" size="small">正常</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <template v-if="!row.deleted_at">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="removeRow(row)">删除</el-button>
          </template>
          <el-button v-else size="small" type="warning" plain @click="restoreRow(row)">恢复</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && !list.length" description="暂无记录" style="margin-top: 24px" />

    <el-dialog
      v-model="dialogVisible"
      :title="editingId == null ? '新建群组维度' : '编辑群组维度'"
      width="640px"
      destroy-on-close
    >
      <el-form label-width="88px">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" maxlength="200" show-word-limit placeholder="便于识别的名称" />
        </el-form-item>
        <el-form-item label="连接" required>
          <el-input
            v-model="form.connection"
            type="textarea"
            :rows="3"
            placeholder="Facebook 群组 URL 或连接标识"
          />
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
</style>
