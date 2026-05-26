import http, { download } from './http'

export type ScrapeTaskType =
  | 'fb_search'
  | 'fb_pages'
  | 'fb_posts_by_page'
  | 'fb_posts_by_hashtag'
  | 'fb_posts_by_search'
  | 'fb_posts_scraper'
  | 'fb_search_cb'

export type ScrapeTaskStatus =
  | 'pending'
  | 'running'
  | 'success'
  | 'failed'
  | 'partial'
  | 'canceled'

export interface ScrapeTask {
  id: number
  name?: string | null
  task_type: ScrapeTaskType
  status: ScrapeTaskStatus
  keywords?: string[] | null
  hashtags?: string[] | null
  address?: string | null
  start_urls?: string[] | null
  max_items: number
  posts_per_page: number
  page_limit: number
  enable_ai_filter: boolean
  llm_provider_id?: number | null
  prompt_template_id?: number | null
  apify_run_id?: string | null
  apify_dataset_id?: string | null
  result_count: number
  filtered_count: number
  error?: string | null
  owner_id: number
  created_at: string
  extra_input?: Record<string, unknown> | null
}

export interface PostItem {
  id: number
  task_id: number | null
  platform: string
  post_id?: string | null
  url?: string | null
  text?: string | null
  published_at?: string | null
  likes: number
  comments_count: number
  shares: number
  author_name?: string | null
  author_url?: string | null
  author_page_id?: string | null
  ai_passed?: boolean | null
  ai_score?: number | null
  ai_reason?: string | null
  influencer_id?: number | null
}

export interface PageItem {
  facebookUrl?: string
  pageUrl?: string
  pageId?: string
  pageName?: string
  title?: string
  facebookId?: string
  categories?: string[]
  intro?: string
  about_me?: { text?: string; urls?: string[] }
  likes?: number
  followers?: number
  followings?: number
  messenger?: string | null
  website?: string
  websites?: string[]
  email?: string
  phone?: string
  address?: string
  rating?: string | number
  ratingOverall?: number
  ratingCount?: number
  profilePictureUrl?: string
  coverPhotoUrl?: string
  profilePhoto?: string
  creation_date?: string
  ad_status?: string
  pageAdLibrary?: { id?: string; is_business_page_active?: boolean }
  _ai_passed?: boolean
  _ai_score?: number
  _ai_reason?: string
  _source_post_ids?: number[]
  [k: string]: unknown
}

export interface Paginated<T> {
  total: number
  page: number
  page_size: number
  items: T[]
}

export const scraperApi = {
  createTask: (data: Partial<ScrapeTask>) =>
    http.post<unknown, ScrapeTask>('/scraper/tasks', data),
  listTasks: () => http.get<unknown, ScrapeTask[]>('/scraper/tasks'),
  getTask: (id: number) => http.get<unknown, ScrapeTask>(`/scraper/tasks/${id}`),
  cancelTask: (id: number) => http.post(`/scraper/tasks/${id}/cancel`),
  listPosts: (
    id: number,
    params?: { page?: number; page_size?: number; only_passed?: boolean }
  ) => http.get<unknown, Paginated<PostItem>>(`/scraper/tasks/${id}/posts`, { params }),
  listPages: (
    id: number,
    params?: { page?: number; page_size?: number; only_passed?: boolean }
  ) => http.get<unknown, Paginated<PageItem>>(`/scraper/tasks/${id}/pages`, { params }),
  exportPosts: (id: number, only_passed = false) =>
    download(
      { url: `/scraper/tasks/${id}/posts/export`, method: 'GET', params: { only_passed } },
      `task_${id}_posts.csv`,
    ),
  exportPages: (id: number, only_passed = false) =>
    download(
      { url: `/scraper/tasks/${id}/pages/export`, method: 'GET', params: { only_passed } },
      `task_${id}_pages.csv`,
    ),
  /** 勾选帖子后，按作者主页抓 facebook-pages-scraper 并合并到任务 page_results */
  scrapeAuthorPagesFromPosts: (taskId: number, postIds: number[]) =>
    http.post<unknown, { msg: string }>(
      `/scraper/tasks/${taskId}/scrape-author-pages`,
      { post_ids: postIds },
      { timeout: 600000 }
    ),
}

/** 各任务类型的元信息：UI 渲染、文案、费用提示 */
export interface TaskTypeMeta {
  value: ScrapeTaskType
  label: string
  summary: string
  pricing: string
  needs: {
    keywords?: boolean
    locations?: boolean
    hashtags?: boolean
    startUrls?: boolean
    postsPerPage?: boolean
    searchPostsOptions?: boolean  // fb_posts_by_search 专属：location_uid / 日期 / 排序
    /** fb_posts_by_page：cleansyntax actor 的模式与可选日期 */
    profilePostsOptions?: boolean
    /** fb_search_cb：crawlerbros actor 的搜索类型选择 */
    cbSearchOptions?: boolean
  }
}

/** 新建任务可选类型（后端仍支持其它类型，仅隐藏入口） */
export const TASK_TYPES: TaskTypeMeta[] = [
  {
    value: 'fb_search',
    label: '关键词搜 Pages（最省钱）',
    summary:
      '使用 apify/facebook-search-scraper：按【关键词 categories + 位置 locations】直接返回匹配的 Facebook Pages 资料。一步到位，不抓帖子。',
    pricing: '约 $10 / 1000 pages',
    needs: { keywords: true, locations: true }
  },
  {
    value: 'fb_posts_by_page',
    label: '主页 / 关键词 / ID → 抓帖子 → AI → 抓主页',
    summary:
      '第一步使用 cleansyntax/facebook-profile-posts-scraper：可选「按主页 URL」「按关键词搜帖」「按 Profile 数字 ID」抓公开帖子；第二步 AI 评估后聚合作者主页，再用 facebook-pages-scraper 抓详情。第一步的条数上限由「每目标帖子数」映射为 actor 的 max_posts（0 表示不限制，费用风险自负）。',
    pricing: '约 $6 / 1000 条（profile actor）+ pages $6.6/1000 + LLM',
    needs: { postsPerPage: true, profilePostsOptions: true }
  },
  {
    value: 'fb_posts_by_hashtag',
    label: 'Hashtag → 抓帖子 → AI → 抓主页 → 建联',
    summary:
      '使用 apify/facebook-hashtag-scraper：按 hashtag（不含 #）搜帖子；AI 过滤后聚合作者主页，再用 facebook-pages-scraper 抓详情。',
    pricing: 'posts $10/1000 + pages $6.6/1000 + LLM',
    needs: { hashtags: true }
  },
  {
    value: 'fb_search_cb',
    label: '关键词搜 Pages/People（crawlerbros，$5/1000）',
    summary:
      '使用 crawlerbros/facebook-search-scraper：按关键词搜索 Facebook Pages 或 People，返回结构化的主页/人员资料。支持选择搜索类型（pages / people）。',
    pricing: '约 $5 / 1000 results',
    needs: { keywords: true, cbSearchOptions: true }
  },
  {
    value: 'fb_posts_scraper',
    label: '主页 URL → 抓帖子（官方 facebook-posts-scraper）',
    summary:
      '使用 apify/facebook-posts-scraper：给定 Facebook 主页/主页 URL 列表，直接抓公开帖子。支持每个主页单独限制条数（每目标帖子数）和全局上限。抓到帖子后可选 AI 评估作者 → 自动抓主页详情。',
    pricing: '约 $2 / 1000 posts + pages $6.6/1000 + LLM（可选）',
    needs: { startUrls: true, postsPerPage: true }
  }
]
