<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { bitbrowserApi, type BitBrowserPlatform } from '@/api/bitbrowser'

const list = ref<BitBrowserPlatform[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)

const form = reactive({
  name: '',
  code: '',
  remark: '',
  sort_order: 0
})

async function refresh() {
  loading.value = true
  try {
    list.value = await bitbrowserApi.listPlatforms()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.name = ''
  form.code = ''
  form.remark = ''
  form.sort_order = 0
  dialogVisible.value = true
}

function openEdit(row: BitBrowserPlatform) {
  editingId.value = row.id
  form.name = row.name
  form.code = row.code || ''
  form.remark = row.remark || ''
  form.sort_order = row.sort_order
  dialogVisible.value = true
}

async function submitForm() {
  const name = form.name.trim()
  if (!name) {
    ElMessage.warning('请填写平台名称')
    return
  }
  try {
    if (editingId.value == null) {
      await bitbrowserApi.createPlatform({
        name,
        code: form.code.trim() || undefined,
        remark: form.remark.trim() || undefined,
        sort_order: form.sort_order
      })
      ElMessage.success('已创建')
    } else {
      await bitbrowserApi.updatePlatform(editingId.value, {
        name,
        code: form.code.trim() || null,
        remark: form.remark.trim() || null,
        sort_order: form.sort_order
      })
      ElMessage.success('已更新')
    }
    dialogVisible.value = false
    await refresh()
  } catch {
    /* http 拦截器已提示 */
  }
}

async function removeRow(row: BitBrowserPlatform) {
  try {
    await ElMessageBox.confirm(`确定删除平台「${row.name}」？已归类的窗口将变为「不归类」。`, '删除', {
      type: 'warning'
    })
    await bitbrowserApi.deletePlatform(row.id)
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
        <h3 style="margin: 0 0 6px 0">平台管理</h3>
        <p style="margin: 0; font-size: 12px; color: #666">
          「比特抓取」模块之一：自建业务平台（如 Instagram、小红书），用于在「浏览器窗口」里给环境做分类；与 BitBrowser 里每条环境的「平台」字段无关。使用前请先在
          <router-link to="/bitbrowser/connect">本机连接</router-link>
          配置 Local API。
        </p>
      </div>
      <el-button type="primary" @click="openCreate">新建平台</el-button>
    </div>

    <el-table v-loading="loading" :data="list" border stripe>
      <el-table-column prop="sort_order" label="排序" width="80" />
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="code" label="代码" width="120" show-overflow-tooltip />
      <el-table-column prop="remark" label="备注" min-width="200" show-overflow-tooltip />
      <el-table-column prop="updated_at" label="更新时间" width="170" />
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="removeRow(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && !list.length" description="暂无平台，请点击「新建平台」" style="margin-top: 24px" />

    <el-dialog v-model="dialogVisible" :title="editingId == null ? '新建平台' : '编辑平台'" width="520px" destroy-on-close>
      <el-form label-width="100px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" maxlength="128" show-word-limit placeholder="如 Instagram" />
        </el-form-item>
        <el-form-item label="代码">
          <el-input v-model="form.code" maxlength="64" placeholder="可选，如 ig" />
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
