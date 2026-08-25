<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/store/auth'
import { usePermissionStore } from '@/store/permission'
import { systemApi } from '@/api/system'
import { useBitBrowserRelay } from '@/composables/useBitBrowserRelay'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const perm = usePermissionStore()

const activeMenu = computed(() => route.path)
// 侧边栏由后端「我的权限」返回的菜单树渲染，未授权的路由不会出现
const menus = computed(() => perm.sidebarMenus)
const defaultOpeneds = computed(() =>
  menus.value.filter((m) => m.type === 'catalog').map((m) => String(m.id))
)
const { connect: relayConnect, disconnect: relayDisconnect } = useBitBrowserRelay()

const pwdVisible = ref(false)
const pwdForm = reactive({ old_password: '', new_password: '', confirm: '' })

onMounted(() => relayConnect())
onUnmounted(() => relayDisconnect())

async function handleLogout() {
  relayDisconnect()
  await auth.logout()
  perm.clear()
  router.push('/login')
}

function openPwd() {
  pwdForm.old_password = ''
  pwdForm.new_password = ''
  pwdForm.confirm = ''
  pwdVisible.value = true
}

async function submitPwd() {
  if (pwdForm.new_password.length < 6) {
    ElMessage.warning('新密码至少 6 位')
    return
  }
  if (pwdForm.new_password !== pwdForm.confirm) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  try {
    await systemApi.changeMyPassword(pwdForm.old_password, pwdForm.new_password)
    ElMessage.success('密码已修改')
    pwdVisible.value = false
  } catch {
    /* 拦截器已提示 */
  }
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
        :default-openeds="defaultOpeneds"
        background-color="#001529"
        text-color="#cfd8dc"
        active-text-color="#ffffff"
        router
      >
        <template v-for="m in menus" :key="m.id">
          <el-sub-menu v-if="m.type === 'catalog'" :index="String(m.id)">
            <template #title>
              <el-icon v-if="m.icon"><component :is="m.icon" /></el-icon>
              <span>{{ m.title }}</span>
            </template>
            <el-menu-item v-for="c in m.children" :key="c.id" :index="c.path || ''">
              {{ c.title }}
            </el-menu-item>
          </el-sub-menu>
          <el-menu-item v-else :index="m.path || ''">
            <el-icon v-if="m.icon"><component :is="m.icon" /></el-icon>
            <span>{{ m.title }}</span>
          </el-menu-item>
        </template>
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
            <el-tag v-if="perm.isSuperAdmin" size="small" type="warning" style="margin-left: 6px">
              超级管理员
            </el-tag>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="openPwd">修改密码</el-dropdown-item>
              <el-dropdown-item divided @click="handleLogout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>

      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>

  <el-dialog v-model="pwdVisible" title="修改密码" width="420px">
    <el-form label-width="90px">
      <el-form-item label="原密码">
        <el-input v-model="pwdForm.old_password" type="password" show-password />
      </el-form-item>
      <el-form-item label="新密码">
        <el-input v-model="pwdForm.new_password" type="password" show-password />
      </el-form-item>
      <el-form-item label="确认新密码">
        <el-input v-model="pwdForm.confirm" type="password" show-password />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="pwdVisible = false">取消</el-button>
      <el-button type="primary" @click="submitPwd">保存</el-button>
    </template>
  </el-dialog>
</template>
