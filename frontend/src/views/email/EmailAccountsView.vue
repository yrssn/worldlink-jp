<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  emailAccountApi,
  type EmailAccount,
  type EmailAccountPayload
} from '@/api/emailAccount'

const list = ref<EmailAccount[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const submitting = ref(false)
const syncingId = ref<number | null>(null)
const showSecret = ref<Record<string, boolean>>({})

const filters = reactive({
  q: '',
  purpose: '',
  status: ''
})

const form = reactive({
  email: '',
  email_password: '',
  provider: 'zoho',
  mail_login_url: 'https://www.zoho.com/jp/mail/',
  verification_email: '',
  verification_password: '',
  verification_login_url: '',
  purpose: 'apify',
  status: 'unused',
  browser_id: '',
  apify_full_name: '',
  apify_username: '',
  apify_user_id: '',
  apify_token: '',
  apify_registered_at: '',
  last_verification_code: '',
  last_verification_at: '',
  note: ''
})

const purposeOptions = [
  { label: 'Apify 注册', value: 'apify' },
  { label: '其他流程', value: 'other' }
]

const statusOptions = [
  { label: '未使用', value: 'unused', type: 'info' },
  { label: '邮箱待登录验证', value: 'mail_login_verifying', type: 'warning' },
  { label: '邮箱已登录', value: 'mail_ready', type: 'success' },
  { label: 'Apify 邮箱待验证', value: 'apify_email_verifying', type: 'warning' },
  { label: 'Apify 已注册', value: 'apify_registered', type: 'success' },
  { label: '异常', value: 'failed', type: 'danger' }
] as const

function statusLabel(value: string) {
  return statusOptions.find((item) => item.value === value)?.label || value
}

function statusType(value: string) {
  return statusOptions.find((item) => item.value === value)?.type || 'info'
}

function resetForm() {
  form.email = ''
  form.email_password = ''
  form.provider = 'zoho'
  form.mail_login_url = 'https://www.zoho.com/jp/mail/'
  form.verification_email = ''
  form.verification_password = ''
  form.verification_login_url = ''
  form.purpose = 'apify'
  form.status = 'unused'
  form.browser_id = ''
  form.apify_full_name = ''
  form.apify_username = ''
  form.apify_user_id = ''
  form.apify_token = ''
  form.apify_registered_at = ''
  form.last_verification_code = ''
  form.last_verification_at = ''
  form.note = ''
  editingId.value = null
}

function toPayload(): EmailAccountPayload {
  return {
    email: form.email.trim(),
    email_password: form.email_password.trim() || null,
    provider: form.provider.trim() || null,
    mail_login_url: form.mail_login_url.trim() || null,
    verification_email: form.verification_email.trim() || null,
    verification_password: form.verification_password.trim() || null,
    verification_login_url: form.verification_login_url.trim() || null,
    purpose: form.purpose,
    status: form.status,
    browser_id: form.browser_id.trim() || null,
    apify_full_name: form.apify_full_name.trim() || null,
    apify_username: form.apify_username.trim() || null,
    apify_user_id: form.apify_user_id.trim() || null,
    apify_token: form.apify_token.trim() || null,
    apify_registered_at: form.apify_registered_at || null,
    last_verification_code: form.last_verification_code.trim() || null,
    last_verification_at: form.last_verification_at || null,
    note: form.note.trim() || null
  }
}

function fillForm(row: EmailAccount) {
  form.email = row.email
  form.email_password = row.email_password || ''
  form.provider = row.provider || ''
  form.mail_login_url = row.mail_login_url || ''
  form.verification_email = row.verification_email || ''
  form.verification_password = row.verification_password || ''
  form.verification_login_url = row.verification_login_url || ''
  form.purpose = row.purpose
  form.status = row.status
  form.browser_id = row.browser_id || ''
  form.apify_full_name = row.apify_full_name || ''
  form.apify_username = row.apify_username || ''
  form.apify_user_id = row.apify_user_id || ''
  form.apify_token = row.apify_token || ''
  form.apify_registered_at = toDatePickerValue(row.apify_registered_at)
  form.last_verification_code = row.last_verification_code || ''
  form.last_verification_at = toDatePickerValue(row.last_verification_at)
  form.note = row.note || ''
}

async function load() {
  loading.value = true
  try {
    list.value = await emailAccountApi.list({
      q: filters.q.trim() || undefined,
      purpose: filters.purpose || undefined,
      status: filters.status || undefined
    })
  } catch {
    ElMessage.error('加载邮箱账号失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  resetForm()
  dialogVisible.value = true
}

function resetFilters() {
  filters.q = ''
  filters.purpose = ''
  filters.status = ''
  load()
}

function openEdit(row: EmailAccount) {
  resetForm()
  editingId.value = row.id
  fillForm(row)
  dialogVisible.value = true
}

async function handleSubmit() {
  if (!form.email.trim()) return ElMessage.warning('请填写注册邮箱')
  submitting.value = true
  try {
    if (editingId.value !== null) {
      await emailAccountApi.update(editingId.value, toPayload())
    } else {
      await emailAccountApi.create(toPayload())
    }
    ElMessage.success(editingId.value !== null ? '已更新邮箱账号' : '已新增邮箱账号')
    dialogVisible.value = false
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    submitting.value = false
  }
}

async function handleDelete(row: EmailAccount) {
  await ElMessageBox.confirm(`确认删除「${row.email}」？`, '删除确认', {
    type: 'warning',
    confirmButtonText: '删除',
    confirmButtonClass: 'el-button--danger'
  })
  try {
    await emailAccountApi.remove(row.id)
    ElMessage.success('已删除')
    await load()
  } catch {
    /* 拦截器已提示 */
  }
}

async function handleRegisterApifyKey(row: EmailAccount) {
  syncingId.value = row.id
  try {
    await emailAccountApi.registerApifyKey(row.id)
    ElMessage.success('已登记到 Apify Key 管理')
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    syncingId.value = null
  }
}

function toggleSecret(row: EmailAccount, field: string) {
  const key = `${row.id}:${field}`
  showSecret.value[key] = !showSecret.value[key]
}

function isSecretVisible(row: EmailAccount, field: string) {
  return !!showSecret.value[`${row.id}:${field}`]
}

function maskSecret(value?: string | null) {
  if (!value) return '—'
  if (value.length <= 8) return '********'
  return value.slice(0, 4) + '...' + value.slice(-4)
}

function formatDate(value?: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString('zh-CN')
}

function toDatePickerValue(value?: string | null) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (num: number) => String(num).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours()
  )}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

onMounted(load)
</script>

<template>
  <div>
    <el-card shadow="never" style="margin-bottom: 16px">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span>邮箱管理</span>
          <el-button type="primary" @click="openCreate">+ 新增邮箱</el-button>
        </div>
      </template>
      <el-alert
        type="info"
        :closable="false"
        style="margin-bottom: 12px"
        title="用于 Apify 等注册流程：保存注册邮箱、邮箱登录验证用的备用 Webmail、Apify 注册信息与创建日期。"
      />
      <el-form :inline="true" @submit.prevent="load">
        <el-form-item label="关键词">
          <el-input
            v-model="filters.q"
            clearable
            placeholder="注册邮箱 / 验证邮箱 / Apify 用户名"
            style="width: 280px"
            @keyup.enter="load"
          />
        </el-form-item>
        <el-form-item label="用途">
          <el-select v-model="filters.purpose" clearable placeholder="全部" style="width: 150px">
            <el-option v-for="item in purposeOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部" style="width: 180px">
            <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="load">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-table :data="list" v-loading="loading" border stripe>
      <el-table-column label="注册邮箱" min-width="220" fixed>
        <template #default="{ row }">
          <div>
            <el-text tag="div" style="font-weight: 600">{{ row.email }}</el-text>
            <el-text tag="div" type="info" size="small">{{ row.provider || '—' }}</el-text>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="邮箱密码" min-width="150">
        <template #default="{ row }">
          <el-space>
            <el-text style="font-family: monospace">
              {{ isSecretVisible(row, 'email') ? row.email_password || '—' : maskSecret(row.email_password) }}
            </el-text>
            <el-button link size="small" @click="toggleSecret(row, 'email')">
              {{ isSecretVisible(row, 'email') ? '隐藏' : '显示' }}
            </el-button>
          </el-space>
        </template>
      </el-table-column>
      <el-table-column label="邮箱登录地址" min-width="220">
        <template #default="{ row }">
          <el-link v-if="row.mail_login_url" :href="row.mail_login_url" target="_blank" type="primary">
            {{ row.mail_login_url }}
          </el-link>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="验证码邮箱" min-width="220">
        <template #default="{ row }">
          <div>
            <el-text tag="div">{{ row.verification_email || '—' }}</el-text>
            <el-link
              v-if="row.verification_login_url"
              :href="row.verification_login_url"
              target="_blank"
              type="primary"
              style="font-size: 12px"
            >
              打开 Webmail
            </el-link>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="验证邮箱密码" min-width="150">
        <template #default="{ row }">
          <el-space>
            <el-text style="font-family: monospace">
              {{ isSecretVisible(row, 'verify') ? row.verification_password || '—' : maskSecret(row.verification_password) }}
            </el-text>
            <el-button link size="small" @click="toggleSecret(row, 'verify')">
              {{ isSecretVisible(row, 'verify') ? '隐藏' : '显示' }}
            </el-button>
          </el-space>
        </template>
      </el-table-column>
      <el-table-column label="用途/状态" width="170" align="center">
        <template #default="{ row }">
          <el-space direction="vertical" :size="4">
            <el-tag effect="plain">{{ row.purpose === 'apify' ? 'Apify 注册' : row.purpose }}</el-tag>
            <el-tag :type="statusType(row.status)" effect="dark">{{ statusLabel(row.status) }}</el-tag>
          </el-space>
        </template>
      </el-table-column>
      <el-table-column label="指纹浏览器" min-width="130">
        <template #default="{ row }">{{ row.browser_id || '—' }}</template>
      </el-table-column>
      <el-table-column label="Apify 账号" min-width="220">
        <template #default="{ row }">
          <div>
            <el-text tag="div">{{ row.apify_username || row.apify_full_name || '—' }}</el-text>
            <el-text tag="div" type="info" size="small">{{ row.apify_user_id || '未记录 User ID' }}</el-text>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="Apify Token" min-width="170">
        <template #default="{ row }">
          <el-space>
            <el-text style="font-family: monospace">
              {{ isSecretVisible(row, 'apify') ? row.apify_token || '—' : maskSecret(row.apify_token) }}
            </el-text>
            <el-button link size="small" @click="toggleSecret(row, 'apify')">
              {{ isSecretVisible(row, 'apify') ? '隐藏' : '显示' }}
            </el-button>
          </el-space>
        </template>
      </el-table-column>
      <el-table-column label="Apify 创建日期" width="170" align="center">
        <template #default="{ row }">{{ formatDate(row.apify_registered_at) }}</template>
      </el-table-column>
      <el-table-column label="最近验证码" width="160">
        <template #default="{ row }">
          <div>
            <el-text tag="div">{{ row.last_verification_code || '—' }}</el-text>
            <el-text tag="div" type="info" size="small">{{ formatDate(row.last_verification_at) }}</el-text>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="记录创建时间" width="170" align="center">
        <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="260" fixed="right" align="center">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button
            size="small"
            type="success"
            :loading="syncingId === row.id"
            :disabled="!row.apify_token"
            @click="handleRegisterApifyKey(row)"
          >登记 Apify</el-button>
          <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId !== null ? '编辑邮箱账号' : '新增邮箱账号'"
      width="760px"
      :close-on-click-modal="false"
    >
      <el-form label-width="130px" @submit.prevent="handleSubmit">
        <el-divider content-position="left">注册邮箱</el-divider>
        <el-form-item label="注册邮箱" required>
          <el-input v-model="form.email" placeholder="用于注册 Zoho / Apify 的邮箱" maxlength="255" />
        </el-form-item>
        <el-form-item label="邮箱密码">
          <el-input v-model="form.email_password" show-password placeholder="通常也作为 Apify 登录密码" maxlength="500" />
        </el-form-item>
        <el-form-item label="邮箱服务商">
          <el-input v-model="form.provider" placeholder="如 zoho" maxlength="64" />
        </el-form-item>
        <el-form-item label="邮箱登录地址">
          <el-input v-model="form.mail_login_url" placeholder="https://www.zoho.com/jp/mail/" maxlength="512" />
        </el-form-item>

        <el-divider content-position="left">登录验证码邮箱</el-divider>
        <el-form-item label="验证邮箱">
          <el-input v-model="form.verification_email" placeholder="如 webmail74 / onamae 里的绑定邮箱" maxlength="255" />
        </el-form-item>
        <el-form-item label="验证邮箱密码">
          <el-input v-model="form.verification_password" show-password placeholder="备用邮箱登录密码" maxlength="500" />
        </el-form-item>
        <el-form-item label="验证邮箱入口">
          <el-input v-model="form.verification_login_url" placeholder="https://webmail74.onamae.ne.jp/" maxlength="512" />
        </el-form-item>
        <el-form-item label="最近验证码">
          <el-col :span="8">
            <el-input v-model="form.last_verification_code" placeholder="如 6298936" maxlength="32" />
          </el-col>
          <el-col :span="1" style="text-align: center">—</el-col>
          <el-col :span="15">
            <el-date-picker
              v-model="form.last_verification_at"
              type="datetime"
              value-format="YYYY-MM-DDTHH:mm:ss"
              placeholder="验证码收到时间"
              style="width: 100%"
            />
          </el-col>
        </el-form-item>

        <el-divider content-position="left">Apify 注册信息</el-divider>
        <el-form-item label="用途">
          <el-select v-model="form.purpose" style="width: 180px">
            <el-option v-for="item in purposeOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 220px">
            <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="指纹浏览器ID">
          <el-input v-model="form.browser_id" placeholder="关联 BitBrowser browser_id（可选）" maxlength="64" />
        </el-form-item>
        <el-form-item label="Apify 全名">
          <el-input v-model="form.apify_full_name" placeholder="Apify 注册 full name" maxlength="128" />
        </el-form-item>
        <el-form-item label="Apify 用户名">
          <el-input v-model="form.apify_username" placeholder="如 indigo_programmer" maxlength="128" />
        </el-form-item>
        <el-form-item label="Apify User ID">
          <el-input v-model="form.apify_user_id" placeholder="Settings 里的 Apify user ID" maxlength="128" />
        </el-form-item>
        <el-form-item label="Apify Token">
          <el-input v-model="form.apify_token" type="textarea" :rows="2" placeholder="Settings 里的 API token" maxlength="500" />
        </el-form-item>
        <el-form-item label="Apify 创建日期">
          <el-date-picker
            v-model="form.apify_registered_at"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ss"
            placeholder="注册完成时间"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="3" placeholder="流程备注 / 异常原因" />
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
