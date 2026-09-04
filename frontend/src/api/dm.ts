import http from './http'
import type { DmOutreachLog } from './influencer'

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
  text_sent: boolean
  images_sent: number
  scrape_task_id?: number | null
  final_url?: string | null
  open_hint?: unknown
}

export interface DmUploadResult {
  url: string
  path: string
  name: string
}

export interface DmOutreachJobTarget {
  influencer_id: number
  url: string
  display_name?: string | null
}

export interface DmOutreachJob {
  id: number
  owner_id: number
  owner_name?: string | null
  platform: string
  browser_id: string
  browser_name?: string | null
  content_id?: number | null
  content_title?: string | null
  targets?: DmOutreachJobTarget[] | null
  interval_min: number
  interval_max: number
  total: number
  sent: number
  failed: number
  status: 'pending' | 'running' | 'done' | 'cancelled'
  current_url?: string | null
  error?: string | null
  started_at?: string | null
  finished_at?: string | null
  created_at: string
}

export interface DmOutreachJobDetail extends DmOutreachJob {
  logs: DmOutreachLog[]
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

  startOutreach: (data: {
    url: string
    browser_id: string
    content_id: number
    platform?: string
    source_task_id?: number
  }) => http.post<unknown, DmOutreachResult>('/dm/outreach/start', data, { timeout: 300000 }),

  createOutreachJob: (data: {
    influencer_ids: number[]
    browser_id: string
    content_id: number
    platform: string
    interval_min?: number
    interval_max?: number
  }) => http.post<unknown, DmOutreachJob>('/dm/outreach/jobs', data),
  listOutreachJobs: (limit = 20) =>
    http.get<unknown, DmOutreachJob[]>('/dm/outreach/jobs', { params: { limit } }),
  getOutreachJob: (id: number) => http.get<unknown, DmOutreachJobDetail>(`/dm/outreach/jobs/${id}`),
  cancelOutreachJob: (id: number) =>
    http.post<unknown, DmOutreachJob>(`/dm/outreach/jobs/${id}/cancel`),

  uploadImage: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post<unknown, DmUploadResult>('/dm/uploads', fd, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  }
}
