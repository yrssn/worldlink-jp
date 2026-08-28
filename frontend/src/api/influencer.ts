import http, { download } from './http'
import type { Paginated } from './scraper'

export type InfluencerStatus = 'pre_contact' | 'contacting' | 'signed' | 'dropped'
export type InfluencerSource = 'scrape' | 'manual'
export type SocialPlatform =
  | 'facebook'
  | 'instagram'
  | 'tiktok'
  | 'youtube'
  | 'twitter'
  | 'wechat'
  | 'xiaohongshu'
  | 'line'
  | 'other'

export interface SocialAccount {
  id?: number
  platform: SocialPlatform
  /** 关联「平台管理」里的平台 id（平台挂在账号上，一个达人可有多个平台账号） */
  platform_id?: number | null
  /** 「平台管理」里的平台展示名 */
  platform_name?: string | null
  handle?: string | null
  url?: string | null
  followers?: number | null
  extra?: Record<string, unknown> | null
}

export interface Influencer {
  id: number
  display_name: string
  real_name?: string | null
  bio?: string | null
  avatar_url?: string | null
  cover_url?: string | null
  email?: string | null
  phone?: string | null
  website?: string | null
  messenger?: string | null
  country?: string | null
  country_id?: number | null
  country_name?: string | null
  country_name_en?: string | null
  country_code?: string | null
  region?: string | null
  city?: string | null
  language?: string | null
  address?: string | null
  fb_page_id?: string | null
  fb_page_url?: string | null
  fb_page_title?: string | null
  fb_categories?: string[] | null
  fb_followers?: number | null
  fb_likes?: number | null
  fb_rating?: number | null
  fb_rating_count?: number | null
  status: InfluencerStatus
  source: InfluencerSource
  platform_id?: number | null
  platform_name?: string | null
  platform_code?: string | null
  notes?: string | null
  progress?: string | null
  tags?: string[] | null
  owner_id: number
  owner_name?: string | null
  has_outreach?: boolean
  /** 关联的社交账号（列表内直接展示：平台 + 账号 + 粉丝） */
  accounts?: SocialAccount[]
  /** 各平台粉丝数最大值（含 FB 主字段），列表展示 & 区间筛选口径 */
  followers?: number | null
  created_at: string
}

export interface InfluencerDetail extends Influencer {
  social_accounts: SocialAccount[]
  source_post_ids: number[]
}

export interface DmOutreachLog {
  id: number
  influencer_id?: number | null
  url: string
  browser_id?: string | null
  content_id?: number | null
  content_title?: string | null
  content_text?: string | null
  images_count: number
  text_sent: boolean
  images_sent: number
  created_at: string
}

export interface InfluencerSourcePost {
  id: number
  task_id: number | null
  url: string | null
  text: string | null
  author_name: string | null
  likes: number
  comments_count: number
  shares: number
  ai_passed: boolean | null
  ai_score: number | null
  ai_reason: string | null
  published_at: string | null
}

/** 可暂存的平台（facebook / instagram 之外的暂不支持自动抓资料，只做预分类暂存） */
export type ScrapePlatform =
  | 'facebook'
  | 'instagram'
  | 'tiktok'
  | 'xiaohongshu'
  | 'youtube'
  | 'twitter'
  | 'line'

/** 支持自动抓取资料的平台 */
export const SCRAPABLE_PLATFORMS: ScrapePlatform[] = ['facebook', 'instagram']

export const PLATFORM_LABELS: Record<ScrapePlatform, string> = {
  facebook: 'Facebook',
  instagram: 'Instagram',
  tiktok: 'TikTok',
  xiaohongshu: '小红书',
  youtube: 'YouTube',
  twitter: 'X / Twitter',
  line: 'LINE',
}

/** 抓取任务里可选的平台，由后端按「平台管理」的代码/名称对齐得到 */
export interface PlatformOption {
  platform: ScrapePlatform
  /** 「平台管理」里的展示名 */
  name: string
  platform_id?: number | null
  code?: string | null
  scrapable: boolean
}

/** 存量头像本地化结果 */
export interface AvatarCacheResult {
  total: number
  cached: number
  failed: number
}

export interface PlatformDetectItem {
  url: string
  platform?: ScrapePlatform | null
  platform_id?: number | null
  platform_name?: string | null
  scrapable: boolean
}

export type ScrapeTaskResult = Partial<Influencer> & {
  platform?: string
  ig_username?: string
  ig_url?: string
  followers?: number
}

export interface InfluencerScrapeTask {
  id: number
  platform: ScrapePlatform
  batch?: string | null
  url: string
  status: 'staged' | 'pending' | 'running' | 'done' | 'failed' | 'contacted'
  error?: string | null
  result?: ScrapeTaskResult | null
  created_at: string
  finished_at?: string | null
  influencer_id?: number | null
}

export interface InfluencerScrapeBatch {
  platform: ScrapePlatform
  batch?: string | null
  /** 批次归属：谁建的就是谁的 */
  owner_id?: number | null
  owner_name?: string | null
  total: number
  staged: number
  running: number
  failed: number
  done: number
}

export interface ScrapeBatchActionResult {
  affected: number
  skipped: number
}

/** 表格导入：某一列的列名与样例，用于选「哪列是主页链接」 */
export interface ImportColumnPreview {
  index: number
  name: string
  samples: string[]
  looks_like_url: boolean
}

export interface ImportPreview {
  filename: string
  total_rows: number
  columns: ImportColumnPreview[]
  suggested_url_column?: number | null
}

export interface ImportResult {
  total_rows: number
  created: number
  duplicated: number
  skipped: number
  scrape_tasks: number
  batch?: string | null
}

/** 表格导入参数：选列 + 选状态 + 选是否抓取 */
export interface ImportOptions {
  url_column: number
  name_column?: number | null
  email_column?: number | null
  followers_column?: number | null
  notes_column?: number | null
  has_header?: boolean
  status?: string
  scrape?: boolean
  platform?: ScrapePlatform | 'auto'
  /** 链接识别不出平台时归为哪个平台，默认 other */
  fallback_platform?: ScrapePlatform | 'other'
}

export const influencerApi = {
  list: (params?: {
    page?: number
    page_size?: number
    keyword?: string
    status?: string
    country?: string
    country_id?: number
    platform_id?: number
    followers_min?: number
    followers_max?: number
    sort?: 'id_desc' | 'followers_desc' | 'followers_asc'
  }) => http.get<unknown, Paginated<Influencer>>('/influencers', { params }),
  listPlatformOptions: () =>
    http.get<unknown, PlatformOption[]>('/influencers/platform-options'),
  /** 把存量达人的远端头像下载到服务器（国内免代理看图） */
  cacheAvatars: (limit = 200) =>
    http.post<unknown, AvatarCacheResult>('/influencers/avatars/cache', null, {
      params: { limit },
    }),
  detectPlatforms: (urls: string[]) =>
    http.post<unknown, PlatformDetectItem[]>('/influencers/detect-platforms', { urls }),
  create: (data: Partial<Influencer> & { social_accounts?: SocialAccount[] }) =>
    http.post<unknown, Influencer>('/influencers', data),
  detail: (id: number) => http.get<unknown, InfluencerDetail>(`/influencers/${id}`),
  update: (id: number, data: Partial<Influencer>) =>
    http.put<unknown, Influencer>(`/influencers/${id}`, data),
  remove: (id: number) => http.delete(`/influencers/${id}`),
  fromScrape: (data: {
    post_id?: number
    author_url?: string
    page_profile?: Record<string, unknown>
    source_post_ids?: number[]
    notes?: string
  }) => http.post<unknown, Influencer>('/influencers/from-scrape', data),
  startScrapeProfile: (url: string, platform: ScrapePlatform = 'facebook') =>
    http.post<unknown, InfluencerScrapeTask>('/influencers/scrape-profile', { url, platform }),
  getScrapeProfile: (taskId: number) =>
    http.get<unknown, InfluencerScrapeTask>(`/influencers/scrape-profile/${taskId}`),
  listScrapeProfiles: (params?: {
    limit?: number
    platform?: ScrapePlatform
    batch?: string
    status?: string
  }) =>
    http.get<unknown, InfluencerScrapeTask[]>('/influencers/scrape-profile', {
      params: { limit: 100, ...(params || {}) },
    }),
  batchStageScrapeProfiles: (data: {
    urls: string[]
    /** 'auto' = 后端按链接正则逐条识别平台 */
    platform: ScrapePlatform | 'auto'
    fallback_platform?: ScrapePlatform
    batch?: string | null
  }) =>
    http.post<unknown, InfluencerScrapeTask[]>('/influencers/scrape-profile/batch', data),
  listScrapeBatches: () =>
    http.get<unknown, InfluencerScrapeBatch[]>('/influencers/scrape-profile-batches'),
  runScrapeBatch: (data: {
    batch?: string | null
    platform?: ScrapePlatform | null
    include_failed?: boolean
    /** 抓完直接入库 + 入库后的建联状态 */
    auto_save?: boolean
    save_status?: string | null
  }) =>
    http.post<unknown, ScrapeBatchActionResult>(
      '/influencers/scrape-profile-batches/run',
      data,
    ),
  deleteScrapeBatch: (data: { batch?: string | null; platform?: ScrapePlatform | null }) =>
    http.post<unknown, ScrapeBatchActionResult>(
      '/influencers/scrape-profile-batches/delete',
      data,
    ),
  runScrapeProfile: (taskId: number, data?: { auto_save?: boolean; save_status?: string | null }) =>
    http.post<unknown, InfluencerScrapeTask>(
      `/influencers/scrape-profile/${taskId}/run`,
      data || {},
    ),
  /** 上传主页链接表格（xlsx / csv / txt）批量导入暂存 */
  uploadScrapeBatch: (
    file: File,
    platform: ScrapePlatform | 'auto',
    options?: { url_column?: number; has_header?: boolean },
  ) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('platform', platform)
    if (options?.url_column !== undefined) fd.append('url_column', String(options.url_column))
    if (options?.has_header !== undefined) fd.append('has_header', String(options.has_header))
    return http.post<unknown, InfluencerScrapeTask[]>(
      '/influencers/scrape-profile/batch/upload',
      fd,
    )
  },
  updateScrapeProfile: (taskId: number, data: { platform?: ScrapePlatform }) =>
    http.patch<unknown, InfluencerScrapeTask>(`/influencers/scrape-profile/${taskId}`, data),
  deleteScrapeProfile: (taskId: number) =>
    http.delete(`/influencers/scrape-profile/${taskId}`),
  saveScrapeProfile: (taskId: number, notes?: string) =>
    http.post<unknown, { influencer: Influencer; created: boolean }>(
      `/influencers/scrape-profile/${taskId}/save`,
      { notes },
    ),
  listPosts: (id: number) =>
    http.get<unknown, InfluencerSourcePost[]>(`/influencers/${id}/posts`),
  listOutreachLogs: (id: number) =>
    http.get<unknown, DmOutreachLog[]>(`/influencers/${id}/outreach-logs`),
  addSocial: (id: number, data: SocialAccount) =>
    http.post<unknown, SocialAccount>(`/influencers/${id}/social-accounts`, data),
  updateSocial: (iid: number, sid: number, data: Partial<SocialAccount>) =>
    http.put<unknown, SocialAccount>(`/influencers/${iid}/social-accounts/${sid}`, data),
  removeSocial: (iid: number, sid: number) =>
    http.delete(`/influencers/${iid}/social-accounts/${sid}`),
  /** 表格导入第一步：回显列名/样例，供选择主页链接列 */
  previewImport: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post<unknown, ImportPreview>('/influencers/import/preview', fd)
  },
  /** 表格导入第二步：按选定列入库，可选建联状态与是否抓取 */
  importTable: (file: File, options: ImportOptions) => {
    const fd = new FormData()
    fd.append('file', file)
    for (const [k, v] of Object.entries(options)) {
      if (v !== undefined && v !== null && v !== '') fd.append(k, String(v))
    }
    return http.post<unknown, ImportResult>('/influencers/import', fd)
  },
  exportList: (params?: {
    keyword?: string
    status?: string
    country?: string
    country_id?: number
    platform_id?: number
    followers_min?: number
    followers_max?: number
  }) =>
    download(
      { url: '/influencers/export', method: 'GET', params },
      'influencers.csv',
    ),
}
