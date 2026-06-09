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

export interface ApifySignupStartResult {
  ok: boolean
  browser_id: string
  signup_url: string
  first_url: string
  final_url: string
  logged_out: boolean
  session_cleared: boolean
  profile_cookies_cleared: boolean
  profile_cookie_config_cleared: boolean
  cleared_cookie_count: number
  all_cookies_cleared: boolean
  still_logged_in: boolean
  ready: boolean
  email_submitted: boolean
  password_submitted: boolean
  profile_submitted: boolean
  captcha_required: boolean
  open_hint?: string | null
}

export const emailAccountApi = {
  list: (params?: { q?: string; purpose?: string; status?: string }) =>
    http.get<unknown, EmailAccount[]>('/email/accounts', { params }),
  create: (data: EmailAccountPayload) => http.post<unknown, EmailAccount>('/email/accounts', data),
  update: (id: number, data: EmailAccountPayload) =>
    http.put<unknown, EmailAccount>(`/email/accounts/${id}`, data),
  remove: (id: number) => http.delete<unknown, { ok: boolean }>(`/email/accounts/${id}`),
  startApifySignup: (id: number) =>
    http.post<unknown, ApifySignupStartResult>(
      `/email/accounts/${id}/apify-signup/start`,
      {},
      { timeout: 180000 }
    ),
  continueApifySignup: (id: number) =>
    http.post<unknown, ApifySignupStartResult>(
      `/email/accounts/${id}/apify-signup/continue`,
      {},
      { timeout: 60000 }
    )
}
