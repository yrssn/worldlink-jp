import { defineStore } from 'pinia'
import { systemApi, type MenuTree, type MyPermission } from '@/api/system'

interface PermissionState {
  loaded: boolean
  isSuperAdmin: boolean
  dataScope: 'own' | 'all'
  menuCodes: string[]
  menus: MenuTree[]
}

/** 第一个可访问的叶子路由，登录后 / 无权限时用作落地页。 */
function firstPath(menus: MenuTree[]): string | null {
  for (const m of menus) {
    if (m.path && !m.is_hidden && !m.path.includes(':')) return m.path
    const child = firstPath(m.children || [])
    if (child) return child
  }
  return null
}

export const usePermissionStore = defineStore('permission', {
  state: (): PermissionState => ({
    loaded: false,
    isSuperAdmin: false,
    dataScope: 'own',
    menuCodes: [],
    menus: []
  }),
  getters: {
    /** 侧边栏使用的菜单树（过滤隐藏项与空目录） */
    sidebarMenus: (s): MenuTree[] => {
      const walk = (nodes: MenuTree[]): MenuTree[] =>
        nodes
          .filter((n) => !n.is_hidden && n.is_active)
          .map((n) => ({ ...n, children: walk(n.children || []) }))
          .filter((n) => n.type !== 'catalog' || n.children.length > 0)
      return walk(s.menus)
    },
    /** 登录后的落地页：第一个有权限的可见路由，没有则去 403 提示联系管理员 */
    landingPath: (s): string => firstPath(s.menus) || '/403'
  },
  actions: {
    has(code?: string) {
      if (!code) return true
      return this.isSuperAdmin || this.menuCodes.includes(code)
    },
    async load(force = false) {
      if (this.loaded && !force) return
      const r: MyPermission = await systemApi.myPermissions()
      this.isSuperAdmin = r.is_super_admin
      this.dataScope = r.data_scope
      this.menuCodes = r.menu_codes
      this.menus = r.menus
      this.loaded = true
    },
    clear() {
      this.loaded = false
      this.isSuperAdmin = false
      this.dataScope = 'own'
      this.menuCodes = []
      this.menus = []
    }
  }
})
