<template>
  <a-layout >
    <!-- 顶部：全局导航 -->
    <div >
      <div >
        <img :src="logoWhite"  alt="Neurova" @click="$router.push('/dashboard')" />
        <AppSidebar />
      </div>
      <div >
        <a-badge :count="3" size="small">
          <a-button type="text"  @click="$router.push('/notifications')">
            <BellOutlined />
          </a-button>
        </a-badge>
        <a-dropdown>
          <div >
            <a-avatar size="small" >{{ usernameC }}</a-avatar>
            <span >{{ authStore.currentUser?.username || '用户' }}</span>
            <CaretDownOutlined  />
          </div>
          <template #overlay>
            <a-menu >
              <a-menu-item key="profile" @click="$router.push('/settings')">
                <UserOutlined /> 个人设置
              </a-menu-item>
              <a-menu-divider />
              <a-menu-item key="logout" @click="handleLogout">
                <LogoutOutlined /> 退出登录
              </a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>
      </div>
    </div>
    <!-- 下方：左侧 Agent 边栏 + 主内容 -->
    <div >
      <AgentSidebar />
      <a-layout-content >
        <div >
          <router-view v-slot="{ Component }">
            <Transition name="fade-slide" mode="out-in">
              <component :is="Component" />
            </Transition>
          </router-view>
        </div>
      </a-layout-content>
    </div>
  </a-layout>
</template>
<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useAgentStore } from '@/stores/agents'
import AppSidebar from '@/components/AppSidebar.vue'
import AgentSidebar from '@/components/AgentSidebar.vue'
import logoWhite from '@/assets/img/NEUROVA-white.png'
import {
  BellOutlined, CaretDownOutlined,
  UserOutlined, LogoutOutlined,
} from '@ant-design/icons-vue'
const router = useRouter()
const authStore = useAuthStore()
const agentStore = useAgentStore()
const usernameC = computed(() => {
  return (authStore.currentUser?.username || 'U')[0].toUpperCase()
})
async function handleLogout() {
  await authStore.logout()
  router.push('/login')
}
onMounted(() => {
  if (agentStore.agents.length === 0) {
    agentStore.loadAgents()
  }
})
</script>
<style scoped>
.main-layout {
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  background: #0a0e27;
  display: flex;
  flex-direction: column;
}
/* 顶部栏 */
.top-bar {
  flex-shrink: 0;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  background: rgba(10, 14, 39, 0.98);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  z-index: 200;
}
.top-bar__left {
  display: flex;
  align-items: center;
  gap: 8px;
  overflow: hidden;
  flex: 1;
  min-width: 0;
}
.top-logo {
  height: 28px;
  cursor: pointer;
  flex-shrink: 0;
  margin-right: 4px;
}
.top-bar__right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  margin-left: 16px;
}
.top-icon-btn {
  color: rgba(255, 255, 255, 0.5) !important;
  font-size: 1.1rem;
}
.top-icon-btn:hover {
  color: rgba(255, 255, 255, 0.85) !important;
}
.user-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px 4px 4px;
  border-radius: 20px;
  cursor: pointer;
  transition: background 0.2s;
  border: 1px solid transparent;
}
.user-trigger:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.1);
}
.user-avatar {
  background: linear-gradient(135deg, #3b82f6, #8b5cf6) !important;
}
.user-name {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.7);
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-caret {
  font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.35);
}
:deep(.user-menu) {
  background: rgba(20, 25, 50, 0.96) !important;
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  padding: 4px;
}
:deep(.user-menu .ant-dropdown-menu-item) {
  color: rgba(255, 255, 255, 0.75) !important;
  border-radius: 6px;
}
:deep(.user-menu .ant-dropdown-menu-item:hover) {
  background: rgba(255, 255, 255, 0.06) !important;
}
/* 下方主体 */
.main-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}
/* 主内容区 */
.main-content {
  flex: 1;
  overflow: auto;
  background: transparent !important;
}
.content-wrapper {
  min-height: 100%;
  padding: 24px;
}
/* 页面切换动画 */
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(16px) scale(0.98);
}
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-12px) scale(0.98);
}
</style>
 