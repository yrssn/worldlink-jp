<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type UploadAjaxError, type UploadProps, type UploadUserFile } from 'element-plus'
import { dmApi, type DmCategory, type DmContent, type DmImageItem } from '@/api/dm'
import { useAuthStore } from '@/store/auth'

const auth = useAuthStore()
const categories = ref<DmCategory[]>([])
const list = ref<DmContent[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const detailVisible = ref(false)
const editingId = ref<number | null>(null)
const detailRow = ref<DmContent | null>(null)

const filter = reactive({
  category_id: null as number | null | undefined,
  keyword: '',
  active_only: false,
  pinned_only: false
})

const form = reactive({
  category_id: null as number | null,
  title: '',
  summary: '',
  content: '',
  tagsText: '',
  is_active: true,
  is_pinned: false,
  sort_order: 0,
  remark: ''
})

const imageFileList = ref<UploadUserFile[]>([])
const uploading = ref(false)

const categoryMap = computed(() => {
  const m: Record<number, DmCategory> = {}
  for (const c of categories.value) m[c.id] = c
  return m
})

async function loadCategories() {
  try {
    categories.value = await dmApi.listCategories()
  } catch {
    categories.value = []
  }
}

async function refresh() {
  loading.value = true
  try {
    const params: {
      category_id?: number
      keyword?: string
      active_only?: boolean
      pinned_only?: boolean
    } = {}
    if (filter.category_id !== null && filter.category_id !== undefined) {
      params.category_id = filter.category_id
    }
    const kw = filter.keyword.trim()
    if (kw) params.keyword = kw
    if (filter.active_only) params.active_only = true
    if (filter.pinned_only) params.pinned_only = true
    list.value = await dmApi.listContents(params)
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.category_id = null
  form.title = ''
  form.summary = ''
  form.content = ''
  form.tagsText = ''
  form.is_active = true
  form.is_pinned = false
  form.sort_order = 0
  form.remark = ''
  imageFileList.value = []
}

function openCreate() {
  editingId.value = null
  resetForm()
  if (filter.category_id != null && filter.category_id !== undefined) {
    form.category_id = filter.category_id
  }
  dialogVisible.value = true
}

function imagesToFileList(images: DmImageItem[]): UploadUserFile[] {
  return (images || []).map((img, i) => ({
    name: img.name || `image-${i + 1}`,
    url: img.url,
    status: 'success',
    uid: i
  }))
}

function fileListToImages(files: UploadUserFile[]): DmImageItem[] {
  return files
    .filter((f) => f.url)
    .map((f, i) => ({
      url: f.url!,
      path: (f.response as { path?: string } | undefined)?.path,
      name: f.name,
      sort: i
    }))
}

function openEdit(row: DmContent) {
  editingId.value = row.id
  form.category_id = row.category_id ?? null
  form.title = row.title
  form.summary = row.summary || ''
  form.content = row.content
  form.tagsText = (row.tags || []).join(', ')
  form.is_active = row.is_active
  form.is_pinned = row.is_pinned
  form.sort_order = row.sort_order
  form.remark = row.remark || ''
  imageFileList.value = imagesToFileList(row.images || [])
  dialogVisible.value = true
}

function openDetail(row: DmContent) {
  detailRow.value = row
  detailVisible.value = true
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败')
  }
}

const handleUpload: UploadProps['httpRequest'] = async (options) => {
  const file = options.file as File
  uploading.value = true
  try {
    const r = await dmApi.uploadImage(file)
    const item: UploadUserFile = {
      name: r.name,
      url: r.url,
      status: 'success',
      uid: Date.now(),
      response: r
    }
    imageFileList.value = [...imageFileList.value, item]
    options.onSuccess?.(r)
  } catch (e) {
    options.onError?.(e as UploadAjaxError)
  } finally {
    uploading.value = false
  }
}

const beforeUpload: UploadProps['beforeUpload'] = (raw) => {
  if (!raw.type.startsWith('image/')) {
    ElMessage.warning('只能上传图片')
    return false
  }
  if (raw.size > 10 * 1024 * 1024) {
    ElMessage.warning('图片不能超过 10MB')
    return false
  }
  return true
}

function onRemoveImage(_file: UploadUserFile, files: UploadUserFile[]) {
  imageFileList.value = files
}

async function submitForm() {
  const title = form.title.trim()
  const content = form.content.trim()
  if (!title) {
    ElMessage.warning('请填写标题')
    return
  }
  if (!content) {
    ElMessage.warning('请填写私信正文')
    return
  }
  const tags = form.tagsText
    .split(/[,，\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
  const payload = {
    category_id: form.category_id,
    title,
    summary: form.summary.trim() || undefined,
    content,
    images: fileListToImages(imageFileList.value),
    tags,
    is_active: form.is_active,
    is_pinned: form.is_pinned,
    sort_order: form.sort_order,
    remark: form.remark.trim() || undefined
  }
  try {
    if (editingId.value == null) {
      await dmApi.createContent(payload)
      ElMessage.success('已创建')
    } else {
      await dmApi.updateContent(editingId.value, payload)
      ElMessage.success('已更新')
    }
    dialogVisible.value = false
    await refresh()
  } catch {
    /* 拦截器 */
  }
}

async function removeRow(row: DmContent) {
  try {
    await ElMessageBox.confirm(`确定删除「${row.title}」？`, '删除', { type: 'warning' })
    await dmApi.deleteContent(row.id)
    ElMessage.success('已删除')
    await refresh()
  } catch {
    /* 取消 */
  }
}

function categoryLabel(row: DmContent) {
  if (row.category_name) return row.category_name
  if (row.category_id && categoryMap.value[row.category_id]) {
    return categoryMap.value[row.category_id].name
  }
  return '未分类'
}

function categoryColor(row: DmContent) {
  const id = row.category_id
  if (id && categoryMap.value[id]?.color) return categoryMap.value[id].color!
  return undefined
}

onMounted(async () => {
  await loadCategories()
  await refresh()
})
</script>

<template>
  <div class="page-card">
    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; gap: 8px">
      <div>
        <h3 style="margin: 0 0 6px 0">私信内容 · 内容库</h3>
        <p style="margin: 0; font-size: 12px; color: #666">
          管理可复用的私信模板：标题、正文、图片与分类。发送时复制正文或连接自动化脚本使用。
        </p>
      </div>
      <div style="display: flex; gap: 8px; flex-wrap: wrap">
        <router-link to="/dm/categories">
          <el-button>分类管理</el-button>
        </router-link>
        <el-button type="primary" @click="openCreate">新建内容</el-button>
      </div>
    </div>

    <el-card shadow="never" style="margin-bottom: 12px">
      <el-form :inline="true" @submit.prevent="refresh">
        <el-form-item label="分类">
          <el-select v-model="filter.category_id" clearable placeholder="全部分类" style="width: 160px">
            <el-option label="未分类" :value="0" />
            <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键词">
          <el-input v-model="filter.keyword" clearable placeholder="标题/摘要/正文" style="width: 200px" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="filter.active_only">仅启用</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="filter.pinned_only">仅置顶</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="refresh">查询</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-table v-loading="loading" :data="list" border stripe row-key="id">
      <el-table-column width="44" align="center">
        <template #default="{ row }">
          <el-icon v-if="row.is_pinned" color="#E6A23C"><StarFilled /></el-icon>
        </template>
      </el-table-column>
      <el-table-column prop="sort_order" label="排序" width="64" align="center" />
      <el-table-column label="分类" width="120">
        <template #default="{ row }">
          <el-tag v-if="categoryColor(row)" :color="categoryColor(row)" effect="dark" size="small" style="border: none">
            {{ categoryLabel(row) }}
          </el-tag>
          <span v-else>{{ categoryLabel(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
      <el-table-column prop="summary" label="摘要" min-width="140" show-overflow-tooltip />
      <el-table-column label="图片" width="100" align="center">
        <template #default="{ row }">
          <span v-if="row.images?.length">{{ row.images.length }} 张</span>
          <span v-else class="dm-muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="标签" min-width="120">
        <template #default="{ row }">
          <el-tag v-for="t in (row.tags || []).slice(0, 3)" :key="t" size="small" style="margin: 2px">{{ t }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="72" align="center">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="updated_at" label="更新" width="158" />
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openDetail(row)">查看</el-button>
          <el-button size="small" type="primary" plain @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" plain @click="removeRow(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && !list.length" description="暂无内容，请先新建或调整筛选" style="margin-top: 24px" />

    <el-dialog
      v-model="dialogVisible"
      :title="editingId == null ? '新建私信内容' : '编辑私信内容'"
      width="760px"
      destroy-on-close
      top="4vh"
    >
      <el-form label-width="96px">
        <el-form-item label="分类">
          <el-select v-model="form.category_id" clearable placeholder="不归类" style="width: 100%">
            <el-option v-for="c in categories.filter((x) => x.is_active)" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题" required>
          <el-input v-model="form.title" maxlength="200" show-word-limit placeholder="私信主题或内部标题" />
        </el-form-item>
        <el-form-item label="摘要">
          <el-input
            v-model="form.summary"
            type="textarea"
            :rows="2"
            maxlength="500"
            show-word-limit
            placeholder="列表展示用，可选"
          />
        </el-form-item>
        <el-form-item label="正文" required>
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="8"
            placeholder="实际发送的私信文案，支持换行"
          />
        </el-form-item>
        <el-form-item label="图片">
          <el-upload
            v-model:file-list="imageFileList"
            list-type="picture-card"
            :http-request="handleUpload"
            :before-upload="beforeUpload"
            :on-remove="onRemoveImage"
            accept="image/*"
            :disabled="uploading"
          >
            <el-icon><Plus /></el-icon>
          </el-upload>
          <p class="dm-form-tip">支持 jpg/png/gif/webp，单张 ≤10MB；也可在正文中单独说明附图链接。</p>
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="form.tagsText" placeholder="逗号分隔，如：活动, 跟进" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort_order" :min="0" :max="9999" />
        </el-form-item>
        <el-form-item label="置顶">
          <el-switch v-model="form.is_pinned" />
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
        <el-button type="primary" :loading="uploading" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" title="私信内容详情" width="680px" destroy-on-close>
      <template v-if="detailRow">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="标题">{{ detailRow.title }}</el-descriptions-item>
          <el-descriptions-item label="分类">{{ categoryLabel(detailRow) }}</el-descriptions-item>
          <el-descriptions-item v-if="detailRow.summary" label="摘要">{{ detailRow.summary }}</el-descriptions-item>
          <el-descriptions-item label="正文">
            <pre class="dm-content-pre">{{ detailRow.content }}</pre>
            <el-button size="small" style="margin-top: 8px" @click="copyText(detailRow.content)">复制正文</el-button>
          </el-descriptions-item>
          <el-descriptions-item v-if="detailRow.images?.length" label="图片">
            <div class="dm-preview-images">
              <el-image
                v-for="(img, i) in detailRow.images"
                :key="i"
                :src="img.url"
                :preview-src-list="detailRow.images.map((x) => x.url)"
                fit="cover"
                class="dm-preview-img"
              />
            </div>
          </el-descriptions-item>
          <el-descriptions-item v-if="detailRow.tags?.length" label="标签">
            <el-tag v-for="t in detailRow.tags" :key="t" size="small" style="margin: 2px">{{ t }}</el-tag>
          </el-descriptions-item>
        </el-descriptions>
      </template>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button v-if="detailRow" type="primary" @click="openEdit(detailRow); detailVisible = false">编辑</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.dm-muted {
  color: #909399;
  font-size: 12px;
}

.dm-form-tip {
  margin: 6px 0 0;
  font-size: 12px;
  color: #909399;
}

.dm-content-pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.5;
}

.dm-preview-images {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.dm-preview-img {
  width: 88px;
  height: 88px;
  border-radius: 6px;
}
</style>
