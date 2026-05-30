<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  fbGroupScrapeApi,
  type FbGroupScheduleTask,
  type FbGroupScheduleTaskCreate,
  type FbGroupScheduleTaskUpdate
} from '@/api/fbGroupScrape'

const props = defineProps<{ configId: number }>()
const configId = computed(() => props.configId)

const schedules = ref<FbGroupScheduleTask[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)

const form = reactive({
  schedule_type: 'cron' as 'cron' | 'interval',
  cron_expr: '0 10 * * *',
  interval_hours: 24,
  results_limit: 20,
  view_option: 'CHRONOLOGICAL' as const,
  max_consecutive_failures: 5,
  remark: ''
})

async function loadSchedules() {
  loading.value = true
  try {
    schedules.value = await fbGroupScrapeApi.listSchedules(configId.value)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.schedule_type = 'cron'
  form.cron_expr = '0 10 * * *'
  form.interval_hours = 24
  form.results_limit = 20
  form.view_option = 'CHRONOLOGICAL'
  form.max_consecutive_failures = 5
  form.remark = ''
  dialogVisible.value = true
}

function openEdit(row: FbGroupScheduleTask) {
  editingId.value = row.id
  form.schedule_type = row.schedule_type
  if (row.schedule_type === 'cron') {
    form.cron_expr = (row.schedule_config as any)?.cron || '0 10 * * *'
  } else {
    form.interval_hours = (row.schedule_config as any)?.hours || 24
  }
  form.results_limit = (row.pull_params as any)?.results_limit || 20
  form.view_option = (row.pull_params as any)?.view_option || 'CHRONOLOGICAL'
  form.max_consecutive_failures = row.max_consecutive_failures
  form.remark = row.remark || ''
  dialogVisible.value = true
}

async function submitForm() {
  if (!form.cron_expr && form.schedule_type === 'cron') {
    ElMessage.warning('请填写 Cron 表达式')
    return
  }

  try {
    const schedule_config =
      form.schedule_type === 'cron'
        ? { cron: form.cron_expr }
        : { hours: form.interval_hours }

    const pull_params = {
      results_limit: form.results_limit,
      view_option: form.view_option
    }

    if (editingId.value === null) {
      const body: FbGroupScheduleTaskCreate = {
        schedule_type: form.schedule_type,
        schedule_config,
        pull_params,
        max_consecutive_failures: form.max_consecutive_failures,
        remark: form.remark || undefined
      }
      await fbGroupScrapeApi.createSchedule(configId.value, body)
      ElMessage.success('已创建定时任务')
    } else {
      const body: FbGroupScheduleTaskUpdate = {
        schedule_type: form.schedule_type,
        schedule_config,
        pull_params,
        max_consecutive_failures: form.max_consecutive_failures,
        remark: form.remark || undefined
      }
      await fbGroupScrapeApi.updateSchedule(editingId.value, body)
      ElMessage.success('已更新定时任务')
    }
    dialogVisible.value = false
    await loadSchedules()
  } catch {
    /* 拦截器 */
  }
}

async function deleteSchedule(row: FbGroupScheduleTask) {
  try {
    await ElMessageBox.confirm(
      `确定删除定时任务「${row.remark || `每${row.schedule_type === 'cron' ? 'Cron' : '间隔'}执行`}」？`,
      '删除',
      { type: 'warning' }
    )
    await fbGroupScrapeApi.deleteSchedule(row.id)
    ElMessage.success('已删除')
    await loadSchedules()
  } catch {
    /* 取消 */
  }
}

async function toggleStatus(row: FbGroupScheduleTask) {
  const newStatus = row.status === 'active' ? 'paused' : 'active'
  try {
    await fbGroupScrapeApi.updateSchedule(row.id, { status: newStatus })
    ElMessage.success(`已${newStatus === 'active' ? '启用' : '暂停'}`)
    await loadSchedules()
  } catch {
    /* 拦截器 */
  }
}

function formatSchedule(row: FbGroupScheduleTask): string {
  if (row.schedule_type === 'cron') {
    return `Cron: ${(row.schedule_config as any)?.cron || '—'}`
  } else {
    const hours = (row.schedule_config as any)?.hours || 24
    return `每 ${hours} 小时`
  }
}

function formatLastRun(row: FbGroupScheduleTask): string {
  if (!row.last_run_at) return '未运行'
  const date = new Date(row.last_run_at)
  return date.toLocaleString('zh-CN')
}

onMounted(() => loadSchedules())
</script>

<template>
  <div style="padding: 20px">
    <div style="margin-bottom: 16px">
      <el-button type="primary" @click="openCreate">新建定时任务</el-button>
    </div>

    <el-table :data="schedules" v-loading="loading" stripe>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column label="调度方式" width="180">
        <template #default="{ row }">
          {{ formatSchedule(row) }}
        </template>
      </el-table-column>
      <el-table-column label="拉取参数" width="150">
        <template #default="{ row }">
          <span style="font-size: 12px; color: #606266">
            条数: {{ (row.pull_params as any)?.results_limit || 20 }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag
            :type="row.status === 'active' ? 'success' : row.status === 'paused' ? 'info' : 'danger'"
            size="small"
          >
            {{ row.status === 'active' ? '启用' : row.status === 'paused' ? '暂停' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="最后运行" width="180">
        <template #default="{ row }">
          {{ formatLastRun(row) }}
        </template>
      </el-table-column>
      <el-table-column label="连续失败" width="100">
        <template #default="{ row }">
          <span :style="{ color: row.consecutive_failures > 0 ? '#f56c6c' : '#67c23a' }">
            {{ row.consecutive_failures }} / {{ row.max_consecutive_failures }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="备注" min-width="150">
        <template #default="{ row }">
          {{ row.remark || '—' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button
            link
            type="primary"
            size="small"
            @click="toggleStatus(row)"
          >
            {{ row.status === 'active' ? '暂停' : '启用' }}
          </el-button>
          <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" size="small" @click="deleteSchedule(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 创建/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingId === null ? '新建定时任务' : '编辑定时任务'"
      width="600px"
    >
      <el-form label-width="140px">
        <el-form-item label="调度方式">
          <el-radio-group v-model="form.schedule_type">
            <el-radio label="cron">Cron 表达式</el-radio>
            <el-radio label="interval">时间间隔</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item v-if="form.schedule_type === 'cron'" label="Cron 表达式">
          <el-input
            v-model="form.cron_expr"
            placeholder="如 0 10 * * * 表示每天 10 点"
            clearable
          />
          <div style="font-size: 12px; color: #909399; margin-top: 4px">
            分 时 日 月 周 (0=周日, 1=周一...6=周六)
          </div>
        </el-form-item>

        <el-form-item v-if="form.schedule_type === 'interval'" label="间隔小时数">
          <el-input-number v-model="form.interval_hours" :min="1" :max="720" />
        </el-form-item>

        <el-form-item label="拉取条数">
          <el-input-number v-model="form.results_limit" :min="1" :max="500" />
        </el-form-item>

        <el-form-item label="排序方式">
          <el-select v-model="form.view_option">
            <el-option label="按时间顺序" value="CHRONOLOGICAL" />
            <el-option label="最近活动" value="RECENT_ACTIVITY" />
            <el-option label="热门帖子" value="TOP_POSTS" />
            <el-option label="按时间顺序（列表）" value="CHRONOLOGICAL_LISTINGS" />
          </el-select>
        </el-form-item>

        <el-form-item label="最大失败次数">
          <el-input-number v-model="form.max_consecutive_failures" :min="1" :max="100" />
          <div style="font-size: 12px; color: #909399; margin-top: 4px">
            超过此次数后自动禁用任务
          </div>
        </el-form-item>

        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" clearable />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>
