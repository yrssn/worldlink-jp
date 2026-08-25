<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { countryApi, type Country } from '@/api/country'

const list = ref<Country[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)

const form = reactive({
  name_zh: '',
  name_en: '',
  code: '',
  remark: '',
  sort_order: 0
})

async function refresh() {
  loading.value = true
  try {
    list.value = await countryApi.list()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.name_zh = ''
  form.name_en = ''
  form.code = ''
  form.remark = ''
  form.sort_order = 0
  dialogVisible.value = true
}

function openEdit(row: Country) {
  editingId.value = row.id
  form.name_zh = row.name_zh
  form.name_en = row.name_en || ''
  form.code = row.code || ''
  form.remark = row.remark || ''
  form.sort_order = row.sort_order
  dialogVisible.value = true
}

async function submitForm() {
  const nameZh = form.name_zh.trim()
  if (!nameZh) {
    ElMessage.warning('请填写中文名')
    return
  }
  const payload = {
    name_zh: nameZh,
    name_en: form.name_en.trim() || null,
    code: form.code.trim() || null,
    remark: form.remark.trim() || null,
    sort_order: form.sort_order
  }
  try {
    if (editingId.value == null) {
      await countryApi.create(payload)
      ElMessage.success('已创建')
    } else {
      await countryApi.update(editingId.value, payload)
      ElMessage.success('已更新')
    }
    dialogVisible.value = false
    await refresh()
  } catch {
    /* http 拦截器已提示 */
  }
}

async function removeRow(row: Country) {
  try {
    await ElMessageBox.confirm(
      `确定删除国家「${row.name_zh}」？已关联该国家的达人会变为「未关联」。`,
      '删除',
      { type: 'warning' }
    )
    await countryApi.remove(row.id)
    ElMessage.success('已删除')
    await refresh()
  } catch {
    /* 取消或失败 */
  }
}

onMounted(refresh)
</script>

<template>
  <div class="page-card">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px">
      <div>
        <h3 style="margin: 0 0 6px 0">国家管理</h3>
        <p style="margin: 0; font-size: 12px; color: #666">
          国家字典（团队共享）：中英文各存一份，代码建议用 ISO 两位写法（JP / US / TW）。「建联达人」的国家列从这里选，改这里的名称/代码，达人列表和导出会跟着变。
        </p>
      </div>
      <el-button type="primary" @click="openCreate">新建国家</el-button>
    </div>

    <el-table v-loading="loading" :data="list" border stripe>
      <el-table-column prop="sort_order" label="排序" width="80" />
      <el-table-column prop="name_zh" label="中文名" min-width="140" />
      <el-table-column prop="name_en" label="英文名" min-width="160" show-overflow-tooltip />
      <el-table-column prop="code" label="代码" width="100" />
      <el-table-column prop="remark" label="备注" min-width="200" show-overflow-tooltip />
      <el-table-column prop="updated_at" label="更新时间" width="170" />
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="removeRow(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && !list.length" description="暂无国家，请点击「新建国家」" style="margin-top: 24px" />

    <el-dialog
      v-model="dialogVisible"
      :title="editingId == null ? '新建国家' : '编辑国家'"
      width="520px"
      destroy-on-close
    >
      <el-form label-width="100px">
        <el-form-item label="中文名" required>
          <el-input v-model="form.name_zh" maxlength="128" show-word-limit placeholder="如 日本" />
        </el-form-item>
        <el-form-item label="英文名">
          <el-input v-model="form.name_en" maxlength="128" placeholder="如 Japan" />
        </el-form-item>
        <el-form-item label="代码">
          <el-input v-model="form.code" maxlength="16" placeholder="如 JP" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort_order" :min="0" :max="9999" />
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
