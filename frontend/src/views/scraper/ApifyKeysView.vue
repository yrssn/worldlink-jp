<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apifyKeyApi, type ApifyKey, type ApifyKeyCreate } from '@/api/apifyKey'
import { emailAccountApi, type EmailAccount } from '@/api/emailAccount'

const list = ref<ApifyKey[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const submitting = ref(false)
const showToken = ref<Record<number, boolean>>({})
const emailAccounts = ref<EmailAccount[]>([])

const form = reactive({
  label: '',
  token: '',
  is_default: false,
  remark: '',
  email_account_id: null as number | null
})

function resetForm() {
  form.label = ''
  form.token = ''
  form.is_default = false
  form.remark = ''
  form.email_account_id = null
  editingId.value = null
}

async function loadEmailAccounts() {
  try {
    emailAccounts.value = await emailAccountApi.list({ purpose: 'apify' })
  } catch {
    emailAccounts.value = []
  }
}

async function load() {
  loading.value = true
  try {
    list.value = await apifyKeyApi.list()
  } catch {
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

async function openCreate() {
  resetForm()
  await loadEmailAccounts()
  dialogVisible.value = true
}

async function openEdit(row: ApifyKey) {
  resetForm()
  await loadEmailAccounts()
  editingId.value = row.id
  form.label = row.label
  form.token = row.token
  form.is_default = row.is_default
  form.remark = row.remark || ''
  form.email_account_id = row.email_account_id || null
  dialogVisible.value = true
}

async function handleSubmit() {
  if (!form.label.trim()) return ElMessage.warning('请填写名称')
  if (!form.token.trim()) return ElMessage.warning('请填写 Token')
  submitting.value = true
  try {
    if (editingId.value !== null) {
      await apifyKeyApi.update(editingId.value, {
        label: form.label.trim(),
        token: form.token.trim(),
        remark: form.remark.trim() || null,
        email_account_id: form.email_account_id
      })
    } else {
      const payload: ApifyKeyCreate = {
        label: form.label.trim(),
        token: form.token.trim(),
        is_default: form.is_default,
        remark: form.remark.trim() || null,
        email_account_id: form.email_account_id
      }
      await apifyKeyApi.create(payload)
    }
    ElMessage.success(editingId.value !== null ? '更新成功' : '创建成功')
    dialogVisible.value = false
    await load()
  } catch {
    ElMessage.error('操作失败')
  } finally {
    submitting.value = false
  }
}

async function handleSetDefault(row: ApifyKey) {
  if (row.is_default) return
  try {
    await apifyKeyApi.setDefault(row.id)
    ElMessage.success(`已将「${row.label}」设为默认`)
    await load()
  } catch {
    ElMessage.error('设置失败')
  }
}

async function handleMarkExhausted(row: ApifyKey) {
  try {
    await apifyKeyApi.markExhausted(row.id)
    ElMessage.success(`已标记「${row.label}」本月用完`)
    await load()
  } catch {
    ElMessage.error('标记失败')
  }
}

async function handleUnmarkExhausted(row: ApifyKey) {
  try {
    await apifyKeyApi.unmarkExhausted(row.id)
    ElMessage.success(`已取消「${row.label}」用完标记`)
    await load()
  } catch {
    ElMessage.error('操作失败')
  }
}

async function handleDelete(row: ApifyKey) {
  await ElMessageBox.confirm(`确认删除「${row.label}」？`, '删除确认', {
    type: 'warning',
    confirmButtonText: '删除',
    confirmButtonClass: 'el-button--danger'
  })
  try {
    await apifyKeyApi.remove(row.id)
    ElMessage.success('已删除')
    await load()
  } catch {
    ElMessage.error('删除失败')
  }
}

function toggleShowToken(id: number) {
  showToken.value[id] = !showToken.value[id]
}

function maskToken(token: string) {
  if (token.length <= 16) return '****'
  return token.slice(0, 12) + '...' + token.slice(-4)
}

function emailAccountLabel(row: EmailAccount) {
  const apifyName = row.apify_username || row.apify_full_name
  return apifyName ? `${row.email} / ${apifyName}` : row.email
}

onMounted(() => {
  load()
  loadEmailAccounts()
})
</script>

<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px">
      <el-button type="primary" @click="openCreate">+ 新增 Key</el-button>
      <el-text type="info" size="small">当前默认 Key 将被抓取任务自动使用；若数据库无默认 Key 则回退到环境变量 APIFY_TOKEN</el-text>
    </div>

    <el-table :data="list" v-loading="loading" border stripe>
      <el-table-column label="名称" prop="label" min-width="140" />

      <el-table-column label="Token" min-width="260">
        <template #default="{ row }">
          <el-space>
            <el-text style="font-family: monospace; font-size: 13px">
              {{ showToken[row.id] ? row.token : maskToken(row.token) }}
            </el-text>
            <el-button
              link
              size="small"
              @click="toggleShowToken(row.id)"
            >{{ showToken[row.id] ? '隐藏' : '显示' }}</el-button>
          </el-space>
        </template>
      </el-table-column>

      <el-table-column label="关联注册邮箱" min-width="220">
        <template #default="{ row }">
          <div v-if="row.email_account_email">
            <el-text tag="div">{{ row.email_account_email }}</el-text>
            <el-text tag="div" type="info" size="small">
              验证邮箱：{{ row.email_account_verification_email || '—' }}
            </el-text>
          </div>
          <el-text v-else type="info">—</el-text>
        </template>
      </el-table-column>

      <el-table-column label="备注" prop="remark" min-width="120">
        <template #default="{ row }">
          <el-text type="info">{{ row.remark || '—' }}</el-text>
        </template>
      </el-table-column>

      <el-table-column label="状态" width="170" align="center">
        <template #default="{ row }">
          <el-space direction="vertical" :size="4">
            <el-tag v-if="row.is_default" type="success" effect="dark">默认</el-tag>
            <el-tag v-else type="info" effect="plain">备用</el-tag>
            <el-tag v-if="row.exhausted_at" type="danger" effect="plain">本月已用完</el-tag>
          </el-space>
        </template>
      </el-table-column>

      <el-table-column label="用完标记时间" width="160" align="center">
        <template #default="{ row }">
          <span v-if="row.exhausted_at" style="color: #f56c6c; font-size: 12px">
            {{ new Date(row.exhausted_at).toLocaleString('zh-CN') }}
          </span>
          <span v-else style="color: #ccc">—</span>
        </template>
      </el-table-column>

      <el-table-column label="创建时间" width="160" align="center">
        <template #default="{ row }">
          {{ new Date(row.created_at).toLocaleString('zh-CN') }}
        </template>
      </el-table-column>

      <el-table-column label="操作" width="280" align="center" fixed="right">
        <template #default="{ row }">
          <el-button
            size="small"
            type="success"
            :disabled="row.is_default"
            @click="handleSetDefault(row)"
          >设为默认</el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button
            v-if="!row.exhausted_at"
            size="small"
            type="warning"
            @click="handleMarkExhausted(row)"
          >本月用完</el-button>
          <el-button
            v-else
            size="small"
            @click="handleUnmarkExhausted(row)"
          >取消用完</el-button>
          <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId !== null ? '编辑 Apify Key' : '新增 Apify Key'"
      width="520px"
      :close-on-click-modal="false"
    >
      <el-form label-width="80px" @submit.prevent="handleSubmit">
        <el-form-item label="名称" required>
          <el-input v-model="form.label" placeholder="如：主账号、备用账号" maxlength="200" />
        </el-form-item>
        <el-form-item label="Token" required>
          <el-input
            v-model="form.token"
            type="textarea"
            :rows="2"
            placeholder="apify_api_xxxxxx"
            maxlength="500"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" placeholder="可选备注" maxlength="500" />
        </el-form-item>
        <el-form-item label="关联邮箱">
          <el-select
            v-model="form.email_account_id"
            filterable
            clearable
            placeholder="选择邮箱管理中的 Apify 注册邮箱"
            style="width: 100%"
          >
            <el-option
              v-for="item in emailAccounts"
              :key="item.id"
              :label="emailAccountLabel(item)"
              :value="item.id"
            >
              <div style="display: flex; justify-content: space-between; gap: 12px">
                <span>{{ emailAccountLabel(item) }}</span>
                <el-text type="info" size="small">{{ item.status }}</el-text>
              </div>
            </el-option>
          </el-select>
          <div style="margin-top: 6px">
            <el-text type="info" size="small">Apify 注册账号应关联到邮箱管理中的注册邮箱记录。</el-text>
            <el-button link size="small" @click="loadEmailAccounts">刷新邮箱</el-button>
          </div>
        </el-form-item>
        <el-form-item v-if="editingId === null" label="设为默认">
          <el-switch v-model="form.is_default" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          {{ editingId !== null ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>
