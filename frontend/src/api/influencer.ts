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
  /** 关联的社交账号（列表悬浮展示） */
  accounts?: SocialAccount[]
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

export const influencerApi = {
  list: (params?: {
    page?: number
    page_size?: number
    keyword?: string
    status?: string
    country?: string
    country_id?: number
    platform_id?: number
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
  runScrapeProfile: (taskId: number) =>
    http.post<unknown, InfluencerScrapeTask>(`/influencers/scrape-profile/${taskId}/run`),
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
  removeSocial: (iid: number, sid: number) =>
    http.delete(`/influencers/${iid}/social-accounts/${sid}`),
  exportList: (params?: {
    keyword?: string
    status?: string
    country?: string
    country_id?: number
    platform_id?: number
  }) =>
    download(
      { url: '/influencers/export', method: 'GET', params },
      'influencers.csv',
    ),
}
