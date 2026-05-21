import http from './http'

export type FbGroupViewOption =
  | 'CHRONOLOGICAL'
  | 'RECENT_ACTIVITY'
  | 'TOP_POSTS'
  | 'CHRONOLOGICAL_LISTINGS'

export interface FbGroupPullParams {
  results_limit?: number
  view_option?: FbGroupViewOption
  search_group_keyword?: string
  search_group_year?: string
  only_posts_newer_than?: string
}

export interface FbGroupPullResult {
  config_id: number
  group_url: string
  apify_run_id?: string | null
  apify_dataset_id?: string | null
  input_used: Record<string, unknown>
  count: number
  field_keys: string[]
  items: Record<string, unknown>[]
}

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
    http.post<unknown, FbGroupScrape>(`/scraper/fb-group-scrapes/${id}/restore`, {}),
  /** 调用 Apify 拉取群组帖子（耗时较长，默认 10 分钟超时） */
  pull: (id: number, params?: FbGroupPullParams) =>
    http.post<unknown, FbGroupPullResult>(`/scraper/fb-group-scrapes/${id}/pull`, params || {}, {
      timeout: 600000
    })
}
