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
  email?: string | null
  phone?: string | null
  website?: string | null
  messenger?: string | null
  country?: string | null
  region?: string | null
  city?: string | null
  fb_page_id?: string | null
  fb_page_url?: string | null
  fb_followers?: number | null
  fb_likes?: number | null
  fb_rating?: number | null
  status: InfluencerStatus
  source: InfluencerSource
  notes?: string | null
  tags?: string[] | null
  owner_id: number
  created_at: string
}

export interface InfluencerDetail extends Influencer {
  social_accounts: SocialAccount[]
  source_post_ids: number[]
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

export const influencerApi = {
  list: (params?: { page?: number; page_size?: number; keyword?: string; status?: string }) =>
    http.get<unknown, Paginated<Influencer>>('/influencers', { params }),
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
  listPosts: (id: number) =>
    http.get<unknown, InfluencerSourcePost[]>(`/influencers/${id}/posts`),
  addSocial: (id: number, data: SocialAccount) =>
    http.post<unknown, SocialAccount>(`/influencers/${id}/social-accounts`, data),
  removeSocial: (iid: number, sid: number) =>
    http.delete(`/influencers/${iid}/social-accounts/${sid}`),
  exportList: (params?: { keyword?: string; status?: string }) =>
    download(
      { url: '/influencers/export', method: 'GET', params },
      'influencers.csv',
    ),
}
