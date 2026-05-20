<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { dmApi, type DmCategory } from '@/api/dm'

const list = ref<DmCategory[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)

const form = reactive({
  name: '',
  code: '',
  color: '#409EFF',
  remark: '',
  sort_order: 0,
  is_active: true
})

const presetColors = ['#409EFF', '#67C23A', '#E6A23C', '#F56C6C', '#909399', '#9b59b6', '#1abc9c']

async function refresh() {
  loading.value = true
  try {
    list.value = await dmApi.listCategories()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.name = ''
  form.code = ''
  form.color = '#409EFF'
  form.remark = ''
  form.sort_order = 0
  form.is_active = true
  dialogVisible.value = true
}

function openEdit(row: DmCategory) {
  editingId.value = row.id
  form.name = row.name
  form.code = row.code || ''
  form.color = row.color || '#409EFF'
  form.remark = row.remark || ''
  form.sort_order = row.sort_order
  form.is_active = row.is_active
  dialogVisible.value = true
}

async function submitForm() {
  const name = form.name.trim()
  if (!name) {
    ElMessage.warning('请填写分类名称')
    return
  }
  try {
    const payload = {
      name,
      code: form.code.trim() || undefined,
      color: form.color || undefined,
      remark: form.remark.trim() || undefined,
      sort_order: form.sort_order,
      is_active: form.is_active
    }
    if (editingId.value == null) {
      await dmApi.createCategory(payload)
      ElMessage.success('已创建')
    } else {
      await dmApi.updateCategory(editingId.value, payload)
      ElMessage.success('已更新')
    }
    dialogVisible.value = false
    await refresh()
  } catch {
    /* 拦截器已提示 */
  }
}

async function removeRow(row: DmCategory) {
  try {
    await ElMessageBox.confirm(`确定删除分类「${row.name}」？该分类下的内容将变为「未分类」。`, '删除', {
      type: 'warning'
    })
    await dmApi.deleteCategory(row.id)
    ElMessage.success('已删除')
    await refresh()
  } catch {
    /* 取消 */
  }
}

onMounted(refresh)
</script>

<template>
  <div class="page-card">
    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; gap: 8px">
      <div>
        <h3 style="margin: 0 0 6px 0">私信内容 · 分类管理</h3>
        <p style="margin: 0; font-size: 12px; color: #666">
          为私信模板分组，如「首次触达」「跟进」「活动邀请」等。在
          <router-link to="/dm/contents">内容库</router-link>
          中创建内容时可选择分类。
        </p>
      </div>
      <el-button type="primary" @click="openCreate">新建分类</el-button>
    </div>

    <el-table v-loading="loading" :data="list" border stripe>
      <el-table-column prop="sort_order" label="排序" width="72" align="center" />
      <el-table-column label="名称" min-width="140">
        <template #default="{ row }">
          <el-tag v-if="row.color" :color="row.color" effect="dark" size="small" style="border: none">
            {{ row.name }}
          </el-tag>
          <span v-else>{{ row.name }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="code" label="代码" width="100" show-overflow-tooltip />
      <el-table-column label="状态" width="80" align="center">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="remark" label="备注" min-width="180" show-overflow-tooltip />
      <el-table-column prop="updated_at" label="更新时间" width="170" />
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="removeRow(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && !list.length" description="暂无分类" style="margin-top: 24px" />

    <el-dialog v-model="dialogVisible" :title="editingId == null ? '新建分类' : '编辑分类'" width="520px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" maxlength="128" show-word-limit placeholder="如：首次触达" />
        </el-form-item>
        <el-form-item label="代码">
          <el-input v-model="form.code" maxlength="64" placeholder="可选，如 first_contact" />
        </el-form-item>
        <el-form-item label="标签色">
          <el-color-picker v-model="form.color" />
          <span
            v-for="c in presetColors"
            :key="c"
            class="dm-color-dot"
            :style="{ background: c }"
            @click="form.color = c"
          />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort_order" :min="0" :max="9999" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_active" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="500" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.dm-color-dot {
  display: inline-block;
  width: 18px;
  height: 18px;
  border-radius: 4px;
  margin-left: 8px;
  cursor: pointer;
  vertical-align: middle;
}
</style>
