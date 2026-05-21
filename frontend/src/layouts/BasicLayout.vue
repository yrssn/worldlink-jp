<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/store/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const activeMenu = computed(() => route.path)

async function handleLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<template>
  <el-container style="height: 100vh">
    <el-aside width="220px" style="background: #001529">
      <div
        style="
          color: #fff;
          font-size: 16px;
          font-weight: 600;
          padding: 18px 16px;
          letter-spacing: 1px;
        "
      >
        Spider · 建联系统
      </div>
      <el-menu
        :default-active="activeMenu"
        background-color="#001529"
        text-color="#cfd8dc"
        active-text-color="#ffffff"
        router
      >
        <el-sub-menu index="llm">
          <template #title>
            <el-icon><Cpu /></el-icon>
            <span>大模型</span>
          </template>
          <el-menu-item index="/llm/providers">厂商配置</el-menu-item>
          <el-menu-item index="/llm/prompts">提示词模板</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="bitbrowser">
          <template #title>
            <el-icon><Monitor /></el-icon>
            <span>比特抓取</span>
          </template>
          <el-menu-item index="/bitbrowser/connect">本机连接</el-menu-item>
          <el-menu-item index="/bitbrowser/windows">浏览器窗口</el-menu-item>
          <el-menu-item index="/bitbrowser/saved">系统登记</el-menu-item>
          <el-menu-item index="/bitbrowser/platforms">平台管理</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="scraper">
          <template #title>
            <el-icon><Search /></el-icon>
            <span>抓取器</span>
          </template>
          <el-menu-item index="/scraper/tasks">抓取任务</el-menu-item>
          <el-menu-item index="/scraper/facebook-groups">Facebook群组维度</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="dm">
          <template #title>
            <el-icon><ChatDotRound /></el-icon>
            <span>私信内容</span>
          </template>
          <el-menu-item index="/dm/contents">内容库</el-menu-item>
          <el-menu-item index="/dm/categories">分类管理</el-menu-item>
        </el-sub-menu>
        <el-menu-item index="/influencers">
          <el-icon><User /></el-icon>
          <span>建联达人</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header
        style="
          background: #fff;
          display: flex;
          align-items: center;
          justify-content: space-between;
          border-bottom: 1px solid #f0f0f0;
        "
      >
        <span style="font-size: 16px; font-weight: 500">{{ route.meta?.title || '' }}</span>
        <el-dropdown>
          <span style="cursor: pointer">
            <el-icon><UserFilled /></el-icon>
            {{ auth.user?.username }}
            <el-tag v-if="auth.isAdmin" size="small" type="warning" style="margin-left: 6px">
              admin
            </el-tag>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="handleLogout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>

      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>
