<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { llmApi, type LlmProvider, type LlmProviderType } from '@/api/llm'

const list = ref<LlmProvider[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref<Partial<LlmProvider> & { api_key?: string }>({})
const isEdit = ref(false)
const testing = ref<number | null>(null)

const PROVIDER_OPTIONS: { label: string; value: LlmProviderType }[] = [
  { label: 'OpenAI', value: 'openai' },
  { label: 'Azure OpenAI', value: 'azure_openai' },
  { label: 'DeepSeek', value: 'deepseek' },
  { label: 'Claude', value: 'claude' },
  { label: '通义千问 Qwen', value: 'qwen' },
  { label: 'Ollama', value: 'ollama' },
  { label: '自定义(OpenAI 兼容)', value: 'custom' }
]

async function refresh() {
  loading.value = true
  try {
    list.value = await llmApi.list()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  isEdit.value = false
  editing.value = {
    provider: 'openai',
    model: 'gpt-4o-mini',
    temperature: 0.2,
    enabled: true,
    is_default: false
  }
  dialogVisible.value = true
}

function openEdit(row: LlmProvider) {
  isEdit.value = true
  editing.value = { ...row, api_key: '' }
  dialogVisible.value = true
}

async function save() {
  const data = { ...editing.value }
  if (!data.name || !data.provider || !data.model) {
    ElMessage.warning('请填写名称 / 厂商 / 模型')
    return
  }
  if (isEdit.value && data.id) {
    if (!data.api_key) delete data.api_key
    await llmApi.update(data.id, data)
  } else {
    await llmApi.create(data)
  }
  dialogVisible.value = false
  ElMessage.success('已保存')
  refresh()
}

async function remove(row: LlmProvider) {
  await ElMessageBox.confirm(`确认删除「${row.name}」？`, '提示', { type: 'warning' })
  await llmApi.remove(row.id)
  ElMessage.success('已删除')
  refresh()
}

async function testIt(row: LlmProvider) {
  testing.value = row.id
  try {
    const r = await llmApi.test(row.id, '你好，请用一句话介绍你自己。')
    if (r.ok) ElMessage.success(`连通成功：${(r.output || '').slice(0, 80)}`)
    else ElMessage.error(`失败：${r.error}`)
  } finally {
    testing.value = null
  }
}

onMounted(refresh)
</script>

<template>
  <div class="page-card">
    <div style="display: flex; justify-content: space-between; margin-bottom: 12px">
      <h3 style="margin: 0">大模型厂商配置</h3>
      <el-button type="primary" @click="openCreate">新增</el-button>
    </div>

    <el-table v-loading="loading" :data="list" border>
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="provider" label="厂商" width="120" />
      <el-table-column prop="model" label="模型" />
      <el-table-column prop="base_url" label="Base URL" />
      <el-table-column prop="temperature" label="Temp" width="80" />
      <el-table-column label="API Key" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="row.has_api_key ? 'success' : 'info'">
            {{ row.has_api_key ? '已设置' : '未设置' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="默认" width="80">
        <template #default="{ row }">
          <el-tag v-if="row.is_default" size="small" type="warning">默认</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="启用" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="row.enabled ? 'success' : 'info'">
            {{ row.enabled ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button size="small" @click="testIt(row)" :loading="testing === row.id">测试</el-button>
          <el-button size="small" type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑大模型' : '新增大模型'" width="560px">
      <el-form :model="editing" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="editing.name" />
        </el-form-item>
        <el-form-item label="厂商">
          <el-select v-model="editing.provider" style="width: 100%">
            <el-option
              v-for="o in PROVIDER_OPTIONS"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="模型名">
          <el-input v-model="editing.model" placeholder="如 gpt-4o-mini / deepseek-chat" />
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="editing.base_url" placeholder="可选，自定义/Azure/Ollama 时填写" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="editing.api_key"
            type="password"
            show-password
            :placeholder="isEdit ? '留空表示不修改' : '请输入 API Key'"
          />
        </el-form-item>
        <el-form-item label="Temperature">
          <el-input-number v-model="editing.temperature" :min="0" :max="2" :step="0.1" />
        </el-form-item>
        <el-form-item label="Max Tokens">
          <el-input-number v-model="editing.max_tokens" :min="1" :max="32000" />
        </el-form-item>
        <el-form-item label="默认">
          <el-switch v-model="editing.is_default" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="editing.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
