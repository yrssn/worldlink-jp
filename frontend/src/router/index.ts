import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/store/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/login/LoginView.vue'),
    meta: { public: true }
  },
  {
    path: '/',
    component: () => import('@/layouts/BasicLayout.vue'),
    redirect: '/scraper/tasks',
    children: [
      {
        path: 'email/accounts',
        name: 'email-accounts',
        component: () => import('@/views/email/EmailAccountsView.vue'),
        meta: { title: '邮箱管理' }
      },
      {
        path: 'llm/providers',
        name: 'llm-providers',
        component: () => import('@/views/llm/ProvidersView.vue'),
        meta: { title: '大模型配置' }
      },
      {
        path: 'llm/prompts',
        name: 'llm-prompts',
        component: () => import('@/views/llm/PromptsView.vue'),
        meta: { title: '提示词模板' }
      },
      {
        path: 'scraper/tasks',
        name: 'scraper-tasks',
        component: () => import('@/views/scraper/TasksView.vue'),
        meta: { title: '抓取任务' }
      },
      {
        path: 'scraper/tasks/:id',
        name: 'scraper-task-detail',
        component: () => import('@/views/scraper/TaskDetailView.vue'),
        meta: { title: '任务详情' }
      },
      {
        path: 'scraper/facebook-groups',
        name: 'scraper-facebook-groups',
        component: () => import('@/views/scraper/facebook-group/FbGroupScrapesView.vue'),
        meta: { title: 'Facebook群组维度抓取' }
      },
      {
        path: 'scraper/apify-keys',
        name: 'scraper-apify-keys',
        component: () => import('@/views/scraper/ApifyKeysView.vue'),
        meta: { title: 'Apify Key 管理' }
      },
      {
        path: 'bitbrowser/connect',
        name: 'bitbrowser-connect',
        component: () => import('@/views/bitbrowser/connect/ConnectView.vue'),
        meta: { title: '本机连接' }
      },
      {
        path: 'bitbrowser/windows',
        name: 'bitbrowser-windows',
        component: () => import('@/views/bitbrowser/WindowsView.vue'),
        meta: { title: '浏览器窗口' }
      },
      {
        path: 'bitbrowser/saved',
        name: 'bitbrowser-saved',
        component: () => import('@/views/bitbrowser/saved/SavedCatalogView.vue'),
        meta: { title: '系统登记' }
      },
      {
        path: 'bitbrowser/platforms',
        name: 'bitbrowser-platforms',
        component: () => import('@/views/bitbrowser/PlatformsView.vue'),
        meta: { title: '平台管理' }
      },
      {
        path: 'dm/contents',
        name: 'dm-contents',
        component: () => import('@/views/dm/ContentsView.vue'),
        meta: { title: '私信内容库' }
      },
      {
        path: 'dm/categories',
        name: 'dm-categories',
        component: () => import('@/views/dm/CategoriesView.vue'),
        meta: { title: '私信分类' }
      },
      {
        path: 'influencers',
        name: 'influencers',
        component: () => import('@/views/influencer/InfluencersView.vue'),
        meta: { title: '建联达人' }
      },
      {
        path: 'influencers/:id',
        name: 'influencer-detail',
        component: () => import('@/views/influencer/InfluencerDetailView.vue'),
        meta: { title: '达人详情' }
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
  if (!auth.user) {
    try {
      await auth.fetchMe()
    } catch (e) {
      auth.clear()
      return { path: '/login' }
    }
  }
  return true
})

export default router
