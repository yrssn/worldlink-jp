import http from './http'

export interface BitBrowserWindow {
  id: number
  owner_id: number
  browser_id: string
  seq?: number | null
  name?: string | null
  remark?: string | null
  platform?: string | null
  group_id?: string | null
  proxy_method?: number | null
  proxy_type?: string | null
  host?: string | null
  port?: string | null
  last_ip?: string | null
  account_username?: string | null
  status?: number | null
  raw_snapshot?: Record<string, unknown> | null
  created_at: string
  updated_at: string
  saved_to_system?: boolean
  catalog_platform_id?: number | null
  catalog_platform_name?: string | null
  catalog_note?: string | null
  catalog_in_local_cache?: boolean | null
}

/** GET /bitbrowser/catalog 一行（系统登记 + 可选本机缓存快照） */
export interface BitBrowserCatalogRow {
  id: number
  owner_id: number
  browser_id: string
  platform_id?: number | null
  platform_name?: string | null
  note?: string | null
  cached_window_name?: string | null
  cached_env_platform?: string | null
  in_local_cache: boolean
  created_at: string
  updated_at: string
  seq?: number | null
  name?: string | null
  platform?: string | null
  remark?: string | null
  proxy_type?: string | null
  host?: string | null
  port?: string | null
  last_ip?: string | null
  account_username?: string | null
  status?: number | null
  window_updated_at?: string | null
}

export interface BitBrowserSyncResult {
  fetched: number
  upserted: number
  removed_stale: number
  last_sync_at?: string | null
}

export interface BitBrowserSyncMeta {
  last_sync_at?: string | null
  cached_rows: number
}

export interface BitBrowserSettings {
  local_url: string | null
  has_api_key: boolean
}

export interface BitBrowserOpenResponse {
  success: boolean
  data: Record<string, unknown>
}

export interface BitBrowserPlatform {
  id: number
  owner_id: number
  name: string
  code?: string | null
  remark?: string | null
  sort_order: number
  created_at: string
  updated_at: string
}

export interface BitBrowserPlatformCreate {
  name: string
  code?: string | null
  remark?: string | null
  sort_order?: number
}

export interface BitBrowserPlatformUpdate {
  name?: string
  code?: string | null
  remark?: string | null
  sort_order?: number
}

export const bitbrowserApi = {
  getSettings: () => http.get<unknown, BitBrowserSettings>('/bitbrowser/settings'),
  updateSettings: (body: { local_url: string; api_key?: string }) =>
    http.put<unknown, BitBrowserSettings>('/bitbrowser/settings', body),

  listPlatforms: () => http.get<unknown, BitBrowserPlatform[]>('/bitbrowser/platforms'),
  createPlatform: (body: BitBrowserPlatformCreate) =>
    http.post<unknown, BitBrowserPlatform>('/bitbrowser/platforms', body),
  updatePlatform: (id: number, body: BitBrowserPlatformUpdate) =>
    http.put<unknown, BitBrowserPlatform>(`/bitbrowser/platforms/${id}`, body),
  deletePlatform: (id: number) => http.delete<unknown, { ok: boolean }>(`/bitbrowser/platforms/${id}`),

  listWindows: (opts?: { savedOnly?: boolean }) =>
    http.get<unknown, BitBrowserWindow[]>('/bitbrowser/windows', {
      params: opts?.savedOnly ? { saved_only: true } : {}
    }),
  listCatalog: () => http.get<unknown, BitBrowserCatalogRow[]>('/bitbrowser/catalog'),
  syncMeta: () => http.get<unknown, BitBrowserSyncMeta>('/bitbrowser/sync-meta'),
  syncWindows: () =>
    http.post<unknown, BitBrowserSyncResult>('/bitbrowser/windows/sync', {}, { timeout: 600000 }),
  saveWindowCatalog: (browserId: string, body: { platform_id?: number | null; note?: string | null }) =>
    http.put<unknown, unknown>(`/bitbrowser/windows/${encodeURIComponent(browserId)}/catalog`, body),
  deleteWindowCatalog: (browserId: string) =>
    http.delete<unknown, { ok: boolean }>(`/bitbrowser/windows/${encodeURIComponent(browserId)}/catalog`),
  openWindow: (browserId: string, opts?: { headless?: boolean }) =>
    http.post<unknown, BitBrowserOpenResponse>(
      `/bitbrowser/windows/${encodeURIComponent(browserId)}/open`,
      {},
      {
        timeout: 180000,
        params: opts?.headless ? { headless: true } : {}
      }
    ),
  localHealth: () =>
    http.get<unknown, { ok: boolean; bitbrowser?: unknown; error?: string; hint?: string; auth_hint?: string }>(
      '/bitbrowser/local-health'
    )
}
