import http from './http'

export interface LoginPayload {
  username: string
  password: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface UserOut {
  id: number
  username: string
  role: 'admin' | 'user'
  is_active: boolean
  email?: string | null
  full_name?: string | null
}

export const authApi = {
  login: (data: LoginPayload) => http.post<unknown, TokenResponse>('/auth/login', data),
  me: () => http.get<unknown, UserOut>('/auth/me'),
  refresh: (refresh_token: string) =>
    http.post<unknown, TokenResponse>('/auth/refresh', { refresh_token }),
  logout: (refresh_token: string) => http.post('/auth/logout', { refresh_token })
}
