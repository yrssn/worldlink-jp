<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { systemApi, type ApiEnforceMode, type Menu, type MenuTree, type MenuType } from '@/api/system'

const tree = ref<MenuTree[]>([])
const flat = ref<Menu[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref<Menu | null>(null)

const form = reactive({
  code: '',
  title: '',
  parent_id: null as number | null,
  path: '',
  icon: '',
  sort_order: 0,
  type: 'menu' as MenuType,
  is_hidden: false,
  is_active: true,
  api_prefixes: '',
  api_enforce_mode: 'all' as ApiEnforceMode,
  remark: ''
})

const catalogs = computed(() => flat.value.filter((m) => m.type === 'catalog'))

async function refresh() {
  loading.value = true
  try {
    const [t, f] = await Promise.all([systemApi.menuTree(), systemApi.listMenus()])
    tree.value = t
    flat.value = f
  } finally {
    loading.value = false
  }
}

function openCreate(parent?: MenuTree) {
  editing.value = null
  form.code = ''
  form.title = ''
  form.parent_id = parent ? parent.id : null
  form.path = ''
  form.icon = ''
  form.sort_order = 0
  form.type = parent ? 'menu' : 'catalog'
  form.is_hidden = false
  form.is_active = true
  form.api_prefixes = ''
  form.api_enforce_mode = 'all'
  form.remark = ''
  dialogVisible.value = true
}

function openEdit(row: Menu) {
  editing.value = row
  form.code = row.code
  form.title = row.title
  form.parent_id = row.parent_id
  form.path = row.path || ''
  form.icon = row.icon || ''
  form.sort_order = row.sort_order
  form.type = row.type
  form.is_hidden = row.is_hidden
  form.is_active = row.is_active
  form.api_prefixes = (row.api_prefixes || []).join('\n')
  form.api_enforce_mode = row.api_enforce_mode
  form.remark = row.remark || ''
  dialogVisible.value = true
}

function payload() {
  return {
    title: form.title.trim(),
    parent_id: form.parent_id,
    path: form.path.trim() || null,
    icon: form.icon.trim() || null,
    sort_order: form.sort_order,
    type: form.type,
    is_hidden: form.is_hidden,
    is_active: form.is_active,
    api_prefixes: form.api_prefixes
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean),
    api_enforce_mode: form.api_enforce_mode,
    remark: form.remark.trim() || null
  }
}

async function submitForm() {
  if (!form.title.trim()) {
    ElMessage.warning('请填写菜单名称')
    return
  }
  try {
    if (editing.value) {
      await systemApi.updateMenu(editing.value.id, payload())
      ElMessage.success('已更新')
    } else {
      if (form.code.trim().length < 2) {
        ElMessage.warning('请填写权限编码（如 scraper:tasks）')
        return
      }
      await systemApi.createMenu({ code: form.code.trim(), ...payload() })
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    await refresh()
  } catch {
    /* 拦截器已提示 */
  }
}

async function remove(row: Menu) {
  try {
    await ElMessageBox.confirm(`确认删除路由「${row.title}」？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    await systemApi.deleteMenu(row.id)
    ElMessage.success('已删除')
    await refresh()
  } catch {
    /* 拦截器已提示 */
  }
}

const enforceText: Record<ApiEnforceMode, string> = {
  all: '读写都校验',
  write: '只校验写操作',
  off: '不校验接口'
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
        title="权限编码需与前端路由 meta.code 一致；接口前缀用于后端同步校验（前端隐藏不等于安全）。"
        style="max-width: 720px"
      />
      <el-button type="primary" @click="openCreate()">新建路由</el-button>
    </div>

    <el-table
      v-loading="loading"
      :data="tree"
      row-key="id"
      default-expand-all
      :tree-props="{ children: 'children' }"
      border
    >
      <el-table-column prop="title" label="名称" min-width="180" />
      <el-table-column prop="code" label="权限编码" min-width="170" />
      <el-table-column prop="path" label="前端路径" min-width="180" />
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.type === 'catalog' ? 'info' : 'primary'">
            {{ row.type === 'catalog' ? '目录' : '页面' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="接口前缀" min-width="220">
        <template #default="{ row }">
          <div v-for="p in row.api_prefixes" :key="p" style="font-size: 12px; color: #666">
            {{ p }}
          </div>
          <span v-if="!row.api_prefixes?.length" style="color: #bbb">—</span>
        </template>
      </el-table-column>
      <el-table-column label="接口校验" width="120">
        <template #default="{ row }">{{ enforceText[row.api_enforce_mode as ApiEnforceMode] }}</template>
      </el-table-column>
      <el-table-column label="状态" width="140">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
          <el-tag v-if="row.is_hidden" size="small" type="info" style="margin-left: 4px">隐藏</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="190" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="row.type === 'catalog'" link type="primary" @click="openCreate(row)">
            加子项
          </el-button>
          <el-button v-if="!row.is_builtin" link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="editing ? `编辑路由：${editing.title}` : '新建路由'"
      width="620px"
    >
      <el-form label-width="110px">
        <el-form-item label="权限编码">
          <el-input
            v-model="form.code"
            :disabled="!!editing && editing.is_builtin"
            placeholder="如 scraper:tasks"
          />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="form.title" />
        </el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="form.type">
            <el-radio value="catalog">目录</el-radio>
            <el-radio value="menu">页面</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="上级目录">
          <el-select v-model="form.parent_id" clearable style="width: 100%">
            <el-option
              v-for="c in catalogs"
              :key="c.id"
              :label="`${c.title}（${c.code}）`"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="前端路径">
          <el-input v-model="form.path" placeholder="如 /scraper/tasks" />
        </el-form-item>
        <el-form-item label="图标">
          <el-input v-model="form.icon" placeholder="Element Plus 图标名，如 Search" />
        </el-form-item>
        <el-form-item label="接口前缀">
          <el-input
            v-model="form.api_prefixes"
            type="textarea"
            :rows="3"
            placeholder="每行一个，如 /api/v1/scraper/tasks"
          />
        </el-form-item>
        <el-form-item label="接口校验">
          <el-select v-model="form.api_enforce_mode" style="width: 100%">
            <el-option label="读写都校验" value="all" />
            <el-option label="只校验写操作（读接口放开给其他页面引用）" value="write" />
            <el-option label="不校验接口（仅前端路由）" value="off" />
          </el-select>
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort_order" :min="0" />
        </el-form-item>
        <el-form-item label="菜单显示">
          <el-switch v-model="form.is_hidden" active-text="不在侧边栏显示" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.is_active" active-text="启用" inactive-text="停用" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
