<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { systemApi, type MenuDataScope, type MenuTree, type Role, type SysUser } from '@/api/system'

const list = ref<Role[]>([])
const menuTree = ref<MenuTree[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref<Role | null>(null)
const treeRef = ref()
const users = ref<SysUser[]>([])
/** 按路由单独放宽的数据范围（key = 菜单 code） */
const menuScopes = ref<Record<string, MenuDataScope>>({})

const form = reactive({
  code: '',
  name: '',
  remark: '',
  data_scope: 'own' as 'own' | 'all',
  is_active: true,
  sort_order: 0
})

const treeProps = { label: 'title', children: 'children' }

async function refresh() {
  loading.value = true
  try {
    const [r, t, u] = await Promise.all([
      systemApi.listRoles(),
      systemApi.menuTree(),
      systemApi.listUsers().catch(() => [] as SysUser[])
    ])
    list.value = r
    menuTree.value = t
    users.value = u
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  form.code = ''
  form.name = ''
  form.remark = ''
  form.data_scope = 'own'
  form.is_active = true
  form.sort_order = 0
  menuScopes.value = {}
  dialogVisible.value = true
  setCheckedLater([])
}

function openEdit(row: Role) {
  editing.value = row
  form.code = row.code
  form.name = row.name
  form.remark = row.remark || ''
  form.data_scope = row.data_scope
  form.is_active = row.is_active
  form.sort_order = row.sort_order
  menuScopes.value = JSON.parse(JSON.stringify(row.menu_data_scopes || {}))
  dialogVisible.value = true
  setCheckedLater(row.menu_ids)
}

/** el-tree 在弹窗渲染后才存在，等一帧再回填勾选 */
function setCheckedLater(ids: number[]) {
  requestAnimationFrame(() => treeRef.value?.setCheckedKeys(ids, false))
}

function checkedMenuIds(): number[] {
  if (!treeRef.value) return []
  const checked: number[] = treeRef.value.getCheckedKeys(false)
  const half: number[] = treeRef.value.getHalfCheckedKeys()
  // 半选的父级目录也要授予，否则菜单树会缺少上级入口
  return [...new Set([...checked, ...half])]
}

/** 只有带 path 的叶子路由才能单独配数据范围 */
function leafMenus(nodes: MenuTree[]): MenuTree[] {
  const out: MenuTree[] = []
  for (const n of nodes) {
    if (n.children?.length) out.push(...leafMenus(n.children))
    else if (n.path) out.push(n)
  }
  return out
}

function scopeOf(code: string): 'own' | 'all' | 'users' {
  return menuScopes.value[code]?.scope || 'own'
}

function setScope(code: string, v: 'own' | 'all' | 'users') {
  if (v === 'own') {
    delete menuScopes.value[code]
    return
  }
  const prev = menuScopes.value[code]
  menuScopes.value[code] = { scope: v, user_ids: v === 'users' ? prev?.user_ids || [] : [] }
}

function setScopeUsers(code: string, ids: number[]) {
  menuScopes.value[code] = { scope: 'users', user_ids: ids }
}

function cleanedMenuScopes(): Record<string, MenuDataScope> | null {
  const out: Record<string, MenuDataScope> = {}
  for (const [code, v] of Object.entries(menuScopes.value)) {
    if (v.scope === 'all') out[code] = { scope: 'all', user_ids: [] }
    else if (v.scope === 'users' && v.user_ids.length) out[code] = { scope: 'users', user_ids: v.user_ids }
  }
  return Object.keys(out).length ? out : null
}

async function submitForm() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写角色名称')
    return
  }
  try {
    if (editing.value) {
      await systemApi.updateRole(editing.value.id, {
        name: form.name.trim(),
        remark: form.remark.trim() || null,
        data_scope: form.data_scope,
        menu_data_scopes: cleanedMenuScopes(),
        is_active: form.is_active,
        sort_order: form.sort_order,
        menu_ids: checkedMenuIds()
      })
      ElMessage.success('已更新')
    } else {
      if (form.code.trim().length < 2) {
        ElMessage.warning('请填写角色编码（英文，至少 2 位）')
        return
      }
      await systemApi.createRole({
        code: form.code.trim(),
        name: form.name.trim(),
        remark: form.remark.trim() || null,
        data_scope: form.data_scope,
        menu_data_scopes: cleanedMenuScopes(),
        is_active: form.is_active,
        sort_order: form.sort_order,
        menu_ids: checkedMenuIds()
      })
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    await refresh()
  } catch {
    /* 拦截器已提示 */
  }
}

async function remove(row: Role) {
  try {
    await ElMessageBox.confirm(`确认删除角色「${row.name}」？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    await systemApi.deleteRole(row.id)
    ElMessage.success('已删除')
    await refresh()
  } catch {
    /* 拦截器已提示 */
  }
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
        title="角色决定「能进哪些路由」和「能看谁的数据」；超级管理员固定拥有全部路由与全部数据。"
        style="max-width: 680px"
      />
      <el-button type="primary" @click="openCreate">新建角色</el-button>
    </div>

    <el-table v-loading="loading" :data="list" border stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="角色名称" width="160" />
      <el-table-column prop="code" label="编码" width="160" />
      <el-table-column label="数据范围" width="120">
        <template #default="{ row }">
          <el-tag :type="row.data_scope === 'all' ? 'warning' : 'info'" size="small">
            {{ row.data_scope === 'all' ? '全部数据' : '仅本人创建' }}
          </el-tag>
          <el-tag
            v-if="row.menu_data_scopes && Object.keys(row.menu_data_scopes).length"
            size="small"
            type="success"
            style="margin-left: 4px"
          >
            {{ Object.keys(row.menu_data_scopes).length }} 条路由放宽
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="路由数" width="90">
        <template #default="{ row }">{{ row.menu_ids.length }}</template>
      </el-table-column>
      <el-table-column prop="user_count" label="用户数" width="90" />
      <el-table-column prop="remark" label="备注" min-width="200" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="170" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">配置权限</el-button>
          <el-button v-if="!row.is_builtin" link type="danger" @click="remove(row)">删除</el-button>
          <el-tag v-else size="small" type="info">内置</el-tag>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="editing ? `配置角色：${editing.name}` : '新建角色'"
      width="640px"
    >
      <el-form label-width="90px">
        <el-form-item label="角色编码">
          <el-input v-model="form.code" :disabled="!!editing" placeholder="如 operator" />
        </el-form-item>
        <el-form-item label="角色名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="数据范围">
          <el-radio-group v-model="form.data_scope">
            <el-radio value="own">仅本人创建（公共配置模块仍共享）</el-radio>
            <el-radio value="all">全部数据</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.data_scope === 'own'" label="按路由放宽">
          <div style="width: 100%">
            <div style="color: #909399; font-size: 12px; margin-bottom: 6px">
              只对下面单独设置的路由生效：可让该角色在某个路由下看到全部人、或指定几个账号的数据；其余路由仍只看本人。
            </div>
            <el-table :data="leafMenus(menuTree)" size="small" border max-height="260">
              <el-table-column prop="title" label="路由" min-width="140" />
              <el-table-column label="数据范围" width="150">
                <template #default="{ row }">
                  <el-select
                    :model-value="scopeOf(row.code)"
                    size="small"
                    @update:model-value="(v: 'own' | 'all' | 'users') => setScope(row.code, v)"
                  >
                    <el-option value="own" label="仅本人" />
                    <el-option value="all" label="全部数据" />
                    <el-option value="users" label="指定账号" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="可看的账号" min-width="220">
                <template #default="{ row }">
                  <el-select
                    v-if="scopeOf(row.code) === 'users'"
                    :model-value="menuScopes[row.code]?.user_ids || []"
                    multiple
                    filterable
                    collapse-tags
                    collapse-tags-tooltip
                    size="small"
                    style="width: 100%"
                    placeholder="选择系统账号"
                    @update:model-value="(ids: number[]) => setScopeUsers(row.code, ids)"
                  >
                    <el-option
                      v-for="u in users"
                      :key="u.id"
                      :value="u.id"
                      :label="u.full_name ? `${u.username}（${u.full_name}）` : u.username"
                    />
                  </el-select>
                  <span v-else style="color: #c0c4cc">—</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort_order" :min="0" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.is_active" active-text="启用" inactive-text="停用" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="路由权限">
          <el-tree
            ref="treeRef"
            :data="menuTree"
            :props="treeProps"
            node-key="id"
            show-checkbox
            default-expand-all
            style="width: 100%; max-height: 320px; overflow: auto; border: 1px solid #eee"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
