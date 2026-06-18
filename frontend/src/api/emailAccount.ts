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
  email_verification_required: boolean
  email_verified: boolean
  email_already_taken: boolean
  apify_login_attempted: boolean
  apify_logged_in: boolean
  apify_login_email_submitted: boolean
  apify_login_password_submitted: boolean
  apify_login_page_not_found: boolean
  apify_login_url?: string | null
  apify_mail_inbox_ready: boolean
  apify_mail_opened: boolean
  apify_verification_link_clicked: boolean
  apify_token_collected: boolean
  apify_token_collection_attempted: boolean
  apify_key_created: boolean
  apify_key_id?: number | null
  apify_key_is_default: boolean
  apify_full_name?: string | null
  apify_username?: string | null
  apify_user_id?: string | null
  apify_token?: string | null
  apify_registered_at?: string | null
  apify_mail_final_url?: string | null
  apify_mail_hint?: string | null
  apify_settings_final_url?: string | null
  open_hint?: string | null
}

export interface ApifySignupTask {
  id: number
  owner_id: number
  email_account_id: number
  action: string
  status: 'pending' | 'running' | 'paused' | 'done' | 'failed' | string
  current_node?: string | null
  node_started_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  error?: string | null
  logs?: string | null
  result?: ApifySignupStartResult | null
  created_at: string
  updated_at: string
}

export interface ApifySignupTaskPage {
  total: number
  page: number
  page_size: number
  items: ApifySignupTask[]
}

export interface ZohoMailLoginResult {
  ok: boolean
  browser_id: string
  mail_opened: boolean
  mail_login_url?: string | null
  mail_final_url?: string | null
  mail_closed_tab_count: number
  mail_email_submitted: boolean
  mail_password_submitted: boolean
  mail_verification_required: boolean
  verification_mail_opened: boolean
  verification_mail_login_url?: string | null
  verification_mail_final_url?: string | null
  verification_mail_login_submitted: boolean
  verification_mail_inbox_ready: boolean
  verification_mail_code_extracted: boolean
  verification_code?: string | null
  mail_verification_code_submitted: boolean
  mail_verification_final_url?: string | null
  mail_verification_submit_hint?: string | null
  mail_open_hint?: string | null
  verification_mail_open_hint?: string | null
}

export interface VerificationMailLoginResult {
  ok: boolean
  browser_id: string
  verification_mail_opened: boolean
  verification_mail_login_url?: string | null
  verification_mail_final_url?: string | null
  verification_mail_login_submitted: boolean
  verification_mail_inbox_ready: boolean
  verification_mail_code_extracted: boolean
  verification_code?: string | null
  verification_mail_open_hint?: string | null
}

export interface EmailImportField {
  key: string
  label: string
  required: boolean
}

export interface EmailImportColumn {
  index: number
  name: string
}

export interface EmailImportPreview {
  columns: EmailImportColumn[]
  sample_rows: string[][]
  total_rows: number
  fields: EmailImportField[]
  suggested_mapping: Record<string, number>
}

export interface EmailImportResult {
  total: number
  created: number
  skipped: number
  failed: number
  errors: string[]
}

export const emailAccountApi = {
  list: (params?: { q?: string; purpose?: string; status?: string }) =>
    http.get<unknown, EmailAccount[]>('/email/accounts', { params }),
  create: (data: EmailAccountPayload) => http.post<unknown, EmailAccount>('/email/accounts', data),
  update: (id: number, data: EmailAccountPayload) =>
    http.put<unknown, EmailAccount>(`/email/accounts/${id}`, data),
  remove: (id: number) => http.delete<unknown, { ok: boolean }>(`/email/accounts/${id}`),
  startApifySignup: (id: number) =>
    http.post<unknown, ApifySignupTask>(
      `/email/accounts/${id}/apify-signup/start`,
      {},
      { timeout: 60000 }
    ),
  continueApifySignup: (id: number) =>
    http.post<unknown, ApifySignupTask>(
      `/email/accounts/${id}/apify-signup/continue`,
      {},
      { timeout: 60000 }
    ),
  getApifySignupTask: (taskId: number) =>
    http.get<unknown, ApifySignupTask>(`/email/accounts/apify-signup/tasks/${taskId}`),
  listApifySignupTasks: (params?: { account_id?: number; status?: string; page?: number; page_size?: number }) =>
    http.get<unknown, ApifySignupTaskPage>('/email/accounts/apify-signup/tasks', { params }),
  getLatestApifySignupTask: (id: number) =>
    http.get<unknown, ApifySignupTask | null>(`/email/accounts/${id}/apify-signup/tasks/latest`),
  startZohoMailLogin: (id: number) =>
    http.post<unknown, ZohoMailLoginResult>(
      `/email/accounts/${id}/mail-login/zoho`,
      {},
      { timeout: 60000 }
    ),
  startVerificationMailLogin: (id: number) =>
    http.post<unknown, VerificationMailLoginResult>(
      `/email/accounts/${id}/mail-login/verification`,
      {},
      { timeout: 60000 }
    ),
  importPreview: (file: File, sampleSize = 5) => {
    const formData = new FormData()
    formData.append('file', file)
    return http.post<unknown, EmailImportPreview>(
      `/email/accounts/import/preview?sample_size=${sampleSize}`,
      formData,
      { timeout: 60000 }
    )
  },
  importAccounts: (file: File, mapping: Record<string, number>, skipDuplicates = true) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('mapping', JSON.stringify(mapping))
    formData.append('skip_duplicates', String(skipDuplicates))
    return http.post<unknown, EmailImportResult>('/email/accounts/import', formData, {
      timeout: 120000
    })
  }
}
