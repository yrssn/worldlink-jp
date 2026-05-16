<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { promptApi, type PromptTemplate } from '@/api/llm'

const list = ref<PromptTemplate[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const isEdit = ref(false)
const editing = ref<Partial<PromptTemplate> & { keywordsText?: string }>({})

async function refresh() {
  loading.value = true
  try {
    list.value = await promptApi.list()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  isEdit.value = false
  editing.value = {
    name: '',
    description: '',
    system_prompt: '你是一个达人/KOL 筛选助手，请根据提供的关键词和过滤规则，对帖子进行评估。',
    keywordsText: '',
    filter_rules: { min_followers: 0, min_likes: 0, min_comments: 0 },
    output_schema: { passed: 'boolean', score: 'float', reason: 'string' },
    is_active: true
  }
  dialogVisible.value = true
}

function openEdit(row: PromptTemplate) {
  isEdit.value = true
  editing.value = {
    ...row,
    keywordsText: (row.keywords || []).join(',')
  }
  dialogVisible.value = true
}

async function save() {
  if (!editing.value.name || !editing.value.system_prompt) {
    ElMessage.warning('请填写名称和系统提示词')
    return
  }
  const data: Partial<PromptTemplate> = {
    name: editing.value.name,
    description: editing.value.description,
    system_prompt: editing.value.system_prompt,
    keywords: (editing.value.keywordsText || '')
      .split(/[,，\n]/)
      .map((s) => s.trim())
      .filter(Boolean),
    filter_rules: editing.value.filter_rules,
    output_schema: editing.value.output_schema,
    is_active: editing.value.is_active
  }
  if (isEdit.value && editing.value.id) {
    await promptApi.update(editing.value.id, data)
  } else {
    await promptApi.create(data)
  }
  ElMessage.success('已保存')
  dialogVisible.value = false
  refresh()
}

async function remove(row: PromptTemplate) {
  await ElMessageBox.confirm(`确认删除「${row.name}」？`, '提示', { type: 'warning' })
  await promptApi.remove(row.id)
  ElMessage.success('已删除')
  refresh()
}

onMounted(refresh)
</script>

<template>
  <div class="page-card">
    <div style="display: flex; justify-content: space-between; margin-bottom: 12px">
      <h3 style="margin: 0">提示词模板（关键词配置）</h3>
      <el-button type="primary" @click="openCreate">新增模板</el-button>
    </div>
    <el-table v-loading="loading" :data="list" border>
      <el-table-column prop="name" label="名称" width="180" />
      <el-table-column prop="description" label="描述" />
      <el-table-column label="关键词">
        <template #default="{ row }">
          <el-tag v-for="k in row.keywords" :key="k" size="small" style="margin-right: 4px">
            {{ k }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="启用" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="row.is_active ? 'success' : 'info'">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="170">
        <template #default="{ row }">
          <el-button size="small" type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑模板' : '新增模板'" width="720px">
      <el-form :model="editing" label-width="120px">
        <el-form-item label="名称">
          <el-input v-model="editing.name" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editing.description" />
        </el-form-item>
        <el-form-item label="系统提示词">
          <el-input v-model="editing.system_prompt" type="textarea" :rows="6" />
        </el-form-item>
        <el-form-item label="关键词">
          <el-input
            v-model="editing.keywordsText"
            type="textarea"
            :rows="2"
            placeholder="多个关键词用英文逗号、中文逗号或换行分隔"
          />
        </el-form-item>
        <el-form-item label="过滤规则(JSON)">
          <el-input
            :model-value="JSON.stringify(editing.filter_rules || {}, null, 2)"
            type="textarea"
            :rows="4"
            @update:model-value="
              (v: string) => {
                try { editing.filter_rules = JSON.parse(v) } catch (e) {}
              }
            "
          />
        </el-form-item>
        <el-form-item label="输出 Schema(JSON)">
          <el-input
            :model-value="JSON.stringify(editing.output_schema || {}, null, 2)"
            type="textarea"
            :rows="3"
            @update:model-value="
              (v: string) => {
                try { editing.output_schema = JSON.parse(v) } catch (e) {}
              }
            "
          />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="editing.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
