import http from './http'

export interface ApifyKey {
  id: number
  label: string
  token: string
  is_default: boolean
  remark?: string | null
  exhausted_at?: string | null
  email_account_id?: number | null
  email_account_email?: string | null
  email_account_verification_email?: string | null
  created_at: string
  updated_at: string
}

export interface ApifyKeyCreate {
  label: string
  token: string
  is_default?: boolean
  remark?: string | null
  email_account_id?: number | null
}

export interface ApifyKeyUpdate {
  label?: string
  token?: string
  remark?: string | null
  email_account_id?: number | null
}

export const apifyKeyApi = {
  list: () => http.get<unknown, ApifyKey[]>('/scraper/apify-keys'),
  create: (data: ApifyKeyCreate) => http.post<unknown, ApifyKey>('/scraper/apify-keys', data),
  update: (id: number, data: ApifyKeyUpdate) =>
    http.put<unknown, ApifyKey>(`/scraper/apify-keys/${id}`, data),
  remove: (id: number) => http.delete<unknown, { ok: boolean }>(`/scraper/apify-keys/${id}`),
  setDefault: (id: number) =>
    http.post<unknown, ApifyKey>(`/scraper/apify-keys/${id}/set-default`, {}),
  markExhausted: (id: number) =>
    http.post<unknown, ApifyKey>(`/scraper/apify-keys/${id}/mark-exhausted`, {}),
  unmarkExhausted: (id: number) =>
    http.post<unknown, ApifyKey>(`/scraper/apify-keys/${id}/unmark-exhausted`, {})
}
