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
  /** 平台内的页面 / 账号 ID */
  page_id?: string | null
  author_id?: string | null
  /** 账号 / 页面名称 */
  title?: string | null
  avatar_url?: string | null
  categories?: string[] | null
  likes?: number | null
  rating?: number | null
  rating_count?: number | null
  checkins_mentions?: number | null
  page_created_at?: string | null
  ad_library_id?: string | null
  ad_status?: string | null
  messenger?: string | null
  notes?: string | null
  last_scraped_at?: string | null
  extra?: Record<string, unknown> | null
}

/** 账号编辑表单里可选的平台 */
export const SOCIAL_PLATFORM_OPTIONS: { value: SocialPlatform; label: string }[] = [
  { value: 'facebook', label: 'Facebook' },
  { value: 'instagram', label: 'Instagram' },
  { value: 'tiktok', label: 'TikTok' },
  { value: 'youtube', label: 'YouTube' },
  { value: 'twitter', label: 'X / Twitter' },
  { value: 'wechat', label: '微信' },
  { value: 'xiaohongshu', label: '小红书' },
  { value: 'line', label: 'LINE' },
  { value: 'other', label: '其他' },
]

/** 存量 Excel 表头对应的「人 / 建联」维度可选字段 */
export interface InfluencerProfileFields {
  /** KOL 编号 */
  code?: string | null
  /** KOL 公司名 */
  company?: string | null
  gender?: string | null
  /** 建联负责人 */
  contact_owner?: string | null
  /** 落地负责人 */
  landing_owner?: string | null
  /** 来源渠道 */
  source_channel?: string | null
  contact_started_at?: string | null
  planned_visit_at?: string | null
  has_twitter?: boolean | null
  twitter_channel?: string | null
  group_name?: string | null
}

export const PROFILE_FIELD_LABELS: { key: keyof InfluencerProfileFields; label: string }[] = [
  { key: 'code', label: 'KOL 编号' },
  { key: 'company', label: 'KOL 公司名' },
  { key: 'gender', label: '性别' },
  { key: 'contact_owner', label: '建联负责人' },
  { key: 'landing_owner', label: '落地负责人' },
  { key: 'source_channel', label: '来源渠道' },
  { key: 'contact_started_at', label: '建联开始日期' },
  { key: 'planned_visit_at', label: '计划首次来访时间' },
  { key: 'has_twitter', label: '是否推特' },
  { key: 'twitter_channel', label: '推特渠道' },
  { key: 'group_name', label: '群名称' },
]

export interface Influencer extends InfluencerProfileFields {
  id: number
  display_name: string
  real_name?: string | null
  bio?: string | null
  avatar_url?: string | null
  cover_url?: string | null
  email?: string | null
  phone?: string | null
  website?: string | null
  country?: string | null
  country_id?: number | null
  country_name?: string | null
  country_name_en?: string | null
  country_code?: string | null
  region?: string | null
  city?: string | null
  language?: string | null
  address?: string | null
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
  /** 各关联账号粉丝数最大值，列表展示 & 区间筛选口径 */
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

/** 抓取任务结果：人维度字段 + FB 账号字段（fb_*）/ IG 账号字段（ig_*） */
export type ScrapeTaskResult = Partial<Influencer> & {
  platform?: string
  messenger?: string | null
  fb_page_id?: string | null
  fb_page_url?: string | null
  fb_page_title?: string | null
  fb_categories?: string[] | null
  fb_followers?: number | null
  fb_likes?: number | null
  fb_rating?: number | null
  fb_rating_count?: number | null
  fb_checkins_mentions?: number | null
  fb_page_created_at?: string | null
  fb_ad_library_id?: string | null
  fb_ad_status?: string | null
  ig_username?: string
  ig_url?: string
  followers?: number
}

/** 把抓取结果里的账号维度字段换成关联账号字段 */
export function accountFromScrapeResult(result: ScrapeTaskResult): SocialAccount {
  if (result.platform === 'instagram') {
    return {
      platform: 'instagram',
      handle: result.ig_username ?? null,
      url: result.ig_url ?? null,
      followers: result.followers ?? null,
      title: result.real_name || result.display_name || null,
      avatar_url: result.avatar_url ?? null,
    }
  }
  return {
    platform: 'facebook',
    page_id: result.fb_page_id ?? null,
    url: result.fb_page_url ?? null,
    title: result.fb_page_title ?? null,
    categories: result.fb_categories ?? null,
    followers: result.fb_followers ?? null,
    likes: result.fb_likes ?? null,
    rating: result.fb_rating ?? null,
    rating_count: result.fb_rating_count ?? null,
    checkins_mentions: result.fb_checkins_mentions ?? null,
    page_created_at: result.fb_page_created_at ?? null,
    ad_library_id: result.fb_ad_library_id ?? null,
    ad_status: result.fb_ad_status ?? null,
    messenger: result.messenger ?? null,
    avatar_url: result.avatar_url ?? null,
  }
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
  /** 列表「一键抓取」时绑定的关联账号，结果回写到该账号 */
  social_account_id?: number | null
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

export interface ImportFieldOption {
  key: string
  label: string
  required?: boolean
}

export interface ImportPreview {
  filename: string
  total_rows: number
  columns: ImportColumnPreview[]
  suggested_url_column?: number | null
  /** 按表头名猜的 字段 key -> 列下标 */
  suggested_columns?: Record<string, number>
  /** 可映射字段清单（后端维护） */
  fields?: ImportFieldOption[]
}

export interface ImportResult {
  total_rows: number
  created: number
  /** 链接匹配到已有达人并补了资料 */
  updated?: number
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
  /** 其余字段映射 JSON：{"code": 1, "company": 4, ...} */
  column_map?: string
  has_header?: boolean
  status?: string
  scrape?: boolean
  /** false = 链接匹配不到已有达人时不新建，只补已有达人 */
  create_missing?: boolean
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
  /** 列表「一键抓取」：选中某条 FB / IG 关联账号后后台抓取，结果回写到该账号 */
  scrapeSocial: (iid: number, socialAccountId: number) =>
    http.post<unknown, InfluencerScrapeTask>(`/influencers/${iid}/social-accounts/scrape`, {
      social_account_id: socialAccountId,
    }),
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
