import http from './http'

export interface FbGroupScrape {
  id: number
  created_by_id: number
  created_by_username?: string | null
  connection: string
  title: string
  remark?: string | null
  created_at: string
  updated_at: string
  deleted_at?: string | null
}

export const fbGroupScrapeApi = {
  list: (params?: { keyword?: string; include_deleted?: boolean }) =>
    http.get<unknown, FbGroupScrape[]>('/scraper/fb-group-scrapes', { params: params || {} }),
  get: (id: number) => http.get<unknown, FbGroupScrape>(`/scraper/fb-group-scrapes/${id}`),
  create: (data: { connection: string; title: string; remark?: string }) =>
    http.post<unknown, FbGroupScrape>('/scraper/fb-group-scrapes', data),
  update: (id: number, data: Partial<{ connection: string; title: string; remark: string | null }>) =>
    http.put<unknown, FbGroupScrape>(`/scraper/fb-group-scrapes/${id}`, data),
  remove: (id: number) => http.delete<unknown, { ok: boolean }>(`/scraper/fb-group-scrapes/${id}`),
  restore: (id: number) =>
    http.post<unknown, FbGroupScrape>(`/scraper/fb-group-scrapes/${id}/restore`, {})
}
