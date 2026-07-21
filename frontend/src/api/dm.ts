import http from './http'

export interface DmCategory {
  id: number
  owner_id: number
  name: string
  code?: string | null
  color?: string | null
  remark?: string | null
  sort_order: number
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface DmImageItem {
  url: string
  path?: string | null
  name?: string | null
  sort: number
}

export interface DmContent {
  id: number
  owner_id: number
  category_id?: number | null
  category_name?: string | null
  title: string
  summary?: string | null
  content: string
  images: DmImageItem[]
  tags: string[]
  is_active: boolean
  is_pinned: boolean
  sort_order: number
  remark?: string | null
  created_at: string
  updated_at: string
}

export interface DmOutreachResult {
  ok: boolean
  browser_id: string
  content_id: number
  content_title?: string | null
  page_opened: boolean
  message_clicked: boolean
  matched_text?: string | null
  final_url?: string | null
  open_hint?: unknown
}

export interface DmUploadResult {
  url: string
  path: string
  name: string
}

export const dmApi = {
  listCategories: (activeOnly = false) =>
    http.get<unknown, DmCategory[]>('/dm/categories', { params: activeOnly ? { active_only: true } : {} }),
  createCategory: (data: Partial<DmCategory>) => http.post<unknown, DmCategory>('/dm/categories', data),
  updateCategory: (id: number, data: Partial<DmCategory>) =>
    http.put<unknown, DmCategory>(`/dm/categories/${id}`, data),
  deleteCategory: (id: number) => http.delete(`/dm/categories/${id}`),

  listContents: (params?: {
    category_id?: number | null
    keyword?: string
    active_only?: boolean
    pinned_only?: boolean
  }) => http.get<unknown, DmContent[]>('/dm/contents', { params: params || {} }),
  getContent: (id: number) => http.get<unknown, DmContent>(`/dm/contents/${id}`),
  createContent: (data: Partial<DmContent>) => http.post<unknown, DmContent>('/dm/contents', data),
  updateContent: (id: number, data: Partial<DmContent>) =>
    http.put<unknown, DmContent>(`/dm/contents/${id}`, data),
  deleteContent: (id: number) => http.delete(`/dm/contents/${id}`),

  startOutreach: (data: { url: string; browser_id: string; content_id: number }) =>
    http.post<unknown, DmOutreachResult>('/dm/outreach/start', data, { timeout: 180000 }),

  uploadImage: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post<unknown, DmUploadResult>('/dm/uploads', fd, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  }
}
