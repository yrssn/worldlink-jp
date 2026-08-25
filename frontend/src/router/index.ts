import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/store/auth'
import { usePermissionStore } from '@/store/permission'

/**
 * 路由权限：每条业务路由的 ``meta.code`` 与后端 ``menus.code`` 一一对应，
 * 守卫里用「我的权限」返回的 menu_codes 判断能否进入；后端另有同名校验
 * （见 backend/app/core/permission_guard.py），前端隐藏只是体验层。
 */
const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/login/LoginView.vue'),
    meta: { public: true }
  },
  {
    path: '/403',
    name: 'forbidden',
    component: () => import('@/views/error/ForbiddenView.vue'),
    meta: { public: true }
  },
  {
    path: '/',
    component: () => import('@/layouts/BasicLayout.vue'),
    children: [
      {
        path: '',
        name: 'home',
        redirect: () => usePermissionStore().landingPath
      },
      {
        path: 'email/accounts',
        name: 'email-accounts',
        component: () => import('@/views/email/EmailAccountsView.vue'),
        meta: { title: '邮箱管理', code: 'email:accounts' }
      },
      {
        path: 'llm/providers',
        name: 'llm-providers',
        component: () => import('@/views/llm/ProvidersView.vue'),
        meta: { title: '大模型配置', code: 'llm:providers' }
      },
      {
        path: 'llm/prompts',
        name: 'llm-prompts',
        component: () => import('@/views/llm/PromptsView.vue'),
        meta: { title: '提示词模板', code: 'llm:prompts' }
      },
      {
        path: 'scraper/tasks',
        name: 'scraper-tasks',
        component: () => import('@/views/scraper/TasksView.vue'),
        meta: { title: '抓取任务', code: 'scraper:tasks' }
      },
      {
        path: 'scraper/tasks/:id',
        name: 'scraper-task-detail',
        component: () => import('@/views/scraper/TaskDetailView.vue'),
        meta: { title: '任务详情', code: 'scraper:task-detail' }
      },
      {
        path: 'scraper/facebook-groups',
        name: 'scraper-facebook-groups',
        component: () => import('@/views/scraper/facebook-group/FbGroupScrapesView.vue'),
        meta: { title: 'Facebook群组维度抓取', code: 'scraper:fb-groups' }
      },
      {
        path: 'scraper/apify-keys',
        name: 'scraper-apify-keys',
        component: () => import('@/views/scraper/ApifyKeysView.vue'),
        meta: { title: 'Apify Key 管理', code: 'scraper:apify-keys' }
      },
      {
        path: 'bitbrowser/connect',
        name: 'bitbrowser-connect',
        component: () => import('@/views/bitbrowser/connect/ConnectView.vue'),
        meta: { title: '本机连接', code: 'bitbrowser:connect' }
      },
      {
        path: 'bitbrowser/windows',
        name: 'bitbrowser-windows',
        component: () => import('@/views/bitbrowser/WindowsView.vue'),
        meta: { title: '浏览器窗口', code: 'bitbrowser:windows' }
      },
      {
        path: 'bitbrowser/saved',
        name: 'bitbrowser-saved',
        component: () => import('@/views/bitbrowser/saved/SavedCatalogView.vue'),
        meta: { title: '系统登记', code: 'bitbrowser:saved' }
      },
      {
        path: 'bitbrowser/platforms',
        name: 'bitbrowser-platforms',
        component: () => import('@/views/bitbrowser/PlatformsView.vue'),
        meta: { title: '平台管理', code: 'bitbrowser:platforms' }
      },
      {
        path: 'dm/contents',
        name: 'dm-contents',
        component: () => import('@/views/dm/ContentsView.vue'),
        meta: { title: '私信内容库', code: 'dm:contents' }
      },
      {
        path: 'dm/categories',
        name: 'dm-categories',
        component: () => import('@/views/dm/CategoriesView.vue'),
        meta: { title: '私信分类', code: 'dm:categories' }
      },
      {
        path: 'influencers',
        name: 'influencers',
        component: () => import('@/views/influencer/InfluencersView.vue'),
        meta: { title: '建联达人', code: 'influencers' }
      },
      {
        path: 'influencers/:id',
        name: 'influencer-detail',
        component: () => import('@/views/influencer/InfluencerDetailView.vue'),
        meta: { title: '达人详情', code: 'influencer:detail' }
      },
      {
        path: 'system/users',
        name: 'system-users',
        component: () => import('@/views/system/UsersView.vue'),
        meta: { title: '用户列表', code: 'system:users' }
      },
      {
        path: 'system/roles',
        name: 'system-roles',
        component: () => import('@/views/system/RolesView.vue'),
        meta: { title: '角色权限', code: 'system:roles' }
      },
      {
        path: 'system/menus',
        name: 'system-menus',
        component: () => import('@/views/system/MenusView.vue'),
        meta: { title: '路由列表', code: 'system:menus' }
      }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach(async (to) => {
  if (to.meta.public) return true
  const auth = useAuthStore()
  if (!auth.isAuthed) return { path: '/login', query: { redirect: to.fullPath } }

  const perm = usePermissionStore()
  if (!auth.user || !perm.loaded) {
    try {
      if (!auth.user) await auth.fetchMe()
      await perm.load()
    } catch (e) {
      auth.clear()
      perm.clear()
      return { path: '/login' }
    }
  }

  const code = to.meta.code as string | undefined
  if (code && !perm.has(code)) return { path: '/403' }
  return true
})

export default router
