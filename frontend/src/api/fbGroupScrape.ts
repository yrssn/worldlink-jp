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

export type FbGroupPullTaskStatus = 'pending' | 'running' | 'done' | 'failed'

export interface FbGroupPullTask {
  id: number
  config_id: number
  config_title?: string | null
  created_by_id: number
  created_by_username?: string | null
  status: FbGroupPullTaskStatus
  params?: Record<string, unknown> | null
  apify_run_id?: string | null
  apify_dataset_id?: string | null
  result_count: number
  error?: string | null
  started_at?: string | null
  finished_at?: string | null
  created_at: string
  updated_at: string
}

export interface FbGroupPost {
  id: number
  task_id: number
  config_id: number
  legacy_id: string
  post_url?: string | null
  facebook_group_id?: string | null
  group_title?: string | null
  user_id?: string | null
  user_name?: string | null
  text?: string | null
  post_time?: string | null
  likes_count: number
  comments_count: number
  shares_count: number
  has_attachments: boolean
  has_shared_post: boolean
  raw_data?: Record<string, unknown> | null
  created_at: string
}

export interface FbGroupPostPage {
  total: number
  page: number
  page_size: number
  items: FbGroupPost[]
}

export interface FbGroupScheduleTask {
  id: number
  config_id: number
  config_title?: string | null
  created_by_id: number
  created_by_username?: string | null
  status: 'active' | 'paused' | 'disabled'
  schedule_type: 'cron' | 'interval'
  schedule_config: Record<string, unknown>
  pull_params?: Record<string, unknown> | null
  last_run_at?: string | null
  next_run_at?: string | null
  last_task_id?: number | null
  consecutive_failures: number
  max_consecutive_failures: number
  remark?: string | null
  created_at: string
  updated_at: string
}

export interface FbGroupScheduleTaskCreate {
  schedule_type: 'cron' | 'interval'
  schedule_config: Record<string, unknown>
  pull_params?: Record<string, unknown> | null
  max_consecutive_failures?: number
  remark?: string | null
}

export interface FbGroupScheduleTaskUpdate {
  status?: 'active' | 'paused' | 'disabled'
  schedule_type?: 'cron' | 'interval'
  schedule_config?: Record<string, unknown>
  pull_params?: Record<string, unknown> | null
  max_consecutive_failures?: number
  remark?: string | null
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

  /** 提交后台拉取任务（立即返回，不阻塞） */
  pull: (id: number, params?: FbGroupPullParams) =>
    http.post<unknown, FbGroupPullTask>(`/scraper/fb-group-scrapes/${id}/pull`, params || {}),

  /** 批量提交后台拉取任务（多个群组共享同一组参数） */
  batchPull: (data: { config_ids: number[] } & FbGroupPullParams) =>
    http.post<unknown, FbGroupPullTask[]>(`/scraper/fb-group-scrapes/batch-pull`, data),

  /** 查询某配置的所有拉取任务 */
  listTasks: (configId: number) =>
    http.get<unknown, FbGroupPullTask[]>(`/scraper/fb-group-scrapes/${configId}/tasks`),

  /** 获取单个任务详情（用于轮询状态） */
  getTask: (taskId: number) =>
    http.get<unknown, FbGroupPullTask>(`/scraper/fb-group-scrapes/tasks/${taskId}`),

  /** 手动将卡住的 pending/running 任务标记为失败 */
  markFailed: (taskId: number) =>
    http.post<unknown, FbGroupPullTask>(`/scraper/fb-group-scrapes/tasks/${taskId}/fail`, {}),

  /** 查询某任务的帖子（分页） */
  listTaskPosts: (
    taskId: number,
    params?: { page?: number; page_size?: number; keyword?: string }
  ) =>
    http.get<unknown, FbGroupPostPage>(`/scraper/fb-group-scrapes/tasks/${taskId}/posts`, {
      params: params || {}
    }),

  /** 查询某配置的所有帖子（跨任务，分页） */
  listConfigPosts: (
    configId: number,
    params?: { page?: number; page_size?: number; keyword?: string }
  ) =>
    http.get<unknown, FbGroupPostPage>(`/scraper/fb-group-scrapes/${configId}/posts`, {
      params: params || {}
    }),

  // ─── 定时任务 ───────────────────────────────────────────────────
  /** 为某配置创建定时拉取任务 */
  createSchedule: (configId: number, body: FbGroupScheduleTaskCreate) =>
    http.post<unknown, FbGroupScheduleTask>(
      `/scraper/fb-group-scrapes/${configId}/schedules`,
      body
    ),

  /** 列出某配置的所有定时任务 */
  listSchedules: (configId: number) =>
    http.get<unknown, FbGroupScheduleTask[]>(`/scraper/fb-group-scrapes/${configId}/schedules`),

  /** 更新定时任务 */
  updateSchedule: (scheduleId: number, body: FbGroupScheduleTaskUpdate) =>
    http.put<unknown, FbGroupScheduleTask>(`/scraper/fb-group-scrapes/schedules/${scheduleId}`, body),

  /** 删除定时任务 */
  deleteSchedule: (scheduleId: number) =>
    http.delete<unknown, { ok: boolean }>(`/scraper/fb-group-scrapes/schedules/${scheduleId}`)
}
