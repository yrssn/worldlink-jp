<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance } from 'element-plus'
import { useAuthStore } from '@/store/auth'

const form = reactive({ username: 'admin', password: 'admin123' })
const formRef = ref<FormInstance>()
const loading = ref(false)
const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

async function handleSubmit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    ElMessage.success('登录成功')
    const redirect = (route.query.redirect as string) || '/'
    router.push(redirect)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="login-title">Spider · 建联系统</div>
      <div class="login-sub"> 内部使用</div>
      <el-form ref="formRef" :model="form" label-width="0" @submit.prevent="handleSubmit">
        <el-form-item prop="username" :rules="[{ required: true, message: '请输入用户名' }]">
          <el-input v-model="form.username" placeholder="用户名" size="large" :prefix-icon="'User'" />
        </el-form-item>
        <el-form-item prop="password" :rules="[{ required: true, message: '请输入密码' }]">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            placeholder="密码"
            size="large"
            :prefix-icon="'Lock'"
            @keyup.enter="handleSubmit"
          />
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          style="width: 100%"
          :loading="loading"
          @click="handleSubmit"
        >
          登录
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.login-wrap {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1f2937 0%, #0f172a 100%);
}
.login-card {
  width: 380px;
  background: #fff;
  padding: 36px 32px;
  border-radius: 12px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
}
.login-title {
  font-size: 22px;
  font-weight: 600;
  text-align: center;
  margin-bottom: 6px;
}
.login-sub {
  color: #999;
  text-align: center;
  margin-bottom: 24px;
  font-size: 13px;
}
</style>
