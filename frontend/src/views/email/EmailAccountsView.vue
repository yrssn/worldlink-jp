<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  emailAccountApi,
  type EmailAccount,
  type EmailAccountPayload
} from '@/api/emailAccount'
import { bitbrowserApi, type BitBrowserCatalogRow } from '@/api/bitbrowser'
import { apifyKeyApi, type ApifyKey } from '@/api/apifyKey'

const list = ref<EmailAccount[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const submitting = ref(false)
const apifySignupId = ref<number | null>(null)
const apifyContinueId = ref<number | null>(null)
const showSecret = ref<Record<string, boolean>>({})
const browserOptions = ref<BitBrowserCatalogRow[]>([])
const apifyKeys = ref<ApifyKey[]>([])

const filters = reactive({
  q: ''
})

const form = reactive({
  email: '',
  email_password: '',
  provider: 'zoho',
  mail_login_url: 'https://www.zoho.com/jp/mail/',
  verification_email: '',
  verification_password: '',
  verification_login_url: '',
  purpose: 'registration',
  status: 'available',
  browser_id: '',
  last_verification_code: '',
  last_verification_at: '',
  note: ''
})

function resetForm() {
  form.email = ''
  form.email_password = ''
  form.provider = 'zoho'
  form.mail_login_url = 'https://www.zoho.com/jp/mail/'
  form.verification_email = ''
  form.verification_password = ''
  form.verification_login_url = ''
  form.purpose = 'registration'
  form.status = 'available'
  form.browser_id = ''
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
  form.last_verification_code = row.last_verification_code || ''
  form.last_verification_at = toDatePickerValue(row.last_verification_at)
  form.note = row.note || ''
}

async function load() {
  loading.value = true
  try {
    list.value = await emailAccountApi.list({
      q: filters.q.trim() || undefined
    })
  } catch {
    ElMessage.error('加载邮箱账号失败')
  } finally {
    loading.value = false
  }
}

async function loadBrowserOptions() {
  try {
    const rows = await bitbrowserApi.listCatalog()
    browserOptions.value = rows.filter((row) => row.in_local_cache)
  } catch {
    browserOptions.value = []
  }
}

async function loadApifyKeys() {
  try {
    apifyKeys.value = await apifyKeyApi.list()
  } catch {
    apifyKeys.value = []
  }
}

function browserLabel(row: BitBrowserCatalogRow) {
  const name = row.name || row.cached_window_name || row.browser_id
  const platform = row.platform_name || row.platform || row.cached_env_platform
  return platform ? `${name} / ${platform}` : name
}

function browserName(browserId?: string | null) {
  if (!browserId) return '—'
  const row = browserOptions.value.find((item) => item.browser_id === browserId)
  return row ? browserLabel(row) : browserId
}

function linkedApifyKey(emailAccountId: number) {
  return apifyKeys.value.find((item) => item.email_account_id === emailAccountId)
}

function canStartApifySignup(row: EmailAccount) {
  return !linkedApifyKey(row.id) && !!row.browser_id
}

function canContinueApifySignup(row: EmailAccount) {
  return !linkedApifyKey(row.id) && !!row.browser_id
}

async function openCreate() {
  resetForm()
  await loadBrowserOptions()
  dialogVisible.value = true
}

function resetFilters() {
  filters.q = ''
  load()
}

async function openEdit(row: EmailAccount) {
  resetForm()
  editingId.value = row.id
  fillForm(row)
  await loadBrowserOptions()
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
    await Promise.all([load(), loadApifyKeys()])
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
    await Promise.all([load(), loadApifyKeys()])
  } catch {
    /* 拦截器已提示 */
  }
}

async function handleStartApifySignup(row: EmailAccount) {
  if (linkedApifyKey(row.id)) {
    ElMessage.info('该邮箱已关联 Apify Key')
    return
  }
  if (!row.browser_id) {
    ElMessage.warning('请先为该邮箱选择指纹浏览器')
    return
  }
  apifySignupId.value = row.id
  try {
    const result = await emailAccountApi.startApifySignup(row.id)
    if (result.still_logged_in) {
      ElMessage.warning('已重启并清理 Apify 会话，但仍保持登录；请检查指纹浏览器环境 Cookie 配置')
    } else if (result.captcha_required) {
      ElMessage.warning(`已清理 Apify 会话并提交注册；弹出图形验证码，请在指纹浏览器窗口里人工完成验证`)
    } else if (result.profile_submitted) {
      ElMessage.success('已提交 Apify 注册资料页，继续后续信息采集/关联')
    } else if (result.password_submitted) {
      ElMessage.success(result.session_cleared ? '已清理 Apify 会话，并已填写邮箱密码提交注册' : '已填写邮箱密码提交注册')
    } else if (result.email_submitted) {
      ElMessage.warning('已填写邮箱并进入密码步骤，但未完成提交，请查看指纹浏览器窗口')
    } else {
      ElMessage.warning('已打开浏览器，但未完成 Apify 注册提交，请查看指纹浏览器窗口')
    }
  } catch {
    /* 拦截器已提示 */
  } finally {
    apifySignupId.value = null
  }
}

async function handleContinueApifySignup(row: EmailAccount) {
  if (linkedApifyKey(row.id)) {
    ElMessage.info('该邮箱已关联 Apify Key')
    return
  }
  if (!row.browser_id) {
    ElMessage.warning('请先为该邮箱选择指纹浏览器')
    return
  }
  apifyContinueId.value = row.id
  try {
    const result = await emailAccountApi.continueApifySignup(row.id)
    if (result.captcha_required) {
      ElMessage.warning('仍检测到图形验证码，请先在指纹浏览器窗口里人工完成验证')
    } else if (result.profile_submitted) {
      ElMessage.success('已用邮箱前缀填写 Apify 注册资料并点击 Continue')
    } else if (result.ready) {
      ElMessage.success('Apify 当前已进入登录后的页面，可继续后续信息采集/关联')
    } else {
      ElMessage.warning('当前还未进入 Apify 登录后页面，请查看指纹浏览器窗口')
    }
  } catch {
    /* 拦截器已提示 */
  } finally {
    apifyContinueId.value = null
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

onMounted(() => {
  load()
  loadBrowserOptions()
  loadApifyKeys()
})
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
        title="用于自动化注册流程：保存注册邮箱、邮箱登录验证用的备用 Webmail 和对应指纹浏览器；注册结果通过各平台管理表的关联记录判断。"
      />
      <el-form :inline="true" @submit.prevent="load">
        <el-form-item label="关键词">
          <el-input
            v-model="filters.q"
            clearable
            placeholder="注册邮箱 / 验证邮箱"
            style="width: 280px"
            @keyup.enter="load"
          />
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
      <el-table-column label="指纹浏览器" min-width="130">
        <template #default="{ row }">
          <div v-if="row.browser_id">
            <el-text tag="div">{{ browserName(row.browser_id) }}</el-text>
            <el-text tag="div" type="info" size="small">{{ row.browser_id }}</el-text>
          </div>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="注册关联" min-width="220">
        <template #default="{ row }">
          <div v-if="linkedApifyKey(row.id)">
            <el-tag type="success" effect="dark">Apify 已关联</el-tag>
            <el-text tag="div" style="margin-top: 4px">
              {{ linkedApifyKey(row.id)?.apify_username || linkedApifyKey(row.id)?.label }}
            </el-text>
            <el-text tag="div" type="info" size="small">
              {{ linkedApifyKey(row.id)?.apify_user_id || '未记录 User ID' }}
            </el-text>
          </div>
          <el-tag v-else type="info" effect="plain">未关联</el-tag>
        </template>
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
      <el-table-column label="操作" width="380" fixed="right" align="center">
        <template #default="{ row }">
          <el-button
            size="small"
            type="success"
            :loading="apifySignupId === row.id"
            :disabled="!canStartApifySignup(row)"
            @click="handleStartApifySignup(row)"
          >Apify 注册</el-button>
          <el-button
            size="small"
            type="warning"
            plain
            :loading="apifyContinueId === row.id"
            :disabled="!canContinueApifySignup(row)"
            @click="handleContinueApifySignup(row)"
          >继续注册</el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
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
          <el-input v-model="form.email" placeholder="用于自动化注册流程的邮箱" maxlength="255" />
        </el-form-item>
        <el-form-item label="邮箱密码">
          <el-input v-model="form.email_password" show-password placeholder="邮箱登录密码" maxlength="500" />
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

        <el-divider content-position="left">浏览器环境</el-divider>
        <el-form-item label="指纹浏览器ID">
          <el-select
            v-model="form.browser_id"
            filterable
            clearable
            placeholder="从系统登记里选择可用环境"
            style="width: 100%"
          >
            <el-option
              v-for="item in browserOptions"
              :key="item.browser_id"
              :label="browserLabel(item)"
              :value="item.browser_id"
            >
              <div style="display: flex; justify-content: space-between; gap: 12px">
                <span>{{ browserLabel(item) }}</span>
                <el-text type="info" size="small">{{ item.browser_id }}</el-text>
              </div>
            </el-option>
          </el-select>
          <div style="margin-top: 6px">
            <el-text type="info" size="small">
              数据来自「比特抓取 → 系统登记」，仅显示当前本机列表中仍可用的环境。
            </el-text>
            <el-button link size="small" @click="loadBrowserOptions">刷新可选环境</el-button>
          </div>
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
