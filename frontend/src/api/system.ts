import http from './http'

export type MenuType = 'catalog' | 'menu' | 'button'
export type ApiEnforceMode = 'all' | 'write' | 'off'
export type DataScope = 'own' | 'all'

export interface Menu {
  id: number
  code: string
  title: string
  parent_id: number | null
  path: string | null
  icon: string | null
  sort_order: number
  type: MenuType
  is_hidden: boolean
  is_active: boolean
  is_builtin: boolean
  api_prefixes: string[]
  api_enforce_mode: ApiEnforceMode
  remark: string | null
}

export interface MenuTree extends Menu {
  children: MenuTree[]
}

export interface MenuPayload {
  code: string
  title: string
  parent_id?: number | null
  path?: string | null
  icon?: string | null
  sort_order?: number
  type?: MenuType
  is_hidden?: boolean
  is_active?: boolean
  api_prefixes?: string[]
  api_enforce_mode?: ApiEnforceMode
  remark?: string | null
}

export interface Role {
  id: number
  code: string
  name: string
  remark: string | null
  data_scope: DataScope
  is_active: boolean
  is_builtin: boolean
  sort_order: number
  menu_ids: number[]
  user_count: number
}

export interface RolePayload {
  code: string
  name: string
  remark?: string | null
  data_scope?: DataScope
  is_active?: boolean
  sort_order?: number
  menu_ids?: number[]
}

export interface RoleBrief {
  id: number
  code: string
  name: string
  data_scope: DataScope
}

export interface SysUser {
  id: number
  username: string
  email: string | null
  full_name: string | null
  role: 'admin' | 'user'
  is_active: boolean
  created_at: string | null
  roles: RoleBrief[]
  is_super_admin: boolean
}

export interface SysUserPayload {
  email?: string | null
  full_name?: string | null
  is_active?: boolean
  role_ids?: number[]
}

export interface MyPermission {
  user: SysUser
  is_super_admin: boolean
  data_scope: DataScope
  menu_codes: string[]
  menus: MenuTree[]
}

export const systemApi = {
  myPermissions: () => http.get<unknown, MyPermission>('/system/profile/permissions'),
  changeMyPassword: (old_password: string, new_password: string) =>
    http.post('/system/profile/password', { old_password, new_password }),

  listMenus: () => http.get<unknown, Menu[]>('/system/menus'),
  menuTree: () => http.get<unknown, MenuTree[]>('/system/menus/tree'),
  createMenu: (data: MenuPayload) => http.post<unknown, Menu>('/system/menus', data),
  updateMenu: (id: number, data: Partial<MenuPayload>) =>
    http.put<unknown, Menu>(`/system/menus/${id}`, data),
  deleteMenu: (id: number) => http.delete(`/system/menus/${id}`),

  listRoles: () => http.get<unknown, Role[]>('/system/roles'),
  createRole: (data: RolePayload) => http.post<unknown, Role>('/system/roles', data),
  updateRole: (id: number, data: Partial<RolePayload>) =>
    http.put<unknown, Role>(`/system/roles/${id}`, data),
  deleteRole: (id: number) => http.delete(`/system/roles/${id}`),

  listUsers: () => http.get<unknown, SysUser[]>('/system/users'),
  createUser: (data: SysUserPayload & { username: string; password: string }) =>
    http.post<unknown, SysUser>('/system/users', data),
  updateUser: (id: number, data: SysUserPayload) =>
    http.put<unknown, SysUser>(`/system/users/${id}`, data),
  resetPassword: (id: number, password: string) =>
    http.post(`/system/users/${id}/password`, { password }),
  disableUser: (id: number) => http.delete(`/system/users/${id}`)
}
