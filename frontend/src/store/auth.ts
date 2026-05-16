import { defineStore } from 'pinia'
import { authApi, type UserOut } from '@/api/auth'

interface AuthState {
  accessToken: string
  refreshToken: string
  user: UserOut | null
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    accessToken: localStorage.getItem('access_token') || '',
    refreshToken: localStorage.getItem('refresh_token') || '',
    user: null
  }),
  getters: {
    isAuthed: (s) => !!s.accessToken,
    isAdmin: (s) => s.user?.role === 'admin'
  },
  actions: {
    async login(username: string, password: string) {
      const r = await authApi.login({ username, password })
      this.setTokens(r.access_token, r.refresh_token)
      await this.fetchMe()
    },
    setTokens(access: string, refresh: string) {
      this.accessToken = access
      this.refreshToken = refresh
      localStorage.setItem('access_token', access)
      localStorage.setItem('refresh_token', refresh)
    },
    async fetchMe() {
      this.user = await authApi.me()
    },
    async logout() {
      try {
        if (this.refreshToken) await authApi.logout(this.refreshToken)
      } catch (e) {
        // ignore
      }
      this.clear()
    },
    clear() {
      this.accessToken = ''
      this.refreshToken = ''
      this.user = null
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
    }
  }
})
