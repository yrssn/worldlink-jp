<script setup lang="ts">
import { useRouter } from 'vue-router'
import { usePermissionStore } from '@/store/permission'

const router = useRouter()
const perm = usePermissionStore()

function goHome() {
  router.push(perm.loaded ? perm.landingPath : '/')
}
</script>

<template>
  <div style="padding: 80px 0">
    <el-result icon="warning" title="403" sub-title="没有该页面的访问权限，请联系管理员分配角色">
      <template #extra>
        <el-button type="primary" @click="goHome">返回可访问页面</el-button>
      </template>
    </el-result>
  </div>
</template>
