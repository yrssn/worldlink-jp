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
