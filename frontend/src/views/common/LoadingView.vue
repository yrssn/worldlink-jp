<template>
  <!-- 首页占位：路由守卫会在权限加载完成后跳到落地页 -->
  <div v-loading="true" class="home-placeholder" />
</template>

<style scoped>
.home-placeholder {
  height: 240px;
}
</style>
