import http from './http'

export interface AiApiKey {
  id: number
  owner_id: number
  name: string
  key_prefix: string
  is_active: boolean
  expires_at?: string | null
  last_used_at?: string | null
  last_used_ip?: string | null
  created_at: string
}

export interface AiApiKeyCreated extends AiApiKey {
  /** 完整明文密钥，仅创建时返回这一次 */
  key: string
}

export interface AiApiKeyCreate {
  name: string
  expires_at?: string | null
  /** 超级管理员可指定属主，替其他用户生成 */
  owner_id?: number | null
}

export interface AiApiKeyUpdate {
  name?: string
  is_active?: boolean
  expires_at?: string | null
}

export interface AiApiCallLog {
  id: number
  key_id?: number | null
  key_name?: string | null
  action: string
  status: 'ok' | 'error' | string
  error?: string | null
  detail?: Record<string, unknown> | null
  created_at: string
}

export interface AiApiCallLogPage {
  total: number
  page: number
  page_size: number
  items: AiApiCallLog[]
}

export const aiWorkshopApi = {
  listKeys: (params?: { owner_id?: number }) =>
    http.get<unknown, AiApiKey[]>('/ai/keys', { params }),
  createKey: (data: AiApiKeyCreate) => http.post<unknown, AiApiKeyCreated>('/ai/keys', data),
  updateKey: (id: number, data: AiApiKeyUpdate) =>
    http.put<unknown, AiApiKey>(`/ai/keys/${id}`, data),
  removeKey: (id: number) => http.delete<unknown, { ok: boolean }>(`/ai/keys/${id}`),
  listLogs: (params: { page?: number; page_size?: number; key_id?: number }) =>
    http.get<unknown, AiApiCallLogPage>('/ai/logs', { params })
}
