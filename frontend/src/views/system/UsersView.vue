<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { systemApi, type Role, type SysUser } from '@/api/system'

const list = ref<SysUser[]>([])
const roles = ref<Role[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const pwdVisible = ref(false)
const editing = ref<SysUser | null>(null)
const pwdTarget = ref<SysUser | null>(null)
const newPassword = ref('')

const form = reactive({
  username: '',
  password: '',
  email: '',
  full_name: '',
  is_active: true,
  role_ids: [] as number[],
  dedupe_against_user_ids: [] as number[]
})

async function refresh() {
  loading.value = true
  try {
    const [u, r] = await Promise.all([systemApi.listUsers(), systemApi.listRoles()])
    list.value = u
    roles.value = r
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  form.username = ''
  form.password = ''
  form.email = ''
  form.full_name = ''
  form.is_active = true
  form.role_ids = []
  form.dedupe_against_user_ids = []
  dialogVisible.value = true
}

function openEdit(row: SysUser) {
  editing.value = row
  form.username = row.username
  form.password = ''
  form.email = row.email || ''
  form.full_name = row.full_name || ''
  form.is_active = row.is_active
  form.role_ids = row.roles.map((r) => r.id)
  form.dedupe_against_user_ids = [...(row.dedupe_against_user_ids || [])]
  dialogVisible.value = true
}

async function submitForm() {
  try {
    if (editing.value) {
      await systemApi.updateUser(editing.value.id, {
        email: form.email.trim() || null,
        full_name: form.full_name.trim() || null,
        is_active: form.is_active,
        role_ids: form.role_ids,
        dedupe_against_user_ids: form.dedupe_against_user_ids
      })
      ElMessage.success('已更新')
    } else {
      if (form.username.trim().length < 3) {
        ElMessage.warning('登录名至少 3 位')
        return
      }
      if (form.password.length < 6) {
        ElMessage.warning('密码至少 6 位')
        return
      }
      await systemApi.createUser({
        username: form.username.trim(),
        password: form.password,
        email: form.email.trim() || null,
        full_name: form.full_name.trim() || null,
        is_active: form.is_active,
        role_ids: form.role_ids,
        dedupe_against_user_ids: form.dedupe_against_user_ids
      })
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    await refresh()
  } catch {
    /* 拦截器已提示 */
  }
}

function openReset(row: SysUser) {
  pwdTarget.value = row
  newPassword.value = randomPassword()
  pwdVisible.value = true
}

function randomPassword(len = 12) {
  const chars = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#%'
  const buf = new Uint32Array(len)
  crypto.getRandomValues(buf)
  return Array.from(buf, (n) => chars[n % chars.length]).join('')
}

async function submitReset() {
  if (!pwdTarget.value) return
  if (newPassword.value.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  try {
    await systemApi.resetPassword(pwdTarget.value.id, newPassword.value)
    ElMessage.success('已重置，请把新密码告知该用户')
    pwdVisible.value = false
  } catch {
    /* 拦截器已提示 */
  }
}

async function toggleActive(row: SysUser) {
  const next = !row.is_active
  try {
    await ElMessageBox.confirm(
      next ? `确认启用 ${row.username}？` : `确认停用 ${row.username}？停用后无法登录，历史数据保留。`,
      '提示'
    )
  } catch {
    return
  }
  try {
    await systemApi.updateUser(row.id, { is_active: next })
    ElMessage.success(next ? '已启用' : '已停用')
    await refresh()
  } catch {
    /* 拦截器已提示 */
  }
}

function hasAllScope(row: SysUser) {
  return row.roles.some((r) => r.data_scope === 'all')
}

onMounted(refresh)
</script>

<template>
  <div>
    <div style="margin-bottom: 12px; display: flex; justify-content: space-between">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="停用代替删除：业务数据以 owner_id 关联用户，物理删除会级联删除数据。"
        style="max-width: 620px"
      />
      <el-button type="primary" @click="openCreate">新建用户</el-button>
    </div>

    <el-table v-loading="loading" :data="list" border stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="username" label="登录名" width="150" />
      <el-table-column prop="full_name" label="姓名" width="130" />
      <el-table-column prop="email" label="邮箱" min-width="180" />
      <el-table-column label="角色" min-width="200">
        <template #default="{ row }">
          <el-tag
            v-for="r in row.roles"
            :key="r.id"
            size="small"
            :type="r.data_scope === 'all' ? 'warning' : 'info'"
            style="margin-right: 6px"
          >
            {{ r.name }}
          </el-tag>
          <span v-if="!row.roles.length" style="color: #999">未分配</span>
        </template>
      </el-table-column>
      <el-table-column label="数据范围" width="110">
        <template #default="{ row }">
          <el-tag v-if="hasAllScope(row)" type="warning" size="small">全部数据</el-tag>
          <el-tag v-else size="small">仅本人</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="primary" @click="openReset(row)">重置密码</el-button>
          <el-button link :type="row.is_active ? 'danger' : 'success'" @click="toggleActive(row)">
            {{ row.is_active ? '停用' : '启用' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="editing ? `编辑用户：${editing.username}` : '新建用户'"
      width="520px"
    >
      <el-form label-width="90px">
        <el-form-item label="登录名">
          <el-input v-model="form.username" :disabled="!!editing" placeholder="登录名" />
        </el-form-item>
        <el-form-item v-if="!editing" label="密码">
          <el-input v-model="form.password" type="password" show-password />
          <el-button link type="primary" @click="form.password = randomPassword()">
            生成随机密码
          </el-button>
          <span v-if="form.password" style="margin-left: 8px; color: #999">
            {{ form.password }}
          </span>
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="form.full_name" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role_ids" multiple style="width: 100%">
            <el-option v-for="r in roles" :key="r.id" :label="r.name" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="链接对照">
          <div style="width: 100%">
            <el-select
              v-model="form.dedupe_against_user_ids"
              multiple
              filterable
              clearable
              collapse-tags
              collapse-tags-tooltip
              style="width: 100%"
              placeholder="不选 = 不做区分"
            >
              <el-option
                v-for="u in list.filter((x) => x.id !== editing?.id)"
                :key="u.id"
                :value="u.id"
                :label="u.full_name ? `${u.username}（${u.full_name}）` : u.username"
              />
            </el-select>
            <div style="color: #909399; font-size: 12px; line-height: 1.5; margin-top: 4px">
              该用户导入 / 批量导入链接时，主页链接已在所选账号名下的行会被区别开：不入库、不抓取，并标出是和哪个账号重复。
            </div>
          </div>
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.is_active" active-text="启用" inactive-text="停用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="pwdVisible" title="重置密码" width="440px">
      <el-form label-width="90px">
        <el-form-item label="新密码">
          <el-input v-model="newPassword" />
        </el-form-item>
        <el-form-item>
          <el-button link type="primary" @click="newPassword = randomPassword()">
            重新生成
          </el-button>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" @click="submitReset">确认重置</el-button>
      </template>
    </el-dialog>
  </div>
</template>
