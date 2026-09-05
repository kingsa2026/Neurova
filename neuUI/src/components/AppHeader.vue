<template>
  <a-layout-header class="app-header">
    <div class="header-left">
      <!-- 移动端菜单按钮 -->
      <a-button type="text" class="mobile-menu-btn" @click="emit('toggle-sidebar')">
        <MenuOutlined />
      </a-button>

      <!-- 面包屑 -->
      <a-breadcrumb class="header-breadcrumb">
        <a-breadcrumb-item v-for="item in breadcrumbs" :key="item.path || item.title">
          <router-link v-if="item.path" :to="item.path" class="breadcrumb-link">
            {{ item.icon }} {{ item.title }}
          </router-link>
          <span v-else class="breadcrumb-current">{{ item.title }}</span>
        </a-breadcrumb-item>
      </a-breadcrumb>
    </div>

    <div class="header-right">
      <!-- 搜索 -->
      <a-input-search
        class="header-search"
        placeholder="搜索功能..."
        :bordered="false"
      />

      <!-- 通知 -->
      <a-badge :count="3" size="small">
        <a-button type="text" class="header-icon-btn" @click="$router.push('/notifications')">
          <BellOutlined />
        </a-button>
      </a-badge>

      <!-- 用户下拉 -->
      <a-dropdown>
        <div class="user-trigger">
          <a-avatar size="small" class="user-avatar">
            {{ usernameC }}
          </a-avatar>
          <span class="user-name">{{ authStore.currentUser?.username || '用户' }}</span>
          <CaretDownOutlined class="user-caret" />
        </div>
        <template #overlay>
          <a-menu class="user-menu">
            <a-menu-item key="profile" @click="$router.push('/settings')">
              <UserOutlined />
              <span>个人设置</span>
            </a-menu-item>
            <a-menu-divider />
            <a-menu-item key="logout" @click="handleLogout">
              <LogoutOutlined />
              <span>退出登录</span>
            </a-menu-item>
          </a-menu>
        </template>
      </a-dropdown>
    </div>
  </a-layout-header>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  MenuOutlined,
  BellOutlined,
  UserOutlined,
  LogoutOutlined,
  CaretDownOutlined,
} from '@ant-design/icons-vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const emit = defineEmits<{
  'toggle-sidebar': []
}>()

// 用户名首字母
const usernameC = computed(() => {
  return (authStore.currentUser?.username || 'U')[0].toUpperCase()
})

// 面包屑
const breadcrumbs = computed(() => {
  const items: { title: string; path?: string; icon?: string }[] = []

  // 首页
  items.push({ title: '首页', path: '/dashboard', icon: '🏠' })

  const path = route.path
  const meta = route.meta as Record<string, unknown>
  const title = meta?.title

  if (path !== '/dashboard' && title) {
    items.push({ title })
  }

  return items
})

async function handleLogout() {
  await authStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.app-header {
  background: rgba(10, 14, 39, 0.85) !important;
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  padding: 0 24px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.mobile-menu-btn {
  display: none;
  color: rgba(255, 255, 255, 0.6) !important;
}

/* 面包屑 */
:deep(.header-breadcrumb) {
  font-size: 0.85rem;
}
:deep(.header-breadcrumb .ant-breadcrumb-link) {
  color: rgba(255, 255, 255, 0.45);
}
.breadcrumb-link {
  color: rgba(255, 255, 255, 0.45) !important;
  transition: color 0.2s;
}
.breadcrumb-link:hover {
  color: #93c5fd !important;
}
.breadcrumb-current {
  color: rgba(255, 255, 255, 0.8);
}
:deep(.header-breadcrumb .ant-breadcrumb-separator) {
  color: rgba(255, 255, 255, 0.2);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 搜索 */
:deep(.header-search) {
  width: 200px;
}
:deep(.header-search .ant-input) {
  background: rgba(255, 255, 255, 0.05) !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  color: rgba(255, 255, 255, 0.7) !important;
  border-radius: 20px !important;
  font-size: 0.82rem;
  height: 34px;
}
:deep(.header-search .ant-input::placeholder) {
  color: rgba(255, 255, 255, 0.25) !important;
}

.header-icon-btn {
  color: rgba(255, 255, 255, 0.5) !important;
  font-size: 1.1rem;
}
.header-icon-btn:hover {
  color: rgba(255, 255, 255, 0.85) !important;
}

/* 用户 */
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

/* 下拉菜单 */
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

@media (max-width: 768px) {
  .mobile-menu-btn { display: inline-flex; }
  :deep(.header-search) { width: 140px; }
}
</style>
