import http from './http'

export interface EmailAccount {
  id: number
  owner_id: number
  email: string
  email_password?: string | null
  provider?: string | null
  mail_login_url?: string | null
  verification_email?: string | null
  verification_password?: string | null
  verification_login_url?: string | null
  purpose: string
  status: string
  browser_id?: string | null
  last_verification_code?: string | null
  last_verification_at?: string | null
  note?: string | null
  created_at: string
  updated_at: string
}

export interface EmailAccountPayload {
  email?: string
  email_password?: string | null
  provider?: string | null
  mail_login_url?: string | null
  verification_email?: string | null
  verification_password?: string | null
  verification_login_url?: string | null
  purpose?: string
  status?: string
  browser_id?: string | null
  last_verification_code?: string | null
  last_verification_at?: string | null
  note?: string | null
}

export const emailAccountApi = {
  list: (params?: { q?: string; purpose?: string; status?: string }) =>
    http.get<unknown, EmailAccount[]>('/email/accounts', { params }),
  create: (data: EmailAccountPayload) => http.post<unknown, EmailAccount>('/email/accounts', data),
  update: (id: number, data: EmailAccountPayload) =>
    http.put<unknown, EmailAccount>(`/email/accounts/${id}`, data),
  remove: (id: number) => http.delete<unknown, { ok: boolean }>(`/email/accounts/${id}`)
}
