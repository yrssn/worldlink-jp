import http from './http'

export interface Country {
  id: number
  owner_id?: number | null
  /** 中文名，如 日本 */
  name_zh: string
  /** 英文名，如 Japan */
  name_en?: string | null
  /** 国家代码，如 JP */
  code?: string | null
  remark?: string | null
  sort_order: number
  /** 后端拼好的「中文 / English」 */
  label: string
  created_at: string
  updated_at: string
}

export interface CountryPayload {
  name_zh: string
  name_en?: string | null
  code?: string | null
  remark?: string | null
  sort_order?: number
}

export const countryApi = {
  list: () => http.get<unknown, Country[]>('/countries'),
  create: (body: CountryPayload) => http.post<unknown, Country>('/countries', body),
  update: (id: number, body: Partial<CountryPayload>) =>
    http.put<unknown, Country>(`/countries/${id}`, body),
  remove: (id: number) => http.delete<unknown, { ok: boolean }>(`/countries/${id}`),
}
